from pathlib import Path
import importlib.util
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
def updater():
    spec=importlib.util.spec_from_file_location('updater',ROOT/'scripts/update/start.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_prefers_existing_project_room_without_creating_an_empty_one(tmp_path):
    repo=tmp_path/'project'
    data=repo/'data'
    data.mkdir(parents=True)
    with sqlite3.connect(data/'pets.sqlite3') as db:
        db.execute('CREATE TABLE pets(id TEXT)')
    assert updater().existing_room(data)
    assert not updater().existing_room(tmp_path/'elsewhere')
    assert not (tmp_path/'elsewhere').exists()

def test_updater_refuses_wrong_artifact(tmp_path):
    import pytest
    wheel=tmp_path/f'cove_pet_nest-{updater().VERSION}-py3-none-any.whl'
    wheel.write_bytes(b'changed download')
    (tmp_path/'SHA256.txt').write_text('0'*64+'  '+wheel.name+'\n')
    with pytest.raises(ValueError):updater().verified_wheel(tmp_path)


def test_project_and_direct_venv_choices_find_the_same_python(tmp_path):
    import os
    room=tmp_path/'我的小屋'
    venv=room/'.venv'
    python=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    python.parent.mkdir(parents=True)
    python.touch()
    (venv/'pyvenv.cfg').touch()
    module=updater()
    assert module.existing_environment(room)==python
    assert module.existing_environment(venv)==python


def test_original_port_is_kept_and_key_never_part_of_destination(tmp_path):
    (tmp_path/'browser-url.txt').write_text('http://localhost:18767/#key=fixture')
    assert updater().saved_port(tmp_path)==18767
    (tmp_path/'browser-url.txt').write_text('https://example.test:10443/#key=fixture')
    assert updater().saved_port(tmp_path)==8767


def test_cancel_with_a_running_room_never_changes_the_environment(tmp_path,monkeypatch):
    import pytest
    module=updater()
    monkeypatch.setattr(module,'occupied',lambda port:True)
    def cancel(action,message):
        assert action=='confirm'
        assert '请先' in message
        raise module.Cancelled()
    monkeypatch.setattr(module,'dialog',cancel)
    monkeypatch.setattr(module,'install',lambda *args:pytest.fail('changed an active installation'))
    with pytest.raises(module.Cancelled):module.run_room(tmp_path,tmp_path)


def test_missing_credentials_requires_reselecting_existing_data(tmp_path,monkeypatch):
    invalid=tmp_path/'invalid'
    valid=tmp_path/'valid'
    for path in (valid,invalid):
        path.mkdir()
        with sqlite3.connect(path/'pets.sqlite3') as db:
            db.execute('create table pets(id text)')
    (valid/'credentials.json').write_text('{}')
    module=updater()
    choices=iter([invalid,valid])
    notices=[]
    def choose(action,message,initial=None):
        if action=='choose':return next(choices)
        notices.append(message)
    monkeypatch.setattr(module,'dialog',choose)
    assert module.select_data(tmp_path)==valid
    assert len(notices)==1
    assert not (invalid/'credentials.json').exists()

def test_v01_backup_must_match_manifest_before_upgrade(tmp_path):
    import hashlib,json,pytest
    snapshot=tmp_path/'copy'
    snapshot.mkdir()
    dbfile=snapshot/'pets.sqlite3'
    with sqlite3.connect(dbfile) as db:
        db.execute('CREATE TABLE pets(id TEXT)')
    (snapshot/'manifest.json').write_text(json.dumps({'files':{'pets.sqlite3':hashlib.sha256(dbfile.read_bytes()).hexdigest()}}))
    updater().verify_snapshot(snapshot)
    dbfile.write_bytes(b'corrupt')
    with pytest.raises(ValueError):updater().verify_snapshot(snapshot)
