"""Household keepsakes. Delivery runs inside the worker's existing transaction."""
import json
import re
import uuid

from .store import NestError, encode

NOTE_KINDS = {'observation', 'affection', 'snack', 'doodle'}
ASSET_REF = re.compile(r'[a-f0-9]{64}\.webp')


def ensure_keepsakes(db):
    # executescript implicitly commits. Keep the caller's transaction intact.
    db.execute('''CREATE TABLE IF NOT EXISTS keepsake_toys(
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, origin TEXT NOT NULL,
        forms TEXT NOT NULL, created_at REAL NOT NULL, placed INTEGER NOT NULL DEFAULT 0,
        form INTEGER NOT NULL DEFAULT 0, x REAL NOT NULL DEFAULT .5, y REAL NOT NULL DEFAULT .75)''')
    db.execute('''CREATE TABLE IF NOT EXISTS keepsake_notes(
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL UNIQUE, pet_id TEXT REFERENCES pets(id),
        kind TEXT NOT NULL, text TEXT NOT NULL, evidence TEXT NOT NULL, created_at REAL NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0, favorite INTEGER NOT NULL DEFAULT 0)''')
    db.execute('''CREATE TABLE IF NOT EXISTS keepsake_play(
        toy_id TEXT REFERENCES keepsake_toys(id), pet_id TEXT REFERENCES pets(id),
        count INTEGER NOT NULL, played_at REAL NOT NULL, PRIMARY KEY(toy_id,pet_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS keepsake_habitats(
        pet_id TEXT PRIMARY KEY REFERENCES pets(id), theme TEXT NOT NULL, decor TEXT NOT NULL,
        revision INTEGER NOT NULL)''')


def _insert_note(db, source_id, pet_id, kind, text, evidence, now):
    key = uuid.uuid4().hex
    db.execute('''INSERT INTO keepsake_notes(id,source_id,pet_id,kind,text,evidence,created_at)
                  VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id) DO NOTHING''',
               (key, source_id, pet_id, kind, text, encode(evidence), now))
    return db.execute('SELECT id FROM keepsake_notes WHERE source_id=?', (source_id,)).fetchone()[0]


def deliver_note(db, *, source_id, pet_id, kind, text, evidence, now):
    if kind not in NOTE_KINDS or not pet_id or not text.strip() or len(text)>60 or not evidence:
        raise NestError('invalid_pet_note')
    ensure_keepsakes(db)
    return _insert_note(db, source_id, pet_id, kind, text, evidence, now)


def deliver_toy(db, *, source_id, name, origin, forms, now, pet_id=None):
    if len(forms)!=4 or not all(isinstance(ref,str) and ASSET_REF.fullmatch(ref) for ref in forms):
        raise NestError('invalid_toy_forms')
    if not name.strip() or not origin.strip():
        raise NestError('invalid_toy_story')
    ensure_keepsakes(db)
    old = db.execute('SELECT id FROM keepsake_toys WHERE source_id=?', (source_id,)).fetchone()
    if old:
        return old[0]
    key = uuid.uuid4().hex
    db.execute('''INSERT INTO keepsake_toys(id,source_id,name,origin,forms,created_at)
                  VALUES(?,?,?,?,?,?)''', (key, source_id, name, origin, encode(forms), now))
    _insert_note(db, 'toy:'+key, pet_id, 'arrival', f'藤篮里多了一件「{name}」。', [key], now)
    return key


class Collection:
    def __init__(self, store):
        self.store = store
        with store.write() as db:
            ensure_keepsakes(db)

    def contents(self):
        with self.store.connect() as db:
            db.execute('BEGIN')
            plays = {}
            for row in db.execute('SELECT * FROM keepsake_play'):
                plays.setdefault(row['toy_id'], {})[row['pet_id']] = row['count']
            toys = []
            for row in db.execute('SELECT id,name,origin,forms,created_at,placed,form,x,y FROM keepsake_toys ORDER BY created_at DESC,id'):
                toys.append({**dict(row), 'forms':json.loads(row['forms']), 'placed':bool(row['placed']),
                             'plays':plays.get(row['id'], {})})
            notes = [{**dict(row), 'favorite':bool(row['favorite']), 'is_read':bool(row['is_read'])}
                     for row in db.execute('''SELECT id,pet_id,kind,text,created_at,favorite,is_read
                                              FROM keepsake_notes ORDER BY created_at DESC,id''')]
            pets = [dict(r) for r in db.execute('SELECT id,name,kind,status FROM pets ORDER BY created_at,id')]
        return {'toys':toys, 'notes':notes, 'pets':pets}

    def change_toy(self, key, changes):
        # Column names come only from the typed route's whitelist.
        if not changes or not changes.keys() <= {'form','placed','x','y'}:
            raise NestError('invalid_toy_update')
        with self.store.write() as db:
            assignments = ', '.join(f'{column}=?' for column in changes)
            result = db.execute(f'UPDATE keepsake_toys SET {assignments} WHERE id=?', (*changes.values(),key))
            if not result.rowcount:
                raise NestError('toy_not_found',404)
        return {'id':key}

    def play(self, toy, pet, request):
        payload = {'op':'toy_play', 'toy':toy, 'pet':pet}
        with self.store.write() as db:
            replay = self.store.replay(db,'user',request,payload)
            if replay is not None:
                return replay
            if not db.execute('SELECT 1 FROM keepsake_toys WHERE id=?',(toy,)).fetchone():
                raise NestError('toy_not_found',404)
            member = db.execute('SELECT status FROM pets WHERE id=?',(pet,)).fetchone()
            if not member:
                raise NestError('pet_not_found',404)
            if member['status'] != 'ready':
                raise NestError('pet_not_ready',409)
            now = self.store.now()
            last_play = db.execute('SELECT MAX(played_at) FROM keepsake_play WHERE toy_id=?',(toy,)).fetchone()[0]
            if last_play is not None and now-last_play<5:
                raise NestError('toy_play_cooldown',429)
            previous = db.execute('SELECT count FROM keepsake_play WHERE toy_id=? AND pet_id=?',(toy,pet)).fetchone()
            count = previous['count']+1 if previous else 1
            db.execute('''INSERT INTO keepsake_play VALUES(?,?,?,?) ON CONFLICT(toy_id,pet_id)
                          DO UPDATE SET count=excluded.count,played_at=excluded.played_at''',(toy,pet,count,now))
            return self.store.receipt(db,'user',request,payload,{'count':count,'pet_id':pet,'toy_id':toy})

    def flag_note(self, key, changes):
        if not changes or not changes.keys() <= {'is_read','favorite'}:
            raise NestError('invalid_note_update')
        with self.store.write() as db:
            assignments = ', '.join(f'{column}=?' for column in changes)
            if not db.execute(f'UPDATE keepsake_notes SET {assignments} WHERE id=?',(*changes.values(),key)).rowcount:
                raise NestError('note_not_found',404)
        return {'id':key}

    @staticmethod
    def _habitat(db, pet):
        member=db.execute('SELECT kind FROM pets WHERE id=?',(pet,)).fetchone()
        if not member:
            raise NestError('pet_not_found',404)
        if member['kind'] not in ('snake','lizard'):
            raise NestError('habitat_requires_reptile')
        row=db.execute('SELECT theme,decor,revision FROM keepsake_habitats WHERE pet_id=?',(pet,)).fetchone()
        if row:
            return {'theme':row['theme'], 'decor':json.loads(row['decor']), 'revision':row['revision']}
        return {'theme':'warm_stone', 'decor':[], 'revision':0}

    def habitat(self, pet):
        with self.store.connect() as db:
            return self._habitat(db, pet)

    def save_habitat(self, pet, theme, decor, revision):
        with self.store.write() as db:
            current = self._habitat(db, pet)
            if revision!=current['revision']:
                raise NestError('habitat_changed',409)
            for item in decor:
                if item['kind']=='toy':
                    if not db.execute('SELECT 1 FROM keepsake_toys WHERE id=?',(item.get('toy_id'),)).fetchone():
                        raise NestError('habitat_toy_not_owned')
                elif item.get('toy_id') is not None:
                    raise NestError('invalid_habitat_decor')
            db.execute('''INSERT INTO keepsake_habitats VALUES(?,?,?,?) ON CONFLICT(pet_id)
                          DO UPDATE SET theme=excluded.theme,decor=excluded.decor,revision=excluded.revision''',
                       (pet,theme,encode(decor),revision+1))
        return {'theme':theme, 'decor':decor, 'revision':revision+1}
