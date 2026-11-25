"""Porównanie taryf na rzeczywistym zużyciu godzinowym (bez Home Assistanta).

Zużycie: lista (początek godziny UTC, kWh) -- np. ze statystyk długoterminowych licznika.
Każda godzina idzie do strefy z połowy godziny (granice stref wypadają na pełnych godzinach).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta

from .cennik import BladCennika, Cennik
from .taryfa import Okno, STREFA_CZASOWA, Taryfa

POLOWA_GODZINY = timedelta(minutes=30)
# rekomendacja zmiany: wariant tańszy co najmniej o tyle procent i złotych (w porównywanym okresie)
PROG_PROC = 3.0
PROG_ZL = 5.0


def dni_okresu(od: datetime, do: datetime) -> list[date]:
    """Dni lokalne w [od, do)."""
    d, koniec = od.astimezone(STREFA_CZASOWA).date(), (do - timedelta(seconds=1)).astimezone(STREFA_CZASOWA).date()
    wynik = []
    while d <= koniec:
        wynik.append(d)
        d += timedelta(days=1)
    return wynik


def koszt(
    godziny: Iterable[tuple[datetime, float]],
    dni: list[date],
    okno: Callable[[datetime], Okno],
    cena: Callable[[Okno], float],
    stale_dzienne: Callable[[date], float],
) -> dict[str, float] | None:
    """Koszt brutto: energia (godzina po godzinie) + opłaty stałe za dni okresu. None = brak stawki."""
    energia = 0.0
    kwh_razem = 0.0
    strefy: dict[str, float] = {}
    try:
        for t, kwh in godziny:
            if kwh <= 0:
                continue
            o = okno(t + POLOWA_GODZINY)
            energia += kwh * cena(o)
            kwh_razem += kwh
            strefy[o.strefa] = strefy.get(o.strefa, 0.0) + kwh
    except BladCennika:
        return None
    stale = sum(stale_dzienne(d) for d in dni)
    return {"energia": energia, "stale": stale, "razem": energia + stale, "kwh": kwh_razem, "strefy": strefy}


def koszt_wariantu(godziny, dni, taryfa: Taryfa, cennik: Cennik) -> dict[str, float] | None:
    return koszt(godziny, dni, taryfa.okno, cennik.cena_brutto, cennik.stale_dzienne_brutto)


def ranking(obecna: dict | None, warianty: dict[str, dict | None], nazwa_obecnej: str) -> dict:
    """Zestawienie: koszty od najniższego, najtańszy wariant, oszczędność i rekomendacja."""
    pozycje = []
    if obecna:
        pozycje.append({"nazwa": nazwa_obecnej, "obecna": True, **_zaokr(obecna)})
    for nazwa, k in warianty.items():
        if k:
            pozycje.append({"nazwa": nazwa, "obecna": False, **_zaokr(k)})
    pozycje.sort(key=lambda p: p["razem"])
    wynik: dict = {"koszty": pozycje}
    if not obecna or not pozycje:
        return wynik
    najtanszy = pozycje[0]
    oszcz = obecna["razem"] - najtanszy["razem"]
    proc = 100 * oszcz / obecna["razem"] if obecna["razem"] else 0.0
    wynik.update(
        najtanszy=najtanszy["nazwa"],
        oszczednosc_zl=round(max(oszcz, 0.0), 2),
        oszczednosc_proc=round(max(proc, 0.0), 1),
        oplaca_sie=(not najtanszy["obecna"]) and oszcz >= PROG_ZL and proc >= PROG_PROC,
    )
    return wynik


def _zaokr(k: dict) -> dict:
    return {
        "energia": round(k["energia"], 2), "stale": round(k["stale"], 2), "razem": round(k["razem"], 2),
        "kwh": round(k["kwh"], 1), "strefy": {s: round(v, 1) for s, v in k["strefy"].items()},
    }
