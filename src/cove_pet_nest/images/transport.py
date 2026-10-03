import base64
import os
from urllib.parse import urlsplit
import httpx
from ..store import NestError


class ImageTransport:
    """One OpenAI-compatible generation request; no automatic provider retries."""
    def __init__(self,endpoint,model,key):
        parsed=urlsplit(endpoint)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query:
            raise NestError('invalid_image_endpoint')
        self.endpoint,self.model,self.key=endpoint,model,key

    async def generate(self,brief,reference=None):
        kind=brief.get('kind','animal')
        details=' '.join(str(brief.get(k,'')) for k in ('identity','palette','marking'))
        prompt=(f'Soft plush picture-book {kind} pet. {details}. A natural cute animal, never humanoid. '
                'Transparent RGBA background. Exactly six square cells in a 3-column 2-row sprite atlas, '
                'same individual in every cell. Poses: idle, blink, sleep, eat, seek food, affection. '
                'Fully visible body, no text, no checkerboard, no external shadow.')
        async with httpx.AsyncClient(timeout=120,follow_redirects=False) as client:
            response=await client.post(self.endpoint,headers={'Authorization':f'Bearer {self.key}'},
                                       json={'model':self.model,'prompt':prompt,'size':'1536x1024','background':'transparent','n':1})
        if response.status_code>=400:
            raise NestError('image_provider_rejected')
        try:
            value=response.json()['data'][0]['b64_json']
            if not isinstance(value,str) or len(value)>24*1024*1024:
                raise ValueError()
            return base64.b64decode(value,validate=True)
        except (KeyError,IndexError,TypeError,ValueError):
            raise NestError('image_provider_invalid_result') from None


def configured_transport():
    endpoint,model,key=(os.environ.get(k) for k in ('PET_NEST_IMAGE_ENDPOINT','PET_NEST_IMAGE_MODEL','PET_NEST_IMAGE_KEY'))
    return ImageTransport(endpoint,model,key) if all((endpoint,model,key)) else None
