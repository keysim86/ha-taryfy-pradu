"""Cennik: składniki z faktury -> cena brutto za kWh w danym oknie taryfy i koszty stałe.

Cennik to słownik (zapisywany w konfiguracji HA, edytowany w panelu):

    {
      "vat": 23.0,                                   # %
      "zmienne": {                                   # netto zł/kWh, zależne od okna taryfy
        "energia":     {"wymiary": ["strefa"], "stawki": {"nocna": 0.5, ...}},
        "dystrybucja": {"wymiary": ["sezon", "dzien", "strefa"],
                        "stawki": {"zima|roboczy|nocna": 0.1094, ...}},
      },
      "za_kwh": {"jakosciowa": 0.0331, "oze": 0.0073, "kogeneracyjna": 0.0030},  # netto zł/kWh
      "stale": {"sieciowa_stala": 10.86, "abonamentowa": 4.56, "mocowa": 24.05,  # netto zł/mies.
                "handlowa": 0.0},
    }

Wymiary składnika zmiennego mówią, od czego zależy jego stawka: dowolny podzbiór
("sezon", "dzien", "strefa"), w tej kolejności; pusty = jedna stawka na wszystko
(klucz "*").

Bez zależności od Home Assistanta.
"""

from __future__ import annotations

import calendar
from datetime import date

from .taryfa import Okno, Taryfa

WYMIARY = ("sezon", "dzien", "strefa")
SKLADNIKI_ZMIENNE = ("energia", "dystrybucja")
SKLADNIKI_ZA_KWH = ("jakosciowa", "oze", "kogeneracyjna")
SKLADNIKI_STALE = ("sieciowa_stala", "abonamentowa", "mocowa", "handlowa")

NAZWY = {
    "energia": "Energia czynna (sprzedawca)",
    "dystrybucja": "Dystrybucja — składnik zmienny",
    "jakosciowa": "Opłata jakościowa",
    "oze": "Opłata OZE",
    "kogeneracyjna": "Opłata kogeneracyjna",
    "sieciowa_stala": "Dystrybucja — składnik stały",
    "abonamentowa": "Opłata abonamentowa",
    "mocowa": "Opłata mocowa",
    "handlowa": "Opłata handlowa (sprzedawca)",
}


class BladCennika(ValueError):
    """Brakuje stawki albo cennik jest niespójny z taryfą."""


def klucz(wymiary: list[str] | tuple[str, ...], okno_lub_klucz) -> str:
    """Klucz stawki: wartości wymiarów połączone „|”; bez wymiarów „*”."""
    if isinstance(okno_lub_klucz, Okno):
        wartosci = {"sezon": okno_lub_klucz.sezon, "dzien": okno_lub_klucz.dzien,
                    "strefa": okno_lub_klucz.strefa}
    else:
        wartosci = dict(zip(WYMIARY, okno_lub_klucz))
    czesci = [wartosci[w] for w in WYMIARY if w in wymiary]
    return "|".join(czesci) if czesci else "*"


def klucze_dla(taryfa: Taryfa, wymiary: list[str]) -> list[str]:
    """Wszystkie klucze stawek, jakie może dać taryfa dla danych wymiarów (do formularza)."""
    sezony = [s["id"] for s in taryfa.sezony]
    dni = ["roboczy", "wolny"] if taryfa.dni == "roboczy_wolny" else ["roboczy"]
    strefy = [s["id"] for s in taryfa.strefy]
    wynik: list[str] = []
    for s in sezony:
        for d in dni:
            for z in strefy:
                k = klucz(wymiary, (s, d, z))
                if k not in wynik:
                    wynik.append(k)
    return wynik


class Cennik:
    def __init__(self, dane: dict) -> None:
        self.dane = dane
        self.vat = float(dane.get("vat", 23.0))
        self.zmienne: dict = dane.get("zmienne") or {}
        self.za_kwh: dict = dane.get("za_kwh") or {}
        self.stale: dict = dane.get("stale") or {}

    @property
    def mnoznik_vat(self) -> float:
        return 1 + self.vat / 100

    def braki(self, taryfa: Taryfa) -> list[str]:
        """Opis brakujących stawek (pusta lista = cennik kompletny dla tej taryfy)."""
        wynik = []
        for nazwa in SKLADNIKI_ZMIENNE:
            sk = self.zmienne.get(nazwa)
            if not sk:
                continue  # składnik pominięty = 0
            for k in klucze_dla(taryfa, sk.get("wymiary") or []):
                if k not in (sk.get("stawki") or {}):
                    wynik.append(f"{NAZWY.get(nazwa, nazwa)}: brak stawki dla {k}")
        return wynik

    def skladowe_netto(self, okno: Okno) -> dict[str, float]:
        """Wszystkie składniki netto zł/kWh obowiązujące w oknie."""
        wynik: dict[str, float] = {}
        for nazwa, sk in self.zmienne.items():
            if not sk:
                continue
            k = klucz(sk.get("wymiary") or [], okno)
            stawki = sk.get("stawki") or {}
            if k not in stawki:
                raise BladCennika(f"{NAZWY.get(nazwa, nazwa)}: brak stawki dla {k}")
            wynik[nazwa] = float(stawki[k])
        for nazwa, v in self.za_kwh.items():
            wynik[nazwa] = float(v or 0)
        return wynik

    def cena_netto(self, okno: Okno) -> float:
        return sum(self.skladowe_netto(okno).values())

    def cena_brutto(self, okno: Okno) -> float:
        return self.cena_netto(okno) * self.mnoznik_vat

    def stale_miesieczne_netto(self) -> float:
        return sum(float(v or 0) for v in self.stale.values())

    def stale_miesieczne_brutto(self) -> float:
        return self.stale_miesieczne_netto() * self.mnoznik_vat

    def stale_dzienne_brutto(self, d: date) -> float:
        """Koszt stały brutto przypadający na dobę `d` (miesięczny / liczba dni miesiąca)."""
        return self.stale_miesieczne_brutto() / calendar.monthrange(d.year, d.month)[1]
