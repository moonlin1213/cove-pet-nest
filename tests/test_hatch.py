import asyncio
from io import BytesIO
import sqlite3

from PIL import Image
import pytest
from test_store import make_store


def atlas():
    image=Image.new('RGBA',(768,512),(0,0,0,0))
    for x in range(40,210):
        for y in range(40,210):
            image.putpixel((x,y),(160,110,80,255))
    stream=BytesIO(); image.save(stream,format='PNG')
    return stream.getvalue()


def test_hatch_identity_and_evidence(tmp_path):
    from cove_pet_nest.growth import prepare_hatch
    from cove_pet_nest.relationships import record_relationship
    from cove_pet_nest.contracts import RelationshipEvent
    s=make_store(tmp_path)
    pet=s.adopt('egg','神秘宝宝','egg',actor='user')['pet']
    assert prepare_hatch(s,pet['id'],now=s.now()) is None
    with sqlite3.connect(s.path) as db:
        db.execute('UPDATE pets SET growth=12')
    now=s.now()+172800
    r=RelationshipEvent(event_id='relationship1',occurred_at=now,summary='虚构的关系摘要',signals={'affection':3})
    s.clock=lambda:now
    assert record_relationship(s,r)['recorded'] is True
    assert record_relationship(s,r)['recorded'] is False
    brief=prepare_hatch(s,pet['id'],now=now)
    assert brief['dimension']=='affection' and brief['customized'] is True
    assert brief==prepare_hatch(s,pet['id'],now=now+100)
    assert '虚构的关系摘要' not in str(brief)
    with pytest.raises(ValueError):
        record_relationship(s,r.model_copy(update={'summary':'changed'}))
    with pytest.raises(ValueError):
        record_relationship(s,RelationshipEvent(event_id='future',occurred_at=now+3600))


def test_image_state_recovery(tmp_path):
    from cove_pet_nest.images.service import ImageJobService
    s=make_store(tmp_path)
    pet=s.adopt('parrot','小绿','bird',actor='user')['pet']
    class OfflineImage:
        async def generate(self,brief,reference=None):
            return atlas()
    jobs=ImageJobService(s,tmp_path/'assets',OfflineImage())
    job=jobs.enqueue(pet['id'],'generate1',{'stage':0,'dimension':'random'})
    assert jobs.enqueue(pet['id'],'generate1',{'stage':0,'dimension':'random'})==job
    asyncio.run(jobs.run_once())
    assert jobs.get(job['id'])['status']=='success'
    assert s.state()['pets'][0]['status']=='ready'
    assert s.state()['pets'][0]['asset_ref'].endswith('.webp')
    pet2=s.adopt('snake','小绿','snake',actor='user')['pet']
    class Disconnect:
        async def generate(self,brief,reference=None):
            raise TimeoutError('private provider response')
    failing=ImageJobService(s,tmp_path/'assets',Disconnect())
    job2=failing.enqueue(pet2['id'],'generate2',{'stage':0})
    asyncio.run(failing.run_once())
    assert failing.get(job2['id'])['status']=='unknown'
    assert 'private provider response' not in str(failing.get(job2['id']))
    assert asyncio.run(failing.run_once())['status']=='idle'
    with pytest.raises(ValueError):
        failing.retry(job2['id'],'retry1')
    assert failing.retry(job2['id'],'retry2',acknowledge_unknown=True)['status']=='reserved'


def test_asset_validation_and_path(tmp_path):
    from cove_pet_nest.images.processing import prepare_asset
    from cove_pet_nest.images.service import ImageJobService
    s=make_store(tmp_path)
    jobs=ImageJobService(s,tmp_path/'assets',None)
    assert prepare_asset(atlas()).startswith(b'RIFF')
    with pytest.raises(ValueError):
        prepare_asset(b'not an image')
    with pytest.raises(ValueError):
        jobs.asset_path('../secrets')


def test_different_relationships_shape_briefs(tmp_path):
    from cove_pet_nest.growth import prepare_hatch
    from cove_pet_nest.relationships import record_relationship
    from cove_pet_nest.contracts import RelationshipEvent
    briefs=[]
    for dimension in ('affection','listening'):
        s=make_store(tmp_path/dimension)
        pet=s.adopt('egg','宝宝','e',actor='user')['pet']
        with sqlite3.connect(s.path) as db:
            db.execute('UPDATE pets SET seed=?,growth=12',('fixed-seed',))
        s.clock=lambda:1_800_172_800.0
        record_relationship(s,RelationshipEvent(event_id='r',occurred_at=s.now(),signals={dimension:3}))
        briefs.append(prepare_hatch(s,pet['id'],now=s.now()))
    assert briefs[0]['identity']==briefs[1]['identity']
    assert briefs[0]['marking']!=briefs[1]['marking']


def test_import_supersedes_queued_generation(tmp_path):
    from cove_pet_nest.config import Settings
    from cove_pet_nest.service import NestService
    from cove_pet_nest.images.service import ImageJobService
    s=make_store(tmp_path)
    class Provider:
        calls=0
        async def generate(self,brief,reference=None):
            self.calls+=1
            return atlas()
    provider=Provider(); jobs=ImageJobService(s,tmp_path/'assets',provider)
    service=NestService(Settings(tmp_path),s,jobs)
    pet=service.adopt('snake','小绿','adopt',actor='user')['pet']
    imported=jobs.import_asset(pet['id'],atlas(),'import')
    job=jobs.for_pet(pet['id'])[0]
    assert asyncio.run(service.tick())['status']=='idle'
    assert provider.calls==0 and s.state()['pets'][0]['asset_ref']==imported['asset_ref']
    assert jobs.get(job['id'])['status']=='superseded'
    with pytest.raises(ValueError,match='job_not_retryable'):
        jobs.retry(job['id'],'retry')


@pytest.mark.parametrize('outcome',['success','failed','unknown'])
def test_import_rejects_late_generation_outcomes(tmp_path,outcome):
    from cove_pet_nest.images.service import ImageJobService
    from cove_pet_nest.store import NestError
    s=make_store(tmp_path)
    pet=s.adopt('snake','小绿','adopt',actor='user')['pet']
    class SlowProvider:
        async def generate(self,brief,reference=None):
            imported=jobs.import_asset(pet['id'],atlas(),'import')
            if outcome=='failed':
                raise NestError('provider_failed')
            if outcome=='unknown':
                raise TimeoutError()
            image=Image.new('RGBA',(768,512),(0,0,0,0))
            image.paste((220,100,40,255),(40,40,210,210))
            buffer=BytesIO(); image.save(buffer,format='PNG')
            return buffer.getvalue()
    jobs=ImageJobService(s,tmp_path/'assets',SlowProvider())
    job=jobs.enqueue(pet['id'],'generate',{'stage':0})
    asyncio.run(jobs.run_once())
    assert jobs.get(job['id'])['status']=='superseded'
    assert s.state()['pets'][0]['asset_ref']==jobs.get(job['id'])['asset_ref']


def test_import_survives_adoption_retry_after_enqueue_interruption(tmp_path,monkeypatch):
    from cove_pet_nest.config import Settings
    from cove_pet_nest.service import NestService
    from cove_pet_nest.images.service import ImageJobService
    s=make_store(tmp_path)
    class Provider:
        calls=0
        async def generate(self,brief,reference=None):
            self.calls+=1
            return atlas()
    provider=Provider(); jobs=ImageJobService(s,tmp_path/'assets',provider)
    service=NestService(Settings(tmp_path),s,jobs)
    original=jobs.enqueue
    def interrupted(*args,**kwargs):
        raise RuntimeError('simulated interruption after adoption commit')
    monkeypatch.setattr(jobs,'enqueue',interrupted)
    with pytest.raises(RuntimeError):
        service.adopt('snake','小绿','adopt',actor='user')
    pet=s.state()['pets'][0]
    assert jobs.for_pet(pet['id'])==[]
    imported=jobs.import_asset(pet['id'],atlas(),'import')
    monkeypatch.setattr(jobs,'enqueue',original)
    service.adopt('snake','小绿','adopt',actor='user')
    assert asyncio.run(service.tick())['status']=='idle'
    assert provider.calls==0 and s.state()['pets'][0]['asset_ref']==imported['asset_ref']
