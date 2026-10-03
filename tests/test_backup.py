import hashlib
import sqlite3
import pytest
from test_store import make_store


def test_backup_and_restore_without_credentials(tmp_path):
    from cove_pet_nest.backup import create_backup,restore_backup
    s=make_store(tmp_path/'source')
    pet=s.adopt('cat','团团','a',actor='user')['pet']
    s.care('feed','f',actor='assistant',pet_ids=[pet['id']])
    (s.path.parent/'credentials.json').write_text('PRIVATE_FAKE_CREDENTIAL')
    backup=tmp_path/'recovery'; create_backup(s,backup)
    assert not (backup/'credentials.json').exists()
    with sqlite3.connect(backup/'pets.sqlite3') as db:
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    restored=tmp_path/'restored'; restore_backup(backup,restored)
    r=make_store(restored)
    assert r.state()['grains']==35
    assert r.care('feed','f',actor='assistant',pet_ids=[pet['id']])['results'][0]['status']=='fed'
    assert r.state()['grains']==35
    with pytest.raises(ValueError):
        restore_backup(backup,restored)
    (backup/'pets.sqlite3').write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        restore_backup(backup,tmp_path/'bad-restore')


def test_backup_preserves_imported_assets(tmp_path):
    from cove_pet_nest.backup import create_backup,restore_backup
    from cove_pet_nest.images.service import ImageJobService
    from test_hatch import atlas
    s=make_store(tmp_path/'source')
    pet=s.adopt('parrot','小绿','p',actor='user')['pet']
    jobs=ImageJobService(s,s.path.parent/'assets',None)
    imported=jobs.import_asset(pet['id'],atlas(),'import-1')
    create_backup(s,tmp_path/'backup')
    restore_backup(tmp_path/'backup',tmp_path/'new')
    assert (tmp_path/'new/assets'/imported['asset_ref']).is_file()
