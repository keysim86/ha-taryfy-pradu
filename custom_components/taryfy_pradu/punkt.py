"""Punkt poboru: licznik źródłowy + harmonogram (taryfa + cennik od dnia) -> strefa, ceny, energia, koszty."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import porownanie, pse
from .cennik import BladCennika, Cennik
from .const import DOMAIN, ZDARZENIE_ZMIANA_STREFY
from .taryfa import Okno, Taryfa

_LOGGER = logging.getLogger(__name__)

WERSJA_MAGAZYNU = 1
# skok odczytu większy niż tyle kWh traktujemy jako błąd licznika (nie liczymy)
MAKS_SKOK_KWH = 100.0
CO_ILE_PSE = timedelta(minutes=30)
DNI_HISTORII_PSE = 31


def _float(state: State | None) -> float | None:
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


def _na_kwh(wartosc: float, jednostka: str | None) -> float:
    if jednostka == "Wh":
        return wartosc / 1000
    if jednostka == "MWh":
        return wartosc * 1000
    return wartosc


class Punkt:
    """Stan i logika jednego punktu poboru (jeden podwpis „punkt”).

    Harmonogram: lista cenników z datą „od” (pierwszy bez daty = od zawsze). Każdy cennik
    wskazuje taryfę, więc zmianę taryfy planuje się tak samo jak zmianę cen.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        subentry_id: str,
        nazwa: str,
        zrodlo: str,
        taryfy: dict[str, Taryfa],
        taryfa_domyslna: str,
        cenniki: list[dict],
        warianty: list[dict] | None = None,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.id = subentry_id
        self.nazwa = nazwa
        self.zrodlo = zrodlo
        self.taryfy = taryfy
        self.taryfa_domyslna = taryfa_domyslna
        self.cenniki = sorted(cenniki or [{}], key=lambda c: c.get("od") or "0000-00-00")
        self._store: Store = Store(hass, WERSJA_MAGAZYNU, f"{DOMAIN}.{subentry_id}")
        self.stan: dict[str, Any] = {}
        self._sluchacze: list[Callable[[], None]] = []
        self._odpiecia: list[Callable[[], None]] = []
        self._timer: Callable[[], None] | None = None
        self._ostatnia_strefa: str | None = None
        self._taryfa_startowa: str | None = None
        self.warianty = [w for w in (warianty or []) if (w.get("taryfa") or "") in taryfy]
        self.porownanie: dict[str, Any] = {}

    # --- harmonogram taryf i cenników -------------------------------------------------

    def wpis_na(self, d: date) -> dict:
        """Cennik obowiązujący w dniu `d` (najpóźniejszy z datą „od” ≤ d)."""
        iso = d.isoformat()
        wybrany = self.cenniki[0]
        for c in self.cenniki:
            if (c.get("od") or "0000-00-00") <= iso:
                wybrany = c
        return wybrany

    def id_taryfy_na(self, d: date) -> str:
        return self.wpis_na(d).get("taryfa") or self.taryfa_domyslna

    def taryfa_na(self, d: date) -> Taryfa:
        return self.taryfy[self.id_taryfy_na(d)]

    def cennik_na(self, d: date) -> Cennik:
        return Cennik({k: v for k, v in self.wpis_na(d).items() if k not in ("od", "taryfa")})

    @property
    def taryfa(self) -> Taryfa:
        """Taryfa obowiązująca dziś."""
        return self.taryfa_na(dt_util.now().date())

    def _dzien(self, chwila: datetime) -> date:
        return dt_util.as_local(chwila).date()

    def _granice(self) -> list[datetime]:
        """Początki dni (UTC), w których zmienia się taryfa."""
        wynik, poprzednia = [], None
        for c in self.cenniki:
            t = c.get("taryfa") or self.taryfa_domyslna
            if poprzednia is not None and t != poprzednia and c.get("od"):
                wynik.append(dt_util.as_utc(dt_util.start_of_local_day(date.fromisoformat(c["od"]))))
            poprzednia = t
        return wynik

    def okno(self, chwila: datetime) -> Okno:
        """Okno strefy w chwili `chwila` wg taryfy obowiązującej tego dnia (przycięte do zmiany taryfy)."""
        o = self.taryfa_na(self._dzien(chwila)).okno(chwila)
        od, do = o.od, o.do
        c = dt_util.as_utc(chwila)
        for g in self._granice():
            if od < g <= c:
                od = g
            if c < g < do:
                do = g
        return Okno(o.strefa, o.sezon, o.dzien, od, do) if (od, do) != (o.od, o.do) else o

    def okno_teraz(self) -> Okno:
        return self.okno(dt_util.now())

    def okna(self, od: datetime, do: datetime):
        chwila, do = dt_util.as_utc(od), dt_util.as_utc(do)
        while chwila < do:
            o = self.okno(chwila)
            koniec = min(o.do, do)
            if koniec <= chwila:
                koniec = chwila + timedelta(minutes=1)
            yield Okno(o.strefa, o.sezon, o.dzien, chwila, koniec)
            chwila = koniec

    def nastepna_zmiana(self, chwila: datetime, *, tylko_strefa: bool = True) -> tuple[datetime, Okno]:
        """Następna zmiana strefy (albo stawki), zmiana taryfy albo koniec znanych stref dynamicznych."""
        teraz = self.okno(chwila)
        t0 = self.id_taryfy_na(self._dzien(chwila))
        o = teraz
        for _ in range(500):
            nastepne = self.okno(o.do)
            if self.id_taryfy_na(self._dzien(o.do)) != t0:
                return o.do, nastepne
            t = self.taryfy[t0]
            if t.typ == "dynamiczna" and (t.dane_do is None or o.do >= t.dane_do):
                return o.do, nastepne
            if (nastepne.strefa != teraz.strefa) if tylko_strefa else (nastepne.klucz != teraz.klucz):
                return o.do, nastepne
            o = nastepne
        return o.do, self.okno(o.do)

    def strefy_harmonogramu(self) -> dict[str, str]:
        """Strefy wszystkich taryf z harmonogramu {id: nazwa} -- obecna taryfa pierwsza."""
        kolejnosc = [self.id_taryfy_na(dt_util.now().date())] + [
            c.get("taryfa") or self.taryfa_domyslna for c in self.cenniki
        ]
        wynik: dict[str, str] = {}
        for tid in kolejnosc:
            t = self.taryfy[tid]
            for s in t.strefy:
                wynik.setdefault(s["id"], t.nazwa_strefy(s["id"]))
        return wynik

    def nazwa_strefy(self, strefa: str, chwila: datetime | None = None) -> str:
        t = self.taryfa_na(self._dzien(chwila)) if chwila else self.taryfa
        return t.nazwa_strefy(strefa)

    # --- ceny ------------------------------------------------------------------------

    def cena(self, okno: Okno) -> float | None:
        """Cena brutto zł/kWh w oknie (None, gdy cennik niekompletny)."""
        try:
            return self.cennik_na(self._dzien(okno.od)).cena_brutto(okno)
        except BladCennika:
            return None

    def braki_cennika(self) -> list[str]:
        d = dt_util.now().date()
        return self.cennik_na(d).braki(self.taryfa_na(d))

    def plan(self, d: date) -> list[dict]:
        """Okna doby `d` (czas lokalny) z cenami -- do atrybutów, kalendarza i Hearth."""
        od = dt_util.start_of_local_day(d)
        do = dt_util.start_of_local_day(d + timedelta(days=1))
        return [
            {
                "od": dt_util.as_local(o.od).isoformat(),
                "do": dt_util.as_local(o.do).isoformat(),
                "strefa": o.strefa,
                "nazwa": self.nazwa_strefy(o.strefa, o.od),
                "cena": None if (c := self.cena(o)) is None else round(c, 4),
            }
            for o in self.okna(od, do)
        ]

    def plan_godzinowy(self, d: date) -> list[str]:
        start = dt_util.as_utc(dt_util.start_of_local_day(d))
        koniec = dt_util.as_utc(dt_util.start_of_local_day(d + timedelta(days=1)))
        wynik, t = [], start
        while t < koniec:
            wynik.append(self.okno(t + timedelta(minutes=30)).strefa)
            t += timedelta(hours=1)
        return wynik

    def ceny_dnia(self, d: date) -> dict[str, float | None]:
        """Cena brutto każdej strefy występującej w dobie `d` (bez zaokrągleń)."""
        od = dt_util.start_of_local_day(d)
        do = dt_util.start_of_local_day(d + timedelta(days=1))
        wynik: dict[str, float | None] = {}
        for o in self.okna(od, do):
            wynik.setdefault(o.strefa, self.cena(o))
        return wynik

    def najtanszy_przedzial(self, dlugosc: timedelta, od: datetime, do: datetime) -> dict[str, Any] | None:
        """Początek przedziału o długości `dlugosc` w [od, do) z najniższą średnią ceną."""
        od, do = dt_util.as_utc(od), dt_util.as_utc(do)
        if dlugosc <= timedelta(0) or od + dlugosc > do:
            return None
        okna = list(self.okna(od, do))
        kandydaci = {od} | {o.od for o in okna if o.od + dlugosc <= do}
        kandydaci |= {o.do - dlugosc for o in okna if o.do - dlugosc >= od}
        najlepszy = None
        for start in sorted(kandydaci):
            koniec = start + dlugosc
            if koniec > do:
                continue
            suma = 0.0
            for o in self.okna(start, koniec):
                c = self.cena(o)
                if c is None:
                    return None
                suma += c * (o.do - o.od).total_seconds()
            srednia = suma / dlugosc.total_seconds()
            if najlepszy is None or srednia < najlepszy[1] - 1e-9:
                najlepszy = (start, srednia)
        if najlepszy is None:
            return None
        start, srednia = najlepszy
        return {
            "start": dt_util.as_local(start).isoformat(),
            "koniec": dt_util.as_local(start + dlugosc).isoformat(),
            "srednia_cena": round(srednia, 4),
        }

    # --- cykl życia ---------------------------------------------------------------------

    async def async_start(self) -> None:
        self.stan = await self._store.async_load() or {}
        self.stan.setdefault("ostatni_odczyt", None)
        self.stan.setdefault("energia", {})
        self.stan.setdefault("koszt_energii", 0.0)
        self.stan.setdefault("okresy", {})
        self.stan.setdefault("pse", {})
        self._przewin_okresy(dt_util.now())
        self._ustaw_pse()
        biezacy = self.hass.states.get(self.zrodlo)
        v = _float(biezacy)
        if v is not None:
            self.stan["ostatni_odczyt"] = _na_kwh(v, biezacy.attributes.get("unit_of_measurement"))
        self._odpiecia.append(async_track_state_change_event(self.hass, [self.zrodlo], self._zmiana_licznika))
        if self._uzywa_pse():
            self._odpiecia.append(async_track_time_interval(self.hass, self._pobierz_pse, CO_ILE_PSE))
            self.hass.async_create_background_task(self._pobierz_pse(), f"{DOMAIN}_pse_{self.id}")
        self._odpiecia.append(async_call_later(self.hass, 90, self._porownaj_w_tle))
        self._odpiecia.append(async_track_time_change(self.hass, self._porownaj_w_tle, hour=3, minute=30, second=0))
        self._taryfa_startowa = self.id_taryfy_na(dt_util.now().date())
        self._ostatnia_strefa = self.okno_teraz().strefa
        self._planuj_timer()

    async def async_stop(self) -> None:
        for odp in self._odpiecia:
            odp()
        self._odpiecia.clear()
        if self._timer:
            self._timer()
            self._timer = None
        await self._store.async_save(self.stan)

    @callback
    def dodaj_sluchacza(self, fn: Callable[[], None]) -> Callable[[], None]:
        self._sluchacze.append(fn)

        def usun() -> None:
            if fn in self._sluchacze:
                self._sluchacze.remove(fn)

        return usun

    @callback
    def _powiadom(self) -> None:
        for fn in list(self._sluchacze):
            fn()

    # --- strefy dynamiczne z PSE -------------------------------------------------------

    def _uzywane_taryfy(self) -> set[str]:
        return {c.get("taryfa") or self.taryfa_domyslna for c in self.cenniki} | {w["taryfa"] for w in self.warianty}

    def _uzywa_pse(self) -> bool:
        return any(
            self.taryfy[t].zrodlo_stref == "pse_kompas" for t in self._uzywane_taryfy() if t in self.taryfy
        )

    def _ustaw_pse(self) -> None:
        godziny = {datetime.fromisoformat(k): v for k, v in (self.stan.get("pse") or {}).items()}
        for t in self.taryfy.values():
            if t.zrodlo_stref == "pse_kompas":
                t.ustaw_godziny(godziny)

    async def _pobierz_pse(self, _now: datetime | None = None) -> None:
        sesja = async_get_clientsession(self.hass)
        dzis = dt_util.now().date()
        nowe: dict[datetime, str] = {}
        for d in (dzis, dzis + timedelta(days=1)):
            try:
                nowe |= await pse.pobierz(sesja, d)
            except Exception as err:  # noqa: BLE001 -- sieć/API: spróbujemy za 30 min
                _LOGGER.debug("PSE: nie udało się pobrać stref na %s: %s", d, err)
        if not nowe:
            return
        granica = dt_util.as_utc(dt_util.start_of_local_day(dzis - timedelta(days=DNI_HISTORII_PSE + 4)))
        stare = {datetime.fromisoformat(k): v for k, v in (self.stan.get("pse") or {}).items()}
        polaczone = {t: z for t, z in (stare | nowe).items() if t >= granica}
        if polaczone == stare:
            return
        self.stan["pse"] = {t.astimezone(timezone.utc).isoformat(): z for t, z in sorted(polaczone.items())}
        self._ustaw_pse()
        self._zapisz()
        self._planuj_timer()
        self._powiadom()

    # --- porównanie taryf ----------------------------------------------------------------

    @callback
    def _porownaj_w_tle(self, _now: datetime | None = None) -> None:
        self.hass.async_create_background_task(self.async_porownaj(), f"{DOMAIN}_porownanie_{self.id}")

    async def _godziny_zuzycia(self, od: datetime, do: datetime) -> list[tuple[datetime, float]]:
        """Godzinowe przyrosty licznika ze statystyk długoterminowych HA (kWh)."""
        if "recorder" not in self.hass.config.components:
            return []
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period

        wiersze = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period, self.hass, od, do, {self.zrodlo}, "hour", None, {"change"}
        )
        wynik = []
        for w in wiersze.get(self.zrodlo, []):
            start = w["start"]
            t = datetime.fromtimestamp(start, timezone.utc) if isinstance(start, (int, float)) else dt_util.as_utc(start)
            if w.get("change") is not None:
                wynik.append((t, float(w["change"])))
        return wynik

    async def _uzupelnij_historie_pse(self) -> None:
        """Strefy PSE z ostatnich dni (do porównania wariantów dynamicznych)."""
        sesja = async_get_clientsession(self.hass)
        mam = {dt_util.as_local(datetime.fromisoformat(k)).date() for k in (self.stan.get("pse") or {})}
        dzis = dt_util.now().date()
        nowe: dict[datetime, str] = {}
        for i in range(1, DNI_HISTORII_PSE + 1):
            d = dzis - timedelta(days=i)
            if d in mam:
                continue
            try:
                nowe |= await pse.pobierz(sesja, d)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("PSE: historia %s niedostępna: %s", d, err)
        if nowe:
            stare = {datetime.fromisoformat(k): v for k, v in (self.stan.get("pse") or {}).items()}
            self.stan["pse"] = {t.astimezone(timezone.utc).isoformat(): z for t, z in sorted((stare | nowe).items())}
            self._ustaw_pse()
            self._zapisz()

    def _cena_lub_blad(self, okno: Okno) -> float:
        c = self.cena(okno)
        if c is None:
            raise BladCennika("brak stawki")
        return c

    async def async_porownaj(self) -> dict[str, Any]:
        """Koszt obecnego harmonogramu i każdego wariantu na zużyciu z ostatnich 30 i 365 dni."""
        if self._uzywa_pse():
            await self._uzupelnij_historie_pse()
        dzis = dt_util.as_utc(dt_util.start_of_local_day(dt_util.now().date()))
        wynik: dict[str, Any] = {}
        for okres, dni in (("30_dni", 30), ("rok", 365)):
            od = dzis - timedelta(days=dni)
            godziny = await self._godziny_zuzycia(od, dzis)
            if not godziny:
                continue
            poczatek = min(t for t, _ in godziny)
            dni_okresu = porownanie.dni_okresu(poczatek, dzis)
            obecna = porownanie.koszt(
                godziny, dni_okresu, self.okno, self._cena_lub_blad,
                lambda d: self.cennik_na(d).stale_dzienne_brutto(d),
            )
            koszty: dict[str, dict | None] = {}
            for w in self.warianty:
                t = self.taryfy[w["taryfa"]]
                if t.typ == "dynamiczna" and dni > DNI_HISTORII_PSE:
                    continue  # strefy dynamiczne znamy tylko z ostatniego miesiąca
                cennik = Cennik({k: v for k, v in w.items() if k not in ("nazwa", "taryfa", "od")})
                koszty[w["nazwa"]] = porownanie.koszt_wariantu(godziny, dni_okresu, t, cennik)
            r = porownanie.ranking(obecna, koszty, f"Obecna ({self.taryfa.nazwa})")
            r.update(od=dni_okresu[0].isoformat(), do=dni_okresu[-1].isoformat(), dni=len(dni_okresu))
            wynik[okres] = r
        self.porownanie = wynik
        self._powiadom()
        return wynik

    # --- licznik i koszty --------------------------------------------------------------

    def _klucze_okresow(self, teraz: datetime) -> dict[str, str]:
        lok = dt_util.as_local(teraz)
        return {"dzien": lok.date().isoformat(), "miesiac": f"{lok:%Y-%m}", "rok": f"{lok:%Y}"}

    def _przewin_okresy(self, teraz: datetime) -> bool:
        zmiana = False
        for okres, klucz in self._klucze_okresow(teraz).items():
            o = self.stan["okresy"].get(okres)
            if not o or o.get("klucz") != klucz:
                self.stan["okresy"][okres] = {"klucz": klucz, "energia": {}, "koszt": 0.0}
                zmiana = True
        return zmiana

    @callback
    def _zmiana_licznika(self, event: Event[EventStateChangedData]) -> None:
        nowy = event.data["new_state"]
        v = _float(nowy)
        if v is None:
            return
        v = _na_kwh(v, nowy.attributes.get("unit_of_measurement"))
        poprzedni = self.stan.get("ostatni_odczyt")
        self.stan["ostatni_odczyt"] = v
        if poprzedni is None:
            self._zapisz()
            return
        delta = v - poprzedni
        if delta <= 0:
            if delta < 0:
                _LOGGER.debug("%s: licznik zmalał (%s -> %s) — nowy punkt odniesienia", self.nazwa, poprzedni, v)
            self._zapisz()
            return
        if delta > MAKS_SKOK_KWH:
            _LOGGER.warning("%s: skok licznika o %.1f kWh pominięty", self.nazwa, delta)
            self._zapisz()
            return
        self.nalicz(delta, dt_util.now())

    def nalicz(self, kwh: float, chwila: datetime) -> None:
        """Dolicz `kwh` zużyte w chwili `chwila` (do strefy i ceny z tej chwili)."""
        self._przewin_okresy(chwila)
        okno = self.okno(chwila)
        koszt = kwh * (self.cena(okno) or 0.0)
        en = self.stan["energia"]
        en[okno.strefa] = en.get(okno.strefa, 0.0) + kwh
        self.stan["koszt_energii"] += koszt
        for o in self.stan["okresy"].values():
            o["energia"][okno.strefa] = o["energia"].get(okno.strefa, 0.0) + kwh
            o["koszt"] += koszt
        self._zapisz()
        self._powiadom()

    def _zapisz(self) -> None:
        self._store.async_delay_save(lambda: self.stan, 30)

    def koszty(self) -> dict[str, dict[str, float]]:
        """Koszt brutto bieżącej doby, miesiąca i roku: energia + część opłat stałych."""
        dzis = dt_util.now().date()
        okresy = self.stan.get("okresy", {})
        stale_dzien = self.cennik_na(dzis).stale_dzienne_brutto(dzis)
        stale_mies = sum(
            self.cennik_na(date(dzis.year, dzis.month, d)).stale_dzienne_brutto(date(dzis.year, dzis.month, d))
            for d in range(1, dzis.day + 1)
        )
        stale_rok = stale_mies + sum(
            self.cennik_na(date(dzis.year, m, 1)).stale_miesieczne_brutto() for m in range(1, dzis.month)
        )
        wynik = {}
        for okres, stale in (("dzien", stale_dzien), ("miesiac", stale_mies), ("rok", stale_rok)):
            energia = float((okresy.get(okres) or {}).get("koszt", 0.0))
            wynik[okres] = {"energia": energia, "stale": stale, "razem": energia + stale}
        return wynik

    def energia_okresu(self, okres: str) -> dict[str, float]:
        return dict((self.stan.get("okresy", {}).get(okres) or {}).get("energia", {}))

    # --- zmiany stref i taryf ----------------------------------------------------------------

    def _planuj_timer(self) -> None:
        if self._timer:
            self._timer()
        teraz = dt_util.now()
        zmiana, _ = self.nastepna_zmiana(teraz, tylko_strefa=False)
        polnoc = dt_util.start_of_local_day(teraz.date() + timedelta(days=1))
        kiedy = min(zmiana, polnoc) + timedelta(seconds=1)
        self._timer = async_track_point_in_time(self.hass, self._zegar, kiedy)

    @callback
    def _zegar(self, _now: datetime) -> None:
        self._timer = None
        teraz = dt_util.now()
        self._przewin_okresy(teraz)
        if (dzis := self.id_taryfy_na(teraz.date())) != self._taryfa_startowa:
            _LOGGER.info("%s: od dziś taryfa %s", self.nazwa, self.taryfa.nazwa)
            self._taryfa_startowa = dzis
        okno = self.okno(teraz)
        if okno.strefa != self._ostatnia_strefa:
            self.hass.bus.async_fire(
                ZDARZENIE_ZMIANA_STREFY,
                {
                    "punkt": self.nazwa,
                    "punkt_id": self.id,
                    "strefa": okno.strefa,
                    "nazwa_strefy": self.nazwa_strefy(okno.strefa),
                    "poprzednia": self._ostatnia_strefa,
                    "cena": self.cena(okno),
                },
            )
            self._ostatnia_strefa = okno.strefa
        self._zapisz()
        self._powiadom()
        self._planuj_timer()
