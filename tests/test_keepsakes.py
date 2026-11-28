import hashlib

from fastapi.testclient import TestClient

from cove_pet_nest.auth import credentials
from cove_pet_nest.backup import create_backup, restore_backup
from cove_pet_nest.config import Settings
from cove_pet_nest.http import create_app
from cove_pet_nest.service import build_service
from test_http import login


def home(folder):
    service = build_service(Settings(folder))
    client = TestClient(create_app(service), base_url='http://127.0.0.1:8767')
    assert client.get('/api/keepsakes').status_code == 401
    login(client, credentials(service.settings))
    return service, client


def gifts(service, pet):
    from cove_pet_nest.keepsakes import deliver_note, deliver_toy
    forms = []
    for i in range(4):
        data = f'fixture-form-{i}'.encode()
        ref = hashlib.sha256(data).hexdigest() + '.webp'
        (service.settings.data_dir / 'assets' / ref).write_bytes(data)
        forms.append(ref)
    def send(db):
        return deliver_toy(db, source_id='fixture-gift', name='苔球', origin='一起读过花园的故事', forms=forms, now=100)
    with service.store.write() as db:
        toy = send(db)
        assert send(db) == toy
        note = deliver_note(db, source_id='fixture-note', pet_id=pet, kind='observation',
                            text='把那片小叶子藏在窗边了。', evidence=['fictional-story'], now=101)
    return toy, note, forms


def test_room_toys_notes_and_atomic_play(tmp_path):
    s,c = home(tmp_path / 'garden')
    pet = s.adopt('cat','石榴','fixture-cat',actor='user')['pet']['id']
    other_pet = s.adopt('dog','青豆','fixture-dog',actor='user')['pet']['id']
    toy,note,forms = gifts(s, pet)
    initial = c.get('/api/keepsakes').json()
    assert [n['kind'] for n in initial['notes']] == ['observation','arrival']
    assert initial['toys'][0]['forms'] == forms
    assert c.patch(f'/api/toys/{toy}', json={'placed':True,'x':.3,'y':.7,'form':3}).status_code == 200
    assert c.patch(f'/api/toys/{toy}', json={'form':4}).status_code == 422
    now = [1000.]
    s.store.clock = lambda:now[0]
    def play(event):
        return c.post(f'/api/toys/{toy}/play',json={'pet_id':pet,'request_id':event})
    first = play('first');assert first.json()['count']==1
    assert play('first').json()==first.json()
    assert play('second').status_code==429
    assert c.post(f'/api/toys/{toy}/play',json={'pet_id':other_pet,'request_id':'other-pet'}).status_code==429
    now[0]+=5
    assert play('second').json()['count']==2
    assert s.state()['pets'][0]['growth']==0
    assert c.patch(f'/api/toys/{toy}',json={'placed':False}).status_code==200
    assert c.patch(f'/api/notes/{note}',json={'favorite':True,'is_read':True}).status_code==200
    _, restarted=home(tmp_path/'garden')
    state = restarted.get('/api/keepsakes').json()
    assert state['notes'][0]['favorite'] and state['notes'][0]['is_read']
    assert not state['toys'][0]['placed'] and state['toys'][0]['form']==3
    assert state['toys'][0]['plays'][pet]==2
    _, other=home(tmp_path/'other')
    assert not other.get('/api/keepsakes').json()['toys']
    assert other.patch(f'/api/toys/{toy}',json={'placed':True}).status_code==404
    create_backup(s.store,tmp_path/'backup')
    restore_backup(tmp_path/'backup',tmp_path/'restored')
    for ref in forms:
        assert (tmp_path/'restored/assets'/ref).is_file()


def test_reptile_layouts_versions_and_owned_toys(tmp_path):
    s,c=home(tmp_path)
    ids={kind:s.adopt(kind,kind,kind,actor='user')['pet']['id'] for kind in ('cat','snake','lizard')}
    toy,_,_=gifts(s,ids['cat'])
    def url(kind):return '/api/habitats/'+ids[kind]
    artist={'kind':'toy','toy_id':toy,'x':.4,'y':.5,'scale':1.2}
    layout={'theme':'moss_forest','decor':[artist],'revision':0}
    assert c.put(url('cat'),json=layout).status_code==422
    assert c.put(url('snake'),json=layout).json()['revision']==1
    assert c.put(url('snake'),json=layout).status_code==409
    assert c.put(url('lizard'),json={**layout,'decor':[{**artist,'toy_id':'unowned'}]}).status_code==422
    assert c.put(url('lizard'),json={**layout,'decor':[{**artist,'x':10}]}).status_code==422
    assert c.get(url('snake')).json()['decor']==[artist]
    assert c.get(url('lizard')).json()['decor']==[]
    assert c.put(url('snake'),json={**layout,'decor':[],'revision':1}).json()['decor']==[]
