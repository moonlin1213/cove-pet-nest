"""Authenticated album projections. Reading never starts a model or image job."""
import json
from .store import NestError,identifier


def asset_url(ref,starter=None):
    if ref:return '/api/assets/'+ref
    return '/starter/'+starter+'-sprites-light.webp' if starter else None


class AlbumService:
    def __init__(self,store,jobs):self.store,self.jobs=store,jobs

    def history(self,pet_id):
        identifier(pet_id)
        with self.store.connect() as db:
            pet=db.execute('SELECT * FROM pets WHERE id=?',(pet_id,)).fetchone()
            if not pet:raise NestError('pet_not_found',404)
            stages=[]
            for row in db.execute('SELECT * FROM pet_stages WHERE pet_id=? ORDER BY stage',(pet_id,)):
                brief=json.loads(row['brief'])
                stages.append({'stage':row['stage'],'active':row['stage']==pet['stage'],'asset_ref':row['asset_ref'],
                    'asset_url':asset_url(row['asset_ref'],row['starter_kind']),'activated_at':row['activated_at'],
                    'date_estimated':bool(row['date_estimated']),'features':brief.get('features',[brief['marking']] if brief.get('marking') else []),
                    'title':'到家' if row['stage']==0 else ('首次孵化' if pet['kind']=='egg' and row['stage']==1 else f"第 {row['stage']} 次成长"),
                    'dimension':brief.get('dimension'),'growth_at_activation':row['growth_at_activation']})
        return {'pet_id':pet_id,'name':pet['name'],'kind':pet['kind'],'current_stage':pet['stage'],
                'stages':stages,'jobs':self.jobs.for_pet(pet_id)}

    def record(self,event):
        from .contracts import LifeEvent
        from .history import participant
        from .store import encode
        import hashlib
        event=LifeEvent.model_validate(event.model_dump())
        if event.occurred_at>self.store.now()+60:raise NestError('invalid_event_time')
        key='shared:'+hashlib.sha256(event.event_id.encode()).hexdigest()
        fingerprint=encode(event.model_dump())
        with self.store.write() as db:
            previous=db.execute('SELECT * FROM life_events WHERE id=?',(key,)).fetchone()
            if previous:
                if previous['fingerprint']!=fingerprint:raise NestError('idempotency_conflict',409)
                return {'id':key,'recorded':True}
            snapshots=[]
            for pet_id in event.pet_ids:
                pet=db.execute('SELECT * FROM pets WHERE id=?',(pet_id,)).fetchone()
                if not pet:raise NestError('pet_not_found',404)
                if pet['status']!='ready':raise NestError('pet_not_ready')
                stage=db.execute('SELECT * FROM pet_stages WHERE pet_id=? AND activated_at<=? ORDER BY stage DESC LIMIT 1',(pet_id,event.occurred_at)).fetchone()
                if not stage:raise NestError('event_appearance_unavailable')
                snapshot=participant(pet)
                snapshot.update(stage=stage['stage'],asset_ref=stage['asset_ref'],starter_kind=stage['starter_kind'])
                snapshots.append(snapshot)
            db.execute('INSERT INTO life_events VALUES(?,?,?,?,?)',(key,event.kind,event.occurred_at,encode(snapshots),fingerprint))
            for pet_id in event.pet_ids:db.execute('INSERT INTO life_participants VALUES(?,?)',(key,pet_id))
        return {'id':key,'recorded':True}

    def sources(self,*,pet_id=None,offset=0,limit=20):
        if type(offset) is not int or type(limit) is not int or offset<0 or not 1<=limit<=100:raise NestError('invalid_pagination')
        labels={'care_feed':'吃饭的片刻','care_play':'一起玩了一会儿','care_comfort':'收到了温柔的摸摸',
            'reading':'一起读书','watching':'一起看故事','listening':'一起听音乐','exploration':'一起探索','companionship':'相伴的片刻'}
        with self.store.connect() as db:
            if pet_id is not None and not db.execute('SELECT 1 FROM pets WHERE id=?',(identifier(pet_id),)).fetchone():raise NestError('pet_not_found',404)
            where=' WHERE EXISTS(SELECT 1 FROM life_participants p WHERE p.event_id=e.id AND p.pet_id=?)' if pet_id else ''
            args=(pet_id,) if pet_id else ()
            total=db.execute('SELECT COUNT(*) FROM life_events e'+where,args).fetchone()[0]
            events=[]
            for row in db.execute('SELECT e.* FROM life_events e'+where+' ORDER BY occurred_at DESC,id DESC LIMIT ? OFFSET ?',(*args,limit,offset)):
                job=db.execute("SELECT * FROM image_jobs WHERE purpose='photo' AND source_id=?",(row['id'],)).fetchone()
                photo=self.jobs.public(job) if job else None
                if photo:photo['asset_url']=asset_url(photo['asset_ref']) if photo['status']=='success' else None
                participants=json.loads(row['participants'])
                for p in participants:p['asset_url']=asset_url(p['asset_ref'],p['starter_kind'])
                events.append({'id':row['id'],'kind':row['kind'],'label':labels[row['kind']],
                    'occurred_at':row['occurred_at'],'participants':participants,'photo':photo})
        return {'total':total,'offset':offset,'limit':limit,'events':events}

    def queue_photo(self,event_id,request_id,*,actor):
        from .store import encode
        import uuid
        identifier(event_id)
        if actor not in ('user','assistant'):raise NestError('invalid_actor')
        payload={'op':'photo','event_id':event_id}
        with self.store.write() as db:
            old=self.store.replay(db,actor,request_id,payload)
            if old is not None:return old
            event=db.execute('SELECT * FROM life_events WHERE id=?',(event_id,)).fetchone()
            if not event:raise NestError('life_event_not_found',404)
            job=db.execute("SELECT * FROM image_jobs WHERE purpose='photo' AND source_id=?",(event_id,)).fetchone()
            if not job:
                participants=json.loads(event['participants'])
                brief={'purpose':'photo','event_kind':event['kind'],'participants':participants,'reference_required':True}
                job_id=uuid.uuid4().hex
                db.execute("INSERT INTO image_jobs(id,pet_id,stage,brief,status,purpose,source_id) VALUES(?,?,NULL,?,'reserved','photo',?)",
                    (job_id,participants[0]['pet_id'],encode(brief),event_id))
                job=db.execute('SELECT * FROM image_jobs WHERE id=?',(job_id,)).fetchone()
            return self.store.receipt(db,actor,request_id,payload,self.jobs.public(job))
