from fastapi.testclient import TestClient
from test_evolution import nest
from cove_pet_nest.auth import credentials
from cove_pet_nest.http import create_app


def test_album_photo_routes_keep_actor_and_host_boundaries(tmp_path):
    n=nest(tmp_path);c=TestClient(create_app(n),base_url='http://127.0.0.1:8767');creds=credentials(n.settings)
    p=n.adopt('cat','宝宝','a',actor='user')['pet'];n.care('play','p',actor='user',pet_ids=[p['id']])
    event=n.album.sources()['events'][0]
    host={'Authorization':'Bearer '+creds['host_token']}
    assert c.get('/api/pets/'+p['id']+'/stages').status_code==401
    assert c.get('/api/life-events').status_code==401
    assert c.post('/api/photos',json={}).status_code==401
    assert c.post('/api/session',headers={'Authorization':'Bearer '+creds['browser_token']}).status_code==200
    assert c.get('/api/pets/'+p['id']+'/stages').json()['stages'][0]['stage']==0
    assert c.get('/api/life-events',params={'pet_id':p['id']}).json()['total']==1
    body={'event_id':event['id'],'request_id':'photo'}
    result=c.post('/api/photos',json=body)
    assert result.status_code==200 and result.json()['purpose']=='photo'
    assert c.post('/api/photos',json=body).json()==result.json()
    assert c.post('/api/photos',json={**body,'actor':'assistant'}).status_code==422
    assert c.post('/api/integration/life-events',json={}).status_code==401
    assert c.get('/api/integration/pets/'+p['id']+'/stages',headers=host).status_code==200
    assert c.get('/api/integration/life-events',headers=host).status_code==200
    event_body={'event_id':'demo','occurred_at':n.store.now(),'kind':'reading','pet_ids':[p['id']]}
    assert c.post('/api/integration/life-events',headers=host,json=event_body).status_code==200
    assert c.post('/api/integration/life-events',headers=host,json={**event_body,'summary':'PRIVATE_RAW_TEXT'}).status_code==422
    assert c.post('/api/integration/photos',headers=host,json={'event_id':event['id'],'request_id':'host-photo'}).status_code==200
    assert c.get('/api/life-events',params={'limit':0}).status_code==422
    assert c.get('/api/life-events',params={'pet_id':'absent'}).status_code==404
