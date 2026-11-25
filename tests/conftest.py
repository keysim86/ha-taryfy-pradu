"""Wspólne przygotowanie testów w Home Assistancie."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Ładuj custom_components z repozytorium."""
    yield
