"""Separate browser and host credentials, created only in the local data directory."""
import hashlib
import hmac
import json
import secrets
import time


def credentials(settings):
    settings.data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=settings.data_dir/'credentials.json'
    if not path.exists():
        values={k:secrets.token_urlsafe(32) for k in ('browser_token','host_token','session_key')}
        try:
            fd=__import__('os').open(path,__import__('os').O_CREAT|__import__('os').O_EXCL|__import__('os').O_WRONLY,0o600)
            with __import__('os').fdopen(fd,'w') as out:
                json.dump(values,out)
        except FileExistsError:
            pass
    return json.loads(path.read_text())


def bearer(request,token):
    return secrets.compare_digest(request.headers.get('authorization',''), 'Bearer '+token)


def session_value(key):
    expiry=str(int(time.time()+12*3600))
    return expiry+'.'+hmac.new(key.encode(),expiry.encode(),hashlib.sha256).hexdigest()


def valid_session(value,key):
    try:
        expiry,signature=value.split('.',1)
        return int(expiry)>time.time() and hmac.compare_digest(signature,hmac.new(key.encode(),expiry.encode(),hashlib.sha256).hexdigest())
    except (ValueError,TypeError,AttributeError):
        return False
