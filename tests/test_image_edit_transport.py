import asyncio
import base64
import httpx
import pytest
from test_hatch import atlas


def test_edit_sends_owned_references_and_cumulative_features_once():
    from cove_pet_nest.images.transport import ImageTransport
    requests=[]
    def handler(request):
        requests.append(request)
        assert request.url.path=='/v1/images/edits'
        body=request.content
        assert body.count(b'name="image[]"')==2
        assert '保留旧月纹'.encode() in body and '新增尾部叶芽'.encode() in body
        assert b'PRIVATE_SUMMARY' not in body and b'PRIVATE_PET_NAME' not in body
        assert b'multipart/form-data' in request.headers['content-type'].encode()
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(atlas()).decode()}]})
    transport=ImageTransport('https://images.example.test/v1/images/generations','demo','fake-key',
        edit_endpoint='https://images.example.test/v1/images/edits',http_transport=httpx.MockTransport(handler))
    brief={'kind':'cat','features':['保留旧月纹','新增尾部叶芽'],'summary':'PRIVATE_SUMMARY','name':'PRIVATE_PET_NAME'}
    assert asyncio.run(transport.generate(brief,[atlas(),atlas()])).startswith(b'\x89PNG')
    assert len(requests)==1


def test_reference_edit_configuration_is_required_before_any_post():
    from cove_pet_nest.images.transport import ImageTransport
    transport=ImageTransport('https://images.example.test/v1/images/generations','demo','fake-key')
    assert transport.can_reference is False
    with pytest.raises(ValueError,match='needs_image_edit_configuration'):
        asyncio.run(transport.generate({'kind':'cat'},[atlas()]))


def test_photo_prompt_uses_one_scene_and_never_sends_source_ids():
    from cove_pet_nest.images.transport import ImageTransport
    def handler(request):
        assert b'one single scene' in request.content and b'no grid' in request.content
        assert b'PRIVATE_SOURCE_ID' not in request.content
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(atlas()).decode()}]})
    transport=ImageTransport('https://images.example.test/generate','demo','fake-key',
        edit_endpoint='https://images.example.test/edit',http_transport=httpx.MockTransport(handler))
    asyncio.run(transport.generate({'purpose':'photo','event_kind':'reading','source_id':'PRIVATE_SOURCE_ID',
        'participants':[{'kind':'cat'}]},[atlas()]))
