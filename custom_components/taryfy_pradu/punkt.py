"""Punkt poboru: licznik źródłowy + taryfa + cenniki -> strefa, ceny, energia i koszty."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .cennik import BladCennika, Cennik
from .const import DOMAIN, ZDARZENIE_ZMIANA_STREFY
from .taryfa import Okno, Taryfa

_LOGGER = logging.getLogger(__name__)

WERSJA_MAGAZYNU = 1
# skok odczytu większy niż tyle kWh traktujemy jako błąd licznika (nie liczymy)
MAKS_SKOK_KWH = 100.0


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
    """Stan i logika jednego punktu poboru (jeden podwpis „punkt”)."""

    def __init__(
        self,
        hass: HomeAssistant,
        subentry_id: str,
        nazwa: str,
        zrodlo: str,
        taryfa: Taryfa,
        cenniki: list[dict],
    ) -> None:
        self.hass = hass
        self.id = subentry_id
        self.nazwa = nazwa
        self.zrodlo = zrodlo
        self.taryfa = taryfa
        self.cenniki = sorted(cenniki, key=lambda c: c.get("od") or "0000-00-00")
        self._store: Store = Store(hass, WERSJA_MAGAZYNU, f"{DOMAIN}.{subentry_id}")
        self.stan: dict[str, Any] = {}
        self._sluchacze: list[Callable[[], None]] = []
        self._odpiecia: list[Callable[[], None]] = []
        self._timer: Callable[[], None] | None = None
        self._ostatnia_strefa: str | None = None

    # --- cykl życia -----------------------------------------------------------------

    async def async_start(self) -> None:
        self.stan = await self._store.async_load() or {}
        self.stan.setdefault("ostatni_odczyt", None)
        self.stan.setdefault("energia", {})
        self.stan.setdefault("koszt_energii", 0.0)
        self.stan.setdefault("okresy", {})
        self._przewin_okresy(dt_util.now())
        # punkt odniesienia z bieżącego stanu licznika (bez naliczania -- nie wiemy, kiedy
        # przybyło to, co ewentualnie przybyło, gdy HA nie działał)
        biezacy = self.hass.states.get(self.zrodlo)
        v = _float(biezacy)
        if v is not None:
            self.stan["ostatni_odczyt"] = _na_kwh(v, biezacy.attributes.get("unit_of_measurement"))
        self._odpiecia.append(
            async_track_state_change_event(self.hass, [self.zrodlo], self._zmiana_licznika)
        )
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

    # --- taryfa i ceny --------------------------------------------------------------

    def cennik_na(self, d: date) -> Cennik:
        """Cennik obowiązujący w dniu `d` (najpóźniejszy z datą „od” ≤ d)."""
        iso = d.isoformat()
        wybrany = self.cenniki[0] if self.cenniki else {}
        for c in self.cenniki:
            if (c.get("od") or "0000-00-00") <= iso:
                wybrany = c
        return Cennik(wybrany)

    def okno_teraz(self) -> Okno:
        return self.taryfa.okno(dt_util.now())

    def cena(self, okno: Okno) -> float | None:
        """Cena brutto zł/kWh w oknie (None, gdy cennik niekompletny)."""
        try:
            return self.cennik_na(dt_util.as_local(okno.od).date()).cena_brutto(okno)
        except BladCennika:
            return None

    def braki_cennika(self) -> list[str]:
        return self.cennik_na(dt_util.now().date()).braki(self.taryfa)

    def plan(self, d: date) -> list[dict]:
        """Okna doby `d` (czas lokalny) z cenami -- do atrybutów, kalendarza i Hearth."""
        od = dt_util.start_of_local_day(d)
        do = dt_util.start_of_local_day(d + timedelta(days=1))
        return [
            {
                "od": dt_util.as_local(o.od).isoformat(),
                "do": dt_util.as_local(o.do).isoformat(),
                "strefa": o.strefa,
                "nazwa": self.taryfa.nazwa_strefy(o.strefa),
                "cena": None if (c := self.cena(o)) is None else round(c, 4),
            }
            for o in self.taryfa.okna(od, do)
        ]

    def ceny_dnia(self, d: date) -> dict[str, float | None]:
        """Cena brutto każdej strefy występującej w dobie `d`."""
        od = dt_util.start_of_local_day(d)
        do = dt_util.start_of_local_day(d + timedelta(days=1))
        wynik: dict[str, float | None] = {}
        for o in self.taryfa.okna(od, do):
            wynik.setdefault(o.strefa, self.cena(o))
        return wynik

    def najtanszy_przedzial(
        self, dlugosc: timedelta, od: datetime, do: datetime
    ) -> dict[str, Any] | None:
        """Początek przedziału o długości `dlugosc` w [od, do) z najniższą średnią ceną."""
        if dlugosc <= timedelta(0) or od + dlugosc > do:
            return None
        okna = list(self.taryfa.okna(od, do))
        kandydaci = {dt_util.as_utc(od)} | {o.od for o in okna if o.od + dlugosc <= dt_util.as_utc(do)}
        # także przedziały kończące się równo z końcem okna
        kandydaci |= {o.do - dlugosc for o in okna if o.do - dlugosc >= dt_util.as_utc(od)}
        najlepszy = None
        for start in sorted(kandydaci):
            koniec = start + dlugosc
            if koniec > dt_util.as_utc(do):
                continue
            suma, ok = 0.0, True
            for o in self.taryfa.okna(start, koniec):
                c = self.cena(o)
                if c is None:
                    ok = False
                    break
                suma += c * (o.do - o.od).total_seconds()
            if not ok:
                return None
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

    # --- licznik i koszty -----------------------------------------------------------

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
        okno = self.taryfa.okno(chwila)
        cena = self.cena(okno) or 0.0
        koszt = kwh * cena
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
        stale_mies = stale_dzien * dzis.day
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

    # --- zmiany stref -----------------------------------------------------------------

    def _planuj_timer(self) -> None:
        if self._timer:
            self._timer()
        teraz = dt_util.now()
        zmiana, _ = self.taryfa.nastepna_zmiana(teraz, tylko_strefa=False)
        polnoc = dt_util.start_of_local_day(teraz.date() + timedelta(days=1))
        kiedy = min(zmiana, polnoc) + timedelta(seconds=1)
        self._timer = async_track_point_in_time(self.hass, self._zegar, kiedy)

    @callback
    def _zegar(self, _now: datetime) -> None:
        self._timer = None
        teraz = dt_util.now()
        self._przewin_okresy(teraz)
        okno = self.taryfa.okno(teraz)
        if okno.strefa != self._ostatnia_strefa:
            self.hass.bus.async_fire(
                ZDARZENIE_ZMIANA_STREFY,
                {
                    "punkt": self.nazwa,
                    "punkt_id": self.id,
                    "strefa": okno.strefa,
                    "nazwa_strefy": self.taryfa.nazwa_strefy(okno.strefa),
                    "poprzednia": self._ostatnia_strefa,
                    "cena": self.cena(okno),
                },
            )
            self._ostatnia_strefa = okno.strefa
        self._zapisz()
        self._powiadom()
        self._planuj_timer()
