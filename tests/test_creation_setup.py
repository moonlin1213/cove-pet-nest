"""Only the signed-in local household can opt into creation."""
import os

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
    assert "首次安装" in guide.text and "browser-url.txt" in guide.text


def test_creation_accepts_loopback_http_but_blocks_plain_http_remote_including_env(tmp_path, monkeypatch):
    from cove_pet_nest.creation_setup import load_creation_settings
    c,creds=client_for(tmp_path)
    login(c,creds)
    route='/api/creation/settings'
    monkeypatch.setenv('PET_NEST_TEXT_MODEL','demo')
    monkeypatch.setenv('PET_NEST_TEXT_KEY','fixture')
    monkeypatch.setenv('PET_NEST_TEXT_ENDPOINT','http://remote.example.test/chat')
    assert c.get(route).json()['text'].get('invalid') is True
    assert not load_creation_settings(tmp_path).text.ready
    for endpoint in ('http://lan.example.test/image', 'http://127.0.0.1.evil.test/image',
                     'https://user@elsewhere.test', 'https://@elsewhere.test', 'https://host.test:invalid/chat'):
        assert c.post(route,json={'image':{'endpoint':endpoint,'model':'demo','key':'fixture'}}).status_code==422
    for host in ('127.0.0.1','localhost','[::1]'):
        result=c.post(route,json={'image':{'endpoint':f'http://{host}:8080/image','model':'demo','key':'fixture'}})
        assert result.status_code==200
        assert load_creation_settings(tmp_path).image.ready
    monkeypatch.setenv('PET_NEST_TEXT_ENDPOINT','https://remote.example.test/chat')
    monkeypatch.setenv('PET_NEST_TEXT_KEY','contains\nnewline')
    assert c.get(route).json()['text'].get('invalid') is True


def test_care_only_is_a_note_source_but_not_a_toy_source(tmp_path):
    c, creds=client_for(tmp_path)
    login(c,creds)
    provider={'endpoint':'https://fiction.example.test/model','model':'test','key':'fixture'}
    c.post('/api/creation/settings',json={'text':provider,'image':provider,'notes_enabled':True,'toys_enabled':True})
    pet=c.post('/api/adoptions',json={'kind':'cat','name':'虚构猫','request_id':'fiction-cat'}).json()['pet']
    c.post('/api/care',json={'action':'comfort','pet_ids':[pet['id']],'request_id':'fiction-care'}).raise_for_status()
    state=c.post('/api/creation/diagnostic',json={}).json()['settings']
    assert state['sources']=={'care':True,'life':False,'relationship':False}
    assert state['feature_status']=={'notes':'waiting_opportunity','toys':'needs_shared_interaction'}


def test_windows_secret_storage_writes_only_account_protected_keys(tmp_path, monkeypatch):
    from cove_pet_nest import creation_setup as setup
    monkeypatch.setattr(setup,'WINDOWS',True)
    sealed='fake-dpapi-ciphertext'
    protected=[]
    def protect(raw):
        protected.append(raw)
        return sealed
    monkeypatch.setattr(setup,'protect_key',protect)
    monkeypatch.setattr(setup,'unprotect_key',lambda value:protected[0] if value==sealed else None)
    c, creds=client_for(tmp_path)
    login(c,creds)
    state=c.post('/api/creation/settings',json={'text':{'endpoint':'https://fiction.example.test/chat',
        'model':'demo','key':'private-fixture'},'notes_enabled':True})
    assert state.status_code==200 and state.json()['text']['ready']
    stored=(tmp_path/'creation-settings.json').read_text()
    assert sealed in stored and 'private-fixture' not in stored
    assert setup.load_creation_settings(tmp_path).text.key=='private-fixture'
    protected.clear()
    def unavailable(_):
        raise OSError('unavailable')
    monkeypatch.setattr(setup,'protect_key',unavailable)
    result=c.post('/api/creation/settings',json={'image':{'endpoint':'https://fiction.example.test/img',
        'model':'demo','key':'another-private-fixture'}})
    assert result.status_code==503 and (tmp_path/'creation-settings.json').read_text()==stored
    # A copied POSIX file must not be rewritten into another plaintext temp or final file.
    (tmp_path/'creation-settings.json').write_text('{"text":{"key":"imported-private-fixture"}}')
    assert c.post('/api/creation/settings',json={'daily_text_limit':4}).status_code==409
    assert c.post('/api/creation/settings',json={'reset_text':True}).status_code==200


def test_real_windows_dpapi_roundtrip():
    import pytest
    if os.name!='nt':
        pytest.skip('native Windows DPAPI')
    from cove_pet_nest.windows_secrets import protect_key,unprotect_key
    value='private-fixture'
    sealed=protect_key(value)
    assert value not in sealed and unprotect_key(sealed)==value

def test_invalid_stored_consent_and_quota_cannot_start_requests(tmp_path):
    from cove_pet_nest.creation_setup import load_creation_settings
    (tmp_path/'creation-settings.json').write_text('{"text":"broken","daily_text_limit":"9","notes_enabled":"yes","toys_enabled":42}')
    cfg=load_creation_settings(tmp_path)
    assert cfg.text.invalid and not cfg.text.ready
    assert cfg.notes_enabled is False and cfg.toys_enabled is False and cfg.daily_text_limit==0


def test_invalid_legacy_image_routes_allow_room_start_and_valid_generation(tmp_path, monkeypatch):
    for key,value in {'MODEL':'fiction','KEY':'fixture','ENDPOINT':'bad://generation'}.items():
        monkeypatch.setenv('PET_NEST_IMAGE_'+key,value)
    client,creds=client_for(tmp_path)
    login(client,creds)
    assert client.get('/api/nest').json()['image_generation_configured'] is False
    assert client.get('/api/creation/settings').json()['image']['invalid']
    monkeypatch.setenv('PET_NEST_IMAGE_ENDPOINT','https://fiction.example.test/generate')
    monkeypatch.setenv('PET_NEST_IMAGE_EDIT_ENDPOINT','http://[broken')
    client,creds=client_for(tmp_path)
    login(client,creds)
    state=client.get('/api/nest').json()
    assert state['image_generation_configured'] and not state['image_edit_configured']
    assert client.get('/api/creation/settings').json()['image']['ready']
    monkeypatch.setenv('PET_NEST_IMAGE_ENDPOINT','https://fiction.example.test:badport/generate')
    client,creds=client_for(tmp_path)
    login(client,creds)
    assert client.get('/api/nest').json()['image_generation_configured'] is False


def test_source_history_and_available_material_are_reported_separately(tmp_path):
    from cove_pet_nest.config import Settings
    from cove_pet_nest.creation_setup import SettingsPatch, save_creation_settings, public_settings
    from cove_pet_nest.creation_material import DAY
    from cove_pet_nest.contracts import RelationshipEvent
    from cove_pet_nest.relationships import record_relationship
    from cove_pet_nest.service import build_service
    service=build_service(Settings(tmp_path))
    now=1_800_000_000
    service.store.clock=lambda:now-20*DAY
    service.adopt('cat','虚构猫','first',actor='user')
    service.store.clock=lambda:now
    provider={'endpoint':'https://fiction.example.test/unused','model':'fiction','key':'sample'}
    save_creation_settings(service,SettingsPatch(text=provider,image=provider,notes_enabled=True,toys_enabled=True))
    def event(event_id,days_ago,summary):
        record_relationship(service.store,RelationshipEvent(event_id=event_id,occurred_at=now-days_ago*DAY,
                                                            summary=summary,signals={'reading':1}))
    event('empty',0,'')
    event('old',15,'虚构海鸥')
    waiting={'notes':'needs_interaction','toys':'needs_shared_interaction'}
    status=public_settings(service)
    assert status['sources']['relationship']
    assert status['feature_status']==waiting
    event('recent-for-toy',9,'虚构航船')
    assert public_settings(service)['feature_status']=={**waiting,'toys':'waiting_opportunity'}
    event('recent-for-both',1,'虚构灯塔')
    assert public_settings(service)['feature_status']=={'notes':'waiting_opportunity','toys':'waiting_opportunity'}
    with service.store.write() as db:
        for kind,source in [('toy','recent-for-toy'),('toy','recent-for-both'),('note','recent-for-both')]:
            db.execute("INSERT INTO creation_jobs(id,kind,source_id,material,status) VALUES(?,?,?,'{}','success')",
                       (kind+source,kind,'relationship:'+source))
    assert public_settings(service)['feature_status']==waiting
