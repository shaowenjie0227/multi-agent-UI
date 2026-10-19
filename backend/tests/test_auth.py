"""可选鉴权：token 为空时放行；设置后 /api 与 /ws 必须携带。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "store", main_mod.Store())
    return TestClient(main_mod.app), main_mod


def test_no_token_means_open(client):
    c, _ = client
    assert c.get("/api/providers").status_code == 200


def test_token_required_after_enable(client):
    c, main_mod = client
    main_mod.store.update_settings(auth={"token": "s3cret"})
    assert c.get("/api/providers").status_code == 401
    ok = c.get("/api/providers", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_x_auth_token_header_and_query(client):
    c, main_mod = client
    main_mod.store.update_settings(auth={"token": "s3cret"})
    assert c.get("/api/providers", headers={"X-Auth-Token": "s3cret"}).status_code == 200
    assert c.get("/api/providers", params={"token": "s3cret"}).status_code == 200


def test_wrong_token_rejected(client):
    c, main_mod = client
    main_mod.store.update_settings(auth={"token": "s3cret"})
    assert c.get("/api/providers", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_settings_endpoint_stays_public(client):
    """前端需要先读设置判断要不要提示填 token。"""
    c, main_mod = client
    main_mod.store.update_settings(auth={"token": "s3cret"})
    assert c.get("/api/settings").status_code == 200


def test_disabling_token_reopens_access(client):
    c, main_mod = client
    main_mod.store.update_settings(auth={"token": "s3cret"})
    assert c.get("/api/providers").status_code == 401
    main_mod.store.update_settings(auth={"token": ""})
    assert c.get("/api/providers").status_code == 200
