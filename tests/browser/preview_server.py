"""Isolated browser fixture. Requires a NEW test directory; never uses real data."""
import os
from pathlib import Path
import asyncio
from io import BytesIO
from PIL import Image
from cove_pet_nest.config import Settings
from cove_pet_nest.service import build_service
from cove_pet_nest.http import create_app
from cove_pet_nest.auth import credentials
import uvicorn

root=Path(os.environ['NEST_TEST_DATA_DIR']);root.mkdir(parents=True,exist_ok=False)
service=build_service(Settings(root))
class OfflinePictures:
    can_reference=True
    async def generate(self,brief,reference=None):
        if brief.get('purpose')=='photo':
            image=Image.new('RGB',(768,512),(235,220,191));out=BytesIO();image.save(out,format='PNG');return out.getvalue()
        if reference:return reference[0]
        return (Path(__import__('cove_pet_nest').__file__).parent/'assets/cat-sprites-light.webp').read_bytes()
service.jobs.transport=OfflinePictures()
pet=service.adopt('cat','团团','adopt-cat',actor='user')['pet']
service.care('play','play-cat',actor='assistant',pet_ids=[pet['id']])
service.album.queue_photo(service.album.sources()['events'][0]['id'],'photo-cat',actor='user')
asyncio.run(service.tick())
start=service.store.now()
for growth,days in ((40,7),(100,14)):
    start+=days*86400;service.store.clock=lambda:start
    with service.store.write() as db:db.execute('UPDATE pets SET growth=? WHERE id=?',(growth,pet['id']))
    asyncio.run(service.tick())
service.care('comfort','hug-cat',actor='user',pet_ids=[pet['id']])
credentials(service.settings)
uvicorn.run(create_app(service),host='127.0.0.1',port=int(os.environ.get('NEST_TEST_PORT','18767')),access_log=False)
