"""Kreatory: wpis główny, taryfa (strefy, sezony, godziny) i punkt poboru (licznik, cenniki)."""

from __future__ import annotations

import copy
import re
from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .cennik import NAZWY, SKLADNIKI_STALE, SKLADNIKI_ZA_KWH, SKLADNIKI_ZMIENNE, WYMIARY, klucze_dla
from .const import (
    CONF_CENNIKI,
    CONF_DEFINICJA,
    CONF_TARYFA,
    CONF_WARIANTY,
    CONF_WZORZEC,
    CONF_ZRODLO,
    DOMAIN,
    TYP_PUNKT,
    TYP_TARYFA,
)
from .taryfa import BladTaryfy, Taryfa, plan_doby
from .wbudowane import WZORCE, wzorzec

PUSTA = "pusta"
NAZWA_DNIA = {"roboczy": "dzień roboczy", "wolny": "dzień wolny (sobota, niedziela, święta)"}
_SEZON = re.compile(r"^\s*(.+?)\s*:\s*(\d{1,2}-\d{1,2})\s*(?:\.\.|–|—|-)\s*(\d{1,2}-\d{1,2})\s*$")


class TaryfyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Taryfy prądu", data={})
        return self.async_show_form(step_id="user")

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {TYP_TARYFA: TaryfaFlow, TYP_PUNKT: PunktFlow}


# --- taryfa ------------------------------------------------------------------------------


def _strefy_na_tekst(strefy: list[dict]) -> str:
    return "\n".join(s.get("nazwa") or s["id"] for s in strefy)


def _sezony_na_tekst(sezony: list[dict]) -> str:
    return "\n".join(f"{s.get('nazwa') or s['id']}: {s['od']} .. {s['do']}" for s in sezony)


def _id_z_nazw(nazwy: list[str], stare: list[dict]) -> list[dict]:
    """Nazwy -> [{"id", "nazwa"}]; id zachowane, gdy nazwa się nie zmieniła."""
    po_nazwie = {(s.get("nazwa") or s["id"]): s["id"] for s in stare}
    wynik, uzyte = [], set()
    for n in nazwy:
        sid = po_nazwie.get(n) or slugify(n) or "strefa"
        baza, i = sid, 2
        while sid in uzyte:
            sid, i = f"{baza}_{i}", i + 1
        uzyte.add(sid)
        wynik.append({"id": sid, "nazwa": n})
    return wynik


def _parsuj_sezony(tekst: str, stare: list[dict]) -> list[dict]:
    linie = [l for l in (tekst or "").splitlines() if l.strip()]
    if not linie:
        raise BladTaryfy("Podaj co najmniej jeden sezon, np. „Cały rok: 01-01 .. 12-31”")
    nazwy, zakresy = [], []
    for l in linie:
        m = _SEZON.match(l)
        if not m:
            raise BladTaryfy(f"Nie rozumiem sezonu „{l.strip()}” — wpisz np. „Lato: 04-01 .. 09-30”")
        nazwy.append(m[1])
        zakresy.append((m[2], m[3]))
    sezony = _id_z_nazw(nazwy, stare)
    for s, (od, do) in zip(sezony, zakresy):
        mo, do_ = (f"{int(x.split('-')[0]):02d}-{int(x.split('-')[1]):02d}" for x in (od, do))
        s["od"], s["do"] = mo, do_
    return sezony


class TaryfaFlow(ConfigSubentryFlow):
    """Kreator taryfy: wzorzec -> podstawy -> godziny stref dla każdego sezonu i rodzaju dnia."""

    def __init__(self) -> None:
        self._d: dict[str, Any] = {}
        self._kolejka: list[tuple[str, str]] = []
        self._i = 0

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            if user_input[CONF_WZORZEC] == PUSTA:
                self._d = {
                    "nazwa": "", "operator": "", "czas": "lokalny", "dni": "roboczy_wolny",
                    "strefy": [{"id": "dzienna", "nazwa": "Dzienna"}, {"id": "nocna", "nazwa": "Nocna"}],
                    "sezony": [{"id": "rok", "nazwa": "Cały rok", "od": "01-01", "do": "12-31"}],
                    "godziny": {},
                }
            else:
                self._d = wzorzec(user_input[CONF_WZORZEC])["taryfa"]
                self._d[CONF_WZORZEC] = user_input[CONF_WZORZEC]
            if self._d.get("typ") == "dynamiczna":
                return await self.async_step_dynamiczna()
            return await self.async_step_podstawy()
        opcje = [selector.SelectOptionDict(value=k, label=w["nazwa"]) for k, w in WZORCE.items()]
        opcje.append(selector.SelectOptionDict(value=PUSTA, label="Pusta — zdefiniuję sam"))
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_WZORZEC, default=next(iter(WZORCE))): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=opcje, mode=selector.SelectSelectorMode.LIST)
                )
            }),
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._d = copy.deepcopy(dict(self._get_reconfigure_subentry().data[CONF_DEFINICJA]))
        if self._d.get("typ") == "dynamiczna":
            return await self.async_step_dynamiczna()
        return await self.async_step_podstawy()

    async def async_step_dynamiczna(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Taryfa dynamiczna: strefy przychodzą ze źródła (PSE), tu tylko nazwa i operator."""
        if user_input is not None:
            self._d["nazwa"] = user_input["nazwa"].strip()
            self._d["operator"] = (user_input.get("operator") or "").strip()
            return self._zakoncz()
        return self.async_show_form(step_id="dynamiczna", data_schema=vol.Schema({
            vol.Required("nazwa", default=self._d.get("nazwa", "")): str,
            vol.Optional("operator", default=self._d.get("operator", "")): str,
        }))

    async def async_step_podstawy(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        blad = ""
        if user_input is not None:
            try:
                nazwy_stref = [l.strip() for l in user_input["strefy"].splitlines() if l.strip()]
                if not nazwy_stref:
                    raise BladTaryfy("Podaj co najmniej jedną strefę")
                strefy = _id_z_nazw(nazwy_stref, self._d.get("strefy") or [])
                sezony = _parsuj_sezony(user_input["sezony"], self._d.get("sezony") or [])
                # sprawdź same sezony (godziny tymczasowo: cała doba w pierwszej strefie)
                pelna = {s["id"]: {d: {strefy[0]["id"]: "0-24"} for d in ("roboczy", "wolny")} for s in sezony}
                Taryfa({"strefy": strefy, "sezony": sezony, "dni": user_input["dni"],
                        "czas": user_input["czas"], "godziny": pelna})
            except BladTaryfy as err:
                errors["base"], blad = "blad_taryfy", str(err)
            else:
                self._d.update(
                    nazwa=user_input["nazwa"].strip(), operator=(user_input.get("operator") or "").strip(),
                    czas=user_input["czas"], dni=user_input["dni"], strefy=strefy, sezony=sezony,
                )
                dni = ("roboczy", "wolny") if self._d["dni"] == "roboczy_wolny" else ("roboczy",)
                self._kolejka = [(s["id"], d) for s in sezony for d in dni]
                self._i = 0
                return await self.async_step_godziny()
        d = self._d
        return self.async_show_form(
            step_id="podstawy",
            data_schema=vol.Schema({
                vol.Required("nazwa", default=d.get("nazwa", "")): str,
                vol.Optional("operator", default=d.get("operator", "")): str,
                vol.Required("czas", default=d.get("czas", "lokalny")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["lokalny", "zimowy"], translation_key="czas")
                ),
                vol.Required("dni", default=d.get("dni", "roboczy_wolny")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["roboczy_wolny", "jednakowe"], translation_key="dni")
                ),
                vol.Required("strefy", default=_strefy_na_tekst(d.get("strefy") or [])):
                    selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Required("sezony", default=_sezony_na_tekst(d.get("sezony") or [])):
                    selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            }),
            errors=errors,
            description_placeholders={"blad": blad},
        )

    async def async_step_godziny(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sezon, dzien = self._kolejka[self._i]
        strefy = self._d["strefy"]
        nazwa_sezonu = next(s["nazwa"] for s in self._d["sezony"] if s["id"] == sezon)
        godziny = self._d.setdefault("godziny", {}).setdefault(sezon, {})
        errors: dict[str, str] = {}
        blad = ""
        if user_input is not None:
            if dzien == "wolny" and user_input.get("jak_roboczy"):
                mapa = dict(godziny.get("roboczy") or {})
            else:
                mapa = {s["id"]: user_input.get(s["nazwa"], "") for s in strefy}
                mapa = {k: v for k, v in mapa.items() if v and v.strip()}
            try:
                plan_doby([s["id"] for s in strefy], mapa)
            except BladTaryfy as err:
                errors["base"], blad = "blad_taryfy", str(err)
            else:
                godziny[dzien] = mapa
                self._i += 1
                if self._i < len(self._kolejka):
                    return await self.async_step_godziny()
                return self._zakoncz()
        obecne = godziny.get(dzien) or {}
        pola: dict[Any, Any] = {}
        if dzien == "wolny":
            pola[vol.Optional("jak_roboczy", default=obecne == godziny.get("roboczy"))] = bool
        for s in strefy:
            pola[vol.Optional(s["nazwa"], description={"suggested_value": obecne.get(s["id"], "")})] = str
        return self.async_show_form(
            step_id="godziny",
            data_schema=vol.Schema(pola),
            errors=errors,
            description_placeholders={
                "sezon": nazwa_sezonu, "dzien": NAZWA_DNIA[dzien],
                "nr": str(self._i + 1), "z": str(len(self._kolejka)), "blad": blad,
            },
        )

    def _zakoncz(self) -> SubentryFlowResult:
        # wyrzuć godziny sezonów/dni, których już nie ma
        sezony = {s["id"] for s in self._d["sezony"]}
        self._d["godziny"] = {k: v for k, v in (self._d.get("godziny") or {}).items() if k in sezony}
        if self._d["dni"] == "jednakowe":
            for v in self._d["godziny"].values():
                v.pop("wolny", None)
        Taryfa(self._d)  # pełna walidacja (kroki sprawdziły już każdą dobę)
        tytul = self._d["nazwa"] + (f" ({self._d['operator']})" if self._d.get("operator") else "")
        if self.source == "reconfigure":
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), title=tytul, data={CONF_DEFINICJA: self._d}
            )
        return self.async_create_entry(title=tytul, data={CONF_DEFINICJA: self._d})


# --- punkt poboru -------------------------------------------------------------------------


def _opis_klucza(taryfa: Taryfa, wymiary: list[str], k: str) -> str:
    if k == "*":
        return "wszystkie strefy"
    czesci = dict(zip([w for w in WYMIARY if w in wymiary], k.split("|")))
    opis = []
    if "sezon" in czesci:
        opis.append(next((s.get("nazwa") or s["id"] for s in taryfa.sezony if s["id"] == czesci["sezon"]),
                         czesci["sezon"]))
    if "dzien" in czesci:
        opis.append("dzień roboczy" if czesci["dzien"] == "roboczy" else "dzień wolny")
    if "strefa" in czesci:
        opis.append(taryfa.nazwa_strefy(czesci["strefa"]))
    return ", ".join(opis)


class PunktFlow(ConfigSubentryFlow):
    """Punkt poboru: licznik + harmonogram cenników (każdy z taryfą i datą „od”) + warianty do porównania."""

    def __init__(self) -> None:
        self._dane: dict[str, Any] = {}
        self._cennik: dict[str, Any] = {}
        self._taryfa_id: str = ""
        self._tryb = "nowy"  # nowy | cennik | nowy_cennik | wariant
        self._od: str | None = None
        self._nazwa_wariantu: str = ""
        self._mapa: dict[str, tuple[str, str]] = {}

    # --- pomocnicze

    def _taryfy(self) -> dict[str, Any]:
        return {sid: s for sid, s in self._get_entry().subentries.items() if s.subentry_type == TYP_TARYFA}

    def _taryfa(self) -> Taryfa:
        return Taryfa(self._taryfy()[self._taryfa_id].data[CONF_DEFINICJA])

    def _opcje_taryf(self) -> list[selector.SelectOptionDict]:
        return [selector.SelectOptionDict(value=sid, label=s.title) for sid, s in self._taryfy().items()]

    def _cennik_dla(self, taryfa_id: str) -> dict[str, Any]:
        """Cennik do podpowiedzi: ostatni tego punktu z tą taryfą, a gdy brak -- ze wzorca taryfy."""
        for c in reversed(self._dane.get(CONF_CENNIKI) or []):
            if (c.get("taryfa") or self._dane.get(CONF_TARYFA)) == taryfa_id:
                return {k: v for k, v in copy.deepcopy(dict(c)).items() if k not in ("od", "taryfa")}
        defin = self._taryfy()[taryfa_id].data[CONF_DEFINICJA]
        if (w := defin.get(CONF_WZORZEC)) in WZORCE:
            return wzorzec(w)["cennik"]
        return {"vat": 23.0, "zmienne": {n: {"wymiary": ["strefa"], "stawki": {}} for n in SKLADNIKI_ZMIENNE},
                "za_kwh": {n: 0.0 for n in SKLADNIKI_ZA_KWH}, "stale": {n: 0.0 for n in SKLADNIKI_STALE}}

    def _aktywny_indeks(self, cenniki: list[dict]) -> int:
        dzis = dt_util.now().date().isoformat()
        idx = 0
        for i, c in enumerate(cenniki):
            if (c.get("od") or "0000-00-00") <= dzis:
                idx = i
        return idx

    # --- dodawanie

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if not self._taryfy():
            return self.async_abort(reason="brak_taryf")
        if user_input is not None:
            self._dane = dict(user_input)
            self._taryfa_id = user_input[CONF_TARYFA]
            self._cennik = self._cennik_dla(self._taryfa_id)
            self._tryb = "nowy"
            return await self.async_step_wymiary()
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("nazwa", default="Dom"): str,
            vol.Required(CONF_ZRODLO): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")),
            vol.Required(CONF_TARYFA, default=next(iter(self._taryfy()))): selector.SelectSelector(
                selector.SelectSelectorConfig(options=self._opcje_taryf())),
        }))

    # --- edycja

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        self._dane = {"nazwa": sub.title, **{k: v for k, v in sub.data.items()}}
        opcje = ["cennik", "nowy_cennik"]
        if len(sub.data.get(CONF_CENNIKI) or []) > 1:
            opcje.append("usun_cennik")
        opcje.append("dodaj_wariant")
        if sub.data.get(CONF_WARIANTY):
            opcje.append("usun_wariant")
        opcje.append("ustawienia")
        return self.async_show_menu(step_id="reconfigure", menu_options=opcje)

    async def async_step_cennik(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        cenniki = self._dane.get(CONF_CENNIKI) or [{}]
        aktywny = dict(cenniki[self._aktywny_indeks(cenniki)])
        self._taryfa_id = aktywny.get("taryfa") or self._dane[CONF_TARYFA]
        self._cennik = {k: v for k, v in copy.deepcopy(aktywny).items() if k not in ("od", "taryfa")} \
            or self._cennik_dla(self._taryfa_id)
        self._tryb = "cennik"
        return await self.async_step_wymiary()

    async def async_step_nowy_cennik(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        cenniki = self._dane.get(CONF_CENNIKI) or [{}]
        biezaca = cenniki[self._aktywny_indeks(cenniki)].get("taryfa") or self._dane[CONF_TARYFA]
        if user_input is not None:
            self._od = user_input["od"]
            self._taryfa_id = user_input[CONF_TARYFA]
            self._cennik = self._cennik_dla(self._taryfa_id)
            self._tryb = "nowy_cennik"
            return await self.async_step_wymiary()
        nowy_rok = date(dt_util.now().year + 1, 1, 1).isoformat()
        return self.async_show_form(step_id="nowy_cennik", data_schema=vol.Schema({
            vol.Required("od", default=nowy_rok): selector.DateSelector(),
            vol.Required(CONF_TARYFA, default=biezaca): selector.SelectSelector(
                selector.SelectSelectorConfig(options=self._opcje_taryf())),
        }))

    async def async_step_usun_cennik(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        cenniki = list(self._dane.get(CONF_CENNIKI) or [])
        taryfy = self._taryfy()

        def opis(c: dict) -> str:
            t = taryfy.get(c.get("taryfa") or self._dane[CONF_TARYFA])
            return f"{c.get('od') or 'od początku'} — {t.title if t else '?'}"

        if user_input is not None:
            cenniki = [c for c in cenniki if opis(c) != user_input["cennik"]]
            return self._zapisz(cenniki=cenniki)
        return self.async_show_form(step_id="usun_cennik", data_schema=vol.Schema({
            vol.Required("cennik"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[opis(c) for c in cenniki]))}))

    async def async_step_dodaj_wariant(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._taryfa_id = user_input[CONF_TARYFA]
            self._nazwa_wariantu = user_input["nazwa"].strip() or self._taryfy()[self._taryfa_id].title
            self._cennik = self._cennik_dla(self._taryfa_id)
            self._tryb = "wariant"
            return await self.async_step_wymiary()
        return self.async_show_form(step_id="dodaj_wariant", data_schema=vol.Schema({
            vol.Required(CONF_TARYFA): selector.SelectSelector(
                selector.SelectSelectorConfig(options=self._opcje_taryf())),
            vol.Optional("nazwa", default=""): str,
        }))

    async def async_step_usun_wariant(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        warianty = list(self._dane.get(CONF_WARIANTY) or [])
        if user_input is not None:
            warianty = [w for w in warianty if w.get("nazwa") != user_input["wariant"]]
            return self._zapisz(warianty=warianty)
        return self.async_show_form(step_id="usun_wariant", data_schema=vol.Schema({
            vol.Required("wariant"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[w.get("nazwa", "?") for w in warianty]))}))

    async def async_step_ustawienia(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._dane.update(user_input)
            return self._zapisz()
        return self.async_show_form(step_id="ustawienia", data_schema=vol.Schema({
            vol.Required("nazwa", default=self._dane.get("nazwa", "Dom")): str,
            vol.Required(CONF_ZRODLO, default=self._dane.get(CONF_ZRODLO)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")),
        }))

    # --- cennik: wymiary i stawki

    async def async_step_wymiary(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            for n in SKLADNIKI_ZMIENNE:
                sk = self._cennik.setdefault("zmienne", {}).setdefault(n, {"wymiary": [], "stawki": {}})
                sk["wymiary"] = [w for w in WYMIARY if w in user_input.get(n, [])]
            return await self.async_step_stawki()
        dynamiczna = self._taryfa().typ == "dynamiczna"
        pola = {}
        for n in SKLADNIKI_ZMIENNE:
            obecne = ((self._cennik.get("zmienne") or {}).get(n) or {}).get("wymiary", ["strefa"])
            opcje = ["strefa"] if dynamiczna else list(WYMIARY)
            pola[vol.Optional(n, default=[w for w in obecne if w in opcje])] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=opcje, multiple=True, translation_key="wymiar")
            )
        return self.async_show_form(step_id="wymiary", data_schema=vol.Schema(pola),
                                    description_placeholders={"taryfa": self._taryfa().nazwa})

    async def async_step_stawki(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        taryfa = self._taryfa()
        if user_input is not None:
            for n in SKLADNIKI_ZMIENNE:
                self._cennik["zmienne"][n]["stawki"] = {}
            for etykieta, (n, k) in self._mapa.items():
                if etykieta in user_input and user_input[etykieta] is not None:
                    self._cennik["zmienne"][n]["stawki"][k] = float(user_input[etykieta])
            self._cennik["za_kwh"] = {n: float(user_input.get(n) or 0) for n in SKLADNIKI_ZA_KWH}
            self._cennik["stale"] = {n: float(user_input.get(n) or 0) for n in SKLADNIKI_STALE}
            self._cennik["vat"] = float(user_input.get("vat", 23))
            return self._zakoncz_cennik()
        kwh = selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=10, step="any", mode=selector.NumberSelectorMode.BOX, unit_of_measurement="zł/kWh"))
        mies = selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=1000, step=0.01, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="zł/mies."))
        pola: dict[Any, Any] = {}
        self._mapa = {}
        for n in SKLADNIKI_ZMIENNE:
            sk = self._cennik["zmienne"][n]
            for k in klucze_dla(taryfa, sk["wymiary"]):
                etykieta = f"{NAZWY[n]} — {_opis_klucza(taryfa, sk['wymiary'], k)}"
                self._mapa[etykieta] = (n, k)
                obecna = (sk.get("stawki") or {}).get(k)
                pola[vol.Required(etykieta, description={"suggested_value": obecna})] = kwh
        for n in SKLADNIKI_ZA_KWH:
            pola[vol.Required(n, default=float((self._cennik.get("za_kwh") or {}).get(n, 0)))] = kwh
        for n in SKLADNIKI_STALE:
            pola[vol.Required(n, default=float((self._cennik.get("stale") or {}).get(n, 0)))] = mies
        pola[vol.Required("vat", default=float(self._cennik.get("vat", 23)))] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100, step=1, mode=selector.NumberSelectorMode.BOX,
                                          unit_of_measurement="%"))
        return self.async_show_form(step_id="stawki", data_schema=vol.Schema(pola),
                                    description_placeholders={"taryfa": taryfa.nazwa})

    def _zakoncz_cennik(self) -> SubentryFlowResult:
        wpis = {**{k: v for k, v in self._cennik.items() if k not in ("od", "taryfa")}, "taryfa": self._taryfa_id}
        if self._tryb == "nowy":
            return self.async_create_entry(
                title=self._dane["nazwa"],
                data={CONF_ZRODLO: self._dane[CONF_ZRODLO], CONF_TARYFA: self._taryfa_id,
                      CONF_CENNIKI: [{"od": None, **wpis}], CONF_WARIANTY: []},
            )
        if self._tryb == "wariant":
            warianty = [w for w in (self._dane.get(CONF_WARIANTY) or []) if w.get("nazwa") != self._nazwa_wariantu]
            warianty.append({"nazwa": self._nazwa_wariantu, **wpis})
            return self._zapisz(warianty=warianty)
        cenniki = [dict(c) for c in (self._dane.get(CONF_CENNIKI) or [])]
        if self._tryb == "cennik":
            if cenniki:
                i = self._aktywny_indeks(cenniki)
                cenniki[i] = {"od": cenniki[i].get("od"), **wpis}
            else:
                cenniki = [{"od": None, **wpis}]
        else:  # nowy_cennik
            cenniki = [c for c in cenniki if c.get("od") != self._od]
            cenniki.append({"od": self._od, **wpis})
            cenniki.sort(key=lambda c: c.get("od") or "0000-00-00")
        return self._zapisz(cenniki=cenniki)

    def _zapisz(self, cenniki: list[dict] | None = None, warianty: list[dict] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        data = {
            CONF_ZRODLO: self._dane[CONF_ZRODLO],
            CONF_TARYFA: self._dane[CONF_TARYFA],
            CONF_CENNIKI: cenniki if cenniki is not None else list(self._dane.get(CONF_CENNIKI) or []),
            CONF_WARIANTY: warianty if warianty is not None else list(self._dane.get(CONF_WARIANTY) or []),
        }
        return self.async_update_and_abort(self._get_entry(), sub, title=self._dane["nazwa"], data=data)
