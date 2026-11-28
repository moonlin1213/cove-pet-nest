"""Household-local creation settings. Provider secrets stay outside the pet database."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from pydantic import Field, StrictBool, StrictInt

from .contracts import RelationshipEvent, StrictModel
from .images.transport import endpoint_url
from .relationships import record_relationship
from .store import NestError, PetStore

CONFIG_NAME = 'creation-settings.json'
DEFAULT_TEXT_LIMIT = 3


@dataclass(frozen=True)
class Provider:
    endpoint: str = ''
    model: str = ''
    key: str = field(default='', repr=False)
    source: str = 'missing'

    @property
    def ready(self):
        return bool(self.endpoint and self.model and self.key)

    def status(self):
        return {'ready': self.ready, 'source': self.source}


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


def _provider(name, raw):
    if name in raw:
        return Provider(**raw[name], source='household')
    prefix = 'PET_NEST_' + name.upper() + '_'
    values = [os.environ.get(prefix+field_name, '') for field_name in ('ENDPOINT','MODEL','KEY')]
    return Provider(*values, source='environment' if any(values) else 'missing')


def load_creation_settings(data_dir):
    raw = _read(data_dir)
    return CreationSettings(raw.get('notes_enabled',False), raw.get('toys_enabled',False),
                            raw.get('daily_text_limit', DEFAULT_TEXT_LIMIT),
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
                if any(not v or any(ord(c)<32 or ord(c)==127 for c in v) for v in values.values()):
                    raise NestError('invalid_provider')
                try:
                    endpoint_url(values['endpoint'])
                    values['key'].encode('ascii')
                except (ValueError, UnicodeError):
                    raise NestError('invalid_provider') from None
                raw[name] = values
        for name in ('notes_enabled', 'toys_enabled', 'daily_text_limit'):
            value = getattr(patch, name)
            if value is not None:
                raw[name] = value
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
    return {'notes_enabled':cfg.notes_enabled,'toys_enabled':cfg.toys_enabled,
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
