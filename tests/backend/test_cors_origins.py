"""CORS origins are a deployment boundary, not a convenience.

`allow_credentials=True` means an allowed origin can make *authenticated*
requests to this API. The Vite dev-server origins were unconditional, so a
production deployment permitted `http://localhost:5173` — harmless in most
threat models, wrong in all of them.
"""
from __future__ import annotations

import pytest

from app.core.config import (
    DEV_ENVS,
    VITE_DEV_ORIGINS,
    cors_origins,
    is_dev_env,
    settings,
)


@pytest.mark.parametrize("env", sorted(DEV_ENVS))
def test_development_environments_allow_the_vite_dev_server(monkeypatch, env: str) -> None:
    monkeypatch.setattr("app.core.config.settings.app_env", env)

    origins = cors_origins()

    assert is_dev_env()
    for dev_origin in VITE_DEV_ORIGINS:
        assert dev_origin in origins


@pytest.mark.parametrize("env", ["production", "prod", "staging", "anything-else"])
def test_non_development_environments_allow_only_the_configured_frontend(
    monkeypatch, env: str
) -> None:
    monkeypatch.setattr("app.core.config.settings.app_env", env)
    monkeypatch.setattr("app.core.config.settings.frontend_url", "https://zorali.example")

    origins = cors_origins()

    assert origins == ["https://zorali.example"]
    for dev_origin in VITE_DEV_ORIGINS:
        assert dev_origin not in origins


def test_the_configured_frontend_is_always_allowed(monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.app_env", "production")
    monkeypatch.setattr("app.core.config.settings.frontend_url", "https://zorali.example")

    assert "https://zorali.example" in cors_origins()


def test_demo_login_and_cors_share_one_definition_of_development(monkeypatch) -> None:
    """The gate that hides demo-login is the gate that drops the dev origins.

    Two separate notions of "is this production" is how one of them ends up
    stale; this asserts there is only one.
    """
    monkeypatch.setattr("app.core.config.settings.app_env", "production")
    assert not is_dev_env()
    assert cors_origins() == [settings.frontend_url]

    monkeypatch.setattr("app.core.config.settings.app_env", "local")
    assert is_dev_env()
    assert cors_origins() == [settings.frontend_url, *VITE_DEV_ORIGINS]
