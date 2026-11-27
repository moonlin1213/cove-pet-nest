import asyncio
from contextlib import suppress
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import tempfile
import threading
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field

from ..contracts import StrictModel
from ..store import NestError
from .bridge import listen
from .pack import make_files

HOME_NETWORKS = tuple(map(ipaddress.IPv4Network, ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')))


def home_ip(value):
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError,TypeError):
        return False
    return any(address in net for net in HOME_NETWORKS)


def suggested_host():
    # UDP connect selects a source interface without emitting an application packet.
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1',9))
            ip=sock.getsockname()[0]
            if home_ip(ip):
                return ip
    except OSError:
        pass
    try:
        return next((ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if home_ip(ip)),'')
    except OSError:
        return ''


class PackRequest(StrictModel):
    pets: list[str] = Field(min_length=1, max_length=32)
    slot: Literal['a','b']
    host: str = Field(max_length=15)


class Ticket(StrictModel):
    ticket: str = Field(pattern='^[0-9a-f]{32}$')


class Pairing:
    def __init__(self,service):
        self.service=service
        self.path=service.settings.data_dir/'passport-bridge.json'
        self.lock=threading.RLock()
        self.listeners={}
        self.closed=False
        self.prepared=None
        self.state=self._load()

    def _load(self):
        try:
            state=json.loads(self.path.read_bytes())
            if (not home_ip(state['host']) or not re.fullmatch('[0-9a-f]{64}',state['token'])
                    or type(state['port']) is not int or not 1<=state['port']<=65535
                    or not isinstance(state['pets'],list) or not all(isinstance(p,str) for p in state['pets'])):
                raise ValueError
            return state
        except FileNotFoundError:
            return {}
        except (OSError,KeyError,ValueError,TypeError):
            # A broken legacy accessory file must never prevent the room opening.
            return {'error':'passport_invalid_config'}

    def _save(self, state):
        name=None
        try:
            with tempfile.NamedTemporaryFile('w',dir=self.path.parent,delete=False) as out:
                name=out.name
                json.dump(state,out)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name,self.path)
            self.state=state
        finally:
            if name:
                Path(name).unlink(missing_ok=True)

    def status(self):
        with self.lock:
            state=self.state
            port=state.get('port',8768)
            token=state.get('token')
            return {'paired':bool(state.get('token')), 'host':state.get('host') or suggested_host(),
                    'port':port, 'pets':state.get('pets',[]), 'error':state.get('error'),
                    'token_sha256':hashlib.sha256(token.encode()).hexdigest() if token else '',
                    'pending_ticket':state.get('pending',{}).get('ticket'),
                    'online':(state.get('host'),port) in self.listeners}

    def _start_listener(self,host,port):
        if not home_ip(host):
            raise NestError('passport_invalid_host')
        if (host,port) in self.listeners:
            return
        try:
            server=listen(self.service,host,port,lambda:self.state)
        except OSError as e:
            raise NestError('passport_lan_unavailable',503) from e
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.listeners[host,port]=server

    def restore(self):
        with self.lock:
            if self.closed or not self.state.get('token'):
                return
            for host in {self.state['host'],self.state.get('pending',{}).get('host',self.state['host'])}:
                with suppress(NestError):
                    self._start_listener(host,self.state['port'])

    def _stop_except(self, keep):
        for key,server in list(self.listeners.items()):
            if key not in keep:
                server.shutdown()
                server.server_close()
                del self.listeners[key]

    def close(self):
        with self.lock:
            self.closed=True
            self._stop_except(set())

    async def maintain(self):
        while True:
            await asyncio.to_thread(self.restore)
            await asyncio.sleep(12)

    def pack(self,request):
        if not home_ip(request.host):
            raise NestError('passport_invalid_host')
        if len(set(request.pets))!=len(request.pets) or any(not 0<len(p)<=128 for p in request.pets):
            raise NestError('passport_invalid_selection')
        with self.lock:
            if self.state.get('error'):
                raise NestError(self.state['error'],409)
        files=make_files(self.service,request.pets,request.slot)
        with self.lock:
            token=self.state.get('token') or secrets.token_hex(32)
            wifi={'host':request.host,'port':self.state.get('port',8768),'token':token}
            ticket=secrets.token_hex(16)
            self.prepared={**wifi,'pets':list(request.pets),'ticket':ticket}
            return {'files':files,'wifi':wifi,'ticket':ticket}

    def activate(self,ticket):
        with self.lock:
            old=self.state
            if old.get('pending',{}).get('ticket')==ticket or old.get('confirmed')==ticket:
                return {'ok':True}
            new=self.prepared
            if not new or new['ticket']!=ticket:
                raise NestError('passport_stale_pairing',409)
            self._start_listener(new['host'],new['port'])
            state={'token':new['token'],'port':new['port'],'host':old.get('host',new['host']),
                   'pets':old.get('pets',[]),'pending':{k:new[k] for k in ('host','pets','ticket')}}
            try:
                self._save(state)
            except OSError:
                self._stop_except({(old.get('host'),old.get('port')),
                                   (old.get('pending',{}).get('host'),old.get('port'))})
                raise
            self.prepared=None
            self._stop_except({(state['host'],state['port']), (new['host'],state['port'])})
            return {'ok':True}

    def confirm(self,ticket):
        with self.lock:
            if self.state.get('confirmed')==ticket:
                return {'ok':True}
            pending=self.state.get('pending')
            if not pending or pending['ticket']!=ticket:
                raise NestError('passport_stale_pairing',409)
            state=dict(self.state)
            del state['pending']
            state.update(host=pending['host'],pets=pending['pets'],confirmed=ticket)
            self._save(state)
            self._stop_except({(state['host'],state['port'])})
            return {'ok':True}

    def router(self,browser):
        router=APIRouter(prefix='/api/passport',dependencies=[Depends(browser)])
        router.add_api_route('/status',self.status,methods=['GET'])

        @router.post('/pack')
        def pack(body:PackRequest):
            return self.pack(body)

        @router.post('/activate')
        def activate(body:Ticket):
            return self.activate(body.ticket)

        @router.post('/confirm')
        def confirm(body:Ticket):
            return self.confirm(body.ticket)
        return router
