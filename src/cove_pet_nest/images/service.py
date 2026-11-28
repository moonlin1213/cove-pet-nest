import hashlib
import json
from pathlib import Path
import re
import uuid
from io import BytesIO
from PIL import Image
from ..store import NestError,encode,identifier
from .processing import prepare_asset
from ..history import ensure_history,record_stage


class ImageJobService:
    def __init__(self,store,assets_root: Path,transport):
        self.store,self.assets_root,self.transport=store,Path(assets_root),transport
        self.creation=None
        self.assets_root.mkdir(parents=True,exist_ok=True,mode=0o700)
        with store.write() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS image_jobs(id TEXT PRIMARY KEY,pet_id TEXT,stage INTEGER,
                brief TEXT,status TEXT,attempt INTEGER DEFAULT 0,lease_until REAL,day TEXT,error TEXT,asset_ref TEXT,
                UNIQUE(pet_id,stage))''')
            ensure_history(db,store)
            # v0.3.2 retained only the latest submission day and total attempts.
            # Assign that historical total to its last known day conservatively.
            has_ledger=db.execute("SELECT 1 FROM sqlite_master WHERE name='image_submissions'").fetchone()
            if not has_ledger:
                db.execute("""CREATE TABLE image_submissions(job_id TEXT NOT NULL, attempt INTEGER NOT NULL,
                              day TEXT NOT NULL, units INTEGER NOT NULL CHECK(units>0), PRIMARY KEY(job_id,attempt))""")
                db.execute("""INSERT INTO image_submissions SELECT id,attempt,day,MAX(1,attempt) FROM image_jobs
                              WHERE day IS NOT NULL AND (attempt>0 OR status IN ('success','submitted','failed','unknown'))""")
                db.execute("CREATE INDEX image_submissions_day ON image_submissions(day)")


    @staticmethod
    def public(row):
        return {k:row[k] for k in ('id','pet_id','stage','status','error','asset_ref','purpose','source_id','completed_at')}

    def get(self,job_id):
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM image_jobs WHERE id=?',(job_id,)).fetchone()
            if not row:
                raise NestError('job_not_found',404)
            return self.public(row)

    def for_pet(self,pet_id):
        with self.store.connect() as db:
            return [self.public(r) for r in db.execute("SELECT * FROM image_jobs WHERE pet_id=? AND purpose='stage' ORDER BY stage",(pet_id,))]

    def enqueue(self,pet_id,request_id,brief):
        stage=brief.get('stage',0)
        payload={'op':'image','pet_id':pet_id,'brief':brief}
        with self.store.write() as db:
            previous=self.store.replay(db,'host',request_id,payload)
            if previous is not None:
                return previous
            if not db.execute('SELECT 1 FROM pets WHERE id=?',(pet_id,)).fetchone():
                raise NestError('pet_not_found',404)
            job=db.execute('SELECT * FROM image_jobs WHERE pet_id=? AND stage=?',(pet_id,stage)).fetchone()
            if not job:
                job_id=uuid.uuid4().hex
                db.execute('INSERT INTO image_jobs(id,pet_id,stage,brief,status) VALUES(?,?,?,?,?)',
                           (job_id,pet_id,stage,encode(brief),'reserved'))
                job=db.execute('SELECT * FROM image_jobs WHERE id=?',(job_id,)).fetchone()
            return self.store.receipt(db,'host',request_id,payload,self.public(job))

    def retry(self,job_id,request_id,*,acknowledge_unknown=False):
        payload={'op':'retry','job':job_id,'ack':acknowledge_unknown}
        with self.store.write() as db:
            old=self.store.replay(db,'host',request_id,payload)
            if old is not None:
                return old
            row=db.execute('SELECT * FROM image_jobs WHERE id=?',(job_id,)).fetchone()
            if not row:
                raise NestError('job_not_found',404)
            if row['status']=='unknown' and not acknowledge_unknown:
                raise NestError('acknowledge_possible_prior_charge',409)
            if row['status'] not in ('failed','unknown','abandoned'):
                raise NestError('job_not_retryable',409)
            db.execute("UPDATE image_jobs SET status='reserved',error=NULL WHERE id=?",(job_id,))
            return self.store.receipt(db,'host',request_id,payload,self.public(db.execute('SELECT * FROM image_jobs WHERE id=?',(job_id,)).fetchone()))

    def asset_path(self,ref):
        if not isinstance(ref,str) or not re.fullmatch(r'[a-f0-9]{64}\.webp',ref):
            raise NestError('invalid_asset_reference',404)
        path=self.assets_root/ref
        if path.resolve().parent!=self.assets_root.resolve():
            raise NestError('invalid_asset_reference',404)
        return path

    def references(self,brief):
        if not brief.get('reference_required'):return None
        participants=brief.get('participants') or [{'asset_ref':brief.get('base_asset_ref'),'starter_kind':brief.get('starter_kind')}]
        result=[]
        for participant in participants:
            if participant.get('asset_ref'):
                path=self.asset_path(participant['asset_ref'])
            else:
                kind=participant.get('starter_kind')
                if kind not in ('cat','dog','egg'):raise NestError('reference_missing')
                path=Path(__file__).parents[1]/'assets'/f'{kind}-sprites-light.webp'
            if not path.is_file():raise NestError('reference_missing')
            with Image.open(path) as source:
                out=BytesIO();source.convert('RGBA').save(out,format='PNG');result.append(out.getvalue())
        return result

    def save_asset(self,webp):
        ref=hashlib.sha256(webp).hexdigest()+'.webp';path=self.asset_path(ref)
        if not path.exists():
            import os
            temp=path.with_suffix('.tmp-'+uuid.uuid4().hex)
            with os.fdopen(os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as stream:stream.write(webp)
            temp.replace(path)
        return ref

    async def run_once(self):
        with self.store.write() as db:
            now=self.store.now(); day=self.store.day(now)
            db.execute("UPDATE image_jobs SET status='unknown',error='interrupted_after_submission' WHERE status='submitted' AND lease_until<?",(now,))
            count=db.execute("SELECT COALESCE(SUM(units),0) FROM image_submissions WHERE day=?",(day,)).fetchone()[0]
            if count>=3:
                return {'status':'daily_limit'}
            candidates=db.execute("SELECT * FROM image_jobs WHERE status='reserved' ORDER BY CASE purpose WHEN 'stage' THEN 0 WHEN 'photo' THEN 1 ELSE 2 END,rowid").fetchall()
            for row in candidates:
                if row['purpose']=='toy':
                    if not self.creation or not self.creation.toy_image_eligible(db,row['id'],now):
                        continue
                    transport=self.creation.toy_image_client()
                else:
                    transport=self.transport
                if transport and (not json.loads(row['brief']).get('reference_required') or getattr(transport,'can_reference',True)):
                    break
            else:
                if self.transport is None:
                    return {'status':'needs_image_configuration'}
                return {'status':'needs_image_edit_configuration' if candidates else 'idle'}
            attempt=row['attempt']+1
            db.execute("INSERT INTO image_submissions(job_id,attempt,day,units) VALUES(?,?,?,1)",(row['id'],attempt,day))
            db.execute("UPDATE image_jobs SET status='submitted',attempt=?,lease_until=?,day=? WHERE id=?",(attempt,now+180,day,row['id']))
        try:
            brief=json.loads(row['brief'])
            raw=await transport.generate(brief,self.references(brief))
            if row['purpose']=='toy':
                from ..toy_art import split_forms
                forms=[self.save_asset(form) for form in split_forms(raw)]
                ref=forms[0]
            else:
                from .processing import prepare_photo
                ref=self.save_asset(prepare_photo(raw) if row['purpose']=='photo' else prepare_asset(raw))
            with self.store.write() as db:
                active=db.execute('SELECT status,attempt FROM image_jobs WHERE id=?',(row['id'],)).fetchone()
                if active['status']!='submitted' or active['attempt']!=attempt:
                    return {'status':'stale_result'}
                if row['purpose']=='toy':
                    if not self.creation.toy_image_eligible(db,row['id'],self.store.now()):
                        return {'status':'stale_result'}
                    self.creation.complete_toy(db,row['id'],forms)
                elif row['purpose']=='stage':
                    pet=db.execute('SELECT * FROM pets WHERE id=?',(row['pet_id'],)).fetchone()
                    if 'base_stage' in brief and (pet['stage']!=brief['base_stage'] or pet['asset_ref']!=brief.get('base_asset_ref')):
                        db.execute("UPDATE image_jobs SET status='superseded',error='appearance_changed' WHERE id=?",(row['id'],))
                        return {'status':'stale_result'}
                    db.execute("UPDATE pets SET status='ready',asset_ref=?,stage=?,traits_json=? WHERE id=?",(ref,row['stage'],encode(brief['traits']) if brief.get('traits') else pet['traits_json'],row['pet_id']))
                    updated=db.execute('SELECT * FROM pets WHERE id=?',(row['pet_id'],)).fetchone()
                    record_stage(db,updated,self.store.now(),brief)
                db.execute("UPDATE image_jobs SET status='success',asset_ref=?,completed_at=?,error=NULL WHERE id=?",(ref,self.store.now(),row['id']))
        except NestError as exc:
            with self.store.write() as db:
                db.execute("UPDATE image_jobs SET status='failed',error=? WHERE id=? AND attempt=? AND status='submitted'",(exc.code,row['id'],attempt))
        except Exception:
            with self.store.write() as db:
                db.execute("UPDATE image_jobs SET status='unknown',error='result_unknown' WHERE id=? AND attempt=? AND status='submitted'",(row['id'],attempt))
        return self.get(row['id'])

    def import_asset(self,pet_id,payload,request_id):
        webp=prepare_asset(payload);ref=self.save_asset(webp)
        fingerprint={'op':'asset_import','pet_id':pet_id,'asset_ref':ref}
        with self.store.write() as db:
            old=self.store.replay(db,'host',request_id,fingerprint)
            if old is not None:
                return old
            pet=db.execute('SELECT * FROM pets WHERE id=?',(pet_id,)).fetchone()
            if not pet:
                raise NestError('pet_not_found',404)
            if pet['kind']=='egg':
                raise NestError('use_hatch_for_fantasy_identity')
            if pet['stage']>0 or db.execute('SELECT 1 FROM stage_briefs WHERE pet_id=?',(pet_id,)).fetchone():
                raise NestError('appearance_locked_after_growth')
            # Imported appearance is final: queued work and late outcomes cannot replace it.
            db.execute("""INSERT INTO image_jobs(id,pet_id,stage,brief,status,asset_ref)
                VALUES(?,?,0,?,'superseded',?) ON CONFLICT(pet_id,stage) DO UPDATE SET
                status='superseded',asset_ref=excluded.asset_ref,error=NULL,lease_until=NULL""",
                (uuid.uuid4().hex,pet_id,encode({'stage':0,'kind':pet['kind']}),ref))
            db.execute("UPDATE pets SET status='ready',asset_ref=? WHERE id=?",(ref,pet_id))
            updated=db.execute('SELECT * FROM pets WHERE id=?',(pet_id,)).fetchone()
            record_stage(db,updated,self.store.now())
            db.execute('UPDATE pet_stages SET asset_ref=?,starter_kind=NULL WHERE pet_id=? AND stage=0',(ref,pet_id))
            return self.store.receipt(db,'host',request_id,fingerprint,{'status':'ready','asset_ref':ref})
