from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest


def make_store(tmp_path):
    from cove_pet_nest.store import PetStore
    return PetStore(tmp_path / 'pets.sqlite3', timezone='Asia/Shanghai', clock=lambda: 1_800_000_000.0)


def test_fresh_store_and_restart(tmp_path):
    s = make_store(tmp_path)
    assert s.state()['pets'] == []
    first = s.adopt('cat', '团团', 'adopt-1', actor='user')
    assert s.state()['grains'] == 36
    assert first == s.adopt('cat', '团团', 'adopt-1', actor='user')
    assert make_store(tmp_path).state()['pets'][0]['id'] == first['pet']['id']
    for kind in ('dog', 'parrot', 'snow_leopard', 'snake', 'lizard', 'egg'):
        pet = s.adopt(kind, '宝宝', kind, actor='user')['pet']
        assert pet['status'] in ('ready', 'pending')
    assert s.state()['total'] == 7
    assert s.state()['grains'] == 36


def test_last_grain_and_actor(tmp_path):
    s = make_store(tmp_path)
    ids = [s.adopt('cat', f'宝宝{i}', str(i), actor='user')['pet']['id'] for i in range(2)]
    with sqlite3.connect(s.path) as db:
        db.execute('UPDATE household SET grains=1')
    def feed(i):
        return s.care('feed', f'feed{i}', actor='assistant', pet_ids=[ids[i]])
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(feed, (0, 1)))
    assert sorted(r['results'][0]['status'] for r in results) == ['fed', 'no_food']
    assert s.state()['grains'] == 0
    fed = next(r for r in results if r['results'][0]['status'] == 'fed')
    pet_id = fed['results'][0]['pet_id']
    i = ids.index(pet_id)
    assert feed(i) == fed
    assert s.care('feed', 'full', actor='user', pet_ids=[pet_id])['results'][0]['status'] == 'full'
    assert s.state()['events'][0]['actor'] == 'assistant'
    assert s.care('comfort', 'hug', actor='user', pet_ids=[pet_id])['results'][0]['status'] == 'comforted'
    assert s.state()['events'][0]['actor'] == 'user'


def test_conflict_validation_and_pending(tmp_path):
    s = make_store(tmp_path)
    from cove_pet_nest.store import NestError
    s.adopt('cat', '团团', 'same', actor='user')
    with pytest.raises(NestError, match='conflict'):
        s.adopt('dog', '团团', 'same', actor='user')
    with pytest.raises(NestError):
        s.adopt('cat', '<script>', 'x', actor='intruder')
    with pytest.raises(NestError):
        s.care('feed', 'x', actor='user', pet_ids=[])
    pet = s.adopt('snake', '小绿', 'pending', actor='user')['pet']
    assert pet['status'] == 'pending'
    assert s.care('feed', 'feed-pending', actor='user', pet_ids=[pet['id']])['results'][0]['status'] == 'pending'


def test_no_source_configuration_access(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = make_store(tmp_path)
    assert s.path.parent == tmp_path
    assert s.state()['total'] == 0
    import sys
    assert 'config' not in sys.modules
