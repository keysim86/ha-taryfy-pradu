"""Taryfy dynamiczne (PSE), nowe wzorce, porównanie taryf -- bez Home Assistanta."""

from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.taryfy_pradu import porownanie, pse
from custom_components.taryfy_pradu.cennik import Cennik
from custom_components.taryfy_pradu.taryfa import STREFA_CZASOWA, Taryfa
from custom_components.taryfy_pradu.wbudowane import WZORCE, wzorzec

PL = STREFA_CZASOWA
UTC = timezone.utc


def t(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=PL)


def test_wszystkie_wzorce_poprawne():
    for k in WZORCE:
        w = wzorzec(k)
        tar = Taryfa(w["taryfa"])
        braki = Cennik(w["cennik"]).braki(tar)
        assert braki and all("Energia" in b for b in braki), k  # brakuje tylko energii sprzedawcy


@pytest.mark.parametrize("klucz,chwila,strefa", [
    ("tauron_g11_2026", "2026-11-25 03:00", "calodobowa"),
    ("tauron_g12_2026", "2026-11-25 14:00", "nocna"),
    ("tauron_g12_2026", "2026-11-28 12:00", "dzienna"),     # G12: weekend jak dzień roboczy
    ("tauron_g12_2026", "2026-11-25 22:30", "nocna"),
    ("tauron_g12w_2026", "2026-11-25 12:00", "szczytowa"),
    ("tauron_g12w_2026", "2026-11-28 12:00", "pozaszczytowa"),  # sobota cała tańsza
    ("tauron_g12w_2026", "2026-12-24 08:00", "pozaszczytowa"),  # Wigilia
    ("tauron_g12as_2026", "2026-11-25 05:59", "nocna"),
    ("tauron_g12as_2026", "2026-11-25 06:00", "dzienna"),
])
def test_strefy_nowych_wzorcow(klucz, chwila, strefa):
    assert Taryfa(wzorzec(klucz)["taryfa"]).okno(t(chwila)).strefa == strefa


# --- taryfa dynamiczna ------------------------------------------------------------------

@pytest.fixture
def g14():
    tar = Taryfa(wzorzec("tauron_g14dynamic_2026")["taryfa"])
    # 26.11: 00 s3, 01-04 s2, 05-22 s3, 23 s2 (czas polski = UTC+1)
    plan = "322223333333333333333332"
    tar.ustaw_godziny({
        datetime(2026, 11, 25, 23, tzinfo=UTC) + timedelta(hours=i): f"s{int(c)}" for i, c in enumerate(plan)
    })
    return tar


def test_dynamiczna_okna(g14):
    o = g14.okno(t("2026-11-26 10:30"))
    assert o.strefa == "s3"
    assert o.od == t("2026-11-26 05:00").astimezone(UTC) and o.do == t("2026-11-26 23:00").astimezone(UTC)
    assert g14.okno(t("2026-11-26 02:00")).strefa == "s2"
    assert g14.plan_godzinowy(date(2026, 11, 26)) == [f"s{c}" for c in "322223333333333333333332"]


def test_dynamiczna_bez_danych_strefa_domyslna(g14):
    assert g14.okno(t("2026-11-28 12:00")).strefa == "s2"
    assert g14.dane_do == t("2026-11-27 00:00").astimezone(UTC)
    kiedy, nastepne = g14.nastepna_zmiana(t("2026-11-26 23:30"))
    assert kiedy == t("2026-11-27 00:00").astimezone(UTC)  # koniec znanych danych


def test_dynamiczna_nastepna_zmiana(g14):
    kiedy, nastepne = g14.nastepna_zmiana(t("2026-11-26 03:00"))
    assert kiedy == t("2026-11-26 05:00").astimezone(UTC) and nastepne.strefa == "s3"


def test_pse_parser():
    rekordy = [
        {"dtime_utc": "2026-11-25 23:00", "usage_fcst": 2, "is_active": True},
        {"dtime_utc": "2026-11-26 00:00", "usage_fcst": 1, "is_active": True},
        {"dtime_utc": "2026-11-26 00:00", "usage_fcst": 3, "is_active": False},  # stara wersja planu
        {"dtime_utc": "zła data", "usage_fcst": 0},
    ]
    assert pse.parsuj(rekordy) == {
        datetime(2026, 11, 25, 23, tzinfo=UTC): "s3",
        datetime(2026, 11, 26, 0, tzinfo=UTC): "s2",
    }


# --- porównanie ---------------------------------------------------------------------------

def test_porownanie_g13s_vs_g11():
    # doba zużycia: 1 kWh co godzinę, 25.11.2026 (zimowy dzień roboczy)
    start = t("2026-11-25 00:00").astimezone(UTC)
    godziny = [(start + timedelta(hours=i), 1.0) for i in range(24)]
    dni = porownanie.dni_okresu(start, start + timedelta(days=1))
    assert dni == [date(2026, 11, 25)]
    g13s = wzorzec("tauron_g13s_2026")
    g13s["cennik"]["zmienne"]["energia"]["stawki"] = {"nocna": 0.40, "pozaszczytowa": 0.50, "szczytowa": 0.70}
    g11 = wzorzec("tauron_g11_2026")
    g11["cennik"]["zmienne"]["energia"]["stawki"] = {"*": 0.55}
    k13 = porownanie.koszt_wariantu(godziny, dni, Taryfa(g13s["taryfa"]), Cennik(g13s["cennik"]))
    k11 = porownanie.koszt_wariantu(godziny, dni, Taryfa(g11["taryfa"]), Cennik(g11["cennik"]))
    assert k13["strefy"] == {"nocna": 10.0, "szczytowa": 9.0, "pozaszczytowa": 5.0}
    za_kwh = 0.0332 + 0.0073 + 0.0030
    oczek13 = (10 * (0.40 + 0.1094) + 9 * (0.70 + 0.3332) + 5 * (0.50 + 0.1999) + 24 * za_kwh) * 1.23
    assert k13["energia"] == pytest.approx(oczek13)
    assert k11["energia"] == pytest.approx(24 * (0.55 + 0.2464 + za_kwh) * 1.23)
    assert k13["stale"] == pytest.approx((10.86 + 4.56 + 24.05) * 1.23 / 30)
    r = porownanie.ranking(k13, {"G11": k11}, "Obecna (G13s)")
    assert r["koszty"][0]["nazwa"] == ("G11" if k11["razem"] < k13["razem"] else "Obecna (G13s)")
    assert r["oplaca_sie"] == (k13["razem"] - k11["razem"] >= 5)  # 5 zł w dobę -- tu nie
    assert r["oplaca_sie"] is False


def test_ranking_rekomenduje_przy_duzej_roznicy():
    obecna = {"energia": 300.0, "stale": 60.0, "razem": 360.0, "kwh": 400.0, "strefy": {}}
    tansza = {"energia": 250.0, "stale": 60.0, "razem": 310.0, "kwh": 400.0, "strefy": {}}
    r = porownanie.ranking(obecna, {"G12w": tansza, "zepsuty": None}, "Obecna")
    assert r["najtanszy"] == "G12w" and r["oplaca_sie"] is True
    assert r["oszczednosc_zl"] == 50.0 and r["oszczednosc_proc"] == pytest.approx(13.9)
    assert [p["nazwa"] for p in r["koszty"]] == ["G12w", "Obecna"]
