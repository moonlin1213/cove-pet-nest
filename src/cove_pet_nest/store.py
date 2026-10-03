"""Local transactions and truthful pet-care receipts. No host database access."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import sqlite3
import time
import uuid

KINDS = ('cat', 'dog', 'parrot', 'snow_leopard', 'snake', 'lizard', 'egg')
TRAITS = ('attachment', 'energy', 'curiosity', 'sociability', 'calm', 'sensitivity')


class NestError(ValueError):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identifier(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or any(ord(c) < 32 for c in value):
        raise NestError('invalid_identifier')
    return value


def temperament(seed):
    return {k: round(10 + 80 * int.from_bytes(hashlib.sha256(f'{seed}:{k}'.encode()).digest()[:8], 'big') / (2**64 - 1), 2) for k in TRAITS}


class PetStore:
    def __init__(self, path: Path, *, timezone='Asia/Shanghai', clock=time.time):
        self.path, self.timezone, self.clock = Path(path), ZoneInfo(timezone), clock
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS household(id INTEGER PRIMARY KEY CHECK(id=1), grains INTEGER NOT NULL CHECK(grains>=0));
            INSERT OR IGNORE INTO household VALUES(1,0);
            CREATE TABLE IF NOT EXISTS pets(id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
              seed TEXT NOT NULL, created_at REAL NOT NULL, satiety REAL NOT NULL, settled_at REAL NOT NULL,
              growth REAL NOT NULL DEFAULT 0, stage INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
              asset_ref TEXT, last_feed REAL, last_play REAL, last_comfort REAL,traits_json TEXT);
            CREATE TABLE IF NOT EXISTS requests(actor TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
              response TEXT NOT NULL, PRIMARY KEY(actor,request_id));
            CREATE TABLE IF NOT EXISTS care_events(id INTEGER PRIMARY KEY, pet_id TEXT NOT NULL,
              actor TEXT NOT NULL, action TEXT NOT NULL, created_at REAL NOT NULL, growth_delta REAL NOT NULL);
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def write(self):
        with self.connect() as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except sqlite3.OperationalError:
                db.rollback()
                raise NestError('storage_busy', 503) from None
            except BaseException:
                db.rollback()
                raise

    def day(self, stamp):
        return datetime.fromtimestamp(stamp, self.timezone).date().isoformat()

    def now(self):
        value = self.clock()
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise NestError('invalid_clock')
        return float(value)

    def replay(self, db, actor, request_id, payload):
        identifier(request_id)
        if actor not in ('user', 'assistant', 'host'):
            raise NestError('invalid_actor')
        fingerprint = encode(payload)
        row = db.execute('SELECT * FROM requests WHERE actor=? AND request_id=?', (actor, request_id)).fetchone()
        if row:
            if row['fingerprint'] != fingerprint:
                raise NestError('idempotency_conflict', 409)
            return json.loads(row['response'])
        return None

    def receipt(self, db, actor, request_id, payload, result):
        db.execute('INSERT INTO requests VALUES(?,?,?,?)', (actor, request_id, encode(payload), encode(result)))
        return result

    def pet(self, row, now):
        return {'id': row['id'], 'name': row['name'], 'kind': row['kind'], 'status': row['status'],
                'satiety': round(max(0, row['satiety'] - max(0, now-row['settled_at']) / 3600 * 2), 2),
                'growth': round(row['growth'], 2), 'stage': row['stage'], 'asset_ref': row['asset_ref'],
                'traits': json.loads(row['traits_json']) if row['traits_json'] else temperament(row['seed'])}

    def adopt(self, kind, name, request_id, *, actor, appearance=None):
        if actor not in ('user', 'assistant') or kind not in KINDS:
            raise NestError('invalid_adoption')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 32 or any(ord(c)<32 for c in name):
            raise NestError('invalid_name')
        if appearance is not None:
            raise NestError('use_asset_import_for_custom_appearance')
        payload = {'op': 'adopt', 'kind': kind, 'name': name.strip()}
        with self.write() as db:
            previous = self.replay(db, actor, request_id, payload)
            if previous is not None:
                return previous
            now, pet_id, seed = self.now(), uuid.uuid4().hex, uuid.uuid4().hex
            first = db.execute('SELECT COUNT(*) FROM pets').fetchone()[0] == 0
            if first:
                db.execute('UPDATE household SET grains=grains+36 WHERE id=1')
            status = 'ready' if kind in ('cat', 'dog', 'egg') else 'pending'
            db.execute('INSERT INTO pets(id,kind,name,seed,created_at,satiety,settled_at,status) VALUES(?,?,?,?,?,60,?,?)',
                       (pet_id, kind, name.strip(), seed, now, now, status))
            row = db.execute('SELECT * FROM pets WHERE id=?', (pet_id,)).fetchone()
            result = {'receipt_id': uuid.uuid4().hex, 'status': 'adopted' if status == 'ready' else 'preparing',
                      'pet': self.pet(row, now), 'grains': db.execute('SELECT grains FROM household').fetchone()[0]}
            return self.receipt(db, actor, request_id, payload, result)

    def state(self, *, offset=0, limit=100):
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
            raise NestError('invalid_pagination')
        with self.connect() as db:
            now = self.now()
            return {'grains': db.execute('SELECT grains FROM household').fetchone()[0],
                    'total': db.execute('SELECT COUNT(*) FROM pets').fetchone()[0],
                    'pets': [self.pet(r, now) for r in db.execute('SELECT * FROM pets ORDER BY created_at,id LIMIT ? OFFSET ?', (limit,offset))],
                    'events': [dict(r) for r in db.execute('SELECT * FROM care_events ORDER BY id DESC LIMIT 30')]}

    def care(self, action, request_id, *, actor, pet_ids=None, scope='selected'):
        if actor not in ('user', 'assistant') or action not in ('feed','play','comfort') or scope not in ('selected','all'):
            raise NestError('invalid_care')
        if scope == 'selected' and (not isinstance(pet_ids, list) or not 1<=len(pet_ids)<=500):
            raise NestError('invalid_pet_selection')
        if scope == 'all' and pet_ids is not None:
            raise NestError('invalid_pet_selection')
        ids = sorted(set(identifier(x) for x in pet_ids)) if pet_ids is not None else None
        payload = {'op':'care', 'action':action, 'ids':ids, 'scope':scope}
        with self.write() as db:
            previous = self.replay(db, actor, request_id, payload)
            if previous is not None:
                return previous
            now = self.now()
            if ids is None:
                rows = list(db.execute('SELECT * FROM pets LIMIT 500'))
            else:
                rows = list(db.execute(f'SELECT * FROM pets WHERE id IN ({",".join("?" for _ in ids)})', ids))
                if len(rows) != len(ids):
                    raise NestError('pet_not_found',404)
            rows.sort(key=lambda r: (self.pet(r,now)['satiety'],r['last_feed'] or 0,r['id']))
            grains = db.execute('SELECT grains FROM household').fetchone()[0]
            results = []
            for row in rows:
                satiety = self.pet(row,now)['satiety']
                delta = 0.0
                if row['status'] != 'ready':
                    status = 'pending'
                elif action == 'feed' and satiety > 60:
                    status = 'full'
                elif action == 'feed' and grains == 0:
                    status = 'no_food'
                else:
                    status = {'feed':'fed','play':'played','comfort':'comforted'}[action]
                    if action == 'feed':
                        satiety, grains, delta = min(100,satiety+40), grains-1, 2.0
                    else:
                        trait = temperament(row['seed'])['attachment' if action=='comfort' else 'energy']
                        recovery = 3600 * (5 - trait / 50)
                        last = row['last_'+action]
                        delta = 1.0 if last is None else min(1,max(0,now-last)/recovery)
                    column = 'last_'+action
                    db.execute(f'UPDATE pets SET satiety=?,settled_at=?,growth=growth+?,{column}=? WHERE id=?',
                               (satiety,now,delta,now,row['id']))
                    db.execute('INSERT INTO care_events(pet_id,actor,action,created_at,growth_delta) VALUES(?,?,?,?,?)',
                               (row['id'],actor,action,now,delta))
                results.append({'pet_id':row['id'],'status':status,'growth_delta':delta})
            db.execute('UPDATE household SET grains=? WHERE id=1',(grains,))
            return self.receipt(db,actor,request_id,payload,{'receipt_id':uuid.uuid4().hex,'results':results,'grains':grains})
