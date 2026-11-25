# Taryfy prądu

Integracja Home Assistant do śledzenia **bieżących kosztów energii elektrycznej według taryfy strefowej**:
która strefa obowiązuje teraz, ile kosztuje kWh, kiedy zmiana, ile kosztował dzisiejszy dzień,
miesiąc i rok — z uwzględnieniem sezonów, dni roboczych, weekendów i świąt.

- **Wbudowane wzorce:** TAURON Dystrybucja **G13** i **G13s** (taryfa na 2026 r.), z godzinami stref i stawkami dystrybucji.
- **Kreator taryf w panelu HA:** własne strefy, sezony, godziny dla dni roboczych i wolnych, czas lokalny albo zimowy.
- **Cennik ze składników faktury:** energia od sprzedawcy, dystrybucja zmienna i stała, opłaty jakościowa, OZE,
  kogeneracyjna, mocowa, abonamentowa, handlowa, VAT. Każdy składnik zmienny może zależeć od sezonu, rodzaju dnia i strefy.
- **Cenniki od dnia:** nowy cennik (np. nowa taryfa od 1 stycznia) wpisujesz wcześniej — integracja przełączy się sama,
  a wcześniejsze koszty zostają policzone po starych cenach.
- **Do automatyzacji:** sensory strefy i ceny, czujniki „najtańsza / najdroższa strefa teraz”, kalendarz stref,
  zdarzenie zmiany strefy i usługa „najtańszy przedział” (kiedy włączyć pralkę).

## Instalacja

Marketplace (HACS) → ⋮ → **Niestandardowe repozytoria** → `https://github.com/keysim86/ha-taryfy-pradu`, typ **Integracja**
→ zainstaluj **Taryfy prądu** → uruchom ponownie Home Assistanta → **Ustawienia → Urządzenia i usługi → Dodaj integrację →
Taryfy prądu**.

## Konfiguracja

1. **Dodaj taryfę** (w integracji: ⋮ / „Dodaj taryfę”). Wybierz wzorzec (G13s, G13) albo pustą taryfę. Kreator prowadzi przez:
   - **podstawy** — nazwa, operator, czas stref, rodzaje dni, lista stref, sezony (`Lato: 04-01 .. 09-30`);
   - **godziny stref** dla każdego sezonu i rodzaju dnia — np. `07:00-09:00, 17:00-21:00` albo `21-7`
     (przez północ). Kreator sprawdza, czy strefy pokrywają dobę dokładnie raz.
2. **Dodaj punkt poboru** — licznik energii (sensor kWh, narastający) i taryfa. Potem cennik:
   - **od czego zależą stawki** każdego składnika zmiennego (sezon / rodzaj dnia / strefa);
   - **stawki netto** z faktury — dystrybucja i opłaty są podpowiedziane z taryfy operatora, energię od sprzedawcy wpisujesz sam.
3. Później: **Cennik i ustawienia** punktu — zmiana obowiązującego cennika, cennik od wybranego dnia, usunięcie cennika,
   zmiana licznika lub taryfy. Taryfę edytujesz tym samym kreatorem.

### Dni wolne

Dzień wolny = sobota, niedziela i dni ustawowo wolne od pracy: Nowy Rok, Trzech Króli, Wielkanoc i Poniedziałek
Wielkanocny, 1 i 3 maja, Zesłanie Ducha Świętego, Boże Ciało, 15 sierpnia, 1 i 11 listopada, **Wigilia (od 2025)**,
25 i 26 grudnia. Święta ruchome liczone są z daty Wielkanocy.

### Czas stref

Taryfy OSD opisują zegary liczników ustawiane **wg czasu zimowego, bez zmiany latem** — chyba że licznik sam
utrzymuje godziny stref. Dlatego taryfa ma wybór:

- **lokalny** — strefy wg zegara w Polsce (latem UTC+2),
- **zimowy** — strefy wg UTC+1 przez cały rok (latem przesunięte o godzinę w stosunku do zegara).

Jeśli nie wiesz, który obowiązuje u Ciebie, porównaj latem dane godzinowe z licznika (np. eLicznik / portal OSD)
z planem stref.

## Encje punktu poboru

| Encja | Opis |
|---|---|
| `sensor.<punkt>_strefa` | bieżąca strefa; atrybuty: sezon, rodzaj dnia, od–do, plan i ceny na dziś i jutro |
| `sensor.<punkt>_cena` | cena brutto zł/kWh teraz (z rozbiciem na składniki) — nadaje się jako cena w panelu **Energia** |
| `sensor.<punkt>_nastepna_strefa`, `_zmiana_strefy`, `_cena_w_nastepnej_strefie` | co i kiedy będzie dalej |
| `sensor.<punkt>_koszt_dzis`, `_koszt_w_tym_miesiacu`, `_koszt_w_tym_roku` | koszt brutto: energia + proporcjonalna część opłat stałych |
| `sensor.<punkt>_koszt_energii_narastajaco` | narastający koszt samej energii — jako „koszt” w panelu Energia |
| `sensor.<punkt>_energia_<strefa>`, `_energia_dzis_<strefa>` | zużycie w strefie (narastająco i dziś) |
| `sensor.<punkt>_cena_dzis_<strefa>` | dzisiejsza cena strefy (diagnostyczne) |
| `binary_sensor.<punkt>_najtansza_strefa_teraz`, `_najdrozsza_strefa_teraz` | czy teraz jest najtaniej / najdrożej w tej dobie |
| `binary_sensor.<punkt>_dzien_wolny_wg_taryfy` | dzień wolny (atrybut `swieto`) |
| `calendar.<punkt>_strefy` | strefy jako wydarzenia (z ceną) — wyzwalacze kalendarza w automatyzacjach |

Koszt energii liczony jest z przyrostów licznika po cenie strefy z chwili zużycia. Przyrosty z czasu, gdy Home
Assistant nie działał, nie są doliczane (nie wiadomo, w której strefie zostały zużyte).

## Automatyzacje

Zdarzenie `taryfy_pradu_zmiana_strefy` (dane: `punkt`, `strefa`, `nazwa_strefy`, `poprzednia`, `cena`):

```yaml
triggers:
  - trigger: event
    event_type: taryfy_pradu_zmiana_strefy
    event_data:
      strefa: nocna
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.bojler
```

Najtańszy przedział dla urządzenia pracującego 2 godziny:

```yaml
actions:
  - action: taryfy_pradu.najtanszy_przedzial
    data:
      encja: sensor.dom_cena
      czas_trwania: "02:00:00"
    response_variable: przedzial
  - action: notify.mobile_app_telefon
    data:
      message: "Pralka najtaniej od {{ as_timestamp(przedzial.start) | timestamp_custom('%H:%M') }}
                (średnio {{ przedzial.srednia_cena }} zł/kWh)"
```

Usługa `taryfy_pradu.cena` zwraca strefę i cenę w podanej chwili (`chwila`, domyślnie teraz).

## Źródła

Godziny stref i stawki wzorców: *Taryfa TAURON Dystrybucja S.A. na rok 2026* (decyzja Prezesa URE
DRE.WRE.4211.54.8.2025.ASa1 z 17.12.2025), wyciąg dla grup taryfowych G. Stawki zmieniają się co rok —
sprawdzaj je z fakturą.

## Licencja

MIT
