"""Split a single transparent 2x2 illustration into four display assets."""
from io import BytesIO
from PIL import Image,UnidentifiedImageError
from .store import NestError


def split_forms(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=16*1024*1024:
        raise NestError('invalid_toy_atlas')
    try:
        with Image.open(BytesIO(raw)) as image:
            w,h=image.size
            if not 128<=w<=3072 or w!=h or w%2 or 'A' not in image.getbands():
                raise NestError('invalid_toy_atlas')
            source=image.convert('RGBA')
            n=w//2
            forms=[]
            for y in (0,n):
                for x in (0,n):
                    cell=source.crop((x,y,x+n,y+n))
                    alpha=cell.getchannel('A')
                    if alpha.getextrema()[0]==255 or not alpha.getbbox():
                        raise NestError('invalid_toy_form')
                    cell.thumbnail((512,512),Image.Resampling.LANCZOS)
                    out=BytesIO()
                    cell.save(out,format='WEBP',quality=82,method=4,exif=b'')
                    forms.append(out.getvalue())
            if len(set(forms))!=4:
                raise NestError('duplicate_toy_forms')
            return forms
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError):
        raise NestError('invalid_toy_atlas') from None
