"""Smoke: the servable composition builds (transport only, no real model)."""

from agents.jev.__main__ import build_app
from tests.agents.jev.test_classifier import RUNTIME, FakeProvider, fixture_response


def test_main_composition_builds() -> None:
    app = build_app(provider=FakeProvider(fixture_response()), runtime=RUNTIME)

    assert app is not None, "provider + runtime + classify compose into the app"
