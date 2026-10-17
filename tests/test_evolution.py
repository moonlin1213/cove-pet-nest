import asyncio
import sqlite3
from pathlib import Path
import pytest
from test_store import make_store
from test_hatch import atlas


def nest(tmp_path,transport=None):
    from cove_pet_nest.config import Settings
    from cove_pet_nest.service import NestService
    from cove_pet_nest.images.service import ImageJobService
    store=make_store(tmp_path)
    return NestService(Settings(tmp_path),store,ImageJobService(store,tmp_path/'assets',transport))


class Portraits:
    def __init__(self):self.briefs=[];self.references=[]
    async def generate(self,brief,reference=None):
        self.briefs.append(brief);self.references.append(reference)
        return atlas()


def grow(service,pet_id,amount,days):
    now=service.store.now()+days*86400
    with service.store.write() as db:db.execute('UPDATE pets SET growth=? WHERE id=?',(amount,pet_id))
    service.store.clock=lambda:now


def test_growth_needs_both_thresholds_and_preserves_stage_until_success(tmp_path):
    provider=Portraits();n=nest(tmp_path,provider)
    p=n.adopt('cat','团团','a',actor='user')['pet']
    grow(n,p['id'],40,6)
    assert asyncio.run(n.tick())['status']=='idle'
    assert n.album.history(p['id'])['stages'][0]['stage']==0
    grow(n,p['id'],40,1)
    assert asyncio.run(n.tick())['status']=='success'
    assert n.state()['pets'][0]['stage']==1
    history=n.album.history(p['id'])['stages']
    assert [h['stage'] for h in history]==[0,1]
    assert history[0]['asset_url']=='/starter/cat-sprites-light.webp'
    assert history[1]['active'] is True and history[0]['active'] is False
    assert provider.references[0] and provider.references[0][0].startswith(b'\x89PNG')
    assert asyncio.run(n.tick())['status']=='idle'
    grow(n,p['id'],100,13)
    assert asyncio.run(n.tick())['status']=='idle'
    grow(n,p['id'],100,1)
    assert asyncio.run(n.tick())['status']=='success'
    assert n.state()['pets'][0]['stage']==2
    assert provider.briefs[0]['features'][0] in provider.briefs[1]['features']
    assert n.state()['grains']==36


def test_failed_evolution_keeps_current_appearance_and_frozen_brief(tmp_path):
    class Offline:
        async def generate(self,brief,reference=None):raise TimeoutError()
    n=nest(tmp_path,Offline());p=n.adopt('dog','绒绒','a',actor='user')['pet']
    grow(n,p['id'],40,7)
    assert asyncio.run(n.tick())['status']=='unknown'
    assert n.state()['pets'][0]['stage']==0
    assert [s['stage'] for s in n.album.history(p['id'])['stages']]==[0]
    job=n.jobs.for_pet(p['id'])[0]
    from cove_pet_nest.growth import prepare_next_stage
    first=prepare_next_stage(n.store,p['id'])
    grow(n,p['id'],200,30)
    assert prepare_next_stage(n.store,p['id'])==first
    assert asyncio.run(n.tick())['status']=='idle'
    n.jobs.retry(job['id'],'retry',acknowledge_unknown=True)
    n.jobs.transport=Portraits();asyncio.run(n.tick())
    assert n.state()['pets'][0]['stage']==1


def test_post_maturity_requires_growth_since_actual_activation(tmp_path):
    n=nest(tmp_path,Portraits());p=n.adopt('cat','团团','a',actor='user')['pet']
    for amount,days in [(40,7),(100,14),(300,21)]:
        grow(n,p['id'],amount,days);assert asyncio.run(n.tick())['status']=='success'
    grow(n,p['id'],419,30)
    assert asyncio.run(n.tick())['status']=='idle'
    grow(n,p['id'],420,0)
    assert asyncio.run(n.tick())['status']=='success'
    assert n.state()['pets'][0]['stage']==4


def test_v01_upgrade_retains_imports_growth_receipts_and_hatch(tmp_path):
    from cove_pet_nest.images.service import ImageJobService
    s=make_store(tmp_path)
    p=s.adopt('cat','团团','a',actor='user')['pet']
    s.care('play','play',actor='user',pet_ids=[p['id']])
    jobs=ImageJobService(s,tmp_path/'assets',None)
    imported=jobs.import_asset(p['id'],atlas(),'import')
    # Remove only v0.2 extension tables to reproduce a v0.1 database fixture.
    with s.write() as db:
        for table in ('pet_stages','stage_briefs','life_events'):db.execute('DROP TABLE IF EXISTS '+table)
    n=nest(tmp_path,None)
    assert n.store.adopt('cat','团团','a',actor='user')['pet']['id']==p['id']
    assert n.state()['pets'][0]['growth']==1
    assert n.album.history(p['id'])['stages'][0]['asset_ref']==imported['asset_ref']
    assert n.state()['grains']==36
    n2=nest(tmp_path,None)
    assert n2.album.history(p['id'])==n.album.history(p['id'])


def test_late_stage_result_does_not_replace_changed_parent(tmp_path):
    n=nest(tmp_path)
    pet=n.adopt('cat','宝宝','a',actor='user')['pet']
    class ChangedParent:
        async def generate(self,brief,reference=None):
            with n.store.write() as db:db.execute('UPDATE pets SET stage=9 WHERE id=?',(pet['id'],))
            return atlas()
    n.jobs.transport=ChangedParent();grow(n,pet['id'],40,7)
    assert asyncio.run(n.tick())['status']=='stale_result'
    assert n.state()['pets'][0]['stage']==9
    assert [s['stage'] for s in n.album.history(pet['id'])['stages']]==[0]
