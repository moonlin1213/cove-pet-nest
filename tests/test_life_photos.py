import asyncio
from io import BytesIO
from PIL import Image
import pytest
from test_evolution import nest,grow
from test_hatch import atlas


def photo():
    image=Image.new('RGB',(768,512),(210,195,168));out=BytesIO();image.save(out,format='PNG');return out.getvalue()


class Camera:
    def __init__(self):self.received=[]
    async def generate(self,brief,reference=None):
        self.received.append((brief,reference))
        if brief.get('purpose')=='photo':return photo()
        image=Image.new('RGBA',(768,512),(0,0,0,0))
        image.paste((60+brief['stage']*30,110,140,255),(40,40,210,210))
        out=BytesIO();image.save(out,format='PNG');return out.getvalue()


def test_real_care_creates_one_frozen_photo_source_and_request_is_idempotent(tmp_path):
    c=Camera();n=nest(tmp_path,c)
    pet=n.adopt('cat','团团','a',actor='user')['pet']
    receipt=n.care('feed','feed',actor='assistant',pet_ids=[pet['id']])
    assert n.care('feed','feed',actor='assistant',pet_ids=[pet['id']])==receipt
    sources=n.album.sources(pet_id=pet['id'])
    assert sources['total']==1 and sources['events'][0]['kind']=='care_feed'
    source=sources['events'][0]
    job=n.album.queue_photo(source['id'],'photo-request',actor='user')
    assert n.album.queue_photo(source['id'],'photo-request',actor='user')==job
    assert n.album.queue_photo(source['id'],'different-request',actor='user')['id']==job['id']
    balance=n.state()['grains']
    assert asyncio.run(n.tick())['status']=='success'
    item=n.album.sources(pet_id=pet['id'])['events'][0]
    assert item['photo']['status']=='success' and item['photo']['asset_url'].endswith('.webp')
    assert len(c.received)==1 and len(c.received[0][1])==1
    assert n.state()['pets'][0]['stage']==0 and n.state()['grains']==balance
    assert n.jobs.for_pet(pet['id'])==[]
    assert asyncio.run(n.tick())['status']=='idle'


def test_shared_event_snapshots_participants_without_private_prose(tmp_path):
    from cove_pet_nest.contracts import LifeEvent
    n=nest(tmp_path,Camera());ids=[n.adopt(k,'宝宝',k,actor='user')['pet']['id'] for k in ('cat','dog')]
    event=LifeEvent(event_id='host-book-1',kind='reading',occurred_at=n.store.now(),pet_ids=ids)
    source=n.album.record(event)
    assert n.album.record(event)==source
    assert n.album.sources(pet_id=ids[1])['total']==1
    assert len(n.album.sources()['events'][0]['participants'])==2
    with pytest.raises(ValueError):
        n.album.record(event.model_copy(update={'kind':'listening'}))
    with pytest.raises(ValueError):
        LifeEvent(**{**event.model_dump(),'summary':'PRIVATE_RAW_STORY'})
    with pytest.raises(ValueError):
        n.album.record(event.model_copy(update={'event_id':'future','occurred_at':n.store.now()+600}))
    with pytest.raises(ValueError):
        n.album.record(event.model_copy(update={'event_id':'missing','pet_ids':['absent']}))
    n.album.queue_photo(source['id'],'photo',actor='user')
    grow(n,ids[0],40,7);asyncio.run(n.tick()) # stage has priority
    asyncio.run(n.tick())
    photo_calls=[item for item in n.jobs.transport.received if item[0].get('purpose')=='photo']
    assert photo_calls[0][0]['participants'][0]['stage']==0
    assert len(photo_calls[0][1])==2


def test_photo_timeout_cannot_requeue_without_explicit_acknowledgement(tmp_path):
    class Timeout:
        async def generate(self,brief,reference=None):raise TimeoutError('PRIVATE_SERVICE_MESSAGE')
    n=nest(tmp_path,Timeout());pet=n.adopt('cat','宝宝','a',actor='user')['pet']
    n.care('comfort','hug',actor='user',pet_ids=[pet['id']])
    event=n.album.sources()['events'][0];job=n.album.queue_photo(event['id'],'p',actor='user')
    assert asyncio.run(n.tick())['status']=='unknown'
    assert asyncio.run(n.tick())['status']=='idle'
    assert n.album.queue_photo(event['id'],'p2',actor='user')['status']=='unknown'
    with pytest.raises(ValueError):n.jobs.retry(job['id'],'retry')
    assert 'PRIVATE_SERVICE_MESSAGE' not in str(n.album.sources())


def test_historical_and_photo_assets_survive_backup_restore(tmp_path):
    from cove_pet_nest.backup import create_backup,restore_backup
    n=nest(tmp_path/'first',Camera());pet=n.adopt('cat','宝宝','a',actor='user')['pet']
    n.care('play','play',actor='user',pet_ids=[pet['id']])
    n.album.queue_photo(n.album.sources()['events'][0]['id'],'photo',actor='user')
    asyncio.run(n.tick())
    grow(n,pet['id'],40,7);asyncio.run(n.tick())
    grow(n,pet['id'],100,14);asyncio.run(n.tick())
    backup=tmp_path/'backup';create_backup(n.store,backup)
    restored=tmp_path/'restored';restore_backup(backup,restored)
    n2=nest(restored,None)
    assert n2.album.history(pet['id'])==n.album.history(pet['id'])
    refs=[s['asset_ref'] for s in n2.album.history(pet['id'])['stages'] if s['asset_ref']]
    assert len(set(refs))==2
    assert all(n2.jobs.asset_path(ref).is_file() for ref in refs)
    ref=n2.album.sources()['events'][0]['photo']['asset_ref']
    assert n2.jobs.asset_path(ref).is_file()


def test_photo_jobs_share_daily_budget_under_concurrent_workers(tmp_path):
    class SlowCamera(Camera):
        async def generate(self,brief,reference=None):
            await asyncio.sleep(.01)
            return await super().generate(brief,reference)
    n=nest(tmp_path,SlowCamera());pet=n.adopt('cat','宝宝','a',actor='user')['pet']
    for i in range(4):n.care('play','play-'+str(i),actor='user',pet_ids=[pet['id']])
    for source in n.album.sources()['events']:n.album.queue_photo(source['id'],'photo-'+source['id'],actor='user')
    async def run():return await asyncio.gather(*(n.jobs.run_once() for _ in range(4)))
    outcomes=asyncio.run(run())
    assert sum(result['status']=='success' for result in outcomes)==3
    assert sum(result['status']=='daily_limit' for result in outcomes)==1
    assert len(n.jobs.transport.received)==3


def test_missing_edit_endpoint_leaves_photo_reserved_without_attempt(tmp_path):
    class NoEdit:
        can_reference=False
        async def generate(self,*args):raise AssertionError('must not submit')
    n=nest(tmp_path,NoEdit());pet=n.adopt('cat','宝宝','a',actor='user')['pet']
    n.care('play','play',actor='user',pet_ids=[pet['id']])
    job=n.album.queue_photo(n.album.sources()['events'][0]['id'],'photo',actor='user')
    assert asyncio.run(n.tick())['status']=='needs_image_edit_configuration'
    with n.store.connect() as db:
        row=db.execute('SELECT status,attempt FROM image_jobs WHERE id=?',(job['id'],)).fetchone()
        assert row['status']=='reserved' and row['attempt']==0
