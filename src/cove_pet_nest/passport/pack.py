"""Encode the layout and RGB565 sprites consumed by the public Passport firmware."""
import base64
from datetime import datetime
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import zlib

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..store import NestError

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


def font(size):
    for candidate in (
        os.environ.get('PASSPORT_FONT'), '/System/Library/Fonts/Hiragino Sans GB.ttc',
        str(Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/'msyh.ttc'),
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        'NotoSansCJK-Regular.ttc', 'DejaVuSans.ttf',
    ):
        if candidate:
            try:
                return ImageFont.truetype(candidate,size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def profile(pet):
    t = pet['traits']
    if pet['satiety'] <= 40:
        wish = 'feed'
    elif t['energy']+t['curiosity'] > t['calm']+t['attachment']:
        wish = 'play'
    else:
        wish = 'comfort'
    return {'pet_id':pet['id'], 'personality':t, 'wish':{'action':wish}}


def selected(service, ids):
    pets = []
    with service.store.connect() as db:
        for ident in ids:
            row = db.execute('SELECT * FROM pets WHERE id=?', (ident,)).fetchone()
            if row is None or row['status'] != 'ready':
                raise NestError('passport_pet_unavailable')
            pet = service.store.pet(row,service.store.now())
            from .affinity import care_profile
            pet.update(care_profile(db,pet,service.store.now()))
            pets.append(pet)
    return pets

W, H = 204, 210
X, Y = (240-W)//2, 68


def pack_frame(cell):
    alpha = cell.getchannel("A")
    indexed = cell.convert("RGB").quantize(colors=95, method=Image.Quantize.MEDIANCUT)
    palette = bytes(indexed.getpalette())
    colors = len(palette)//3
    lut = bytearray(b"\x00\x00")
    for i in range(colors):
        r,g,b=palette[3*i:3*i+3]
        rgb=((r>>3)<<11)|((g>>2)<<5)|(b>>3)
        lut.extend(max(1,rgb).to_bytes(2,"big"))
    pixels = bytes((n+1 if a>8 else 0) for n,a in zip(indexed.tobytes(),alpha.tobytes()))
    compressor=zlib.compressobj(9,wbits=10)
    return bytes([colors+1])+lut+compressor.compress(pixels)+compressor.flush()


def portrait(atlas, room, egg):
    poses = (0,1) if egg else (0,1,2,4)
    cells={}
    if atlas:
        w,h=atlas.size
        for n in poses:
            cell=atlas.crop((w*(n%3)//3,h*(n//3)//2,w*(n%3+1)//3,h*(n//3+1)//2)).convert("RGBA")
            box=cell.getbbox()
            if box:
                cells[n]=cell.crop(box)
    scale=min([W/max(c.width for c in cells.values()), H/max(c.height for c in cells.values())]) if cells else 1
    frames={}
    with BytesIO() as f:
        for n in poses:
            rgba=Image.new("RGBA",(W,H))
            if n in cells:
                c=cells[n]
                c=c.resize((max(1,round(c.width*scale)),max(1,round(c.height*scale))),Image.Resampling.LANCZOS)
                rgba.alpha_composite(c,((W-c.width)//2,H-c.height))
            # Blend anti-aliased edges against the same background used on hardware.
            backdrop=room.crop((X,Y,X+W,Y+H)).convert("RGBA")
            blended=Image.alpha_composite(backdrop,rgba)
            blended.putalpha(rgba.getchannel("A"))
            frames[str(n)]=f.tell()
            f.write(pack_frame(blended))
        return dict(frames=frames,egg=egg,ready=bool(cells)),f.getvalue()


def menu_frames(pet, atlas, room, sync_time):
    regular, title = font(14), font(19)
    footer = font(12)
    for pose in (0,1,3,5):
        page = Image.new('RGB',(240,240),'#f8f2e6')
        scene = ImageOps.fit(room,(240,190),centering=(.5,.68))
        w,h = atlas.size
        x,y = pose%3,pose//3
        cell = atlas.crop((w*x//3,h*y//2,w*(x+1)//3,h*(y+1)//2)).convert('RGBA')
        box = cell.getbbox()
        if box:
            cell = ImageOps.contain(cell.crop(box),(124,139), Image.Resampling.LANCZOS)
            scene.paste(cell,((240-cell.width)//2,180-cell.height),cell)
        page.paste(scene)
        if pose == 0:
            draw = ImageDraw.Draw(page)
            draw.text((12,198),pet['name'][:11],font=title,fill='#494137')
            draw.text((228,201),'阶段 '+str(pet['stage']),font=regular,fill='#494137',anchor='ra')
            label = '成长 %s  ·  同步 %s' % (pet['growth'],sync_time)
            draw.text((12,222),label,font=footer,fill='#494137')
        else:
            page = page.crop((58,41,182,180))
        rgb = page.tobytes()
        raw = bytearray()
        for r,g,b in zip(rgb[::3],rgb[1::3],rgb[2::3]):
            raw.extend((((r>>3)<<11)|((g>>2)<<5)|(b>>3)).to_bytes(2,'big'))
        yield pose, bytes(raw)


def make_files(service, ids, slot):
    group = 'link-'+slot
    nest = '/nest/'+group+'/'
    files = []
    def add(path, raw):
        files.append({'path':path,'data':base64.b64encode(raw).decode('ascii'),
                      'sha256':hashlib.sha256(raw).hexdigest()})
    roster, moods, index = [], {}, {}
    with Image.open(ASSETS/'room-light.webp') as image:
        room = image.convert('RGB')
    screen = ImageOps.fit(room,(240,320),centering=(.5,.69))
    sync_time=datetime.fromtimestamp(service.store.now(),service.store.timezone).strftime('%m/%d %H:%M')
    for i,pet in enumerate(selected(service,ids)):
        if pet['asset_ref']:
            path = service.jobs.asset_path(pet['asset_ref'])
        elif pet['stage']==0 and pet['kind'] in ('cat','dog','egg'):
            path = ASSETS/(pet['kind']+'-sprites-light.webp')
        else:
            raise NestError('passport_pet_unavailable')
        stem = 'p'+str(i)
        try:
            with Image.open(path) as image:
                atlas = image.convert('RGBA')
        except (ValueError,OSError) as e:
            raise NestError('passport_pet_unavailable') from e
        ident = pet['id']
        meta, data = portrait(atlas,screen,pet['kind']=='egg' and pet['stage']==0)
        meta['file'] = group+'/'+stem+'.bin'
        index[ident] = meta
        add('/portrait/'+meta['file'],data)
        for pose,raw in menu_frames(pet,atlas,room,sync_time):
            add(nest+stem+'/pose'+str(pose)+'.rgb',raw)
        roster.append({'id':ident,'name':pet['name'],'growth':pet['growth'],'stage':pet['stage'],'kind':pet['kind'],
                       **{k:pet[k] for k in ('born','age_days','bond') if k in pet},'dir':group+'/'+stem+'/'})
        moods[ident] = {'traits':pet['traits'],'wish':profile(pet)['wish']['action']}
    for name,obj in [('roster',{'pets':roster}),('moods',moods),('portrait',index)]:
        add(nest+name+'.json',json.dumps(obj,separators=(',',':')).encode())
    return files
