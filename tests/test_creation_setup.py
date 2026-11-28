"""Only the signed-in local household can opt into creation."""
import os
from pathlib import Path

from test_http import client_for, login


def test_upgrade_is_quiet_and_configuration_is_household_local(tmp_path, monkeypatch):
    for prefix in ("TEXT", "IMAGE"):
        for name in ("ENDPOINT", "MODEL", "KEY"):
            monkeypatch.delenv(f"PET_NEST_{prefix}_{name}", raising=False)
    a, creds = client_for(tmp_path / "one")
    b, other = client_for(tmp_path / "two")
    login(a, creds)
    login(b, other)
    route = "/api/creation/settings"
    empty = a.get(route)
    assert empty.status_code == 200
    assert empty.json()["notes_enabled"] is False
    assert empty.json()["toys_enabled"] is False
    assert not empty.json()["text"]["ready"]
    secret = "fixture-" + "only-here"
    provider = {"endpoint": "https://fiction.example.test/chat", "model": "sample", "key": secret}
    result = a.post(route, json={"text": provider, "notes_enabled": True, "daily_text_limit": 2})
    assert result.status_code == 200
    assert secret not in result.text and "fiction.example" not in result.text
    assert result.json()["notes_enabled"] and result.json()["text"]["ready"]
    fresh, fresh_creds = client_for(tmp_path / "one")
    login(fresh, fresh_creds)
    assert fresh.get(route).json() == result.json()
    assert not b.get(route).json()["text"]["ready"]
    from cove_pet_nest.creation_setup import load_creation_settings
    config = load_creation_settings(tmp_path / "one")
    assert config.text.key == secret and config.daily_text_limit == 2
    if os.name != "nt":
        assert (tmp_path / "one/creation-settings.json").stat().st_mode & 0o077 == 0
    assert a.post(route, json={"notes_enabled":False}).json()["notes_enabled"] is False
    assert load_creation_settings(tmp_path / "one").text.key == secret


def test_provider_replacement_does_not_forward_an_existing_key(tmp_path, monkeypatch):
    for field, value in {"ENDPOINT":"https://first.example.test/generate","MODEL":"original","KEY":"fixture-a"}.items():
        monkeypatch.setenv("PET_NEST_IMAGE_"+field,value)
    c, credentials = client_for(tmp_path)
    login(c, credentials)
    route = "/api/creation/settings"
    initial = c.get(route)
    assert initial.status_code == 200
    assert initial.json()["image"] == {"ready":True,"source":"environment"}
    assert c.post(route,json={"image":{"endpoint":"https://different.example.test/image","model":"other"}}).status_code == 422
    assert c.post(route,json={"text":{"endpoint":"https://bad.example.test/chat?token=x","model":"t","key":"fake"}}).status_code == 422
    assert c.get(route).json()["image"] == initial.json()["image"]
    assert c.post(route,json={"image":{"endpoint":"https://new.example.test/image","model":"other","key":"fixture-b"}}).json()["image"]["source"] == "household"
    assert c.post(route,json={"reset_image":True}).json()["image"] == initial.json()["image"]


def test_diagnostics_do_not_supply_production_evidence_and_creation_requires_session(tmp_path):
    c, creds = client_for(tmp_path)
    url = "/api/creation"
    host = {"Authorization":"Bearer "+creds["host_token"]}
    for method,path in (("get","/settings"),("post","/settings"),("post","/diagnostic"),("post","/trial")):
        assert getattr(c,method)(url+path,headers=host,**({} if method=="get" else {"json":{}})).status_code==401
    login(c, creds)
    for _ in range(2):
        r = c.post(url+"/diagnostic",json={})
        assert r.status_code == 200
        assert r.json()["stored"] and r.json()["deduplicated"] and r.json()["isolated"]
    assert not any(c.get(url+"/settings").json()["sources"].values())
    assert c.post(url+"/trial",json={"confirmed":False,"request_id":"one"}).status_code==422
    r=c.post("/api/integration/relationship",headers=host,json={"event_id":"demo","occurred_at":1,"summary":"sample"})
    assert r.status_code==200
    assert c.get(url+"/settings").json()["sources"]["relationship"] is True


def test_upgrade_guide_is_present_at_both_entrypoints_with_port_independent_links(tmp_path):
    c, _ = client_for(tmp_path)
    for page in ("/","/passport"):
        content=c.get(page).text
        assert 'href="/creation"' in content
        assert "data-copy-creation-guide" in content
    assert c.get("/creation").status_code==200
    guide=c.get("/creation/guide")
    assert guide.status_code == 200 and "工程 agent" in guide.text
    assert "/api/integration/relationship" in guide.text
