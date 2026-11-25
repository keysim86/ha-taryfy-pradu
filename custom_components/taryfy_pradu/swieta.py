"""Dni ustawowo wolne od pracy w Polsce (ustawa z 18 stycznia 1951 r. z późn. zm.).

Bez zależności od Home Assistanta -- używane przez silnik taryf i testy.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def wielkanoc(rok: int) -> date:
    """Niedziela Wielkanocna (algorytm Meeusa/Jonesa/Butchera, kalendarz gregoriański)."""
    a = rok % 19
    b, c = divmod(rok, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    miesiac, dzien = divmod(h + l - 7 * m + 114, 31)
    return date(rok, miesiac, dzien + 1)


@lru_cache(maxsize=64)
def swieta(rok: int) -> dict[date, str]:
    """Dni ustawowo wolne od pracy w danym roku: {data: nazwa}."""
    w = wielkanoc(rok)
    dni = {
        date(rok, 1, 1): "Nowy Rok",
        date(rok, 5, 1): "Święto Pracy",
        date(rok, 5, 3): "Święto Konstytucji 3 Maja",
        date(rok, 8, 15): "Wniebowzięcie NMP",
        date(rok, 11, 1): "Wszystkich Świętych",
        date(rok, 11, 11): "Narodowe Święto Niepodległości",
        date(rok, 12, 25): "Boże Narodzenie (pierwszy dzień)",
        date(rok, 12, 26): "Boże Narodzenie (drugi dzień)",
        w: "Wielkanoc",
        w + timedelta(days=1): "Poniedziałek Wielkanocny",
        w + timedelta(days=49): "Zesłanie Ducha Świętego",
        w + timedelta(days=60): "Boże Ciało",
    }
    if rok >= 2011:
        dni[date(rok, 1, 6)] = "Trzech Króli"
    if rok >= 2025:
        dni[date(rok, 12, 24)] = "Wigilia Bożego Narodzenia"
    return dni


def swieto(d: date) -> str | None:
    """Nazwa święta albo None."""
    return swieta(d.year).get(d)


def dzien_wolny(d: date) -> bool:
    """Sobota, niedziela albo dzień ustawowo wolny od pracy."""
    return d.isoweekday() >= 6 or d in swieta(d.year)
