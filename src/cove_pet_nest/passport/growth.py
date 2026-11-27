"""Apply Passport bonuses to the owner's local public Pet Nest v0.2 database."""
import json
import re
import time
from datetime import datetime, timedelta
from ..store import NestError


def settle(service, allowed, row, *, now=None):
    if not isinstance(row,dict) or set(row)!={'id','op','pet','seconds','at'}:
        raise ValueError('invalid record')
    key,pet,op,at,seconds=(row[k] for k in ('id','pet','op','at','seconds'))
    if (not isinstance(key,str) or not re.fullmatch(r'passport-[a-f0-9]{32}',key)
            or not isinstance(pet,str) or op not in ('wear','feed','play','comfort')
            or type(at) is not int or type(seconds) is not int or not 0<=seconds<=86400
            or (op=='wear')!=bool(seconds) or at<1577836800
            or at+seconds>(time.time() if now is None else now)+120):
        raise ValueError('invalid record')
    if pet not in allowed:
        return {'id':key,'status':'refused','bonus':0}
    fingerprint=json.dumps(row,sort_keys=True)
    with service.store.write() as db:
        db.execute('CREATE TABLE IF NOT EXISTS passport_events(id TEXT PRIMARY KEY, payload TEXT NOT NULL, receipt TEXT)')
        db.execute('INSERT OR IGNORE INTO passport_events(id,payload) VALUES(?,?)',(key,fingerprint))
        saved,receipt=db.execute('SELECT payload,receipt FROM passport_events WHERE id=?',(key,)).fetchone()
        if saved!=fingerprint:raise ValueError('changed record')
        if receipt:return json.loads(receipt)
    status='worn'
    if op!='wear':
        try:
            reply=service.care(op,key,actor='user',scope='selected',pet_ids=[pet])
            item=reply['results'][0]
            if item['pet_id']!=pet:raise ValueError('wrong care receipt')
            status=item['status']
        except NestError as error:
            if error.status!=404:raise
            status='refused'
    zone=service.store.timezone
    with service.store.write() as db:
        receipt=db.execute('SELECT receipt FROM passport_events WHERE id=?',(key,)).fetchone()[0]
        if receipt:return json.loads(receipt)
        db.execute('CREATE TABLE IF NOT EXISTS passport_days(pet TEXT,day TEXT,wear INTEGER DEFAULT 0,care INTEGER DEFAULT 0,PRIMARY KEY(pet,day))')
        db.execute('CREATE TABLE IF NOT EXISTS passport_remainders(pet TEXT PRIMARY KEY,seconds INTEGER)')
        bonus=0
        if not db.execute('SELECT 1 FROM pets WHERE id=?',(pet,)).fetchone():
            status='refused'
        elif op=='wear':
            value=db.execute('SELECT seconds FROM passport_remainders WHERE pet=?',(pet,)).fetchone()
            remainder=value[0] if value else 0
            while seconds:
                day=datetime.fromtimestamp(at,zone).date()
                midnight=datetime.combine(day+timedelta(days=1),datetime.min.time(),zone)
                span=min(seconds,int(midnight.timestamp())-at)
                hours,remainder=divmod(remainder+span,3600)
                db.execute('INSERT OR IGNORE INTO passport_days(pet,day) VALUES(?,?)',(pet,day.isoformat()))
                earned=db.execute('SELECT wear FROM passport_days WHERE pet=? AND day=?',(pet,day.isoformat())).fetchone()[0]
                add=min(hours,4-earned)
                db.execute('UPDATE passport_days SET wear=wear+? WHERE pet=? AND day=?',(add,pet,day.isoformat()))
                bonus+=add
                seconds-=span
                at+=span
            db.execute('INSERT OR REPLACE INTO passport_remainders VALUES(?,?)',(pet,remainder))
        elif status in ('fed','played','comforted'):
            day=datetime.fromtimestamp(at,zone).date().isoformat()
            db.execute('INSERT OR IGNORE INTO passport_days(pet,day) VALUES(?,?)',(pet,day))
            bonus=db.execute('UPDATE passport_days SET care=care+1 WHERE pet=? AND day=? AND care<3',(pet,day)).rowcount
        if bonus:db.execute('UPDATE pets SET growth=growth+? WHERE id=?',(bonus,pet))
        result={'id':key,'status':status,'bonus':bonus}
        current=db.execute('SELECT growth FROM pets WHERE id=?',(pet,)).fetchone()
        if current:result['growth']=current[0]
        db.execute('UPDATE passport_events SET receipt=? WHERE id=?',(json.dumps(result),key))
        return result
