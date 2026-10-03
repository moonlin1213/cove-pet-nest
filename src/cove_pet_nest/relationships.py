from .contracts import RelationshipEvent
from .store import NestError,encode


def record_relationship(store,event: RelationshipEvent) -> dict:
    event=RelationshipEvent.model_validate(event.model_dump())
    if event.occurred_at>store.now()+60:
        raise NestError('future_relationship_event')
    payload=encode(event.model_dump())
    with store.write() as db:
        db.execute('CREATE TABLE IF NOT EXISTS relationships(id TEXT PRIMARY KEY, occurred_at REAL, payload TEXT)')
        old=db.execute('SELECT payload FROM relationships WHERE id=?',(event.event_id,)).fetchone()
        if old:
            if old[0]!=payload:
                raise NestError('idempotency_conflict',409)
            return {'recorded':False}
        db.execute('INSERT INTO relationships VALUES(?,?,?)',(event.event_id,event.occurred_at,payload))
    return {'recorded':True}
