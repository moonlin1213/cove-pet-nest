import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from .store import NestError


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_backup(store,destination:Path):
    destination=Path(destination)
    destination.mkdir(mode=0o700,parents=True,exist_ok=False)
    db_path=destination/'pets.sqlite3'
    with store.connect() as source,sqlite3.connect(db_path) as target:
        source.backup(target)
    db_path.chmod(0o600)
    with sqlite3.connect(db_path) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise NestError('backup_database_invalid')
        refs={r[0] for r in db.execute('SELECT asset_ref FROM pets WHERE asset_ref IS NOT NULL')}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='image_jobs'").fetchone():
            refs.update(r[0] for r in db.execute('SELECT asset_ref FROM image_jobs WHERE asset_ref IS NOT NULL'))
    files={'pets.sqlite3':digest(db_path)}
    for ref in refs:
        if not re.fullmatch(r'[a-f0-9]{64}\.webp',ref):
            raise NestError('backup_asset_invalid')
        src=store.path.parent/'assets'/ref
        if not src.is_file() or src.is_symlink():
            raise NestError('backup_asset_missing')
        (destination/'assets').mkdir(exist_ok=True,mode=0o700)
        target=destination/'assets'/ref
        shutil.copyfile(src,target);target.chmod(0o600)
        files['assets/'+ref]=digest(target)
    manifest=destination/'manifest.json'
    manifest.write_text(json.dumps({'version':1,'files':files},indent=2));manifest.chmod(0o600)
    return {'files':len(files),'database_sha256':files['pets.sqlite3']}


def restore_backup(source:Path,new_data_dir:Path):
    source,new_data_dir=Path(source),Path(new_data_dir)
    if new_data_dir.exists():
        raise NestError('restore_destination_exists')
    files=json.loads((source/'manifest.json').read_text())['files']
    if 'pets.sqlite3' not in files:
        raise NestError('backup_manifest_invalid')
    for name,expected in files.items():
        if name!='pets.sqlite3' and not re.fullmatch(r'assets/[a-f0-9]{64}\.webp',name):
            raise NestError('backup_manifest_invalid')
        path=source/name
        if path.is_symlink() or not path.is_file() or digest(path)!=expected:
            raise NestError('backup_hash_mismatch')
    with sqlite3.connect(f'file:{source / "pets.sqlite3"}?mode=ro',uri=True) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise NestError('backup_database_invalid')
    new_data_dir.mkdir(mode=0o700,parents=True)
    for name in files:
        target=new_data_dir/name;target.parent.mkdir(exist_ok=True,mode=0o700)
        shutil.copyfile(source/name,target);target.chmod(0o600)
    return {'restored_files':len(files)}
