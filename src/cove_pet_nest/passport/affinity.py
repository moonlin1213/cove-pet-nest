"""Idempotent receipts for offline relationship changes from a paired Passport."""
import re

def total(db, pet):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='passport_affinity'").fetchone():
        return 0
    return min(100,db.execute('SELECT COALESCE(SUM(gain),0) FROM passport_affinity WHERE pet=?',(pet,)).fetchone()[0])

def record(db, allowed, row):
    if not isinstance(row,list) or len(row)!=4:
        raise ValueError('invalid care record')
    event,pet,op,gain=row
    if (not isinstance(event,str) or not re.fullmatch('passport-[a-f0-9]{32}',event)
            or not isinstance(pet,str) or pet not in allowed or op not in ('bath','clean','comfort','play','feed')
            or type(gain) is not int or not 0<=gain<=(3 if op in ('bath','clean') else 2)):
        raise ValueError('invalid care record')
    db.execute('CREATE TABLE IF NOT EXISTS passport_affinity(id TEXT PRIMARY KEY,pet TEXT,op TEXT,gain INTEGER)')
    db.execute('INSERT OR IGNORE INTO passport_affinity VALUES(?,?,?,?)',row)
    if tuple(db.execute('SELECT pet,op,gain FROM passport_affinity WHERE id=?',(event,)).fetchone())!=tuple(row[1:]):
        raise ValueError('conflicting care record')
    return {'id':event}

def care_profile(db, pet, now):
    """Recover the hatch date where the home has an activated first portrait."""
    key=pet['id']
    row=db.execute('SELECT created_at FROM pets WHERE id=?',(key,)).fetchone()
    born=int(row[0]) if row else None
    if pet['kind']=='egg' and pet['stage']>0:
        activated=None
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='pet_stages'").fetchone():
            activated=db.execute('SELECT activated_at FROM pet_stages WHERE pet_id=? AND stage=1 AND date_estimated=0',(key,)).fetchone()
        born=int(activated[0]) if activated and activated[0] else None
    result={'kind':pet['kind'],'stage':pet['stage'],'bond':total(db,key)}
    if born:
        result.update(born=born,age_days=max(0,int((now-born)//86400)))
    return result
