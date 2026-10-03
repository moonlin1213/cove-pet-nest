import hashlib
import math
from .contracts import UsageEvent
from .store import NestError, encode
from .usage import normalize_usage


def _grains(total):
    total = min(total,20000)
    return min(total,4000)//200 + max(0,total-4000)//800


def record_usage(store, event: UsageEvent) -> dict:
    result = {'credited_grains':0,'token_grains':0,'baseline_grains':0,
              'measurement':'bounded_visible_estimate_v1'}
    if event.has_error:
        return result
    payload = event.model_dump()
    fingerprint = hashlib.sha256(encode(payload).encode()).hexdigest()
    key = encode([event.source_id,event.conversation_id,event.user_turn_id])
    with store.write() as db:
        for statement in (
            'CREATE TABLE IF NOT EXISTS usage_events(source TEXT, reply TEXT, revision INTEGER, fingerprint TEXT, PRIMARY KEY(source,reply,revision))',
            'CREATE TABLE IF NOT EXISTS usage_turns(key TEXT PRIMARY KEY, day TEXT, tokens INTEGER)',
            'CREATE TABLE IF NOT EXISTS usage_revisions(source TEXT, reply TEXT, revision INTEGER, PRIMARY KEY(source,reply))',
            'CREATE TABLE IF NOT EXISTS usage_days(day TEXT PRIMARY KEY, tokens INTEGER, baseline INTEGER)',
            'CREATE TABLE IF NOT EXISTS pantry_ledger(id INTEGER PRIMARY KEY, source TEXT, day TEXT, amount INTEGER, balance_after INTEGER)'):
            db.execute(statement)
        old = db.execute('SELECT fingerprint FROM usage_events WHERE source=? AND reply=? AND revision=?',
                         (event.source_id,event.reply_id,event.revision)).fetchone()
        if old:
            if old[0] != fingerprint:
                raise NestError('idempotency_conflict',409)
            return result
        high = db.execute('SELECT revision FROM usage_revisions WHERE source=? AND reply=?',(event.source_id,event.reply_id)).fetchone()
        db.execute('INSERT INTO usage_events VALUES(?,?,?,?)',(event.source_id,event.reply_id,event.revision,fingerprint))
        if high and event.revision < high[0]:
            return result
        db.execute('INSERT INTO usage_revisions VALUES(?,?,?) ON CONFLICT(source,reply) DO UPDATE SET revision=excluded.revision',
                   (event.source_id,event.reply_id,event.revision))
        first_adopt = db.execute('SELECT MIN(created_at) FROM pets').fetchone()[0]
        if first_adopt is None or event.completed_at < first_adopt:
            return result
        old_turn = db.execute('SELECT day,tokens FROM usage_turns WHERE key=?',(key,)).fetchone()
        day = old_turn['day'] if old_turn else store.day(event.completed_at)
        contribution = normalize_usage(event)['contribution_tokens']
        delta = max(0,contribution-(old_turn['tokens'] if old_turn else 0))
        db.execute('INSERT INTO usage_turns VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET tokens=MAX(tokens,excluded.tokens)',(key,day,contribution))
        daily = db.execute('SELECT tokens,baseline FROM usage_days WHERE day=?',(day,)).fetchone()
        before = daily['tokens'] if daily else 0
        after = min(20000,before+delta)
        base = daily['baseline'] if daily else 0
        if not daily:
            count = db.execute('SELECT COUNT(*) FROM pets WHERE created_at<=?',(event.completed_at,)).fetchone()[0]
            base = min(6,2+math.ceil(math.sqrt(count)))
            result['baseline_grains'] = base
        result['token_grains'] = _grains(after)-_grains(before)
        result['credited_grains'] = result['token_grains']+result['baseline_grains']
        db.execute('INSERT INTO usage_days VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET tokens=excluded.tokens', (day,after,base))
        for source,column in (('tokens','token_grains'),('baseline','baseline_grains')):
            amount = result[column]
            if amount:
                db.execute('UPDATE household SET grains=grains+? WHERE id=1',(amount,))
                balance = db.execute('SELECT grains FROM household').fetchone()[0]
                db.execute('INSERT INTO pantry_ledger(source,day,amount,balance_after) VALUES(?,?,?,?)',(source,day,amount,balance))
    return result
