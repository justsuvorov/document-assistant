"""Cookie авторизации после входа через Keycloak.

До 0.9 в cookie лежали сами токены Keycloak: корпоративный токен больше 4 КБ
браузер не сохранял (бесконечный редирект на логин), а nginx отдавал 502 на
слишком большие заголовки. Теперь в cookie — подписанная запись о пользователе.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from document_assistant.auth import dependencies as deps
from document_assistant.auth.keycloak import TokenClaims
from document_assistant.core.settings import settings

CLAIMS = TokenClaims(sub="user-sub-1", preferred_username="ivanov", email=None,
                     roles=["r"] * 500)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    app = FastAPI()

    @app.get("/login")
    def login():
        r = RedirectResponse("/me", 302)
        deps.set_auth_cookie(r, CLAIMS)
        return r

    @app.get("/me")
    def me(user: deps.CurrentUser = Depends(deps.get_current_user)):
        return {"id": user.user_id, "name": user.user_name}

    @app.get("/logout")
    def logout():
        r = RedirectResponse("/", 302)
        deps.clear_auth_cookies(r)
        return r

    return TestClient(app)


def _auth_cookie(client) -> str:
    return deps._cookie_name(deps.AUTH_COOKIE)


def test_login_roundtrip(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert r.json() == {"id": "user-sub-1", "name": "ivanov"}


def test_cookie_is_small_regardless_of_token_size(client):
    r = client.get("/login", follow_redirects=False)
    value = r.cookies.get(_auth_cookie(client))
    assert value and len(value) < 500


def test_no_cookie_is_401(client):
    assert client.get("/me").status_code == 401


def test_tampered_cookie_is_rejected(client):
    client.get("/login", follow_redirects=False)
    good = client.cookies.get(_auth_cookie(client))
    client.cookies.set(_auth_cookie(client), good[:-2] + "xx")
    assert client.get("/me").status_code == 401


def test_other_secret_is_rejected(client, monkeypatch):
    client.get("/login", follow_redirects=False)
    monkeypatch.setattr(settings, "session_secret", type(settings.session_secret)("другой"))
    assert client.get("/me").status_code == 401


def test_expired_session_is_rejected(client, monkeypatch):
    client.get("/login", follow_redirects=False)
    monkeypatch.setattr(settings, "session_max_age_hours", -1)
    assert client.get("/me").status_code == 401


def test_logout_and_login_clear_legacy_token_cookies(client):
    r = client.get("/login", follow_redirects=False)
    cleared = [h for h in r.headers.get_list("set-cookie") if 'Max-Age=0' in h or 'max-age=0' in h.lower()]
    assert any(deps._cookie_name("access_token") in h for h in cleared)

    r = client.get("/logout", follow_redirects=False)
    names = " ".join(r.headers.get_list("set-cookie"))
    assert deps._cookie_name(deps.AUTH_COOKIE) in names


def test_changing_access_policy_invalidates_existing_sessions(client, monkeypatch):
    client.get("/login", follow_redirects=False)
    assert client.get("/me").status_code == 200
    monkeypatch.setattr(settings, "keycloak_allowed_groups", "dms-assistant")
    assert client.get("/me").status_code == 401


class TestAccessPolicy:
    @staticmethod
    def _check(monkeypatch, allow_groups="", allow_roles="", groups=(), roles=()):
        from document_assistant.auth.keycloak import access_denied_reason
        monkeypatch.setattr(settings, "keycloak_allowed_groups", allow_groups)
        monkeypatch.setattr(settings, "keycloak_allowed_roles", allow_roles)
        return access_denied_reason(TokenClaims(sub="s", preferred_username="u", email=None,
                                                roles=list(roles), groups=list(groups)))

    def test_no_policy_allows_everyone(self, monkeypatch):
        assert self._check(monkeypatch) is None

    def test_group_by_name_or_full_path_case_insensitive(self, monkeypatch):
        assert self._check(monkeypatch, allow_groups="dms-assistant",
                           groups=["/ВСК/DMS-Assistant"]) is None
        assert self._check(monkeypatch, allow_groups="/ВСК/dms-assistant",
                           groups=["/ВСК/DMS-Assistant"]) is None
        assert self._check(monkeypatch, allow_groups="other, dms-assistant",
                           groups=["dms-assistant"]) is None

    def test_user_without_group_is_denied(self, monkeypatch):
        reason = self._check(monkeypatch, allow_groups="dms-assistant", groups=["/ВСК/other"])
        assert reason and "other" in reason

    def test_parent_group_name_does_not_grant_access(self, monkeypatch):
        assert self._check(monkeypatch, allow_groups="ВСК", groups=["/ВСК/other"]) is not None

    def test_empty_groups_claim_hints_mapper(self, monkeypatch):
        reason = self._check(monkeypatch, allow_groups="dms-assistant")
        assert "Group Membership" in reason

    def test_role_is_enough(self, monkeypatch):
        assert self._check(monkeypatch, allow_groups="dms-assistant", allow_roles="dms-user",
                           roles=["dms-user"]) is None
