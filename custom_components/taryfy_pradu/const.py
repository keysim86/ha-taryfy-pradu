"""Stałe integracji Taryfy prądu."""

DOMAIN = "taryfy_pradu"

TYP_TARYFA = "taryfa"
TYP_PUNKT = "punkt"

CONF_DEFINICJA = "definicja"
CONF_WZORZEC = "wzorzec"
CONF_ZRODLO = "zrodlo"
CONF_TARYFA = "taryfa"
CONF_CENNIKI = "cenniki"
CONF_WARIANTY = "warianty"

ZDARZENIE_ZMIANA_STREFY = f"{DOMAIN}_zmiana_strefy"
SYGNAL_AKTUALIZACJA = f"{DOMAIN}_aktualizacja_{{}}"

WALUTA = "PLN"
JEDNOSTKA_CENY = "PLN/kWh"
