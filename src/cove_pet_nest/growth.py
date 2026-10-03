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
