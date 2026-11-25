"""Strefy G14dynamic z Energetycznego Kompasu PSE (raport `pdgsz` w API raporty.pse.pl).

`usage_fcst` na każdą godzinę doby handlowej:
0 = zalecane użytkowanie (S1), 1 = normalne użytkowanie (S2),
2 = zalecane oszczędzanie (S3), 3 = wymagane ograniczenie (S4).
PSE publikuje plan na następną dobę ok. 16:00 i może go korygować (nowe rekordy
`is_active`, stare dostają `valid_to_ts`) — liczą się tylko aktywne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

URL = "https://api.raporty.pse.pl/api/pdgsz"
STREFY = {0: "s1", 1: "s2", 2: "s3", 3: "s4"}
NAZWA_ZRODLA = "PSE — Energetyczny Kompas"


def parsuj(rekordy: list[dict[str, Any]]) -> dict[datetime, str]:
    """Rekordy API -> {początek godziny w UTC: strefa}."""
    wynik: dict[datetime, str] = {}
    for r in rekordy:
        if not r.get("is_active", True):
            continue
        try:
            t = datetime.fromisoformat(r["dtime_utc"]).replace(tzinfo=timezone.utc)
            wynik[t] = STREFY[int(r["usage_fcst"])]
        except (KeyError, ValueError, TypeError):
            continue
    return wynik


async def pobierz(sesja, dzien: date) -> dict[datetime, str]:
    """Aktywny plan stref na dobę handlową `dzien` (pusty, gdy PSE jeszcze nie opublikowało)."""
    params = {"$filter": f"business_date eq '{dzien.isoformat()}' and is_active eq true"}
    async with sesja.get(URL, params=params, timeout=30) as odp:
        odp.raise_for_status()
        dane = await odp.json()
    return parsuj(dane.get("value") or [])
