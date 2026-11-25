# Changelog

Wszystkie istotne zmiany w tym projekcie. Format: [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersje: [SemVer](https://semver.org/lang/pl/).

## [Unreleased]

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
