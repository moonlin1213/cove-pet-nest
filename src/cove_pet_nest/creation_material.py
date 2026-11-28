"""Select one local, dated source. Private identifiers stay in SQLite."""
import json
import re
from .store import NestError
from .toy_appearance import render_appearance

DAY = 86400
LIFE = {'reading':'共读','watching':'共影','listening':'共听','exploration':'一起探索','companionship':'一起相伴'}
ACTIONS = {'feed':'喂食','play':'陪玩','comfort':'摸摸'}
ACTORS = {'user':'家人','assistant':'陪伴伙伴'}
ENDINGS = ('蹭蹭你','想和你再待一会儿','分你一颗想象中的糖','画一颗小星星','记在我的小本子里')


# A short expressive wish may vary freely within a grammar that cannot assert
# an additional action, participant or past event on behalf of this household.
PET_VOICE = re.compile(
    r'(?:(?:呼噜|喵呜|汪呜|沙沙|嘀啾|嘿嘿)[，、～ ]?)?'
    r'(?:我|宝宝)?(?:好想|还想|想要|想|希望|最想|真想)'
    r'(?:再|悄悄|轻轻|慢慢|一直|一起|和你|陪你){0,2}'
    r'(?:听一遍|读一遍|看一遍|玩一会儿|待一会儿|挨着你|蹭蹭你|靠近你|画颗星星|分你一颗糖|记住这一刻)'
    r'(?:呀|呢|啦|哦|啊|～)?'
)


def choose_source(db, kind, since, now, rng, pet_id=None):
    """Sample recent unused sources; never pair a care receipt with another pet."""
    found = []
    params = (since, now, kind)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='relationships'").fetchone():
        for row in db.execute("""SELECT * FROM relationships AS r WHERE occurred_at BETWEEN ? AND ?
            AND NOT EXISTS(SELECT 1 FROM creation_jobs j WHERE j.kind=? AND j.source_id='relationship:'||r.id)
            ORDER BY occurred_at DESC,id LIMIT 64""", params):
            event = json.loads(row['payload'])
            fact = event.get('summary','').strip()[:240]
            if fact:
                found.append(('relationship:'+row['id'], {'type':'relationship','fact':fact}))
    predicate = ''
    if pet_id:
        predicate = 'AND EXISTS(SELECT 1 FROM life_participants p WHERE p.event_id=e.id AND p.pet_id=?)'
    for row in db.execute("""SELECT e.id,e.kind FROM life_events e WHERE occurred_at BETWEEN ? AND ?
            AND id LIKE 'shared:%' AND NOT EXISTS(SELECT 1 FROM creation_jobs j WHERE j.kind=? AND j.source_id=e.id)
            """+predicate+" ORDER BY occurred_at DESC,id LIMIT 64", (*params,pet_id) if pet_id else params):
        if row['kind'] in LIFE:
            found.append((row['id'],{'type':'life','fact':'一起留下了'+LIFE[row['kind']]+'的记录'}))
    if kind=='note':
        for row in db.execute("""SELECT id,actor,action FROM care_events e WHERE created_at BETWEEN ? AND ?
            AND pet_id=? AND NOT EXISTS(SELECT 1 FROM creation_jobs j WHERE j.kind='note' AND j.source_id='care:'||e.id)
            ORDER BY created_at DESC,id DESC LIMIT 64""",(since,now,pet_id)):
            if row['actor'] in ACTORS and row['action'] in ACTIONS:
                found.append(('care:'+str(row['id']),{'type':'care','actor':row['actor'],'action':row['action'],
                            'fact':ACTORS[row['actor']]+'给了我一次'+ACTIONS[row['action']]}))
    return rng.choice(found) if found else None


def clean_field(answer,key,limit):
    value = answer.get(key)
    if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value):
        raise NestError('invalid_creation_result')
    return value.strip()


def validate_answer(kind, answer, material):
    if not isinstance(answer,dict) or answer.get('evidence')!='source':
        raise NestError('unsupported_creation_evidence')
    source = material['source']
    quote = clean_field(answer,'quote',60)
    if quote not in source['fact'] or (kind!='toy' and source['type']=='care' and quote!=source['fact']):
        raise NestError('unsupported_creation_evidence')
    if kind=='toy':
        appearance=answer.get('appearance')
        render_appearance(appearance)
        return {'name':clean_field(answer,'name',40),'origin':quote,'appearance':appearance}
    style,ending = answer.get('kind'),clean_field(answer,'ending',32)
    if style not in ('observation','snack','affection','doodle') or (ending not in ENDINGS and not PET_VOICE.fullmatch(ending)):
        raise NestError('invalid_creation_result')
    # Model chooses the excerpt, voice and sentiment. Only the verified source
    # can supply factual details about who acted, which pet, and what happened.
    prefix = {'observation':'我记下了','snack':'小点心纸条','affection':'悄悄记着','doodle':'爪印涂鸦'}[style]
    if len(prefix)+len(quote)+len(ending)+5>60:
        raise NestError('invalid_creation_result')
    return {'kind':style,'text':f'{prefix}：{quote}。{ending}。'}
