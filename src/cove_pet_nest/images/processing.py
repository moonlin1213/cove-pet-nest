from io import BytesIO
from PIL import Image,UnidentifiedImageError
from ..store import NestError


def prepare_asset(payload: bytes) -> bytes:
    if not isinstance(payload,bytes) or not 1<=len(payload)<=16*1024*1024:
        raise NestError('invalid_image_size')
    try:
        with Image.open(BytesIO(payload)) as image:
            w,h=image.size
            if w<768 or h<512 or w>3072 or h>2048 or w*2!=h*3 or 'A' not in image.getbands():
                raise NestError('expected_transparent_3x2_atlas')
            image.load()
            rgba=image.convert('RGBA')
            low,high=rgba.getchannel('A').getextrema()
            if low==255 or high==0:
                raise NestError('expected_transparent_subject')
            # Re-encode pixels only; EXIF and other input metadata are discarded.
            rgba.thumbnail((1152,768))
            out=BytesIO(); rgba.save(out,format='WEBP',quality=86)
            return out.getvalue()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):
        raise NestError('invalid_image') from None


def prepare_photo(payload: bytes) -> bytes:
    """Single scene, independent of the transparent six-pose atlas contract."""
    if not isinstance(payload,bytes) or not 1<=len(payload)<=16*1024*1024:raise NestError('invalid_image_size')
    try:
        with Image.open(BytesIO(payload)) as image:
            w,h=image.size
            if w<768 or h<512 or w>3072 or h>2048 or w*2!=h*3:raise NestError('expected_landscape_photo')
            image.load();rgba=image.convert('RGBA')
            opaque=Image.new('RGB',rgba.size,(250,245,232));opaque.paste(rgba,mask=rgba.getchannel('A'))
            opaque.thumbnail((1152,768));out=BytesIO();opaque.save(out,format='WEBP',quality=86)
            return out.getvalue()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):raise NestError('invalid_image') from None
