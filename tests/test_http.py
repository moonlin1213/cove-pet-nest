from fastapi.testclient import TestClient
import pytest


def client_for(tmp_path):
    from cove_pet_nest.config import Settings
    from cove_pet_nest.service import build_service
    from cove_pet_nest.http import create_app
    from cove_pet_nest.auth import credentials
    settings=Settings(tmp_path)
    return TestClient(create_app(build_service(settings)),base_url='http://127.0.0.1:8767'),credentials(settings)


def login(client,creds):
    return client.post('/api/session',headers={'Authorization':'Bearer '+creds['browser_token'],'Origin':'http://127.0.0.1:8767'})


def test_http_identity_and_integration_boundary(tmp_path):
    c,creds=client_for(tmp_path)
    assert c.get('/api/nest').status_code==401
    assert login(c,creds).status_code==200
    pet=c.post('/api/adoptions',json={'kind':'cat','name':'团团','request_id':'a'}).json()['pet']
    receipt=c.post('/api/care',json={'action':'feed','pet_ids':[pet['id']],'request_id':'f'})
    assert receipt.status_code==200 and receipt.json()['results'][0]['status']=='fed'
    assert c.get('/api/nest').json()['events'][0]['actor']=='user'
    assert c.post('/api/care',json={'action':'play','pet_ids':[pet['id']],'request_id':'p','actor':'assistant'}).status_code==422
    assert c.post('/api/integration/usage',json={}).status_code==401
    assert c.get('/api/nest',headers={'Host':'evil.example'}).status_code==403
    assert c.post('/api/care',headers={'Origin':'https://evil.example'},json={}).status_code==403
    body={'event_id':'r','occurred_at':0,'summary':'PRIVATE_EXAMPLE_ONLY','signals':{'affection':3}}
    assert c.post('/api/integration/relationship',headers={'Authorization':'Bearer '+creds['host_token']},json=body).status_code==200
    assert 'PRIVATE_EXAMPLE_ONLY' not in c.get('/api/nest').text
    assert c.get('/api/assets/..%2Fcredentials.json').status_code in (404,422)


def test_validation_errors_do_not_echo_secrets(tmp_path):
    c,creds=client_for(tmp_path); login(c,creds)
    r=c.post('/api/adoptions',json={'kind':'invalid','name':'PRIVATE_INPUT','request_id':'a','secret':'PRIVATE_SECRET'})
    assert r.status_code==422
    assert 'PRIVATE_SECRET' not in r.text and 'PRIVATE_INPUT' not in r.text


def test_host_token_cannot_impersonate_browser(tmp_path):
    c,creds=client_for(tmp_path)
    assert c.post('/api/session',headers={'Authorization':'Bearer '+creds['host_token']}).status_code==401
    assert c.get('/api/nest',headers={'Authorization':'Bearer '+creds['host_token']}).status_code==401


def test_host_http_tools_use_fixed_assistant_identity(tmp_path):
    c,creds=client_for(tmp_path); login(c,creds)
    headers={'Authorization':'Bearer '+creds['host_token']}
    assert c.get('/api/integration/nest').status_code==401
    assert c.post('/api/integration/adoptions',json={}).status_code==401
    assert c.post('/api/integration/care',json={}).status_code==401
    pet=c.post('/api/integration/adoptions',headers=headers,
               json={'kind':'cat','name':'宝宝','request_id':'host-adopt'}).json()['pet']
    body={'action':'feed','pet_ids':[pet['id']],'request_id':'host-feed'}
    receipt=c.post('/api/integration/care',headers=headers,json=body)
    assert receipt.status_code==200 and receipt.json()['results'][0]['status']=='fed'
    assert c.post('/api/integration/care',headers=headers,json=body).json()==receipt.json()
    state=c.get('/api/integration/nest',headers=headers).json()
    assert state['events'][0]['actor']=='assistant'
    assert c.post('/api/integration/care',headers=headers,json={**body,'actor':'user'}).status_code==422
