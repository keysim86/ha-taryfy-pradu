"""Taryfy prądu — strefy, ceny i koszty energii elektrycznej wg taryfy (G13, G13s i własne)."""

from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import CONF_CENNIKI, CONF_DEFINICJA, CONF_TARYFA, CONF_ZRODLO, DOMAIN, TYP_PUNKT, TYP_TARYFA
from .punkt import Punkt
from .taryfa import BladTaryfy, Taryfa

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CALENDAR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type TaryfyConfigEntry = ConfigEntry[dict[str, Punkt]]

USLUGA_NAJTANSZY = "najtanszy_przedzial"
USLUGA_CENA = "cena"

SCHEMAT_NAJTANSZY = vol.Schema({
    vol.Required("encja"): cv.entity_id,
    vol.Required("czas_trwania"): cv.positive_time_period,
    vol.Optional("od"): cv.datetime,
    vol.Optional("do"): cv.datetime,
})
SCHEMAT_CENA = vol.Schema({
    vol.Required("encja"): cv.entity_id,
    vol.Optional("chwila"): cv.datetime,
})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Usługi dla automatyzacji (z odpowiedzią)."""

    def _punkt(encja: str) -> Punkt:
        wpis = er.async_get(hass).async_get(encja)
        if wpis is None or wpis.platform != DOMAIN or not wpis.config_subentry_id:
            raise ServiceValidationError(f"{encja} nie jest encją punktu poboru Taryf prądu")
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            if (p := entry.runtime_data.get(wpis.config_subentry_id)) is not None:
                return p
        raise ServiceValidationError(f"Punkt poboru dla {encja} nie jest załadowany")

    def _lokalnie(chwila):
        if chwila is None:
            return dt_util.now()
        return chwila if chwila.tzinfo else chwila.replace(tzinfo=dt_util.get_default_time_zone())

    async def najtanszy(call: ServiceCall) -> ServiceResponse:
        p = _punkt(call.data["encja"])
        od = _lokalnie(call.data.get("od"))
        do = _lokalnie(call.data["do"]) if "do" in call.data else od + timedelta(hours=24)
        wynik = p.najtanszy_przedzial(call.data["czas_trwania"], od, do)
        if wynik is None:
            raise ServiceValidationError(
                "Nie da się wyznaczyć przedziału (za krótki zakres albo niekompletny cennik)"
            )
        return wynik

    async def cena(call: ServiceCall) -> ServiceResponse:
        p = _punkt(call.data["encja"])
        okno = p.taryfa.okno(_lokalnie(call.data.get("chwila")))
        return {
            "strefa": okno.strefa,
            "nazwa_strefy": p.taryfa.nazwa_strefy(okno.strefa),
            "sezon": okno.sezon,
            "rodzaj_dnia": okno.dzien,
            "od": dt_util.as_local(okno.od).isoformat(),
            "do": dt_util.as_local(okno.do).isoformat(),
            "cena": p.cena(okno),
        }

    hass.services.async_register(DOMAIN, USLUGA_NAJTANSZY, najtanszy, SCHEMAT_NAJTANSZY,
                                 supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, USLUGA_CENA, cena, SCHEMAT_CENA,
                                 supports_response=SupportsResponse.ONLY)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TaryfyConfigEntry) -> bool:
    taryfy = {sid: s for sid, s in entry.subentries.items() if s.subentry_type == TYP_TARYFA}
    punkty: dict[str, Punkt] = {}
    for sid, sub in entry.subentries.items():
        if sub.subentry_type != TYP_PUNKT:
            continue
        t_sub = taryfy.get(sub.data.get(CONF_TARYFA))
        if t_sub is None:
            _LOGGER.warning("Punkt %s: brak taryfy (usunięta?) — pomijam", sub.title)
            continue
        try:
            taryfa = Taryfa(t_sub.data[CONF_DEFINICJA])
        except BladTaryfy as err:
            _LOGGER.error("Taryfa %s jest niepoprawna: %s", t_sub.title, err)
            continue
        p = Punkt(hass, sid, sub.title, sub.data[CONF_ZRODLO], taryfa, list(sub.data.get(CONF_CENNIKI) or []))
        await p.async_start()
        punkty[sid] = p
    entry.runtime_data = punkty
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_przeladuj))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TaryfyConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    for p in (entry.runtime_data or {}).values():
        await p.async_stop()
    return ok


async def _przeladuj(hass: HomeAssistant, entry: TaryfyConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
