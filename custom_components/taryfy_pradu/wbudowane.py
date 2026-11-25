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

WZORCE = {
    "tauron_g13_2026": {"nazwa": "TAURON G13 (2026)", "taryfa": TAURON_G13, "cennik": CENNIK_G13_2026},
    "tauron_g13s_2026": {"nazwa": "TAURON G13s (2026)", "taryfa": TAURON_G13S, "cennik": CENNIK_G13S_2026},
}


def wzorzec(klucz: str) -> dict:
    """Głęboka kopia wzorca (żeby edycja w kreatorze nie psuła stałych)."""
    return copy.deepcopy(WZORCE[klucz])
