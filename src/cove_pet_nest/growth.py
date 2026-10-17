"""Freeze a fantasy identity from bounded signals, without exporting private prose."""
from datetime import date
import hashlib
import json
from .store import NestError,encode,temperament

DIMENSIONS={'affection':('心形绒纹','attachment'),'reading':('书页月纹','calm'),
            'watching':('流光肩纹','curiosity'),'listening':('风铃耳尖','sensitivity'),
            'exploration':('森林尾尖','energy')}


def prepare_hatch(store,pet_id,*,now):
    with store.write() as db:
        db.execute('CREATE TABLE IF NOT EXISTS hatches(pet_id TEXT PRIMARY KEY, brief TEXT)')
        old=db.execute('SELECT brief FROM hatches WHERE pet_id=?',(pet_id,)).fetchone()
        if old:
            return json.loads(old[0])
        pet=db.execute('SELECT * FROM pets WHERE id=?',(pet_id,)).fetchone()
        if not pet:
            raise NestError('pet_not_found',404)
        age=(date.fromisoformat(store.day(now))-date.fromisoformat(store.day(pet['created_at']))).days
        if pet['kind']!='egg' or pet['growth']<12 or age<2:
            return None
        scores={k:0 for k in DIMENSIONS}
        daily={}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='relationships'").fetchone():
            for row in db.execute('SELECT * FROM relationships WHERE occurred_at>=? AND occurred_at<=?',(pet['created_at'],now)):
                for key,weight in json.loads(row['payload'])['signals'].items():
                    bucket=(store.day(row['occurred_at']),key)
                    daily[bucket]=min(3,daily.get(bucket,0)+weight)
        for (_,key),weight in daily.items():
            scores[key]+=weight
        # Real individual care provides a small secondary character influence.
        care=db.execute('SELECT action,COUNT(*) n FROM care_events WHERE pet_id=? GROUP BY action',(pet_id,)).fetchall()
        experience={r['action']:r['n'] for r in care}
        signal_customized=any(scores.values())
        scores['affection']+=min(1,experience.get('comfort',0)*.1)
        scores['exploration']+=min(1,experience.get('play',0)*.1)
        dimension=max(scores,key=scores.get) if any(scores.values()) else 'random'
        digest=hashlib.sha256(pet['seed'].encode()).digest()
        identity=('月光绒兽','森林长耳兽','星尘角兽','潮汐软鳞兽')[digest[0]%4]
        traits=temperament(pet['seed'])
        if dimension in DIMENSIONS:
            key=DIMENSIONS[dimension][1]
            traits[key]=round(min(100,traits[key]+min(20,scores[dimension]*3)),2)
        brief={'stage':1,'kind':'fantasy','identity':identity,'palette':('奶油银白','青绿蜜金','莓紫暖灰','湖蓝珊瑚')[digest[1]%4],
               'dimension':dimension,'marking':DIMENSIONS[dimension][0] if dimension in DIMENSIONS else '柔和星屑纹',
               'customized':signal_customized,'traits':traits}
        db.execute('INSERT INTO hatches VALUES(?,?)',(pet_id,encode(brief)))
        return brief


def growth_target(pet,current,store):
    target=pet['stage']+1
    rules=({1:(12,2),2:(40,7),3:(100,14),4:(220,21)} if pet['kind']=='egg'
           else {1:(40,7),2:(100,14),3:(220,21)})
    required,days=rules.get(target,(current['growth_at_activation']+120,30))
    anchor=pet['created_at'] if target==1 else current['activated_at']
    elapsed=(date.fromisoformat(store.day(store.now()))-date.fromisoformat(store.day(anchor))).days
    return {'stage':target,'required_growth':required,'required_days':days,'elapsed_days':max(0,elapsed),
            'ready':pet['growth']>=required and elapsed>=days}


def prepare_next_stage(store,pet_id):
    """Freeze exactly one next appearance from bounded signals and prior identity."""
    with store.connect() as db:
        pet=db.execute('SELECT * FROM pets WHERE id=?',(pet_id,)).fetchone()
        if not pet:raise NestError('pet_not_found',404)
        if pet['status']!='ready':return None
        current=db.execute('SELECT * FROM pet_stages WHERE pet_id=? AND stage=?',(pet_id,pet['stage'])).fetchone()
        if not current:return None
        progress=growth_target(pet,current,store)
        if not progress['ready']:return None
        old=db.execute('SELECT brief FROM stage_briefs WHERE pet_id=? AND stage=?',(pet_id,progress['stage'])).fetchone()
        if old:return json.loads(old['brief'])
        previous=json.loads(current['brief'])
        snapshot=dict(pet);active=dict(current)
    if snapshot['kind']=='egg' and snapshot['stage']==0:
        brief=prepare_hatch(store,pet_id,now=store.now())
        if brief is None:return None
        brief={**brief,'features':[brief['marking']],'base_stage':0,'reference_required':False}
    else:
        scores={key:0 for key in DIMENSIONS};daily={}
        with store.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='relationships'").fetchone():
                for row in db.execute('SELECT * FROM relationships WHERE occurred_at>=? AND occurred_at<=?',(active['activated_at'],store.now())):
                    for key,value in json.loads(row['payload'])['signals'].items():
                        bucket=(store.day(row['occurred_at']),key);daily[bucket]=min(3,daily.get(bucket,0)+value)
            for (_,key),value in daily.items():scores[key]+=value
        dimension=max(scores,key=scores.get) if any(scores.values()) else ('reading','watching','listening','affection','exploration')[int(hashlib.sha256(f"{pet_id}:{progress['stage']}".encode()).hexdigest()[:4],16)%5]
        index=progress['stage']
        theme={'reading':'层叠书页形','watching':'流星形','listening':'风铃形','affection':'心形','exploration':'叶芽形'}[dimension]
        surface={'snake':'软鳞','lizard':'软鳞','parrot':'羽簇'}.get(snapshot['kind'],'绒簇')
        placement=('额心','背侧','尾尖')[(index-1)%3]
        feature=f'{placement}新增第{(index-1)//3+1}簇{theme}{surface}'
        features=list(previous.get('features',[previous['marking']] if previous.get('marking') else []))+[feature]
        traits=json.loads(snapshot['traits_json']) if snapshot['traits_json'] else temperament(snapshot['seed'])
        trait=DIMENSIONS[dimension][1];traits[trait]=round(min(100,traits[trait]+3),2)
        brief={'stage':index,'kind':'fantasy' if snapshot['kind']=='egg' else snapshot['kind'],
            'identity':previous.get('identity',snapshot['kind']),'palette':previous.get('palette','preserve reference colors'),
            'dimension':dimension,'customized':any(scores.values()),'features':features,'marking':feature,
            'traits':traits,'base_stage':snapshot['stage'],'reference_required':True}
    brief['base_asset_ref']=snapshot['asset_ref']
    brief['starter_kind']=snapshot['kind'] if snapshot['asset_ref'] is None else None
    with store.write() as db:
        live=db.execute('SELECT stage,asset_ref FROM pets WHERE id=?',(pet_id,)).fetchone()
        if live['stage']!=snapshot['stage'] or live['asset_ref']!=snapshot['asset_ref']:return None
        db.execute('INSERT OR IGNORE INTO stage_briefs VALUES(?,?,?)',(pet_id,brief['stage'],encode(brief)))
        return json.loads(db.execute('SELECT brief FROM stage_briefs WHERE pet_id=? AND stage=?',(pet_id,brief['stage'])).fetchone()[0])
