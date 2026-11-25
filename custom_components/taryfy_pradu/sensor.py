"""Sensory punktu poboru: strefa, ceny, zmiany, koszty, energia w strefach."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TaryfyConfigEntry
from .const import JEDNOSTKA_CENY, WALUTA
from .entity import EncjaPunktu
from .punkt import Punkt


async def async_setup_entry(
    hass: HomeAssistant, entry: TaryfyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for sid, p in entry.runtime_data.items():
        encje: list[SensorEntity] = [
            Strefa(p), Cena(p), NastepnaStrefa(p), ZmianaStrefy(p), CenaNastepna(p),
            Koszt(p, "dzien"), Koszt(p, "miesiac"), Koszt(p, "rok"), KosztEnergii(p),
            OplatyStale(p),
        ]
        for s in p.taryfa.strefy:
            encje += [EnergiaStrefy(p, s["id"]), EnergiaDzisStrefy(p, s["id"]), CenaStrefyDzis(p, s["id"])]
        async_add_entities(encje, config_subentry_id=sid)


class Strefa(EncjaPunktu, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:clock-time-four-outline"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "strefa")
        self._attr_options = [punkt.taryfa.nazwa_strefy(s["id"]) for s in punkt.taryfa.strefy]

    @property
    def native_value(self) -> str:
        return self._punkt.taryfa.nazwa_strefy(self._punkt.okno_teraz().strefa)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self._punkt
        o = p.okno_teraz()
        dzis = dt_util.now().date()
        jutro = dzis + timedelta(days=1)
        return {
            "strefa_id": o.strefa,
            "sezon": o.sezon,
            "rodzaj_dnia": o.dzien,
            "od": dt_util.as_local(o.od).isoformat(),
            "do": dt_util.as_local(o.do).isoformat(),
            "taryfa": p.taryfa.nazwa,
            "czas_stref": p.taryfa.czas,
            "plan_godzinowy_dzis": p.taryfa.plan_godzinowy(dzis),
            "plan_godzinowy_jutro": p.taryfa.plan_godzinowy(jutro),
            "ceny_dzis": p.ceny_dnia(dzis),
            "ceny_jutro": p.ceny_dnia(jutro),
            "plan_dzis": p.plan(dzis),
            "plan_jutro": p.plan(jutro),
        }


class Cena(EncjaPunktu, SensorEntity):
    """Cena brutto teraz -- nadaje się jako „cena energii” w panelu Energia."""

    _attr_native_unit_of_measurement = JEDNOSTKA_CENY
    _attr_suggested_display_precision = 4
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash-clock"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "cena")

    @property
    def native_value(self) -> float | None:
        return self._punkt.cena(self._punkt.okno_teraz())

    @property
    def available(self) -> bool:
        return self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self._punkt
        o = p.okno_teraz()
        c = p.cennik_na(dt_util.now().date())
        attrs: dict[str, Any] = {"vat": c.vat}
        try:
            netto = c.skladowe_netto(o)
            attrs["skladowe_netto"] = {k: round(v, 4) for k, v in netto.items()}
            attrs["cena_netto"] = round(sum(netto.values()), 4)
        except ValueError:
            pass
        if braki := p.braki_cennika():
            attrs["braki_cennika"] = braki
        return attrs


class NastepnaStrefa(EncjaPunktu, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:clock-end"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "nastepna_strefa")
        self._attr_options = [punkt.taryfa.nazwa_strefy(s["id"]) for s in punkt.taryfa.strefy]

    @property
    def native_value(self) -> str:
        _, o = self._punkt.taryfa.nastepna_zmiana(dt_util.now())
        return self._punkt.taryfa.nazwa_strefy(o.strefa)


class ZmianaStrefy(EncjaPunktu, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-sand"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "zmiana_strefy")

    @property
    def native_value(self) -> datetime:
        kiedy, _ = self._punkt.taryfa.nastepna_zmiana(dt_util.now())
        return kiedy


class CenaNastepna(EncjaPunktu, SensorEntity):
    _attr_native_unit_of_measurement = JEDNOSTKA_CENY
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:cash-fast"

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "cena_nastepna")

    @property
    def native_value(self) -> float | None:
        _, o = self._punkt.taryfa.nastepna_zmiana(dt_util.now())
        return self._punkt.cena(o)


class CenaStrefyDzis(EncjaPunktu, SensorEntity):
    """Dzisiejsza cena jednej strefy (do porównań w automatyzacjach)."""

    _attr_native_unit_of_measurement = JEDNOSTKA_CENY
    _attr_suggested_display_precision = 4
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cash"

    def __init__(self, punkt: Punkt, strefa: str) -> None:
        super().__init__(punkt, "cena_strefy", strefa=strefa)

    @property
    def native_value(self) -> float | None:
        return self._punkt.ceny_dnia(dt_util.now().date()).get(self._strefa)


_POCZATEK = {
    "dzien": lambda d: dt_util.start_of_local_day(d),
    "miesiac": lambda d: dt_util.start_of_local_day(d.replace(day=1)),
    "rok": lambda d: dt_util.start_of_local_day(date(d.year, 1, 1)),
}


class Koszt(EncjaPunktu, SensorEntity):
    """Koszt brutto okresu: energia (wg strefy i ceny w chwili zużycia) + część opłat stałych."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = WALUTA
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, punkt: Punkt, okres: str) -> None:
        super().__init__(punkt, f"koszt_{okres}")
        self._okres = okres

    @property
    def native_value(self) -> float:
        return round(self._punkt.koszty()[self._okres]["razem"], 4)

    @property
    def last_reset(self) -> datetime:
        return _POCZATEK[self._okres](dt_util.now().date())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        k = self._punkt.koszty()[self._okres]
        return {
            "energia": round(k["energia"], 2),
            "oplaty_stale": round(k["stale"], 2),
            "zuzycie_kwh": {s: round(v, 3) for s, v in self._punkt.energia_okresu(self._okres).items()},
        }


class KosztEnergii(EncjaPunktu, SensorEntity):
    """Narastający koszt energii (bez opłat stałych) -- do panelu Energia jako „koszt”."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = WALUTA
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "koszt_energii")

    @property
    def native_value(self) -> float:
        return round(float(self._punkt.stan.get("koszt_energii", 0.0)), 4)


class OplatyStale(EncjaPunktu, SensorEntity):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = WALUTA
    _attr_suggested_display_precision = 2
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, punkt: Punkt) -> None:
        super().__init__(punkt, "oplaty_stale")

    @property
    def native_value(self) -> float:
        return round(self._punkt.cennik_na(dt_util.now().date()).stale_miesieczne_brutto(), 2)


class EnergiaStrefy(EncjaPunktu, SensorEntity):
    """Narastające zużycie w strefie (od dodania punktu) -- źródło dla panelu Energia."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(self, punkt: Punkt, strefa: str) -> None:
        super().__init__(punkt, "energia_strefy", strefa=strefa)

    @property
    def native_value(self) -> float:
        return round(float(self._punkt.stan.get("energia", {}).get(self._strefa, 0.0)), 4)


class EnergiaDzisStrefy(EncjaPunktu, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2

    def __init__(self, punkt: Punkt, strefa: str) -> None:
        super().__init__(punkt, "energia_dzis_strefy", strefa=strefa)

    @property
    def native_value(self) -> float:
        return round(self._punkt.energia_okresu("dzien").get(self._strefa, 0.0), 4)
