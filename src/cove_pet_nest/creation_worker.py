"""Per-room scheduling, quota reservation and recoverable text submissions."""
import json
import random
import uuid

from .creation_material import DAY, choose_source, validate_answer
from .creation_text import generate_text
from .images.transport import ImageTransport
from .store import NestError, encode, identifier


def toy_source(db, now, rng):
    return choose_source(db, 'toy', now - 14 * DAY, now, rng)


def note_source(db, now, pet, rng):
    since = max(now - 7 * DAY, pet['created_at'])
    return choose_source(db, 'note', since, now, rng, pet['id'])


def public_job(row):
    status=row['status']
    error=row['error']
    if status=='waiting_image' and row['image_status'] in ('submitted','failed','unknown'):
        status,error=row['image_status'],row['image_error']
    return {'id':row['id'],'kind':row['kind'],'status':status,'error':error}


class CreationWorker:
    def __init__(self,store):
        self.store=store
        self.rng=random.SystemRandom()
        self.generate_text=generate_text
        with store.write() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS creation_schedule(
                id INTEGER PRIMARY KEY CHECK(id=1), toy_due REAL, note_day TEXT)''')
            db.execute('INSERT OR IGNORE INTO creation_schedule(id) VALUES(1)')
            db.execute('''CREATE TABLE IF NOT EXISTS creation_jobs(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, pet_id TEXT, source_id TEXT NOT NULL,
                material TEXT NOT NULL, status TEXT NOT NULL, error TEXT, attempt INTEGER NOT NULL DEFAULT 0,
                lease_until REAL, concept TEXT, UNIQUE(kind,source_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS creation_usage(day TEXT PRIMARY KEY,calls INTEGER NOT NULL)''')

    def config(self):
        from .creation_setup import load_creation_settings
        return load_creation_settings(self.store.path.parent)

    def background_settings(self):
        # A broken optional household file must not stop existing growth or photos.
        try:
            return self.config()
        except (OSError, NestError):
            return None

    @staticmethod
    def image_transport(cfg):
        return ImageTransport(cfg.endpoint,cfg.model,cfg.key)

    def toy_image_client(self):
        cfg=self.background_settings()
        if cfg and cfg.toys_enabled and cfg.image.ready:
            return self.image_transport(cfg.image)
        return None

    def _next_toy(self,db,now):
        due=now+self.rng.randint(DAY,7*DAY)
        db.execute('UPDATE creation_schedule SET toy_due=? WHERE id=1',(due,))

    @staticmethod
    def _new_job(db,kind,source,pet_id=None,material_extra=None):
        source_id,fact=source
        material={'source':fact,**(material_extra or {})}
        job_id=uuid.uuid4().hex
        db.execute("""INSERT INTO creation_jobs(id,kind,pet_id,source_id,material,status)
                    VALUES(?,?,?,?,?,'reserved')""",(job_id,kind,pet_id,source_id,encode(material)))
        return job_id

    def _schedule(self,db,cfg,now):
        from .keepsakes import ensure_keepsakes
        ensure_keepsakes(db)
        schedule=db.execute('SELECT * FROM creation_schedule WHERE id=1').fetchone()
        if cfg.toys_enabled:
            if schedule['toy_due'] is None:
                self._next_toy(db,now)
            elif cfg.image.ready and schedule['toy_due']<=now and not db.execute(
                    "SELECT 1 FROM creation_jobs WHERE kind='toy' AND status NOT IN ('success','superseded')").fetchone():
                source=toy_source(db, now, self.rng)
                if source:
                    recent=db.execute("""SELECT concept FROM creation_jobs WHERE kind='toy' AND status='success'
                                         ORDER BY rowid DESC LIMIT 8""")
                    names=[json.loads(row['concept'])['name'] for row in recent]
                    self._new_job(db,'toy',source,material_extra={'recent_toys':names})
        day=self.store.day(now)
        if not cfg.notes_enabled or schedule['note_day']==day:
            return
        if db.execute("SELECT 1 FROM creation_jobs WHERE kind='note' AND status IN ('reserved','submitted')").fetchone():
            return
        candidates=db.execute("""SELECT p.id,p.created_at FROM pets p WHERE p.created_at<=? AND p.status='ready'
            AND (p.kind!='egg' OR p.stage>0) AND NOT EXISTS(
              SELECT 1 FROM keepsake_notes n WHERE n.pet_id=p.id AND n.kind!='arrival' AND n.created_at>?)
            ORDER BY p.id""",(now-DAY,now-3*DAY)).fetchall()
        self.rng.shuffle(candidates)
        for pet in candidates:
            source=note_source(db, now, pet, self.rng)
            if source:
                db.execute('UPDATE creation_schedule SET note_day=? WHERE id=1',(day,))
                if self.rng.random()<0.30:
                    self._new_job(db,'note',source,pet['id'])
                return

    @staticmethod
    def _expire(db,now):
        db.execute("""UPDATE creation_jobs SET status='unknown',error='interrupted_after_submission'
                      WHERE status='submitted' AND lease_until<=?""",(now,))

    @staticmethod
    def _source_is_current(db, row, now):
        """Recheck eligibility inside the claim or delivery transaction."""
        if row['kind'] == 'trial':
            return True
        since = now - 14 * DAY
        if row['kind'] == 'note':
            pet = db.execute("""SELECT created_at FROM pets WHERE id=? AND created_at<=?
                                AND status='ready' AND (kind!='egg' OR stage>0)""",
                             (row['pet_id'], now - DAY)).fetchone()
            recent = db.execute("""SELECT 1 FROM keepsake_notes WHERE pet_id=?
                                   AND kind!='arrival' AND created_at>?""", (row['pet_id'], now - 3 * DAY)).fetchone()
            if not pet or recent:
                return False
            since = max(now - 7 * DAY, pet['created_at'])
        source_id = row['source_id']
        prefix, _, key = source_id.partition(':')
        if prefix == 'care' and row['kind'] == 'note':
            source = db.execute("""SELECT 1 FROM care_events WHERE id=? AND pet_id=?
                                   AND created_at BETWEEN ? AND ?""", (key, row['pet_id'], since, now))
        elif prefix == 'shared':
            source = db.execute("""SELECT 1 FROM life_events WHERE id=? AND occurred_at BETWEEN ? AND ?
                                   AND (? IS NULL OR EXISTS (SELECT 1 FROM life_participants
                                       WHERE event_id=? AND pet_id=?))""",
                                (source_id, since, now, row['pet_id'], source_id, row['pet_id']))
        elif prefix == 'relationship':
            source = db.execute("SELECT 1 FROM relationships WHERE id=? AND occurred_at BETWEEN ? AND ?",
                                (key, since, now))
        else:
            return False
        return source.fetchone() is not None

    def _expire_source(self, db, row, now):
        if self._source_is_current(db, row, now):
            return False
        db.execute("""UPDATE creation_jobs SET status='superseded',error='source_no_longer_eligible',
                      lease_until=NULL WHERE id=?""", (row['id'],))
        return True

    def toy_image_eligible(self, db, job_id, now):
        row = db.execute("SELECT * FROM creation_jobs WHERE id=? AND status='waiting_image'", (job_id,)).fetchone()
        if row and not self._expire_source(db, row, now):
            return True
        db.execute("""UPDATE image_jobs SET status='superseded',error='source_no_longer_eligible',
                      lease_until=NULL WHERE id=?""", (job_id,))
        return False

    def _claim(self,db,cfg,job_id,now):
        day=self.store.day(now)
        reserved = db.execute("SELECT * FROM creation_jobs WHERE id=? AND status='reserved'", (job_id,)).fetchone()
        if not reserved or self._expire_source(db, reserved, now):
            return None
        usage=db.execute('SELECT calls FROM creation_usage WHERE day=?',(day,)).fetchone()
        if (usage['calls'] if usage else 0)>=cfg.daily_text_limit:
            return None
        row=db.execute("""UPDATE creation_jobs SET status='submitted',error=NULL,attempt=attempt+1,lease_until=?
                          WHERE id=? AND status='reserved' RETURNING *""",(now+180,job_id)).fetchone()
        if row:
            db.execute('''INSERT INTO creation_usage(day,calls) VALUES(?,1)
                          ON CONFLICT(day) DO UPDATE SET calls=calls+1''',(day,))
        return row

    async def _submit(self,row,cfg):
        material=json.loads(row['material'])
        try:
            answer=await self.generate_text(cfg.text,row['kind'],material)
            result=validate_answer(row['kind'],answer,material)
            with self.store.write() as db:
                live=db.execute("SELECT 1 FROM creation_jobs WHERE id=? AND status='submitted' AND attempt=?",
                                (row['id'],row['attempt'])).fetchone()
                if not live or self._expire_source(db, row, self.store.now()):
                    return
                status='success'
                if row['kind']=='toy':
                    status='waiting_image'
                    db.execute("""INSERT INTO image_jobs(id,brief,status,purpose,source_id)
                                  VALUES(?,?,'reserved','toy',?)""",(row['id'],encode({
                                  'purpose':'toy','appearance':result['appearance']}),row['id']))
                elif row['kind']=='note':
                    from .keepsakes import deliver_note
                    deliver_note(db,source_id=row['id'],pet_id=row['pet_id'],kind=result['kind'],
                                 text=result['text'],evidence=[row['source_id']],now=self.store.now())
                db.execute('UPDATE creation_jobs SET status=?,concept=?,lease_until=NULL WHERE id=?',
                           (status,encode(result),row['id']))
        except NestError as exc:
            self._record_error(row,'failed',exc.code)
        except Exception:
            self._record_error(row,'unknown','result_unknown')

    def _record_error(self,row,status,error):
        with self.store.write() as db:
            db.execute("""UPDATE creation_jobs SET status=?,error=? WHERE id=? AND attempt=? AND status='submitted'""",
                       (status,error,row['id'],row['attempt']))

    def complete_toy(self,db,job_id,forms):
        from .keepsakes import deliver_toy
        row=db.execute("SELECT * FROM creation_jobs WHERE id=? AND status='waiting_image'",(job_id,)).fetchone()
        if row is None:
            raise NestError('invalid_toy_job')
        result=json.loads(row['concept'])
        now=self.store.now()
        deliver_toy(db,source_id=job_id,name=result['name'],origin=result['origin'],forms=forms,now=now)
        db.execute("UPDATE creation_jobs SET status='success' WHERE id=?",(job_id,))
        self._next_toy(db,now)

    async def tick(self):
        cfg=self.background_settings()
        if not cfg or not (cfg.notes_enabled or cfg.toys_enabled):
            return
        with self.store.write() as db:
            now=self.store.now()
            self._expire(db,now)
            if not cfg.text.ready:
                return
            self._schedule(db,cfg,now)
            job=db.execute("""SELECT id FROM creation_jobs WHERE status='reserved'
                AND ((kind='toy' AND ?) OR (kind='note' AND ?)) ORDER BY rowid LIMIT 1""",
                (cfg.toys_enabled and cfg.image.ready,cfg.notes_enabled)).fetchone()
            row=self._claim(db,cfg,job['id'],now) if job else None
        if row:
            await self._submit(row,cfg)

    async def trial(self,request_id):
        identifier(request_id)
        cfg=self.config()
        with self.store.write() as db:
            now=self.store.now()
            self._expire(db,now)
            old=db.execute("SELECT id,status FROM creation_jobs WHERE kind='trial' AND source_id=?",
                           (request_id,)).fetchone()
            if old and old['status']!='reserved':
                return dict(old)
            if not cfg.text.ready:
                raise NestError('needs_text_configuration')
            job_id=old['id'] if old else self._new_job(db,'trial',(request_id,{
                'type':'relationship','fact':'虚构诊断家庭共读了一本灯塔绘本'}))
            row=self._claim(db,cfg,job_id,now)
            if not row:
                return {'id':job_id,'status':'daily_limit'}
        await self._submit(row,cfg)
        with self.store.connect() as db:
            return dict(db.execute('SELECT id,status FROM creation_jobs WHERE id=?',(job_id,)).fetchone())

    def status(self):
        with self.store.write() as db:
            self._expire(db,self.store.now())
            rows=db.execute("""SELECT j.*,i.status AS image_status,i.error AS image_error
                FROM creation_jobs j LEFT JOIN image_jobs i ON i.id=j.id ORDER BY j.rowid DESC LIMIT 100""")
            return [public_job(r) for r in rows]

    def retry(self,job_id,request_id,acknowledge_unknown=False):
        payload={'op':'retry_creation','id':job_id,'ack':acknowledge_unknown}
        with self.store.write() as db:
            previous=self.store.replay(db,'user',request_id,payload)
            if previous is not None:
                return previous
            row=db.execute("""SELECT j.*,i.status AS image_status,i.error AS image_error
                FROM creation_jobs j LEFT JOIN image_jobs i ON i.id=j.id WHERE j.id=?""",(job_id,)).fetchone()
            if not row:
                raise NestError('creation_job_not_found',404)
            job=public_job(row)
            if job['status']=='unknown' and not acknowledge_unknown:
                raise NestError('acknowledge_possible_prior_charge',409)
            if job['status'] not in ('unknown','failed') or row['kind']=='trial':
                raise NestError('job_not_retryable',409)
            if row['status']=='waiting_image':
                db.execute("UPDATE image_jobs SET status='reserved',error=NULL WHERE id=?",(job_id,))
            else:
                db.execute("UPDATE creation_jobs SET status='reserved',error=NULL WHERE id=?",(job_id,))
            return self.store.receipt(db,'user',request_id,payload,{'id':job_id,'status':'reserved'})
