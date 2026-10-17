"""Append-only activated portraits; additive, idempotent v0.1 migration."""
import json
from .store import encode


def record_stage(db,pet,now,brief=None,*,estimated=False):
    db.execute('''INSERT OR IGNORE INTO pet_stages
        (pet_id,stage,asset_ref,starter_kind,activated_at,growth_at_activation,brief,date_estimated)
        VALUES(?,?,?,?,?,?,?,?)''',(pet['id'],pet['stage'],pet['asset_ref'],
        pet['kind'] if pet['asset_ref'] is None and pet['kind'] in ('cat','dog','egg') else None,
        now,pet['growth'],encode(brief or {}),int(estimated)))


def ensure_history(db,store):
    db.execute('''CREATE TABLE IF NOT EXISTS pet_stages(pet_id TEXT,stage INTEGER,
        asset_ref TEXT,starter_kind TEXT,activated_at REAL,growth_at_activation REAL,
        brief TEXT,date_estimated INTEGER DEFAULT 0,PRIMARY KEY(pet_id,stage))''')
    db.execute('CREATE TABLE IF NOT EXISTS stage_briefs(pet_id TEXT,stage INTEGER,brief TEXT,PRIMARY KEY(pet_id,stage))')
    db.execute('''CREATE TABLE IF NOT EXISTS life_events(id TEXT PRIMARY KEY,kind TEXT,
        occurred_at REAL,participants TEXT,fingerprint TEXT)''')
    db.execute('CREATE TABLE IF NOT EXISTS life_participants(event_id TEXT,pet_id TEXT,PRIMARY KEY(event_id,pet_id))')
    columns={r['name'] for r in db.execute('PRAGMA table_info(image_jobs)')}
    for name,definition in (('purpose',"TEXT NOT NULL DEFAULT 'stage'"),('source_id','TEXT'),('completed_at','REAL')):
        if name not in columns:db.execute(f'ALTER TABLE image_jobs ADD COLUMN {name} {definition}')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS image_photo_source ON image_jobs(source_id) WHERE purpose='photo'")
    for row in db.execute("SELECT * FROM pets WHERE status='ready'").fetchall():
        if db.execute('SELECT 1 FROM pet_stages WHERE pet_id=? AND stage=?',(row['id'],row['stage'])).fetchone():continue
        brief={};at=row['created_at'];estimated=False
        if row['kind']=='egg' and row['stage']>0:
            original=dict(row);original.update(stage=0,asset_ref=None,growth=0)
            record_stage(db,original,row['created_at'])
        if row['stage']>0:
            job=db.execute("SELECT * FROM image_jobs WHERE pet_id=? AND stage=? AND status='success'",(row['id'],row['stage'])).fetchone()
            # v0.1 did not store activation time. A conservative estimate never
            # moves a pet backwards or invents an exact historical hatch time.
            at=min(store.now(),max(row['created_at'],job['lease_until'] if job and job['lease_until'] else store.now()))
            brief=json.loads(job['brief']) if job else {}
            estimated=True
        record_stage(db,row,at,brief,estimated=estimated)


def participant(pet):
    return {'pet_id':pet['id'],'kind':pet['kind'],'stage':pet['stage'],'asset_ref':pet['asset_ref'],
            'starter_kind':pet['kind'] if pet['asset_ref'] is None and pet['kind'] in ('cat','dog','egg') else None}


def record_care_source(db,pet,action,now,event_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='life_events'").fetchone():return
    key='care:'+str(event_id)
    db.execute('INSERT OR IGNORE INTO life_events VALUES(?,?,?,?,?)',(key,'care_'+action,now,encode([participant(pet)]),key))
    db.execute('INSERT OR IGNORE INTO life_participants VALUES(?,?)',(key,pet['id']))
