import hashlib
import json
from pathlib import Path
import re
import uuid
from ..store import NestError,encode,identifier
from .processing import prepare_asset


class ImageJobService:
    def __init__(self,store,assets_root: Path,transport):
        self.store,self.assets_root,self.transport=store,Path(assets_root),transport
        self.assets_root.mkdir(parents=True,exist_ok=True,mode=0o700)
        with store.write() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS image_jobs(id TEXT PRIMARY KEY,pet_id TEXT,stage INTEGER,
                brief TEXT,status TEXT,attempt INTEGER DEFAULT 0,lease_until REAL,day TEXT,error TEXT,asset_ref TEXT,
                UNIQUE(pet_id,stage))''')

    @staticmethod
    def public(row):
        return {k:row[k] for k in ('id','pet_id','stage','status','error','asset_ref')}

    def get(self,job_id):
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM image_jobs WHERE id=?',(job_id,)).fetchone()
            if not row:
                raise NestError('job_not_found',404)
            return self.public(row)

    def for_pet(self,pet_id):
        with self.store.connect() as db:
            return [self.public(r) for r in db.execute('SELECT * FROM image_jobs WHERE pet_id=? ORDER BY stage',(pet_id,))]

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

    async def run_once(self):
        with self.store.write() as db:
            now=self.store.now(); day=self.store.day(now)
            db.execute("UPDATE image_jobs SET status='unknown',error='interrupted_after_submission' WHERE status='submitted' AND lease_until<?",(now,))
            if self.transport is None:
                return {'status':'needs_image_configuration'}
            count=db.execute("SELECT COUNT(*) FROM image_jobs WHERE day=? AND status IN ('success','submitted')",(day,)).fetchone()[0]
            if count>=3:
                return {'status':'daily_limit'}
            row=db.execute("SELECT * FROM image_jobs WHERE status='reserved' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return {'status':'idle'}
            attempt=row['attempt']+1
            db.execute("UPDATE image_jobs SET status='submitted',attempt=?,lease_until=?,day=? WHERE id=?",(attempt,now+180,day,row['id']))
        try:
            raw=await self.transport.generate(json.loads(row['brief']),None)
            webp=prepare_asset(raw)
            ref=hashlib.sha256(webp).hexdigest()+'.webp'
            path=self.asset_path(ref)
            if not path.exists():
                temp=path.with_suffix('.tmp-'+uuid.uuid4().hex)
                temp.write_bytes(webp); temp.chmod(0o600); temp.replace(path)
            with self.store.write() as db:
                active=db.execute('SELECT status,attempt FROM image_jobs WHERE id=?',(row['id'],)).fetchone()
                if active['status']!='submitted' or active['attempt']!=attempt:
                    return {'status':'stale_result'}
                db.execute("UPDATE image_jobs SET status='success',asset_ref=?,error=NULL WHERE id=?",(ref,row['id']))
                db.execute("UPDATE pets SET status='ready',asset_ref=?,stage=?,traits_json=? WHERE id=?",(ref,row['stage'],encode(json.loads(row['brief']).get('traits')) if json.loads(row['brief']).get('traits') else None,row['pet_id']))
        except NestError as exc:
            with self.store.write() as db:
                db.execute("UPDATE image_jobs SET status='failed',error=? WHERE id=? AND attempt=? AND status='submitted'",(exc.code,row['id'],attempt))
        except Exception:
            with self.store.write() as db:
                db.execute("UPDATE image_jobs SET status='unknown',error='result_unknown' WHERE id=? AND attempt=? AND status='submitted'",(row['id'],attempt))
        return self.get(row['id'])

    def import_asset(self,pet_id,payload,request_id):
        webp=prepare_asset(payload); ref=hashlib.sha256(webp).hexdigest()+'.webp'
        path=self.asset_path(ref)
        if not path.exists():
            path.write_bytes(webp); path.chmod(0o600)
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
            # Imported appearance is final: queued work and late outcomes cannot replace it.
            db.execute("""INSERT INTO image_jobs(id,pet_id,stage,brief,status,asset_ref)
                VALUES(?,?,0,?,'superseded',?) ON CONFLICT(pet_id,stage) DO UPDATE SET
                status='superseded',asset_ref=excluded.asset_ref,error=NULL,lease_until=NULL""",
                (uuid.uuid4().hex,pet_id,encode({'stage':0,'kind':pet['kind']}),ref))
            db.execute("UPDATE pets SET status='ready',asset_ref=? WHERE id=?",(ref,pet_id))
            return self.store.receipt(db,'host',request_id,fingerprint,{'status':'ready','asset_ref':ref})
