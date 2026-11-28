"""Household-local creation settings. Provider secrets stay outside the pet database."""
from dataclasses import dataclass, field
import json
import ipaddress
from urllib.parse import urlsplit
import os
import random
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from pydantic import Field, StrictBool, StrictInt

from .contracts import RelationshipEvent, StrictModel
from .creation_worker import note_source, toy_source
from .images.transport import endpoint_url
from .relationships import record_relationship
from .store import NestError, PetStore
from .windows_secrets import protect_key, unprotect_key

WINDOWS = os.name == 'nt'
CONFIG_NAME = 'creation-settings.json'
DEFAULT_TEXT_LIMIT = 3


@dataclass(frozen=True)
class Provider:
    endpoint: str = ''
    model: str = ''
    key: str = field(default='', repr=False)
    source: str = 'missing'
    invalid: bool = False

    @property
    def ready(self):
        return bool(self.endpoint and self.model and self.key)

    def status(self):
        result = {'ready': self.ready, 'source': self.source}
        if self.invalid:
            result['invalid'] = True
        return result


@dataclass(frozen=True)
class CreationSettings:
    notes_enabled: bool
    toys_enabled: bool
    daily_text_limit: int
    text: Provider
    image: Provider


class ProviderInput(StrictModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    key: str = Field(min_length=1, max_length=4096, repr=False)


class SettingsPatch(StrictModel):
    text: ProviderInput | None = None
    image: ProviderInput | None = None
    reset_text: StrictBool = False
    reset_image: StrictBool = False
    notes_enabled: StrictBool | None = None
    toys_enabled: StrictBool | None = None
    daily_text_limit: StrictInt | None = Field(None, ge=0, le=100)


def _read(data_dir):
    try:
        values = (Path(data_dir)/CONFIG_NAME).read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}
    try:
        document = json.loads(values)
        if not isinstance(document, dict):
            raise ValueError()
        return document
    except (TypeError, ValueError):
        raise NestError('invalid_creation_settings', 409) from None


def _checked_provider(values, source):
    endpoint, model, key = (values.get(k, '') for k in ('endpoint','model','key'))
    if not all(isinstance(v, str) for v in (endpoint, model, key)):
        raise ValueError('invalid provider fields')
    if any(ord(c) < 32 or ord(c) == 127 for v in (endpoint, model, key) for c in v):
        raise ValueError('invalid provider fields')
    if endpoint:
        parsed = urlsplit(endpoint_url(endpoint))
        if '\\' in endpoint or any(c.isspace() for c in endpoint) or parsed.port == 0 or parsed.username is not None:
            raise ValueError('invalid provider address')
        if parsed.scheme == 'http' and parsed.hostname != 'localhost':
            if not ipaddress.ip_address(parsed.hostname).is_loopback:
                raise ValueError('plain HTTP requires loopback')
    if any(v != v.strip() for v in (model, key)):
        raise ValueError('invalid provider fields')
    key.encode('ascii')
    return Provider(endpoint, model, key, source)


def _provider(name, raw):
    source = 'household' if name in raw else 'environment'
    try:
        if name in raw:
            values = raw[name]
            if not isinstance(values, dict):
                raise ValueError('invalid provider fields')
            if WINDOWS or 'account_protected' in values:
                values = json.loads(unprotect_key(values['account_protected']))
                if not isinstance(values, dict):
                    raise ValueError('invalid provider fields')
        else:
            prefix = 'PET_NEST_' + name.upper() + '_'
            values = {k:os.environ.get(prefix+k.upper(),'') for k in ('endpoint','model','key')}
            if not any(values.values()):
                return Provider()
        return _checked_provider(values, source)
    except (OSError, TypeError, ValueError, KeyError):
        return Provider(source=source, invalid=True)


def load_creation_settings(data_dir):
    raw = _read(data_dir)
    limit = raw.get('daily_text_limit', DEFAULT_TEXT_LIMIT)
    if type(limit) is not int or not 0 <= limit <= 100:
        limit = 0
    return CreationSettings(raw.get('notes_enabled') is True, raw.get('toys_enabled') is True, limit,
                            _provider('text',raw), _provider('image',raw))


def save_creation_settings(service, patch):
    folder = service.settings.data_dir
    # Serialize read-modify-write even for two independent room processes.
    with service.store.write():
        raw = _read(folder)
        for name in ('text', 'image'):
            provider = getattr(patch, name)
            reset = getattr(patch, 'reset_'+name)
            if provider and reset:
                raise NestError('invalid_provider_update')
            if reset:
                raw.pop(name,None)
            if provider:
                values = {k:v.strip() for k,v in provider.model_dump().items()}
                try:
                    checked = _checked_provider(values, 'household')
                    if not checked.ready:
                        raise ValueError('incomplete provider')
                except ValueError:
                    raise NestError('invalid_provider') from None
                if WINDOWS:
                    try:
                        # Bind the destination to its credential in the same protected envelope.
                        raw[name] = {'account_protected':protect_key(json.dumps(values))}
                    except OSError:
                        raise NestError('creation_secret_storage_failed', 503) from None
                else:
                    raw[name] = values
        for name in ('notes_enabled', 'toys_enabled', 'daily_text_limit'):
            value = getattr(patch, name)
            if value is not None:
                raw[name] = value
        if WINDOWS:
            for kind in ('text', 'image'):
                if kind in raw and (not isinstance(raw[kind], dict) or set(raw[kind]) != {'account_protected'}):
                    raise NestError('reenter_provider_after_move', 409)
        with NamedTemporaryFile('w', encoding='utf-8', dir=folder, delete=False) as out:
            temporary = Path(out.name)
            try:
                json.dump(raw, out, ensure_ascii=False)
                out.flush()
                os.fsync(out.fileno())
            except BaseException:
                out.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary,folder/CONFIG_NAME)
        finally:
            temporary.unlink(missing_ok=True)
    return public_settings(service)


def public_settings(service):
    cfg = load_creation_settings(service.settings.data_dir)
    with service.store.connect() as db:
        has_relationships = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='relationships'"
        ).fetchone()
        relationship = bool(has_relationships and db.execute('SELECT 1 FROM relationships LIMIT 1').fetchone())
        care = bool(db.execute('SELECT 1 FROM care_events LIMIT 1').fetchone())
        life = bool(db.execute("SELECT 1 FROM life_events WHERE kind NOT LIKE 'care_%' LIMIT 1").fetchone())
        # Use the same windows and source filters as the worker, without touching
        # its random stream, schedules, claims or daily quota.
        now = service.store.now()
        probe = random.Random(0)
        toy_material = cfg.toys_enabled and bool(toy_source(db, now, probe))
        note_material = False
        if cfg.notes_enabled:
            pets = db.execute("SELECT id,created_at FROM pets WHERE status='ready' AND (kind!='egg' OR stage>0)")
            note_material = any(note_source(db, now, pet, probe) for pet in pets)

    def readiness(enabled, has_material, *, image_required=False):
        if not enabled:
            return 'off'
        if not cfg.text.ready:
            return 'invalid_text' if cfg.text.invalid else 'needs_text'
        if image_required and not cfg.image.ready:
            return 'invalid_image' if cfg.image.invalid else 'needs_image'
        if not cfg.daily_text_limit:
            return 'text_limit_zero'
        if not has_material:
            return 'needs_shared_interaction' if image_required else 'needs_interaction'
        return 'waiting_opportunity'

    feature_status = {'notes':readiness(cfg.notes_enabled, note_material),
                      'toys':readiness(cfg.toys_enabled, toy_material, image_required=True)}
    return {'feature_status':feature_status,'notes_enabled':cfg.notes_enabled,'toys_enabled':cfg.toys_enabled,
            'daily_text_limit':cfg.daily_text_limit,'text':cfg.text.status(),'image':cfg.image.status(),
            'sources':{'relationship':relationship,'care':care,'life':life}}


def offline_diagnostic(service):
    # Exercise the same event writer and reload path using an isolated fictional household.
    with TemporaryDirectory(prefix='nest-diagnostic-') as directory:
        path = Path(directory)/'pets.sqlite3'
        store = PetStore(path)
        event = RelationshipEvent(event_id='diagnostic-reading', occurred_at=store.now(),
                                  summary='虚构测试：两位读者一起读了一本关于纸船的书。', signals={'reading':1})
        stored = record_relationship(store,event)['recorded']
        reopened = PetStore(path)
        deduplicated = not record_relationship(reopened,event)['recorded']
    return {'stored':stored,'deduplicated':deduplicated,'isolated':True,'settings':public_settings(service)}
