"""Wbudowane taryfy i domyślne cenniki dystrybucji.

Źródło: Taryfa TAURON Dystrybucja S.A. na rok 2026 (decyzja Prezesa URE
DRE.WRE.4211.54.8.2025.ASa1 z 17.12.2025) — wyciąg dla grup G, pkt 2.2.2 i 2.2.2a
(strefy), tabele 7.1, 7.3, 7.4 i pkt 7.5–7.7 (stawki netto).

Wzorce do kreatora: użytkownik wybiera wzorzec, a potem może zmienić wszystko
(godziny, sezony, ceny). Energia od sprzedawcy jest pusta — wpisuje się ją z faktury.
"""

from __future__ import annotations

import copy

_SEZONY_LATO_ZIMA = [
    {"id": "lato", "nazwa": "Lato", "od": "04-01", "do": "09-30"},
    {"id": "zima", "nazwa": "Zima", "od": "10-01", "do": "03-31"},
]

TAURON_G13 = {
    "nazwa": "G13",
    "operator": "TAURON Dystrybucja",
    "zrodlo": "Taryfa TAURON Dystrybucja 2026, pkt 2.2.2",
    "czas": "lokalny",
    "dni": "roboczy_wolny",
    "strefy": [
        {"id": "pozostale", "nazwa": "Pozostałe godziny doby"},
        {"id": "przedpoludniowa", "nazwa": "Szczyt przedpołudniowy"},
        {"id": "popoludniowa", "nazwa": "Szczyt popołudniowy"},
    ],
    "sezony": copy.deepcopy(_SEZONY_LATO_ZIMA),
    "godziny": {
        "lato": {
            "roboczy": {"przedpoludniowa": "07:00-13:00", "popoludniowa": "19:00-22:00",
                        "pozostale": "13:00-19:00, 22:00-07:00"},
            "wolny": {"pozostale": "00:00-24:00"},
        },
        "zima": {
            "roboczy": {"przedpoludniowa": "07:00-13:00", "popoludniowa": "16:00-21:00",
                        "pozostale": "13:00-16:00, 21:00-07:00"},
            "wolny": {"pozostale": "00:00-24:00"},
        },
    },
}

_G13S_GODZINY = {
    "lato": {"nocna": "21:00-07:00", "szczytowa": "07:00-09:00, 17:00-21:00",
             "pozaszczytowa": "09:00-17:00"},
    "zima": {"nocna": "21:00-07:00", "szczytowa": "07:00-10:00, 15:00-21:00",
             "pozaszczytowa": "10:00-15:00"},
}

TAURON_G13S = {
    "nazwa": "G13s",
    "operator": "TAURON Dystrybucja",
    "zrodlo": "Taryfa TAURON Dystrybucja 2026, pkt 2.2.2a",
    "czas": "lokalny",
    "dni": "roboczy_wolny",
    "strefy": [
        {"id": "nocna", "nazwa": "Nocna"},
        {"id": "pozaszczytowa", "nazwa": "Dzienna pozaszczytowa"},
        {"id": "szczytowa", "nazwa": "Dzienna szczytowa"},
    ],
    "sezony": copy.deepcopy(_SEZONY_LATO_ZIMA),
    # godziny takie same w dni robocze i wolne -- od rodzaju dnia zależy tylko stawka
    "godziny": {s: {"roboczy": dict(g), "wolny": dict(g)} for s, g in _G13S_GODZINY.items()},
}

# Wspólne dla grup G (2026, netto)
_ZA_KWH_2026 = {"jakosciowa": 0.0331, "oze": 0.0073, "kogeneracyjna": 0.0030}
_STALE_2026 = {
    "sieciowa_stala": 10.86,  # układ 3-fazowy; 1-fazowy 7,38
    "abonamentowa": 4.56,
    "mocowa": 24.05,          # zużycie roczne > 2800 kWh; 1200-2800: 17,18; 500-1200: 10,31; < 500: 4,29
    "handlowa": 0.0,
}

CENNIK_G13_2026 = {
    "vat": 23.0,
    "zmienne": {
        "energia": {"wymiary": ["strefa"], "stawki": {}},
        "dystrybucja": {"wymiary": ["strefa"], "stawki": {
            "przedpoludniowa": 0.2203, "popoludniowa": 0.3898, "pozostale": 0.0392}},
    },
    "za_kwh": dict(_ZA_KWH_2026),
    "stale": dict(_STALE_2026),
}

CENNIK_G13S_2026 = {
    "vat": 23.0,
    "zmienne": {
        "energia": {"wymiary": ["strefa"], "stawki": {}},
        "dystrybucja": {"wymiary": ["sezon", "dzien", "strefa"], "stawki": {
            "lato|roboczy|pozaszczytowa": 0.1000, "lato|roboczy|szczytowa": 0.2842,
            "lato|roboczy|nocna": 0.1094,
            "lato|wolny|pozaszczytowa": 0.0400, "lato|wolny|szczytowa": 0.1176,
            "lato|wolny|nocna": 0.1094,
            "zima|roboczy|pozaszczytowa": 0.1999, "zima|roboczy|szczytowa": 0.3332,
            "zima|roboczy|nocna": 0.1094,
            "zima|wolny|pozaszczytowa": 0.1200, "zima|wolny|szczytowa": 0.1960,
            "zima|wolny|nocna": 0.1094,
        }},
    },
    "za_kwh": dict(_ZA_KWH_2026),
    "stale": dict(_STALE_2026),
}

_ROK = [{"id": "rok", "nazwa": "Cały rok", "od": "01-01", "do": "12-31"}]

TAURON_G11 = {
    "nazwa": "G11", "operator": "TAURON Dystrybucja", "zrodlo": "Taryfa TAURON Dystrybucja 2026",
    "czas": "lokalny", "dni": "jednakowe",
    "strefy": [{"id": "calodobowa", "nazwa": "Całodobowa"}],
    "sezony": copy.deepcopy(_ROK),
    "godziny": {"rok": {"roboczy": {"calodobowa": "00:00-24:00"}}},
}

TAURON_G12 = {
    "nazwa": "G12", "operator": "TAURON Dystrybucja", "zrodlo": "Taryfa TAURON Dystrybucja 2026, pkt 2.2",
    "czas": "lokalny", "dni": "jednakowe",
    "strefy": [{"id": "nocna", "nazwa": "Nocna"}, {"id": "dzienna", "nazwa": "Dzienna"}],
    "sezony": copy.deepcopy(_ROK),
    "godziny": {"rok": {"roboczy": {"dzienna": "06:00-13:00, 15:00-22:00", "nocna": "13:00-15:00, 22:00-06:00"}}},
}

TAURON_G12W = {
    "nazwa": "G12w", "operator": "TAURON Dystrybucja", "zrodlo": "Taryfa TAURON Dystrybucja 2026, pkt 2.2",
    "czas": "lokalny", "dni": "roboczy_wolny",
    "strefy": [{"id": "pozaszczytowa", "nazwa": "Pozaszczytowa"}, {"id": "szczytowa", "nazwa": "Szczytowa"}],
    "sezony": copy.deepcopy(_ROK),
    "godziny": {"rok": {
        "roboczy": {"szczytowa": "06:00-13:00, 15:00-22:00", "pozaszczytowa": "13:00-15:00, 22:00-06:00"},
        "wolny": {"pozaszczytowa": "00:00-24:00"},
    }},
}

# G12as: nocna stawka dystrybucji 0,0246 tylko dla zużycia PONAD zużycie z analogicznego okresu
# poprzedniego roku (do tego poziomu 0,2464) -- tego progu integracja nie liczy (wzorzec: 0,2464).
TAURON_G12AS = {
    "nazwa": "G12as", "operator": "TAURON Dystrybucja", "zrodlo": "Taryfa TAURON Dystrybucja 2026, pkt 2.2",
    "czas": "lokalny", "dni": "jednakowe",
    "strefy": [{"id": "nocna", "nazwa": "Nocna"}, {"id": "dzienna", "nazwa": "Dzienna"}],
    "sezony": copy.deepcopy(_ROK),
    "godziny": {"rok": {"roboczy": {"dzienna": "06:00-22:00", "nocna": "22:00-06:00"}}},
}

TAURON_G14DYNAMIC = {
    "nazwa": "G14dynamic", "operator": "TAURON Dystrybucja",
    "zrodlo": "Taryfa TAURON Dystrybucja 2026; strefy: PSE Energetyczny Kompas",
    "typ": "dynamiczna", "zrodlo_stref": "pse_kompas", "domyslna": "s2",
    "czas": "lokalny", "dni": "jednakowe",
    "strefy": [
        {"id": "s1", "nazwa": "Zalecane użytkowanie"},
        {"id": "s2", "nazwa": "Normalne użytkowanie"},
        {"id": "s3", "nazwa": "Zalecane oszczędzanie"},
        {"id": "s4", "nazwa": "Wymagane ograniczenie"},
    ],
    "sezony": copy.deepcopy(_ROK),
}


def _cennik(dystrybucja: dict, wymiary: list | None = None, stale: dict | None = None) -> dict:
    return {
        "vat": 23.0,
        "zmienne": {
            "energia": {"wymiary": ["strefa"], "stawki": {}},
            "dystrybucja": {"wymiary": ["strefa"] if wymiary is None else wymiary, "stawki": dystrybucja},
        },
        "za_kwh": dict(_ZA_KWH_2026),
        "stale": dict(_STALE_2026, **(stale or {})),
    }


CENNIK_G11_2026 = _cennik({"*": 0.2464}, wymiary=[])
CENNIK_G11_2026["zmienne"]["energia"]["wymiary"] = []
CENNIK_G12_2026 = _cennik({"dzienna": 0.2841, "nocna": 0.0558})
CENNIK_G12W_2026 = _cennik({"szczytowa": 0.3298, "pozaszczytowa": 0.0512})
CENNIK_G12AS_2026 = _cennik({"dzienna": 0.2464, "nocna": 0.2464},
                            stale={"sieciowa_stala": 21.72})  # 3-faz.; 1-faz. 14,76
CENNIK_G14DYNAMIC_2026 = _cennik({"s1": 0.0224, "s2": 0.0893, "s3": 0.3881, "s4": 2.3756})

WZORCE = {
    "tauron_g13_2026": {"nazwa": "TAURON G13 (2026)", "taryfa": TAURON_G13, "cennik": CENNIK_G13_2026},
    "tauron_g13s_2026": {"nazwa": "TAURON G13s (2026)", "taryfa": TAURON_G13S, "cennik": CENNIK_G13S_2026},
    "tauron_g11_2026": {"nazwa": "TAURON G11 (2026)", "taryfa": TAURON_G11, "cennik": CENNIK_G11_2026},
    "tauron_g12_2026": {"nazwa": "TAURON G12 (2026)", "taryfa": TAURON_G12, "cennik": CENNIK_G12_2026},
    "tauron_g12w_2026": {"nazwa": "TAURON G12w (2026)", "taryfa": TAURON_G12W, "cennik": CENNIK_G12W_2026},
    "tauron_g12as_2026": {"nazwa": "TAURON G12as (2026)", "taryfa": TAURON_G12AS, "cennik": CENNIK_G12AS_2026},
    "tauron_g14dynamic_2026": {"nazwa": "TAURON G14dynamic (2026, strefy z PSE)", "taryfa": TAURON_G14DYNAMIC,
                               "cennik": CENNIK_G14DYNAMIC_2026},
}


def wzorzec(klucz: str) -> dict:
    """Głęboka kopia wzorca (żeby edycja w kreatorze nie psuła stałych)."""
    return copy.deepcopy(WZORCE[klucz])
