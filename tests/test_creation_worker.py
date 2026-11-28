import asyncio
from io import BytesIO
import json
from random import Random
from types import SimpleNamespace
import httpx
from PIL import Image, ImageDraw
import pytest

from cove_pet_nest.config import Settings
from cove_pet_nest.contracts import RelationshipEvent
from cove_pet_nest.relationships import record_relationship
from cove_pet_nest.service import build_service
from cove_pet_nest.store import NestError
from cove_pet_nest.images.transport import ImageTransport

DAY = 86400


def atlas(empty_cell=False):
    canvas = Image.new('RGBA', (512, 512))
    draw = ImageDraw.Draw(canvas)
    for i, color in enumerate(['red','blue','yellow','purple']):
        if i == 3 and empty_cell:
            break
        x,y=(i%2)*256,(i//2)*256
        draw.ellipse((x+20,y+20,x+236,y+236),fill=color)
    out=BytesIO()
    canvas.save(out,format='PNG')
    return out.getvalue()


class Fixed(Random):
    def random(self):
        return 0.125


APPEARANCE={'shape':'lighthouse','material':'felt','color':'orange','detail':'stars'}


class FakeProviders:
    def __init__(self):
        self.calls=[]
        self.images=[]

    async def text(self,cfg,kind,material):
        self.calls.append((kind,material))
        source=material['source']
        if kind=='toy':
            return {'evidence':'source','name':'小灯','appearance':APPEARANCE,'quote':source['fact'][:12]}
        return {'evidence':'source','quote':source['fact'][:12], 'kind':'affection','ending':'蹭蹭你'}

    async def generate(self,brief,reference):
        self.images.append((brief,reference))
        return atlas()


def household(folder, enabled=True):
    svc=build_service(Settings(folder))
    svc.store.clock=lambda:1_800_000_000
    member=svc.adopt('cat','小雨','adopt',actor='user')['pet']['id']
    now=[svc.store.now()]
    svc.store.clock=lambda:now[0]
    ready=SimpleNamespace(ready=True,endpoint='https://invalid.example.test',model='fixture',key='fixture')
    cfg=SimpleNamespace(notes_enabled=enabled,toys_enabled=enabled,daily_text_limit=8,text=ready,image=ready)
    fake=FakeProviders()
    worker=svc.creation
    worker.config=lambda:cfg
    worker.rng=Fixed(2)
    worker.generate_text=fake.text
    worker.image_transport=lambda _:fake
    return svc,member,now,cfg,fake


def event(svc,summary):
    record_relationship(svc.store,RelationshipEvent(event_id='story',occurred_at=svc.store.now(),summary=summary,signals={'reading':1}))


def rows(svc,sql,args=()):
    with svc.store.connect() as db:
        return list(db.execute(sql,args))


def test_home_creations_restart_isolation_and_evidence(tmp_path):
    a,pet,clock,cfg,one=household(tmp_path/'a')
    b,_,_,_,two=household(tmp_path/'b',False)
    event(a,'一起读了灯塔故事');event(b,'另一家一起看彩虹')
    asyncio.run(a.tick());asyncio.run(b.tick())
    assert one.calls==two.calls==[]
    due=rows(a,'select toy_due from creation_schedule')[0][0]
    assert clock[0]+DAY<=due<=clock[0]+7*DAY
    asyncio.run(a.tick())
    assert rows(a,'select toy_due from creation_schedule')[0][0]==due
    clock[0]=due+1
    for _ in range(4):asyncio.run(a.tick())
    assert {kind for kind,_ in one.calls}=={'toy','note'}
    assert '灯塔故事' in str(one.calls) and '彩虹' not in str(one.calls)
    assert len(one.images)==1 and two.images==[]
    brief,refs=one.images[0]
    assert set(brief)=={'purpose','appearance'} and brief['appearance']==APPEARANCE and refs is None
    assert len(rows(a,"select * from keepsake_notes where kind='arrival'"))==1
    assert rows(a,"select pet_id from keepsake_notes where kind='affection'")[0][0]==pet
    assert all(j['status']=='success' for j in a.creation.status())
    assert rows(b,'select * from creation_jobs')==[]


def test_mcp_care_note_claim_is_atomic_and_daily_budget(tmp_path):
    svc,pet,clock,cfg,provider=household(tmp_path)
    cfg.toys_enabled=False;cfg.daily_text_limit=1
    clock[0]+=DAY+1
    svc.care('comfort','touch',actor='assistant',pet_ids=[pet])
    async def run():
        await asyncio.gather(svc.creation.tick(),svc.creation.tick())
    asyncio.run(run())
    assert len(provider.calls)==1
    source=provider.calls[0][1]['source']
    assert source['actor']=='assistant' and source['action']=='comfort'
    assert len(rows(svc,"select * from keepsake_notes where pet_id=?",(pet,)))==1
    result=asyncio.run(svc.creation.trial('trial-first'))
    assert result['status']=='daily_limit' and len(provider.calls)==1


def test_unknown_submission_never_auto_resends_and_retry_is_idempotent(tmp_path):
    svc,_,clock,cfg,provider=household(tmp_path)
    cfg.notes_enabled=False;event(svc,'一起看了灯塔的照片')
    asyncio.run(svc.tick());clock[0]=rows(svc,'select toy_due from creation_schedule')[0][0]
    async def timeout(*args):
        provider.calls.append('timeout')
        raise httpx.ReadTimeout('synthetic')
    svc.creation.generate_text=timeout
    asyncio.run(svc.tick());asyncio.run(svc.tick())
    job=svc.creation.status()[0]
    assert job['status']=='unknown' and provider.calls==['timeout']
    with pytest.raises(NestError):svc.creation.retry(job['id'],'retry',False)
    assert svc.creation.retry(job['id'],'retry',True)==svc.creation.retry(job['id'],'retry',True)
    svc.creation.generate_text=provider.text
    cfg.toys_enabled=False;asyncio.run(svc.tick());assert provider.images==[]
    cfg.toys_enabled=True;asyncio.run(svc.tick())
    assert len(provider.calls)==2 and len(provider.images)==1


def test_model_must_reference_the_real_source_and_cannot_write_an_invented_care(tmp_path):
    svc,pet,clock,cfg,_=household(tmp_path)
    cfg.toys_enabled=False;clock[0]+=DAY;svc.care('play','party',actor='user',pet_ids=[pet])
    async def wrong(*args):
        return {'evidence':'source','quote':'刚刚喂我吃鱼了','kind':'affection','ending':'蹭蹭你'}
    svc.creation.generate_text=wrong
    asyncio.run(svc.tick())
    assert svc.creation.status()[0]['status']=='failed'
    assert rows(svc,'select * from keepsake_notes')==[]


def test_toy_image_quota_unknown_and_empty_cell(tmp_path):
    svc,_,clock,cfg,provider=household(tmp_path);cfg.notes_enabled=False
    event(svc,'一起看了风车');asyncio.run(svc.tick())
    clock[0]=rows(svc,'select toy_due from creation_schedule')[0][0]
    with svc.store.write() as db:
        for i in range(3):
            db.execute('insert into image_submissions values(?,1,?,1)',(str(i),svc.store.day(clock[0])))
    asyncio.run(svc.tick());assert not provider.images
    assert svc.creation.status()[0]['status']=='waiting_image'
    clock[0]+=DAY
    async def bad(*args):
        provider.images.append('sent')
        return atlas(empty_cell=True)
    provider.generate=bad;asyncio.run(svc.tick());asyncio.run(svc.tick())
    assert provider.images==['sent'] and svc.creation.status()[0]['status']=='failed'
    assert rows(svc,"select * from keepsake_notes where kind='arrival'")==[]


def test_toy_transport_uses_square_four_form_request():
    seen=[]
    def receive(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'data':[{'b64_json':'dGVzdA=='}]})
    image=ImageTransport('https://example.test/images','model','fixture',http_transport=httpx.MockTransport(receive))
    asyncio.run(image.generate({'purpose':'toy','appearance':APPEARANCE}))
    assert seen[0]['size']=='1024x1024' and seen[0]['background']=='transparent'
    assert 'orange felt lighthouse' in seen[0]['prompt'] and '2x2' in seen[0]['prompt']


def test_signed_off_trial_uses_synthetic_source_once_even_in_two_calls(tmp_path):
    svc,_,_,_,fake=household(tmp_path,enabled=False)
    event(svc,'这段真实数据不能用于诊断')
    async def both():
        return await asyncio.gather(svc.creation.trial('test-1'),svc.creation.trial('test-1'))
    results=asyncio.run(both())
    assert results[0]['id']==results[1]['id'] and results[1]['status']=='success'
    assert len(fake.calls)==1 and '真实数据不能' not in str(fake.calls) and '虚构' in str(fake.calls)
    assert all('concept' not in r for r in results)
    assert not rows(svc,"select * from image_jobs where purpose='toy'")
    assert rows(svc,'select calls from creation_usage')[0][0]==1


def test_interrupted_text_lease_survives_restart_and_old_result_cannot_win(tmp_path):
    svc,_,clock,cfg,fake=household(tmp_path)
    cfg.notes_enabled=False
    event(svc,'一起探索灯港');asyncio.run(svc.creation.tick())
    clock[0]=rows(svc,'select toy_due from creation_schedule')[0][0]
    started=asyncio.Event();finish=asyncio.Event()
    async def slow(*args):
        started.set()
        await finish.wait()
        return await fake.text(*args)
    svc.creation.generate_text=slow
    async def interrupt():
        first=asyncio.create_task(svc.creation.tick())
        await started.wait()
        second=build_service(Settings(tmp_path))
        second.store.clock=lambda:clock[0]
        second.creation.config=lambda:cfg
        clock[0]+=181
        await second.creation.tick()
        assert second.creation.status()[0]['status']=='unknown'
        finish.set()
        await first
        assert second.creation.status()[0]['status']=='unknown'
    asyncio.run(interrupt())
    assert not rows(svc,"select * from image_jobs where purpose='toy'")


def test_bad_creation_config_does_not_stop_existing_growth_loop(tmp_path):
    svc,_,_,_,_=household(tmp_path)
    def broken():
        raise NestError('creation_config_invalid')
    svc.creation.config=broken
    assert asyncio.run(svc.tick())['status']=='needs_image_configuration'


def test_note_allows_new_pet_voice_without_accepting_another_invented_event():
    from cove_pet_nest.creation_material import validate_answer
    material={'source':{'type':'relationship','fact':'一起读了灯塔故事'}}
    answer={'evidence':'source','quote':'灯塔故事','kind':'affection','ending':'呼噜，好想再听一遍呀'}
    assert '呼噜，好想再听一遍呀' in validate_answer('note',answer,material)['text']
    with pytest.raises(NestError):
        validate_answer('note',{**answer,'ending':'昨天又给我喂了三条鱼'},material)


def test_unknown_image_retries_consume_distinct_day_slots_even_after_restart(tmp_path):
    svc,_,clock,cfg,fake=household(tmp_path)
    cfg.notes_enabled=False
    event(svc,'一起读了灯塔故事');asyncio.run(svc.tick())
    clock[0]=rows(svc,'select toy_due from creation_schedule')[0][0]
    async def unavailable(*args):
        fake.images.append('attempt')
        raise httpx.ReadTimeout('synthetic')
    fake.generate=unavailable
    for i in range(4):
        asyncio.run(svc.tick())
        job=svc.creation.status()[0]
        if i<3:
            assert job['status']=='unknown'
            svc.creation.retry(job['id'],'attempt-'+str(i),True)
    assert len(fake.images)==3
    restarted=build_service(Settings(tmp_path))
    assert sum(r[0] for r in rows(restarted,'select units from image_submissions'))==3
    clock[0]+=DAY
    asyncio.run(svc.tick())
    assert len(fake.images)==4


def test_legacy_img_attempts_survive_migration_and_are_not_counted_twice(tmp_path):
    svc,_,clock,_,_=household(tmp_path)
    with svc.store.write() as db:
        db.execute('drop table if exists image_submissions')
        db.execute("""insert into image_jobs(id,brief,status,day,attempt)
            values('historical','{}','unknown',?,2)""",(svc.store.day(clock[0]),))
    for _ in range(2):
        restarted=build_service(Settings(tmp_path))
        assert rows(restarted,'select sum(units) from image_submissions')[0][0]==2


@pytest.mark.parametrize('appearance',[
    'copy private-source-name.example from private chat',{'shape':'fake-private-name','material':'felt','color':'orange','detail':'stars'},
    {'shape':'lighthouse','material':'felt','color':'orange','detail':'stars','extra':'private text'}])
def test_toy_rejects_free_provider_input_before_any_image_submission(tmp_path,appearance):
    svc,_,clock,cfg,fake=household(tmp_path)
    cfg.notes_enabled=False;event(svc,'家里私有的灯塔故事')
    asyncio.run(svc.tick());clock[0]=rows(svc,'select toy_due from creation_schedule')[0][0]
    async def leak(*args):
        return {'name':'塔','evidence':'source','quote':'灯塔','appearance':appearance}
    svc.creation.generate_text=leak
    asyncio.run(svc.tick())
    assert svc.creation.status()[0]['status']=='failed'
    assert fake.images==[]


def test_old_note_retry_rechecks_newer_note_cooldown_without_provider_call(tmp_path):
    svc,pet,clock,cfg,fake=household(tmp_path);cfg.toys_enabled=False
    clock[0]+=DAY
    svc.care('comfort','morning',actor='user',pet_ids=[pet])
    async def timeout(*args):raise httpx.ReadTimeout('fixture')
    svc.creation.generate_text=timeout;asyncio.run(svc.tick())
    original=svc.creation.status()[0];assert original['status']=='unknown'
    clock[0]+=DAY
    svc.care('play','afternoon',actor='assistant',pet_ids=[pet]);svc.creation.generate_text=fake.text
    asyncio.run(svc.tick())
    assert len(fake.calls)==1
    svc.creation.retry(original['id'],'try-old',True);asyncio.run(svc.tick())
    assert len(fake.calls)==1 and len(rows(svc,'select * from keepsake_notes where pet_id=?',(pet,)))==1


def test_old_toy_claim_after_14_days_is_skipped_without_submission(tmp_path):
    svc,_,clock,cfg,fake=household(tmp_path);cfg.notes_enabled=False
    event(svc,'有过一个风车');start=clock[0];asyncio.run(svc.tick())
    clock[0]=rows(svc,'select toy_due from creation_schedule')[0][0]
    cfg.daily_text_limit=0;asyncio.run(svc.tick());assert not fake.calls
    clock[0]=start+14*DAY+1;cfg.daily_text_limit=8;asyncio.run(svc.tick())
    assert not fake.calls and not fake.images


@pytest.mark.parametrize('host,trust',[('127.9.0.1',False),('[::1]',False),('localhost',False),('example.test',True)])
def test_provider_proxy_behavior_for_both_transports(monkeypatch,host,trust):
    from cove_pet_nest.creation_text import generate_text
    captures=[]
    real=httpx.AsyncClient
    def client(**kwargs):
        captures.append(kwargs.get('trust_env',True))
        payload={'data':[{'b64_json':'dGVzdA=='}],'choices':[{'message':{'content':'{}'}}]}
        kwargs['transport']=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))
        return real(**kwargs)
    monkeypatch.setattr(httpx,'AsyncClient',client)
    endpoint=f'http://{host}:8011/generate'
    asyncio.run(generate_text(SimpleNamespace(endpoint=endpoint,model='fixture',key='fixture'),'note',{}))
    asyncio.run(ImageTransport(endpoint,'fixture','fixture').generate({'kind':'cat'}))
    assert captures==[trust,trust]


def test_gateway_failure_has_unknown_charge_status(tmp_path):
    svc,_,clock,cfg,_=household(tmp_path)
    def gateway(req):return httpx.Response(504)
    svc.creation.image_transport=lambda _:ImageTransport('https://example.test/image','fixture','fixture',http_transport=httpx.MockTransport(gateway))
    cfg.notes_enabled=False;event(svc,'一起看了风车')
    asyncio.run(svc.tick());clock[0]=rows(svc,'select toy_due from creation_schedule')[0][0]
    asyncio.run(svc.tick());job=svc.creation.status()[0]
    assert job['status']=='unknown'
    with pytest.raises(NestError):svc.creation.retry(job['id'],'again',False)


def test_reserved_toy_art_expires_without_an_image_call(tmp_path):
    svc,_,clock,cfg,fake=household(tmp_path)
    cfg.notes_enabled=False
    start=clock[0]
    event(svc,'听了灯塔的故事')
    asyncio.run(svc.creation.tick())
    clock[0]=rows(svc,'select toy_due from creation_schedule')[0][0]
    asyncio.run(svc.creation.tick())
    assert svc.creation.status()[0]['status']=='waiting_image'
    clock[0]=start+14*DAY+1
    asyncio.run(svc.jobs.run_once())
    assert svc.creation.status()[0]['status']=='superseded'
    assert not fake.images and not rows(svc,'select * from image_submissions')


def test_concurrent_old_note_waits_for_in_flight_note_of_same_pet(tmp_path):
    svc,pet,clock,cfg,fake=household(tmp_path)
    cfg.toys_enabled=False
    clock[0]+=DAY
    svc.care('comfort','earlier',actor='user',pet_ids=[pet])
    async def timeout(*args):
        raise httpx.ReadTimeout('fictional')
    svc.creation.generate_text=timeout
    asyncio.run(svc.creation.tick())
    old=svc.creation.status()[0]
    clock[0]+=DAY
    svc.care('play','today',actor='assistant',pet_ids=[pet])
    async def race():
        started=asyncio.Event()
        finish=asyncio.Event()
        async def hold(*args):
            started.set()
            result=await fake.text(*args)
            if len(fake.calls)==1:
                await finish.wait()
            return result
        svc.creation.generate_text=hold
        latest=asyncio.create_task(svc.creation.tick())
        await started.wait()
        try:
            svc.creation.retry(old['id'],'retry-old',True)
            await svc.creation.tick()
            assert len(fake.calls)==1
        finally:
            finish.set()
            await latest
        await svc.creation.tick()
    asyncio.run(race())
    assert len(fake.calls)==1
    assert len(rows(svc,'select * from keepsake_notes where pet_id=?',(pet,)))==1
