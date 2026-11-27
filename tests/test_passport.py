import base64
import hashlib
import json
import time

import pytest

from test_http import client_for, login


def adopt(client, kind):
    return client.post('/api/adoptions', json={'kind':kind, 'name':kind, 'request_id':kind}).json()['pet']['id']


def test_authenticated_pack_keeps_order_and_paired_credentials(tmp_path, monkeypatch):
    from cove_pet_nest.passport.pairing import Pairing
    monkeypatch.setattr(Pairing, '_start_listener', lambda self, host, port: None)
    token='b'*64
    (tmp_path/'passport-bridge.json').write_text(json.dumps({'host':'192.168.1.23','port':8768,'token':token,'pets':['old']}))
    c, creds=client_for(tmp_path)
    assert c.get('/api/passport/status').status_code==401
    login(c,creds)
    a,b=adopt(c,'cat'),adopt(c,'dog')
    host='192.168.1.23'
    assert c.get('/api/passport/status').json()['pets']==['old']
    def pack(ids):
        return c.post('/api/passport/pack',json={'host':host,'slot':'b','pets':ids})
    assert pack(['missing']).status_code==422
    assert pack([a,a]).status_code==422
    unknown=adopt(c,'parrot')
    assert pack([unknown]).status_code==422
    package=pack([b,a]).json()
    assert package['wifi']=={'host':host,'port':8768,'token':token}
    files={}
    for item in package['files']:
        data=base64.b64decode(item['data'],validate=True)
        assert hashlib.sha256(data).hexdigest()==item['sha256']
        files[item['path']]=data
    roster=json.loads(files['/nest/link-b/roster.json'])['pets']
    assert [p['id'] for p in roster]==[b,a]
    assert len(files['/nest/link-b/p0/pose0.rgb'])==240*240*2
    assert len(files['/nest/link-b/p1/pose5.rgb'])==124*139*2
    assert '/portrait/link-b/p0.bin' in files
    assert not any('wifi' in path for path in files)
    assert c.get('/api/passport/status').json()['pets']==['old']
    payload={'ticket':package['ticket']}
    assert c.post('/api/passport/activate',json=payload).status_code==200
    assert c.post('/api/passport/activate',json=payload).status_code==200
    staged=json.loads((tmp_path/'passport-bridge.json').read_text())
    assert staged['pets']==['old']
    assert staged['pending']['pets']==[b,a]
    status=c.get('/api/passport/status').json()
    assert status['pending_ticket']==package['ticket']
    from cove_pet_nest.passport.bridge import dispatch
    growth={'id':'passport-'+'c'*32,'op':'wear','pet':b,'seconds':3600,'at':int(time.time())-3602}
    status,_=dispatch(None,staged,'POST','/companion',{'Authorization':'Bearer '+token},json.dumps(growth).encode())
    assert status==503  # Keep the record on the device until the active slot is confirmed.
    status,_=dispatch(None,staged,'POST','/api/pet-nest/care',{'Authorization':'Bearer '+token},json.dumps({
        'scope':'selected','pet_ids':[b],'action':'feed','request_id':'passport-'+'d'*32}).encode())
    assert status==503
    # Resume after losing the browser and restarting the local room.
    c,creds=client_for(tmp_path)
    login(c,creds)
    for _ in range(2):
        assert c.post('/api/passport/confirm',json=payload).status_code==200
    assert c.get('/api/passport/status').json()['pets']==[b,a]
    assert c.post('/api/passport/activate',json={'ticket':'0'*32}).status_code==409


def test_phone_only_authorized_clock_and_idempotent_growth(tmp_path):
    from cove_pet_nest.passport.bridge import dispatch
    from cove_pet_nest.config import Settings
    from cove_pet_nest.service import build_service
    service=build_service(Settings(tmp_path))
    pet=service.adopt('cat','fixture','a',actor='user')['pet']['id']
    token='b'*64
    cfg={'token':token,'pets':[pet]}
    def request(method,path,row=None,auth=token,origin=None):
        return dispatch(service,cfg,method,path,{'Authorization':'Bearer '+auth,**({'Origin':origin} if origin else {})},json.dumps(row).encode() if row is not None else b'')
    assert request('GET','/clock')[0]==200
    assert request('GET','/clock',auth='incorrect')[0]==403
    assert request('GET','/clock',origin='http://example.invalid')[0]==403
    assert request('GET','/api/nest')[0]==404
    row={'op':'wear','seconds':3600,'pet':pet,'id':'passport-'+'a'*32,'at':int(time.time())-3605}
    status,receipt=request('POST','/companion',row)
    assert status==200 and receipt['bonus']==1
    assert request('POST','/companion',row)==(200,receipt)
    assert request('POST','/companion',{**row,'pet':'other'})[1]['status']=='refused'
    assert request('POST','/companion',{**row,'seconds':123})[0] in (400,409,422)
    care={**row,'id':'passport-'+'d'*32,'op':'play','seconds':0}
    ok,played=request('POST','/companion',care)
    assert ok==200 and played['status']=='played' and played['bonus']==1
    assert request('POST','/companion',care)==(ok,played)
    assert len(service.state()['events'])==1


def test_device_listener_lives_with_room_and_restarts(tmp_path, monkeypatch):
    from urllib.request import Request, build_opener, ProxyHandler
    from urllib.error import HTTPError
    from cove_pet_nest.passport import pairing
    # Bind on loopback and ephemeral ports; no household interface or data is touched.
    real_listen = pairing.listen
    sockets = []
    def bind_fixture(service, host, port, config):
        server = real_listen(service,'127.0.0.1',0,config)
        sockets.append(server)
        return server
    monkeypatch.setattr(pairing,'listen',bind_fixture)
    token='d'*64
    (tmp_path/'passport-bridge.json').write_text(json.dumps({'host':'192.168.1.23','port':8768,'token':token,'pets':[]}))
    c,creds=client_for(tmp_path)
    login(c,creds)
    a,b=adopt(c,'cat'),adopt(c,'dog')
    with c:
        package=c.post('/api/passport/pack',json={'host':'192.168.1.23','slot':'a','pets':[a,b]}).json()
        ticket={'ticket':package['ticket']}
        assert c.post('/api/passport/activate',json=ticket).status_code==200
        assert c.post('/api/passport/confirm',json=ticket).status_code==200
    assert sockets and sockets[-1].fileno()==-1
    again,creds=client_for(tmp_path)
    opener=build_opener(ProxyHandler({}))
    with again:
        # Only the service is running: no browser login and no helper process.
        for _ in range(100):
            if sockets[-1].fileno()!=-1:break
            time.sleep(.02)
        url='http://127.0.0.1:'+str(sockets[-1].server_address[1])
        def call(path,obj=None,secret=token):
            req=Request(url+path,data=None if obj is None else json.dumps(obj).encode(),headers={'Authorization':'Bearer '+secret})
            with opener.open(req,timeout=3) as res:
                return json.load(res)
        assert abs(call('/clock')-time.time())<5
        assert [item['pet_id'] for item in call('/api/pet-nest/ecosystem')['pets']]==[a,b]
        with pytest.raises(HTTPError) as error: call('/clock',secret='invalid')
        assert error.value.code==403
        event={'id':'passport-'+'b'*32,'op':'wear','pet':b,'at':int(time.time())-3602,'seconds':3600}
        receipt=call('/companion',event)
        assert receipt['bonus']==1
        assert call('/companion',event)==receipt
    assert sockets[-1].fileno()==-1


def test_authenticated_status_provides_only_device_token_fingerprint(tmp_path):
    token='7'*64
    c,creds=client_for(tmp_path)
    assert c.get('/api/passport/status').status_code==401
    login(c,creds)
    assert c.get('/api/passport/status').json()['token_sha256']==''
    (tmp_path/'passport-bridge.json').write_text(json.dumps({
        'host':'192.168.1.23','port':8768,'pets':['old'],'token':token
    }))
    paired,creds=client_for(tmp_path)
    login(paired,creds)
    response=paired.get('/api/passport/status')
    assert response.json()['token_sha256']==hashlib.sha256(token.encode()).hexdigest()
    assert token not in response.text


def test_request_during_first_activation_fails_closed(tmp_path):
    from cove_pet_nest.passport.bridge import dispatch
    assert dispatch(None,{},'GET','/clock',{},b'')==(403,{})
    assert dispatch(None,{'token':'a'*64,'pets':[]},'GET','/clock',{'Authorization':'Bearer 非ASCII'},b'')==(403,{})


def test_menu_card_uses_room_timezone_for_sync_time(tmp_path,monkeypatch):
    from datetime import datetime,timezone
    from PIL import ImageDraw
    from cove_pet_nest.config import Settings
    from cove_pet_nest.service import build_service
    from cove_pet_nest.passport.pack import make_files
    service=build_service(Settings(tmp_path,timezone='Pacific/Honolulu'))
    service.store.clock=lambda:datetime(2026,1,1,3,30,tzinfo=timezone.utc).timestamp()
    pet=service.adopt('cat','fixture','a',actor='user')['pet']['id']
    labels=[]
    draw=ImageDraw.ImageDraw.text
    def capture(self,xy,text,*args,**kwargs):
        labels.append(text)
        return draw(self,xy,text,*args,**kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw,'text',capture)
    make_files(service,[pet],'a')
    assert any('同步 12/31 17:30' in t for t in labels)
