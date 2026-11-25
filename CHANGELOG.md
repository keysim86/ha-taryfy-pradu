# Changelog

Wszystkie istotne zmiany w tym projekcie. Format: [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersje: [SemVer](https://semver.org/lang/pl/).

## [Unreleased]

## [0.1.1] - 2026-11-25

### Dodano

- Sensory łącznego zużycia: „Energia dziś” i „Energia w tym miesiącu” (wszystkie strefy, atrybut z podziałem).

### Naprawiono

- Rekomendacja porównania z polskim zapisem liczb (112,57 zł, 13,9%).

## [0.1.0] - 2026-11-25

### Dodano

- Silnik taryf strefowych: strefy, sezony, dni robocze i wolne (soboty, niedziele, dni ustawowo wolne
  z Wigilią od 2025 i świętami ruchomymi), czas stref lokalny albo zimowy, poprawne doby zmiany czasu.
- Wzorce TAURON Dystrybucja G13 i G13s na 2026 r. (godziny stref i stawki dystrybucji netto).
- Kreator taryf w panelu (podwpis „Taryfa”): wzorzec albo pusta taryfa, podstawy, godziny dla każdego sezonu
  i rodzaju dnia z kontrolą pokrycia doby; edycja tym samym kreatorem.
- Punkt poboru (podwpis): licznik energii, taryfa, cennik ze składników faktury (składniki zmienne zależne od
  sezonu / rodzaju dnia / strefy, opłaty za kWh, opłaty stałe, VAT), cenniki od wybranego dnia.
- Encje: strefa (z planem i cenami na dziś i jutro), cena brutto, następna strefa i zmiana, koszty dziś /
  miesiąc / rok, narastający koszt energii, energia w strefach, najtańsza / najdroższa strefa teraz,
  dzień wolny, kalendarz stref.
- Zdarzenie `taryfy_pradu_zmiana_strefy`, usługi `taryfy_pradu.najtanszy_przedzial` i `taryfy_pradu.cena`.
- Brand integracji (ikona i logo, jasne i ciemne) z generatorem `assets/brand.py`.
- Wzorce TAURON G11, G12, G12w, G12as i G14dynamic (2026).
- Taryfy dynamiczne: strefy G14dynamic z Energetycznego Kompasu PSE (raport `pdgsz`), pobierane co 30 min,
  zapisywane w stanie punktu; dla godzin bez danych strefa domyślna.
- Harmonogram punktu: każdy cennik ma własną taryfę — zmiana cen i/lub taryfy od wybranego dnia; encje stref
  wszystkich taryf z harmonogramu powstają od razu.
- Porównanie taryf: warianty (taryfa + cennik oferty), koszt na rzeczywistym zużyciu godzinowym z ostatnich 30 dni
  i 12 miesięcy, encje „Najtańsza taryfa”, „Możliwa oszczędność”, „Opłaca się zmiana taryfy”, usługa
  `taryfy_pradu.porownaj_taryfy`.

### Zmieniono

- Porównanie taryf nie liczy opłaty handlowej (zależy od wybranej oferty sprzedawcy, nie od taryfy).
- Cennik ma opcjonalną nazwę oferty (np. „Tanie Godziny”) — pokazywaną przy obecnej pozycji porównania.

### Naprawiono

- Domyślna opłata jakościowa we wzorcach: 0,0332 zł/kWh (zgodnie z fakturami i tauron.pl; wyciąg z taryfy
  OSD podawał 0,0331).
- Testy uruchamiane samym `pytest` (CI) nie znajdowały pakietu integracji.
