"""Kalendarz stref taryfy: każde okno strefy jako wydarzenie (z ceną w opisie)."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TaryfyConfigEntry
from .entity import EncjaPunktu
from .punkt import Punkt
from .taryfa import Okno


async def async_setup_entry(
    hass: HomeAssistant, entry: TaryfyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for sid, p in entry.runtime_data.items():
        async_add_entities([KalendarzStref(p)], config_subentry_id=sid)


class KalendarzStref(EncjaPunktu, CalendarEntity):
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "kalendarz")

    def _wydarzenie(self, o: Okno) -> CalendarEvent:
        p = self._punkt
        cena = p.cena(o)
        opis = f"Cena: {cena:.4f} zł/kWh" if cena is not None else "Cena: brak w cenniku"
        return CalendarEvent(
            start=dt_util.as_local(o.od),
            end=dt_util.as_local(o.do),
            summary=p.taryfa.nazwa_strefy(o.strefa),
            description=f"{opis}\nSezon: {o.sezon}, dzień: {o.dzien}",
            uid=f"{p.id}-{int(o.od.timestamp())}",
        )

    @property
    def event(self) -> CalendarEvent | None:
        p = self._punkt
        teraz = dt_util.now()
        # całe okno strefy -- sklejone wstecz przez północ, jeśli strefa się nie zmienia
        o = p.okno_teraz()
        od = o.od
        for _ in range(7):
            wczesniej = p.taryfa.okno(od - timedelta(seconds=1))
            if wczesniej.strefa != o.strefa:
                break
            od = wczesniej.od
        kiedy, _ = p.taryfa.nastepna_zmiana(teraz)
        return self._wydarzenie(Okno(o.strefa, o.sezon, o.dzien, od, kiedy))

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        wynik: list[CalendarEvent] = []
        poprzednie: Okno | None = None
        for o in self._punkt.taryfa.okna(start_date, end_date):
            # sklej sąsiednie okna tej samej strefy (np. noc przez północ)
            if poprzednie and poprzednie.strefa == o.strefa and poprzednie.do == o.od:
                poprzednie = Okno(o.strefa, poprzednie.sezon, poprzednie.dzien, poprzednie.od, o.do)
                continue
            if poprzednie:
                wynik.append(self._wydarzenie(poprzednie))
            poprzednie = o
        if poprzednie:
            wynik.append(self._wydarzenie(poprzednie))
        return wynik
