"""Single-request generation or reference editing, without route fallbacks."""
import base64
import os
from urllib.parse import urlsplit
import httpx
from ..store import NestError


def endpoint_url(value):
    parsed=urlsplit(value)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise NestError('invalid_image_endpoint')
    return value


class ImageTransport:
    def __init__(self,endpoint,model,key,*,edit_endpoint=None,http_transport=None):
        self.endpoint=endpoint_url(endpoint)
        self.edit_endpoint=endpoint_url(edit_endpoint) if edit_endpoint else None
        self.model,self.key,self.http_transport=model,key,http_transport
        self.can_reference=self.edit_endpoint is not None

    async def generate(self,brief,reference=None):
        if reference is not None:
            if not self.can_reference:raise NestError('needs_image_edit_configuration')
            if not 1<=len(reference)<=4 or any(not isinstance(r,bytes) or len(r)>8*1024*1024 for r in reference) or sum(map(len,reference))>16*1024*1024:
                raise NestError('invalid_reference_images')
        photo=brief.get('purpose')=='photo'
        style='Soft plush picture-book artwork, muted natural colors, gentle light. No text, logos or human body parts. '
        toy=brief.get('purpose')=='toy'
        if toy:
            prompt=(style+'One square transparent 2x2 sprite sheet. Show the same handmade toy in four distinct '
                    'playful forms, one complete centered object per equally sized cell with transparent margins. '
                    'Render this appearance: '+brief['appearance'])
        elif photo:
            events={'care_feed':'a pet calmly enjoying its food','care_play':'a pet playing peacefully','care_comfort':'a pet resting contentedly after care',
                'reading':'pets beside an open picture book','watching':'pets quietly watching a blank story screen','listening':'pets beside a small music box',
                'exploration':'pets curiously exploring their room','companionship':'pets quietly keeping one another company'}
            cast='; '.join(f"reference {i+1}: one {p['kind']} individual" for i,p in enumerate(brief['participants']))
            prompt=(style+'Render one single scene with an opaque illustrated background, no grid, no montage, no sprite sheet. '
                'Each reference atlas shows multiple poses of ONE pet: draw exactly one of each participant. '
                'Preserve faces, colors, markings, body proportions and cumulative features from references. '
                'Do not invent physical contact, romance or birth. Grounded event: '+events[brief['event_kind']]+'. '+cast)
        else:
            details=' '.join(str(brief.get(k,'')) for k in ('identity','palette','marking'))
            features='; '.join(brief.get('features',[]))
            prompt=(style+f"A natural cute {brief.get('kind','animal')} pet, never humanoid. {details}. "
                'Transparent RGBA background. Exactly six square cells in a 3-column 2-row sprite atlas, '
                'same individual in every cell. Poses: idle, blink, sleep, eat, seek food, affection. '
                'Fully visible body, no checkerboard, no external shadow. '
                'Preserve the referenced face, anatomy, eye colors and ALL existing features in every pose. '
                'Add the frozen new body feature visibly without replacing old details. Cumulative features: '+features)
        fields={'model':self.model,'prompt':prompt,'size':'1024x1024' if toy else '1536x1024','background':'opaque' if photo else 'transparent','n':'1'}
        url=self.edit_endpoint if reference is not None else self.endpoint
        if reference is None:
            request={'json':{**fields,'n':1}}
        else:
            request={'data':fields,'files':[('image[]',(f'reference-{i+1}.png',raw,'image/png')) for i,raw in enumerate(reference)]}
        async with httpx.AsyncClient(timeout=120,follow_redirects=False,transport=self.http_transport) as client:
            async with client.stream('POST',url,headers={'Authorization':f'Bearer {self.key}'},**request) as response:
                if response.status_code>=400:raise NestError('image_provider_rejected')
                body=bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body)>32*1024*1024:raise NestError('image_provider_invalid_result')
                import json
                try:
                    value=json.loads(body)['data'][0]['b64_json']
                    if not isinstance(value,str) or len(value)>24*1024*1024:raise ValueError()
                    return base64.b64decode(value,validate=True)
                except (KeyError,IndexError,TypeError,ValueError):raise NestError('image_provider_invalid_result') from None


def configured_transport():
    def optional_address(variable):
        value = os.environ.get(variable)
        if not value:
            return None
        try:
            parsed = urlsplit(endpoint_url(value))
            # Accessing port also checks its numeric syntax and range.
            if parsed.port == 0 or parsed.username is not None or '\\' in value or any(c.isspace() for c in value):
                return None
        except ValueError:
            return None
        return value

    endpoint = optional_address('PET_NEST_IMAGE_ENDPOINT')
    model = os.environ.get('PET_NEST_IMAGE_MODEL')
    key = os.environ.get('PET_NEST_IMAGE_KEY')
    if not all((endpoint, model, key)):
        return None
    return ImageTransport(endpoint, model, key, edit_endpoint=optional_address('PET_NEST_IMAGE_EDIT_ENDPOINT'))
