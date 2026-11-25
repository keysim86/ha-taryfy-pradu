"""Silnik taryf strefowych: która strefa obowiązuje w danej chwili, plan doby, zmiany.

Definicja taryfy to zwykły słownik (zapisywany w konfiguracji HA, edytowany kreatorem):

    {
      "nazwa": "G13s",
      "operator": "TAURON Dystrybucja",
      "czas": "lokalny" | "zimowy",
      "strefy": [{"id": "nocna", "nazwa": "Nocna"}, ...],          # kolejność = od najtańszej
      "sezony": [{"id": "lato", "nazwa": "Lato", "od": "04-01", "do": "09-30"}, ...],
      "dni": "roboczy_wolny" | "jednakowe",
      "godziny": {"<sezon>": {"roboczy": {"<strefa>": "07:00-09:00, 17:00-21:00", ...},
                              "wolny": {...}}}                     # przy "jednakowe" tylko "roboczy"
    }

Czas "zimowy": godziny stref liczone wg czasu zimowego (UTC+1) przez cały rok -- tak
taryfy OSD opisują zegary liczników, które nie przestawiają się latem. Czas "lokalny":
wg zegara w Polsce (latem UTC+2).

Bez zależności od Home Assistanta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .swieta import dzien_wolny

STREFA_CZASOWA = ZoneInfo("Europe/Warsaw")
CZAS_ZIMOWY = timezone(timedelta(hours=1), "CET")
MINUT_W_DOBIE = 24 * 60
DNI = ("roboczy", "wolny")

_PRZEDZIAL = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*-\s*(\d{1,2})(?::(\d{2}))?\s*$")


class BladTaryfy(ValueError):
    """Niepoprawna definicja taryfy (komunikat po polsku, do pokazania w kreatorze)."""


@dataclass(frozen=True)
class Okno:
    """Ciągły przedział czasu z jedną strefą, sezonem i rodzajem dnia (od/do w UTC)."""

    strefa: str
    sezon: str
    dzien: str  # "roboczy" | "wolny"
    od: datetime
    do: datetime

    @property
    def klucz(self) -> tuple[str, str, str]:
        return (self.sezon, self.dzien, self.strefa)


def parsuj_przedzialy(tekst: str) -> list[tuple[int, int]]:
    """'07:00-09:00, 17-21' -> [(420, 540), (1020, 1260)]; '21-7' -> [(1260, 1440), (0, 420)]."""
    wynik: list[tuple[int, int]] = []
    if not tekst or not tekst.strip():
        return wynik
    for kawalek in re.split(r"[,;]", tekst):
        if not kawalek.strip():
            continue
        m = _PRZEDZIAL.match(kawalek)
        if not m:
            raise BladTaryfy(f"Nie rozumiem przedziału „{kawalek.strip()}” — wpisz np. 07:00-09:00")
        h1, m1, h2, m2 = int(m[1]), int(m[2] or 0), int(m[3]), int(m[4] or 0)
        if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59 or (h1 == 24 and m1) or (h2 == 24 and m2):
            raise BladTaryfy(f"Niepoprawna godzina w „{kawalek.strip()}”")
        od, do = h1 * 60 + m1, h2 * 60 + m2
        if od == do:
            raise BladTaryfy(f"Przedział „{kawalek.strip()}” jest pusty")
        if od < do:
            wynik.append((od, do))
        else:  # przez północ
            wynik.append((od, MINUT_W_DOBIE))
            if do:
                wynik.append((0, do))
    return wynik


def _mmdd(tekst: str) -> tuple[int, int]:
    try:
        m, d = (int(x) for x in tekst.strip().split("-"))
        date(2024, m, d)  # rok przestępny -- dopuszcza 02-29
    except (ValueError, AttributeError) as err:
        raise BladTaryfy(f"Niepoprawna data sezonu „{tekst}” — wpisz MM-DD, np. 04-01") from err
    return m, d


class Taryfa:
    """Taryfa strefowa zbudowana z definicji (słownika)."""

    def __init__(self, definicja: dict) -> None:
        self.definicja = definicja
        self.nazwa: str = definicja.get("nazwa") or "Taryfa"
        self.czas: str = definicja.get("czas", "lokalny")
        if self.czas not in ("lokalny", "zimowy"):
            raise BladTaryfy("Czas stref musi być „lokalny” albo „zimowy”")
        self.strefy: list[dict] = list(definicja.get("strefy") or [])
        self.sezony: list[dict] = list(definicja.get("sezony") or [])
        self.dni: str = definicja.get("dni", "roboczy_wolny")
        if self.dni not in ("roboczy_wolny", "jednakowe"):
            raise BladTaryfy("Rodzaj dni musi być „roboczy_wolny” albo „jednakowe”")
        self._strefy_id = [s["id"] for s in self.strefy]
        if not self._strefy_id:
            raise BladTaryfy("Taryfa musi mieć co najmniej jedną strefę")
        if len(set(self._strefy_id)) != len(self._strefy_id):
            raise BladTaryfy("Identyfikatory stref muszą być różne")
        if not self.sezony:
            raise BladTaryfy("Taryfa musi mieć co najmniej jeden sezon")
        self._sezony = self._zbuduj_sezony()
        self._plany = self._zbuduj_plany(definicja.get("godziny") or {})

    # --- budowa i walidacja -------------------------------------------------------

    def _zbuduj_sezony(self) -> list[tuple[str, tuple[int, int], tuple[int, int]]]:
        wynik = []
        for s in self.sezony:
            wynik.append((s["id"], _mmdd(s["od"]), _mmdd(s["do"])))
        # każdy dzień roku (przestępnego) musi należeć do dokładnie jednego sezonu
        d = date(2024, 1, 1)
        while d.year == 2024:
            trafione = [sid for sid, od, do in wynik if self._w_sezonie(d, od, do)]
            if len(trafione) != 1:
                opis = "żadnego sezonu" if not trafione else "kilku sezonów: " + ", ".join(trafione)
                raise BladTaryfy(f"Dzień {d:%d.%m} należy do {opis}")
            d += timedelta(days=1)
        return wynik

    @staticmethod
    def _w_sezonie(d: date, od: tuple[int, int], do: tuple[int, int]) -> bool:
        x = (d.month, d.day)
        return od <= x <= do if od <= do else (x >= od or x <= do)

    def _zbuduj_plany(self, godziny: dict) -> dict[tuple[str, str], list[tuple[int, int, str]]]:
        plany = {}
        dni = DNI if self.dni == "roboczy_wolny" else ("roboczy",)
        for sid, _, _ in self._sezony:
            for dzien in dni:
                strefy = (godziny.get(sid) or {}).get(dzien) or {}
                odcinki: list[tuple[int, int, str]] = []
                for strefa, tekst in strefy.items():
                    if strefa not in self._strefy_id:
                        raise BladTaryfy(f"Nieznana strefa „{strefa}” w godzinach ({sid}, {dzien})")
                    odcinki += [(od, do, strefa) for od, do in parsuj_przedzialy(tekst)]
                odcinki.sort()
                kursor = 0
                for od, do, strefa in odcinki:
                    if od != kursor:
                        co = "nakładają się" if od < kursor else "zostawiają lukę"
                        raise BladTaryfy(
                            f"Godziny stref {co} ok. {kursor // 60:02d}:{kursor % 60:02d} "
                            f"({self._nazwa_sezonu(sid)}, dzień {dzien})"
                        )
                    kursor = do
                if kursor != MINUT_W_DOBIE:
                    raise BladTaryfy(
                        f"Godziny stref nie pokrywają całej doby "
                        f"({self._nazwa_sezonu(sid)}, dzień {dzien})"
                    )
                # sklej sąsiednie odcinki tej samej strefy
                sklejone: list[tuple[int, int, str]] = []
                for od, do, strefa in odcinki:
                    if sklejone and sklejone[-1][2] == strefa and sklejone[-1][1] == od:
                        sklejone[-1] = (sklejone[-1][0], do, strefa)
                    else:
                        sklejone.append((od, do, strefa))
                plany[(sid, dzien)] = sklejone
        return plany

    def _nazwa_sezonu(self, sid: str) -> str:
        return next((s.get("nazwa") or sid for s in self.sezony if s["id"] == sid), sid)

    # --- zapytania ----------------------------------------------------------------

    @property
    def strefa_czasowa(self):
        return CZAS_ZIMOWY if self.czas == "zimowy" else STREFA_CZASOWA

    def nazwa_strefy(self, strefa: str) -> str:
        return next((s.get("nazwa") or strefa for s in self.strefy if s["id"] == strefa), strefa)

    def sezon_dnia(self, d: date) -> str:
        return next(sid for sid, od, do in self._sezony if self._w_sezonie(d, od, do))

    def rodzaj_dnia(self, d: date) -> str:
        if self.dni == "jednakowe":
            return "roboczy"
        return "wolny" if dzien_wolny(d) else "roboczy"

    def _odcinki_dnia(self, d: date) -> list[tuple[datetime, datetime, Okno]]:
        """Okna jednej doby w czasie taryfy (od północy do północy)."""
        tz = self.strefa_czasowa
        sezon, dzien = self.sezon_dnia(d), self.rodzaj_dnia(d)
        wynik = []
        for od, do, strefa in self._plany[(sezon, dzien)]:
            t_od = _chwila(d, od, tz)
            t_do = _chwila(d, do, tz)
            wynik.append((t_od, t_do, Okno(strefa, sezon, dzien, t_od, t_do)))
        return wynik

    def okno(self, chwila: datetime) -> Okno:
        """Okno (strefa, sezon, rodzaj dnia, od, do) obowiązujące w chwili `chwila`."""
        if chwila.tzinfo is None:
            raise ValueError("chwila musi mieć strefę czasową")
        lokalna = chwila.astimezone(self.strefa_czasowa)
        chwila = chwila.astimezone(timezone.utc)
        for t_od, t_do, okno in self._odcinki_dnia(lokalna.date()):
            if t_od <= chwila < t_do:
                return okno
        # zabezpieczenie na przejściach czasu -- weź ostatnie okno doby
        return self._odcinki_dnia(lokalna.date())[-1][2]

    def okna(self, od: datetime, do: datetime):
        """Kolejne okna nachodzące na przedział [od, do), przycięte do niego (czasy w UTC)."""
        chwila, do = od.astimezone(timezone.utc), do.astimezone(timezone.utc)
        while chwila < do:
            o = self.okno(chwila)
            koniec = min(o.do, do)
            if koniec <= chwila:  # nie powinno się zdarzyć -- ochrona przed pętlą
                koniec = chwila + timedelta(minutes=1)
            yield Okno(o.strefa, o.sezon, o.dzien, chwila, koniec)
            chwila = koniec

    def nastepna_zmiana(self, chwila: datetime, *, tylko_strefa: bool = True) -> tuple[datetime, Okno]:
        """Pierwsza chwila po `chwila`, gdy zmienia się strefa (albo klucz stawki), i okno od niej."""
        teraz = self.okno(chwila)
        o = teraz
        for _ in range(400):
            nastepne = self.okno(o.do)
            if (nastepne.strefa != teraz.strefa) if tylko_strefa else (nastepne.klucz != teraz.klucz):
                return o.do, nastepne
            o = nastepne
        raise BladTaryfy("Strefa nie zmienia się przez ponad rok")

    def plan_godzinowy(self, d: date) -> list[str]:
        """Strefa dla każdej pełnej godziny doby `d` w czasie lokalnym (23-25 pozycji)."""
        start = datetime.combine(d, time(0), STREFA_CZASOWA).astimezone(timezone.utc)
        koniec = datetime.combine(d + timedelta(days=1), time(0), STREFA_CZASOWA).astimezone(timezone.utc)
        wynik = []
        t = start
        while t < koniec:
            wynik.append(self.okno(t + timedelta(minutes=30)).strefa)
            t += timedelta(hours=1)
        return wynik


def _chwila(d: date, minuta: int, tz) -> datetime:
    """Początek minuty `minuta` doby `d` w strefie `tz`, w UTC (24:00 = północ następnego dnia).

    W UTC, bo Python porównuje i odejmuje datetime z tą samą strefą po wskazaniu zegara --
    w dniu zmiany czasu dawałoby to złe długości i kolejność.
    """
    if minuta >= MINUT_W_DOBIE:
        return datetime.combine(d + timedelta(days=1), time(0), tz).astimezone(timezone.utc)
    return datetime.combine(d, time(minuta // 60, minuta % 60), tz).astimezone(timezone.utc)
