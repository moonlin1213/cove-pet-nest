"""Device-only HTTP protocol spoken by the public FoloToy firmware."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import sqlite3
import time

from ..store import NestError
from .growth import settle
from .pack import profile, selected


def dispatch(service, config, method, path, headers, raw):
    if not config.get('token'):
        return 403, {}
    expected = ('Bearer '+config['token']).encode()
    if headers.get('Origin') or not hmac.compare_digest(headers.get('Authorization','').encode(),expected):
        return 403, {}
    allowed = config['pets']
    if method=='GET' and path=='/clock':
        return 200, int(time.time())
    try:
        if method=='GET' and path=='/api/pet-nest/ecosystem':
            return 200, {'pets':[profile(p) for p in selected(service,allowed)]}
        if method=='POST' and path=='/care-log':
            from .affinity import record
            if not 0<len(raw)<=512:return 400, {}
            with service.store.write() as db:
                return 200,record(db,allowed,json.loads(raw))
        if method!='POST' or path not in ('/companion','/api/pet-nest/care'):
            return 404, {}
        if not 0<len(raw)<=(512 if path=='/companion' else 2048):
            return 400, {}
        data=json.loads(raw)
        pending=config.get('pending',{}).get('pets',[])
        if path=='/companion':
            if isinstance(data,dict) and data.get('pet') in pending and data['pet'] not in allowed:
                return 503, {}
            return 200, settle(service,allowed,data)
        if not isinstance(data,dict):
            return 400, {}
        ids = data.get('pet_ids')
        if isinstance(ids,list) and any(pet in pending and pet not in allowed for pet in ids):
            return 503, {}
        if (data.get('scope')!='selected' or not isinstance(ids,list) or len(ids)!=1
                or ids[0] not in allowed or data.get('action') not in ('feed','play','comfort')
                or not re.fullmatch('passport-[a-f0-9]{32}',str(data.get('request_id','')))):
            return 400, {}
        reply = service.care(data['action'],data['request_id'],actor='user',scope='selected',pet_ids=ids)
        return 200, {'pantry':{'grains':reply['grains']}, 'receipt_id':reply['receipt_id'], 'results':reply['results']}
    except NestError as e:
        return e.status, {}
    except (ValueError,TypeError,KeyError):
        return 400, {}
    except (OSError,sqlite3.Error):
        return 503, {}


def listen(service, host, port, get_config):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def route(self):
            self.connection.settimeout(5)
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<=size<=2048 or self.headers.get('Transfer-Encoding'):
                    self.send_error(400)
                    return
                raw=self.rfile.read(size)
                if len(raw)!=size:
                    self.send_error(400)
                    return
                status,body=dispatch(service,get_config(),self.command,self.path,self.headers,raw)
                data=json.dumps(body,separators=(',',':')).encode()
                self.send_response(status)
                self.send_header('Content-Length',str(len(data)))
                self.send_header('Content-Type','application/json')
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                self.wfile.write(data)
            except ValueError:
                self.send_error(400)
            except OSError:
                self.close_connection=True
        do_GET=do_POST=route

    return ThreadingHTTPServer((host,port),Handler)
