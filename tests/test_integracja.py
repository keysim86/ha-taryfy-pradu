"""Integracja w Home Assistancie: kreatory, encje, naliczanie, usługi, cenniki od dnia."""

from datetime import datetime

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.taryfy_pradu.const import DOMAIN

ZRODLO = "sensor.licznik_glowny"
ENERGIA = {"nocna": 0.50, "pozaszczytowa": 0.55, "szczytowa": 0.70}


async def _licznik(hass: HomeAssistant, kwh: float) -> None:
    hass.states.async_set(ZRODLO, str(kwh), {"unit_of_measurement": "kWh", "device_class": "energy",
                                              "state_class": "total_increasing"})
    await hass.async_block_till_done()


async def _wpis(hass: HomeAssistant):
    wynik = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    wynik = await hass.config_entries.flow.async_configure(wynik["flow_id"], {})
    assert wynik["type"] is FlowResultType.CREATE_ENTRY
    return hass.config_entries.async_entries(DOMAIN)[0]


async def _taryfa_g13s(hass: HomeAssistant, entry) -> str:
    fm = hass.config_entries.subentries
    w = await fm.async_init((entry.entry_id, "taryfa"), context={"source": SOURCE_USER})
    w = await fm.async_configure(w["flow_id"], {"wzorzec": "tauron_g13s_2026"})
    assert w["step_id"] == "podstawy"
    w = await fm.async_configure(w["flow_id"], {
        "nazwa": "G13s", "operator": "TAURON Dystrybucja", "czas": "lokalny", "dni": "roboczy_wolny",
        "strefy": "Nocna\nDzienna pozaszczytowa\nDzienna szczytowa",
        "sezony": "Lato: 04-01 .. 09-30\nZima: 10-01 .. 03-31",
    })
    # 4 kroki godzin: lato/roboczy, lato/wolny, zima/roboczy, zima/wolny -- wzorzec podpowiada
    godziny = {
        "lato": {"Nocna": "21:00-07:00", "Dzienna szczytowa": "07:00-09:00, 17:00-21:00",
                 "Dzienna pozaszczytowa": "09:00-17:00"},
        "zima": {"Nocna": "21:00-07:00", "Dzienna szczytowa": "07:00-10:00, 15:00-21:00",
                 "Dzienna pozaszczytowa": "10:00-15:00"},
    }
    for sezon in ("lato", "zima"):
        assert w["step_id"] == "godziny"
        w = await fm.async_configure(w["flow_id"], godziny[sezon])
        assert w["step_id"] == "godziny"
        w = await fm.async_configure(w["flow_id"], {"jak_roboczy": True})
    assert w["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    return next(sid for sid, s in entry.subentries.items() if s.subentry_type == "taryfa")


async def _punkt(hass: HomeAssistant, entry, taryfa_id: str) -> None:
    fm = hass.config_entries.subentries
    w = await fm.async_init((entry.entry_id, "punkt"), context={"source": SOURCE_USER})
    w = await fm.async_configure(w["flow_id"], {"nazwa": "Dom", "zrodlo": ZRODLO, "taryfa": taryfa_id})
    assert w["step_id"] == "wymiary"
    w = await fm.async_configure(w["flow_id"], {"energia": ["strefa"], "dystrybucja": ["sezon", "dzien", "strefa"]})
    assert w["step_id"] == "stawki"
    pola = {str(k): k for k in w["data_schema"].schema}
    dane = {}
    for etykieta in pola:
        if etykieta.startswith("Energia czynna"):
            strefa = {"Nocna": "nocna", "Dzienna pozaszczytowa": "pozaszczytowa",
                      "Dzienna szczytowa": "szczytowa"}[etykieta.split("— ")[1]]
            dane[etykieta] = ENERGIA[strefa]
    # reszta z podpowiedzi wzorca (dystrybucja 2026)
    for k in w["data_schema"].schema:
        if str(k) not in dane:
            sugestia = (k.description or {}).get("suggested_value")
            dane[str(k)] = sugestia if sugestia is not None else k.default()
    w = await fm.async_configure(w["flow_id"], dane)
    assert w["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


@pytest.fixture
async def uruchomione(hass: HomeAssistant, freezer):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    freezer.move_to(datetime.fromisoformat("2026-11-25T16:33:00+01:00"))
    await _licznik(hass, 1000.0)
    entry = await _wpis(hass)
    taryfa_id = await _taryfa_g13s(hass, entry)
    await _punkt(hass, entry, taryfa_id)
    await hass.async_block_till_done()
    return hass.config_entries.async_get_entry(entry.entry_id)


async def test_encje_strefy_i_ceny(hass: HomeAssistant, uruchomione) -> None:
    assert hass.states.get("sensor.dom_strefa").state == "Dzienna szczytowa"
    cena = float(hass.states.get("sensor.dom_cena").state)
    assert cena == pytest.approx((0.70 + 0.3332 + 0.0332 + 0.0073 + 0.0030) * 1.23, abs=1e-4)
    assert hass.states.get("sensor.dom_nastepna_strefa").state == "Nocna"
    assert hass.states.get("sensor.dom_zmiana_strefy").state == "2026-11-25T20:00:00+00:00"
    a = hass.states.get("sensor.dom_strefa").attributes
    assert a["rodzaj_dnia"] == "roboczy" and a["sezon"] == "zima"
    assert len(a["plan_godzinowy_dzis"]) == 24
    assert hass.states.get("binary_sensor.dom_najdrozsza_strefa_teraz").state == "on"
    assert hass.states.get("binary_sensor.dom_najtansza_strefa_teraz").state == "off"
    assert hass.states.get("binary_sensor.dom_dzien_wolny_wg_taryfy").state == "off"
    assert hass.states.get("calendar.dom_strefy").attributes["message"] == "Dzienna szczytowa"


async def test_naliczanie_energii_i_kosztu(hass: HomeAssistant, uruchomione, freezer) -> None:
    await _licznik(hass, 1001.5)  # +1,5 kWh w szczycie
    cena = float(hass.states.get("sensor.dom_cena").state)
    assert float(hass.states.get("sensor.dom_energia_dzienna_szczytowa").state) == pytest.approx(1.5)
    assert float(hass.states.get("sensor.dom_koszt_energii_narastajaco").state) == pytest.approx(1.5 * cena, abs=1e-3)
    # noc: +2 kWh po cenie nocnej
    freezer.move_to(datetime.fromisoformat("2026-11-25T22:00:00+01:00"))
    await _licznik(hass, 1003.5)
    assert float(hass.states.get("sensor.dom_energia_nocna").state) == pytest.approx(2.0)
    koszt_dzis = hass.states.get("sensor.dom_koszt_dzis")
    assert koszt_dzis.attributes["zuzycie_kwh"] == {"szczytowa": 1.5, "nocna": 2.0}
    assert float(hass.states.get("sensor.dom_energia_dzis").state) == pytest.approx(3.5)
    assert float(hass.states.get("sensor.dom_energia_w_tym_miesiacu").state) == pytest.approx(3.5)
    stale_dzien = (10.86 + 4.56 + 24.05) * 1.23 / 30
    assert koszt_dzis.attributes["oplaty_stale"] == pytest.approx(stale_dzien, abs=0.01)
    # spadek licznika (wymiana) nie nalicza
    await _licznik(hass, 5.0)
    await _licznik(hass, 6.0)
    assert float(hass.states.get("sensor.dom_energia_nocna").state) == pytest.approx(3.0)


async def test_uslugi(hass: HomeAssistant, uruchomione) -> None:
    wynik = await hass.services.async_call(
        DOMAIN, "najtanszy_przedzial",
        {"encja": "sensor.dom_cena", "czas_trwania": {"hours": 2}},
        blocking=True, return_response=True,
    )
    # od 16:33 w ciągu doby: najtaniej w nocy (nocna 0,50 + 0,1094 < pozaszczytowa 0,55 + 0,1999)
    assert wynik["start"] == "2026-11-25T21:00:00+01:00"
    assert wynik["koniec"] == "2026-11-25T23:00:00+01:00"
    cena = await hass.services.async_call(
        DOMAIN, "cena", {"encja": "sensor.dom_cena", "chwila": "2026-11-28 12:00:00"},
        blocking=True, return_response=True,
    )
    assert cena["strefa"] == "pozaszczytowa" and cena["rodzaj_dnia"] == "wolny"
    assert cena["cena"] == pytest.approx((0.55 + 0.1200 + 0.0435) * 1.23, abs=1e-4)


async def test_nowy_cennik_od_dnia(hass: HomeAssistant, uruchomione, freezer) -> None:
    entry = uruchomione
    punkt_id = next(sid for sid, s in entry.subentries.items() if s.subentry_type == "punkt")
    fm = hass.config_entries.subentries
    w = await fm.async_init((entry.entry_id, "punkt"),
                            context={"source": SOURCE_RECONFIGURE, "subentry_id": punkt_id})
    assert w["type"] is FlowResultType.MENU
    w = await fm.async_configure(w["flow_id"], {"next_step_id": "nowy_cennik"})
    w = await fm.async_configure(w["flow_id"], {"od": "2027-01-01"})
    w = await fm.async_configure(w["flow_id"], {"energia": [], "dystrybucja": ["sezon", "dzien", "strefa"]})
    dane = {}
    for k in w["data_schema"].schema:
        if str(k).startswith("Energia czynna"):
            dane[str(k)] = 0.40
        else:
            sugestia = (k.description or {}).get("suggested_value")
            dane[str(k)] = sugestia if sugestia is not None else k.default()
    w = await fm.async_configure(w["flow_id"], dane)
    assert w["type"] is FlowResultType.ABORT and w["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    # dziś stary cennik
    assert float(hass.states.get("sensor.dom_cena").state) == pytest.approx(
        (0.70 + 0.3332 + 0.0435) * 1.23, abs=1e-4)
    # w nowym roku nowy (energia 0,40 bez podziału na strefy)
    cena = await hass.services.async_call(
        DOMAIN, "cena", {"encja": "sensor.dom_cena", "chwila": "2027-01-04 16:00:00"},
        blocking=True, return_response=True,
    )
    assert cena["cena"] == pytest.approx((0.40 + 0.3332 + 0.0435) * 1.23, abs=1e-4)


async def test_kreator_wykrywa_luke_w_godzinach(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Warsaw")
    entry = await _wpis(hass)
    fm = hass.config_entries.subentries
    w = await fm.async_init((entry.entry_id, "taryfa"), context={"source": SOURCE_USER})
    w = await fm.async_configure(w["flow_id"], {"wzorzec": "pusta"})
    w = await fm.async_configure(w["flow_id"], {
        "nazwa": "G12", "operator": "", "czas": "lokalny", "dni": "jednakowe",
        "strefy": "Dzienna\nNocna", "sezony": "Cały rok: 01-01 .. 12-31",
    })
    w = await fm.async_configure(w["flow_id"], {"Dzienna": "06-13, 15-22", "Nocna": "22-6"})
    assert w["type"] is FlowResultType.FORM and w["errors"] == {"base": "blad_taryfy"}
    assert "13:00" in w["description_placeholders"]["blad"]
    w = await fm.async_configure(w["flow_id"], {"Dzienna": "06-13, 15-22", "Nocna": "22-6, 13-15"})
    assert w["type"] is FlowResultType.CREATE_ENTRY


async def test_encje_przypisane_do_podwpisu(hass: HomeAssistant, uruchomione) -> None:
    reg = er.async_get(hass)
    wpis = reg.async_get("sensor.dom_cena")
    assert wpis.config_subentry_id in uruchomione.subentries


async def test_zmiana_strefy_przez_zegar(hass: HomeAssistant, uruchomione, freezer) -> None:
    from pytest_homeassistant_custom_component.common import async_capture_events, async_fire_time_changed

    zdarzenia = async_capture_events(hass, f"{DOMAIN}_zmiana_strefy")
    chwila = datetime.fromisoformat("2026-11-25T21:00:02+01:00")
    freezer.move_to(chwila)
    async_fire_time_changed(hass, chwila)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.dom_strefa").state == "Nocna"
    assert hass.states.get("binary_sensor.dom_najtansza_strefa_teraz").state == "on"
    assert len(zdarzenia) == 1
    assert zdarzenia[0].data["strefa"] == "nocna" and zdarzenia[0].data["poprzednia"] == "szczytowa"


async def test_stan_po_przeladowaniu(hass: HomeAssistant, uruchomione) -> None:
    await _licznik(hass, 1002.0)
    assert float(hass.states.get("sensor.dom_energia_dzienna_szczytowa").state) == pytest.approx(2.0)
    assert await hass.config_entries.async_reload(uruchomione.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.dom_energia_dzienna_szczytowa").state) == pytest.approx(2.0)
    await _licznik(hass, 1002.5)
    assert float(hass.states.get("sensor.dom_energia_dzienna_szczytowa").state) == pytest.approx(2.5)


# --- rozszerzenia: wzorce, harmonogram taryf, G14dynamic, porównanie -------------------------

async def _taryfa_ze_wzorca(hass: HomeAssistant, entry, wzorzec: str, nazwa: str) -> str:
    """Taryfa przez kreator z podpowiedziami wzorca; zwraca subentry_id."""
    fm = hass.config_entries.subentries
    przed = set(hass.config_entries.async_get_entry(entry.entry_id).subentries)
    w = await fm.async_init((entry.entry_id, "taryfa"), context={"source": SOURCE_USER})
    w = await fm.async_configure(w["flow_id"], {"wzorzec": wzorzec})
    while w["type"] is FlowResultType.FORM:
        dane = {}
        for k in w["data_schema"].schema:
            sug = (k.description or {}).get("suggested_value")
            dom = k.default() if callable(getattr(k, "default", None)) else None
            dane[str(k)] = sug if sug is not None else dom
        if w["step_id"] in ("podstawy", "dynamiczna"):
            dane["nazwa"] = nazwa
        dane = {k: v for k, v in dane.items() if v is not None and v != ""}
        w = await fm.async_configure(w["flow_id"], dane)
    assert w["type"] is FlowResultType.CREATE_ENTRY, w
    await hass.async_block_till_done()
    po = hass.config_entries.async_get_entry(entry.entry_id).subentries
    return next(iter(set(po) - przed))


def _stawki(w, energia: float) -> dict:
    dane = {}
    for k in w["data_schema"].schema:
        if str(k).startswith("Energia czynna"):
            dane[str(k)] = energia
        else:
            sug = (k.description or {}).get("suggested_value")
            dane[str(k)] = sug if sug is not None else k.default()
    return dane


async def _rekonfiguruj(hass, entry, krok: str):
    punkt_id = next(sid for sid, s in entry.subentries.items() if s.subentry_type == "punkt")
    fm = hass.config_entries.subentries
    w = await fm.async_init((entry.entry_id, "punkt"), context={"source": SOURCE_RECONFIGURE, "subentry_id": punkt_id})
    return fm, await fm.async_configure(w["flow_id"], {"next_step_id": krok})


async def test_zmiana_taryfy_od_dnia(hass: HomeAssistant, uruchomione, freezer) -> None:
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entry = uruchomione
    g12w = await _taryfa_ze_wzorca(hass, entry, "tauron_g12w_2026", "G12w")
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    fm, w = await _rekonfiguruj(hass, entry, "nowy_cennik")
    w = await fm.async_configure(w["flow_id"], {"od": "2026-11-26", "taryfa": g12w})
    w = await fm.async_configure(w["flow_id"], {"energia": ["strefa"], "dystrybucja": ["strefa"]})
    w = await fm.async_configure(w["flow_id"], _stawki(w, 0.60))
    assert w["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    # dziś dalej G13s, jutro G12w
    assert hass.states.get("sensor.dom_strefa").state == "Dzienna szczytowa"
    cena = await hass.services.async_call(DOMAIN, "cena", {"encja": "sensor.dom_cena", "chwila": "2026-11-26 12:00:00"},
                                          blocking=True, return_response=True)
    assert cena["taryfa"] == "G12w" and cena["strefa"] == "szczytowa"
    assert cena["cena"] == pytest.approx((0.60 + 0.3298 + 0.0435) * 1.23, abs=1e-4)
    # następna zmiana: o północy (zmiana taryfy), a nie o 21:00? -- 21:00 jest wcześniej
    assert hass.states.get("sensor.dom_zmiana_strefy").state == "2026-11-25T20:00:00+00:00"
    # encje stref obu taryf istnieją od razu (bez przebudowy w dniu zmiany)
    assert hass.states.get("sensor.dom_energia_nocna") is not None
    # północ: od dziś G12w
    chwila = datetime.fromisoformat("2026-11-26T00:00:02+01:00")
    freezer.move_to(chwila)
    async_fire_time_changed(hass, chwila)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.dom_strefa").state == "Pozaszczytowa"
    assert hass.states.get("sensor.dom_strefa").attributes["taryfa"] == "G12w"
    await _licznik(hass, 1000.4)  # +0,4 kWh w nocy G12w = strefa pozaszczytowa
    assert float(hass.states.get("sensor.dom_energia_dzis_dzienna_pozaszczytowa").state) == pytest.approx(0.4)


async def test_g14dynamic_z_pse(hass: HomeAssistant, freezer, aioclient_mock) -> None:
    from custom_components.taryfy_pradu import pse

    await hass.config.async_set_time_zone("Europe/Warsaw")
    freezer.move_to(datetime.fromisoformat("2026-11-26T10:30:00+01:00"))
    plan = "322223333333333333333332"
    rekordy = [{"dtime_utc": (datetime(2026, 11, 25, 23) + __import__("datetime").timedelta(hours=i)).strftime("%Y-%m-%d %H:%M"),
                "usage_fcst": int(c) - 1, "is_active": True, "business_date": "2026-11-26"} for i, c in enumerate(plan)]
    aioclient_mock.get(pse.URL, json={"value": rekordy})
    await _licznik(hass, 500.0)
    entry = await _wpis(hass)
    g14 = await _taryfa_ze_wzorca(hass, entry, "tauron_g14dynamic_2026", "G14dynamic")
    fm = hass.config_entries.subentries
    w = await fm.async_init((entry.entry_id, "punkt"), context={"source": SOURCE_USER})
    w = await fm.async_configure(w["flow_id"], {"nazwa": "Dom", "zrodlo": ZRODLO, "taryfa": g14})
    w = await fm.async_configure(w["flow_id"], {"energia": ["strefa"], "dystrybucja": ["strefa"]})
    w = await fm.async_configure(w["flow_id"], _stawki(w, 0.50))
    assert w["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert aioclient_mock.call_count >= 1
    assert hass.states.get("sensor.dom_strefa").state == "Zalecane oszczędzanie"
    assert float(hass.states.get("sensor.dom_cena").state) == pytest.approx((0.50 + 0.3881 + 0.0435) * 1.23, abs=1e-4)
    a = hass.states.get("sensor.dom_strefa").attributes
    assert a["plan_godzinowy_dzis"] == [f"s{c}" for c in plan]
    assert a["strefy_znane_do"] == "2026-11-27T00:00:00+01:00"
    assert hass.states.get("sensor.dom_zmiana_strefy").state == "2026-11-26T22:00:00+00:00"


async def test_porownanie_wariantow(hass: HomeAssistant, uruchomione) -> None:
    from unittest.mock import patch

    from custom_components.taryfy_pradu.punkt import Punkt

    entry = uruchomione
    g11 = await _taryfa_ze_wzorca(hass, entry, "tauron_g11_2026", "G11")
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    fm, w = await _rekonfiguruj(hass, entry, "dodaj_wariant")
    w = await fm.async_configure(w["flow_id"], {"taryfa": g11, "nazwa": "G11 oferta"})
    w = await fm.async_configure(w["flow_id"], {"energia": [], "dystrybucja": []})
    w = await fm.async_configure(w["flow_id"], _stawki(w, 0.20))  # bardzo tania oferta
    assert w["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    async def zuzycie(self, od, do):
        godz, t = [], od
        while t < do:
            godz.append((t, 1.0))
            t += __import__("datetime").timedelta(hours=1)
        return godz

    with patch.object(Punkt, "_godziny_zuzycia", zuzycie):
        wynik = await hass.services.async_call(DOMAIN, "porownaj_taryfy", {"encja": "sensor.dom_cena"},
                                               blocking=True, return_response=True)
    await hass.async_block_till_done()
    r = wynik["30_dni"]
    assert r["dni"] == 30 and r["najtanszy"] == "G11 oferta" and r["oplaca_sie"] is True
    assert [p["nazwa"] for p in r["koszty"]] == ["G11 oferta", "Obecna (G13s)"]
    assert hass.states.get("sensor.dom_najtansza_taryfa_30_dni").state == "G11 oferta"
    assert hass.states.get("binary_sensor.dom_oplaca_sie_zmiana_taryfy").state == "on"
    assert float(hass.states.get("sensor.dom_mozliwa_oszczednosc_30_dni").state) == r["oszczednosc_zl"]
    assert "rok" in wynik and wynik["rok"]["dni"] == 365
