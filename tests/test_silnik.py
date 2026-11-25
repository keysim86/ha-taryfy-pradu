"""Rdzeń bez Home Assistanta: święta, strefy, czas zimowy, zmiany czasu, cennik, walidacja."""

from datetime import date, datetime, timedelta

import pytest

from custom_components.taryfy_pradu.cennik import Cennik, klucze_dla
from custom_components.taryfy_pradu.swieta import dzien_wolny, swieto, wielkanoc
from custom_components.taryfy_pradu.taryfa import (
    CZAS_ZIMOWY,
    STREFA_CZASOWA,
    BladTaryfy,
    Taryfa,
    parsuj_przedzialy,
)
from custom_components.taryfy_pradu.wbudowane import wzorzec

PL = STREFA_CZASOWA


def t(s: str) -> datetime:
    """'2026-11-25 16:33' w czasie polskim."""
    return datetime.fromisoformat(s).replace(tzinfo=PL)


@pytest.fixture
def g13s():
    return Taryfa(wzorzec("tauron_g13s_2026")["taryfa"])


@pytest.fixture
def g13():
    return Taryfa(wzorzec("tauron_g13_2026")["taryfa"])


# --- święta -------------------------------------------------------------------------

@pytest.mark.parametrize("rok,dzien", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
                                       (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)),
                                       (2038, date(2038, 4, 25))])
def test_wielkanoc(rok, dzien):
    assert wielkanoc(rok) == dzien


@pytest.mark.parametrize("d,wolny", [
    ("2026-11-25", False), ("2026-11-27", False), ("2026-11-28", True), ("2026-11-29", True),
    ("2026-11-11", True), ("2026-01-06", True), ("2026-04-06", True), ("2026-04-07", False),
    ("2026-06-04", True), ("2026-06-05", False), ("2026-12-24", True), ("2026-12-31", False),
    ("2024-12-24", False),  # Wigilia wolna dopiero od 2025
    ("2027-03-29", True), ("2027-05-27", True), ("2026-08-15", True), ("2026-05-03", True),
])
def test_dzien_wolny(d, wolny):
    assert dzien_wolny(date.fromisoformat(d)) is wolny


def test_nazwa_swieta():
    assert swieto(date(2026, 6, 4)) == "Boże Ciało"
    assert swieto(date(2026, 11, 25)) is None


# --- G13s ---------------------------------------------------------------------------

@pytest.mark.parametrize("chwila,strefa,sezon,dzien", [
    ("2026-11-25 06:59", "nocna", "zima", "roboczy"),
    ("2026-11-25 07:00", "szczytowa", "zima", "roboczy"),
    ("2026-11-25 09:59", "szczytowa", "zima", "roboczy"),
    ("2026-11-25 10:00", "pozaszczytowa", "zima", "roboczy"),
    ("2026-11-25 14:59", "pozaszczytowa", "zima", "roboczy"),
    ("2026-11-25 15:00", "szczytowa", "zima", "roboczy"),
    ("2026-11-25 16:33", "szczytowa", "zima", "roboczy"),
    ("2026-11-25 21:00", "nocna", "zima", "roboczy"),
    ("2026-11-28 12:00", "pozaszczytowa", "zima", "wolny"),   # sobota: te same godziny
    ("2026-11-11 08:00", "szczytowa", "zima", "wolny"),       # święto
    ("2026-07-15 08:30", "szczytowa", "lato", "roboczy"),
    ("2026-07-15 09:00", "pozaszczytowa", "lato", "roboczy"),
    ("2026-07-15 16:59", "pozaszczytowa", "lato", "roboczy"),
    ("2026-07-15 17:00", "szczytowa", "lato", "roboczy"),
    ("2026-07-15 23:00", "nocna", "lato", "roboczy"),
    ("2026-03-31 12:00", "pozaszczytowa", "zima", "roboczy"),
    ("2026-04-01 09:30", "pozaszczytowa", "lato", "roboczy"),  # pierwszy dzień lata
    ("2026-09-30 16:00", "pozaszczytowa", "lato", "roboczy"),
    ("2026-10-01 16:00", "szczytowa", "zima", "roboczy"),
])
def test_g13s_strefy(g13s, chwila, strefa, sezon, dzien):
    o = g13s.okno(t(chwila))
    assert (o.strefa, o.sezon, o.dzien) == (strefa, sezon, dzien)


def test_g13s_plan_dnia(g13s):
    skrot = {"nocna": "n", "pozaszczytowa": "p", "szczytowa": "s"}
    zima = "".join(skrot[s] for s in g13s.plan_godzinowy(date(2026, 11, 25)))
    lato = "".join(skrot[s] for s in g13s.plan_godzinowy(date(2026, 7, 15)))
    assert zima == "nnnnnnnssspppppssssssnnn"
    assert lato == "nnnnnnnssppppppppssssnnn"


def test_g13s_okno_przez_polnoc_w_dzien_wolny(g13s):
    # piątek 21:00 -> sobota 07:00 to jedna strefa nocna, ale dwa okna (różny rodzaj dnia)
    o = g13s.okno(t("2026-11-27 23:00"))
    assert (o.strefa, o.dzien) == ("nocna", "roboczy")
    assert o.do == t("2026-11-28 00:00")
    zmiana, nastepne = g13s.nastepna_zmiana(t("2026-11-27 23:00"))
    assert zmiana == t("2026-11-28 07:00") and nastepne.strefa == "szczytowa"
    zmiana, nastepne = g13s.nastepna_zmiana(t("2026-11-27 23:00"), tylko_strefa=False)
    assert zmiana == t("2026-11-28 00:00") and nastepne.dzien == "wolny"


# --- G13 ----------------------------------------------------------------------------

@pytest.mark.parametrize("chwila,strefa", [
    ("2026-11-25 06:59", "pozostale"), ("2026-11-25 07:00", "przedpoludniowa"),
    ("2026-11-25 12:59", "przedpoludniowa"), ("2026-11-25 13:00", "pozostale"),
    ("2026-11-25 16:00", "popoludniowa"), ("2026-11-25 20:59", "popoludniowa"),
    ("2026-11-25 21:00", "pozostale"),
    ("2026-07-15 16:00", "pozostale"), ("2026-07-15 19:00", "popoludniowa"),
    ("2026-07-15 21:59", "popoludniowa"), ("2026-07-15 22:00", "pozostale"),
    ("2026-11-28 10:00", "pozostale"),  # sobota cała w strefie III
    ("2026-12-24 10:00", "pozostale"),  # Wigilia
    ("2026-06-04 10:00", "pozostale"),  # Boże Ciało
])
def test_g13_strefy(g13, chwila, strefa):
    assert g13.okno(t(chwila)).strefa == strefa


def test_g13_weekend_jedno_okno_do_poniedzialku(g13):
    # sobota 0:00 -> poniedziałek 7:00 bez zmiany strefy
    zmiana, nastepne = g13.nastepna_zmiana(t("2026-11-28 10:00"))
    assert zmiana == t("2026-11-30 07:00") and nastepne.strefa == "przedpoludniowa"


# --- czas zimowy i zmiany czasu ----------------------------------------------------

def test_czas_zimowy_przesuwa_strefy_latem():
    d = wzorzec("tauron_g13s_2026")["taryfa"]
    d["czas"] = "zimowy"
    tz = Taryfa(d)
    # latem 9:00 czasu zimowego = 10:00 czasu polskiego
    assert tz.okno(t("2026-07-15 09:30")).strefa == "szczytowa"
    assert tz.okno(t("2026-07-15 10:00")).strefa == "pozaszczytowa"
    assert tz.okno(t("2026-07-15 17:30")).strefa == "pozaszczytowa"
    # zimą bez różnicy
    assert tz.okno(t("2026-11-25 10:00")).strefa == "pozaszczytowa"


def test_dzien_zmiany_czasu_ma_23_i_25_godzin(g13s):
    assert len(g13s.plan_godzinowy(date(2026, 3, 29))) == 23
    assert len(g13s.plan_godzinowy(date(2026, 10, 25))) == 25


def test_ciaglosc_okien_przez_rok(g13s, g13):
    for taryfa in (g13s, g13):
        od = datetime(2026, 1, 1, tzinfo=PL)
        do = datetime(2027, 1, 1, tzinfo=PL)
        poprzednie = None
        suma = timedelta()
        for o in taryfa.okna(od, do):
            assert o.od < o.do
            if poprzednie:
                assert o.od == poprzednie.do
            suma += o.do - o.od
            poprzednie = o
        assert suma == do - od


def test_strefa_czasowa_wymagana(g13s):
    with pytest.raises(ValueError):
        g13s.okno(datetime(2026, 1, 1, 12))


def test_czas_zimowy_stala_utc_plus_1():
    assert CZAS_ZIMOWY.utcoffset(None) == timedelta(hours=1)


# --- walidacja (kreator) -------------------------------------------------------------

def test_przedzialy():
    assert parsuj_przedzialy("07:00-09:00, 17-21") == [(420, 540), (1020, 1260)]
    assert parsuj_przedzialy("21-7") == [(1260, 1440), (0, 420)]
    assert parsuj_przedzialy("0-24") == [(0, 1440)]
    with pytest.raises(BladTaryfy):
        parsuj_przedzialy("7 do 9")
    with pytest.raises(BladTaryfy):
        parsuj_przedzialy("25-3")


def test_walidacja_luki_i_nakladania():
    d = wzorzec("tauron_g13s_2026")["taryfa"]
    d["godziny"]["zima"]["roboczy"]["pozaszczytowa"] = "10:00-14:00"
    with pytest.raises(BladTaryfy, match="lukę"):
        Taryfa(d)
    d = wzorzec("tauron_g13s_2026")["taryfa"]
    d["godziny"]["lato"]["wolny"]["nocna"] = "20:00-07:00"
    with pytest.raises(BladTaryfy, match="nakładają"):
        Taryfa(d)


def test_walidacja_sezonow():
    d = wzorzec("tauron_g13_2026")["taryfa"]
    d["sezony"][1]["od"] = "10-02"
    with pytest.raises(BladTaryfy, match="01.10"):
        Taryfa(d)


def test_taryfa_jednakowe_dni_i_jeden_sezon():
    t1 = Taryfa({
        "nazwa": "G12", "czas": "lokalny", "dni": "jednakowe",
        "strefy": [{"id": "dzien"}, {"id": "noc"}],
        "sezony": [{"id": "rok", "od": "01-01", "do": "12-31"}],
        "godziny": {"rok": {"roboczy": {"dzien": "6-13, 15-22", "noc": "22-6, 13-15"}}},
    })
    assert t1.okno(t("2026-11-28 14:00")).strefa == "noc"
    assert t1.okno(t("2026-11-28 14:00")).dzien == "roboczy"


# --- cennik ---------------------------------------------------------------------------

def test_cennik_g13s(g13s):
    w = wzorzec("tauron_g13s_2026")
    w["cennik"]["zmienne"]["energia"]["stawki"] = {"nocna": 0.50, "pozaszczytowa": 0.55, "szczytowa": 0.70}
    c = Cennik(w["cennik"])
    assert c.braki(g13s) == []
    o = g13s.okno(t("2026-11-25 16:33"))  # zima, roboczy, szczytowa
    netto = 0.70 + 0.3332 + 0.0331 + 0.0073 + 0.0030
    assert c.cena_netto(o) == pytest.approx(netto)
    assert c.cena_brutto(o) == pytest.approx(netto * 1.23)
    assert c.stale_miesieczne_netto() == pytest.approx(10.86 + 4.56 + 24.05)
    assert c.stale_dzienne_brutto(date(2026, 11, 25)) == pytest.approx((10.86 + 4.56 + 24.05) * 1.23 / 30)


def test_cennik_braki(g13s):
    c = Cennik(wzorzec("tauron_g13s_2026")["cennik"])
    braki = c.braki(g13s)
    assert len(braki) == 3 and all("Energia" in b for b in braki)


def test_klucze_formularza(g13s, g13):
    assert len(klucze_dla(g13s, ["sezon", "dzien", "strefa"])) == 12
    assert klucze_dla(g13s, ["strefa"]) == ["nocna", "pozaszczytowa", "szczytowa"]
    assert klucze_dla(g13, []) == ["*"]
