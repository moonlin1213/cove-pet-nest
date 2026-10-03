import importlib.util
from pathlib import Path
from io import BytesIO
from PIL import Image


def checker():
    spec=importlib.util.spec_from_file_location('check_release',Path(__file__).parents[1]/'scripts/check_release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_release_rejects_runtime_data_and_secrets_without_echo():
    scan=checker().scan_entry
    fake='sk-'+'X'*40
    path='/'+'Users'+'/'+'example'+'/private'
    assert scan('src/example.py',('API_KEY="'+fake+'"').encode())
    assert scan('src/example.py',path.encode())
    assert scan('data/pets.sqlite3',b'database')
    assert scan('credentials.json',b'{}')
    assert scan('debug.log',b'private text')
    assert fake not in str(scan('src/example.py',fake.encode()))
    assert path not in str(scan('src/example.py',path.encode()))
    assert scan('examples/demo.json','{"summary":"虚构示例：一起读书。"}'.encode())==[]


def test_release_rejects_image_metadata():
    scan=checker().scan_entry
    image=Image.new('RGB',(10,10),'white')
    exif=Image.Exif(); exif[315]='Synthetic metadata for rejection test'
    stream=BytesIO(); image.save(stream,format='JPEG',exif=exif)
    assert scan('assets/example.jpg',stream.getvalue())


def test_release_rejects_quoted_json_credentials():
    import json
    scan=checker().scan_entry
    for key in ('host_token','browser_token','session_key','api_key'):
        fake='Z'*43
        result=scan('examples/config.json',json.dumps({key:fake}).encode())
        assert 'credential_literal' in result
        assert fake not in str(result)
