"""Local-only fictional room for browser acceptance. Prints its ephemeral login URL."""
import asyncio
import socket
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
import uvicorn

from cove_pet_nest.auth import credentials
from cove_pet_nest.config import Settings
from cove_pet_nest.http import create_app
from cove_pet_nest.keepsakes import deliver_note, deliver_toy, ensure_keepsakes
from cove_pet_nest.service import build_service

with tempfile.TemporaryDirectory(prefix='fictional-keepsakes-') as folder:
    settings=Settings(Path(folder))
    s=build_service(settings)
    s.jobs.transport=None
    pets=[s.adopt(kind,name,'fixture-'+kind,actor='user')['pet']['id']
          for kind,name in [('cat','蒲公英'),('snake','细雨'),('lizard','晴川')]]
    refs=[]
    for i in range(4):
        img=Image.new('RGBA',(128,128))
        ImageDraw.Draw(img).ellipse((12+i,12,109,100),fill=(160,120+i*15,75,255))
        out=BytesIO();img.save(out,format='WEBP');refs.append(s.jobs.save_asset(out.getvalue()))
    with s.store.write() as db:
        ensure_keepsakes(db)
        deliver_toy(db,source_id='fixture-toy',name='花园铃',origin='一起读过花园的故事',forms=refs,now=s.store.now())
        deliver_note(db,source_id='fixture-note',pet_id=pets[0],kind='observation',text='今天听见了花园铃。',evidence=['fixture'],now=s.store.now())
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        print(f"http://127.0.0.1:{sock.getsockname()[1]}/#key="+credentials(settings)['browser_token'],flush=True)
        asyncio.run(uvicorn.Server(uvicorn.Config(create_app(s),log_level='error')).serve(sockets=[sock]))
