"""Wspólna baza encji punktu poboru."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .punkt import Punkt


class EncjaPunktu(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        punkt: Punkt,
        klucz: str,
        *,
        strefa: str | None = None,
    ) -> None:
        """`klucz` = translation_key; `strefa` = encja osobna dla strefy (id w unique_id, nazwa w opisie)."""
        self._punkt = punkt
        self._strefa = strefa
        self._attr_unique_id = f"{punkt.id}_{klucz}" + (f"_{strefa}" if strefa else "")
        self._attr_translation_key = klucz
        if strefa:
            self._attr_translation_placeholders = {"strefa": punkt.taryfa.nazwa_strefy(strefa)}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, punkt.id)},
            name=punkt.nazwa,
            manufacturer=punkt.taryfa.definicja.get("operator") or "Taryfy prądu",
            model=f"Taryfa {punkt.taryfa.nazwa}",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._punkt.dodaj_sluchacza(self._odswiez))

    @callback
    def _odswiez(self) -> None:
        self.async_write_ha_state()
