"""Czujniki binarne: najtańsza / najdroższa strefa teraz, dzień wolny wg taryfy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TaryfyConfigEntry
from .entity import EncjaPunktu
from .punkt import Punkt
from .swieta import swieto


async def async_setup_entry(
    hass: HomeAssistant, entry: TaryfyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for sid, p in entry.runtime_data.items():
        async_add_entities([NajtanszaStrefa(p), NajdrozszaStrefa(p), DzienWolny(p), OplacaSieZmiana(p)],
                           config_subentry_id=sid)


class _Porownanie(EncjaPunktu, BinarySensorEntity):
    """Cena teraz vs ceny wszystkich stref dzisiejszej doby."""

    _najtansza = True

    @property
    def is_on(self) -> bool | None:
        p = self._punkt
        teraz = p.cena(p.okno_teraz())
        ceny = [c for c in p.ceny_dnia(dt_util.now().date()).values() if c is not None]
        if teraz is None or not ceny:
            return None
        cel = min(ceny) if self._najtansza else max(ceny)
        return abs(teraz - cel) < 1e-9

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"ceny_dzis": self._punkt.ceny_dnia(dt_util.now().date())}


class NajtanszaStrefa(_Porownanie):
    _attr_icon = "mdi:piggy-bank-outline"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "najtansza_strefa")


class NajdrozszaStrefa(_Porownanie):
    _najtansza = False
    _attr_icon = "mdi:cash-remove"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "najdrozsza_strefa")


class DzienWolny(EncjaPunktu, BinarySensorEntity):
    """Dzień wolny wg taryfy (sobota, niedziela, dzień ustawowo wolny)."""

    _attr_icon = "mdi:calendar-star"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "dzien_wolny")

    @property
    def is_on(self) -> bool:
        return self._punkt.okno_teraz().dzien == "wolny"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"swieto": swieto(dt_util.now().date())}


class OplacaSieZmiana(EncjaPunktu, BinarySensorEntity):
    """Wariant z porównania tańszy od obecnej taryfy (≥ 3% i ≥ 5 zł w ostatnich 30 dniach)."""

    _attr_icon = "mdi:swap-horizontal-circle"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "oplaca_sie_zmiana")

    @property
    def is_on(self) -> bool | None:
        r = self._punkt.porownanie.get("30_dni")
        return None if not r or "oplaca_sie" not in r else bool(r["oplaca_sie"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._punkt.porownanie.get("30_dni") or {}
        return {k: r.get(k) for k in ("najtanszy", "oszczednosc_zl", "oszczednosc_proc", "dni")}
