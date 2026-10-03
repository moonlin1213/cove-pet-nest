import pytest
from test_store import make_store


def event(**changes):
    from cove_pet_nest.contracts import UsageEvent
    values = dict(source_id='demo', conversation_id='chat1', user_turn_id='u1', reply_id='r1',
                  completed_at=1_800_000_000.0, new_user_utf8_bytes=300, final_visible_reply_utf8_bytes=600,
                  usage={'input_tokens':9000,'output_tokens':200})
    values.update(changes)
    return UsageEvent(**values)


def test_visible_contribution_and_provider_fields():
    from cove_pet_nest.usage import normalize_usage
    assert normalize_usage(event())['contribution_tokens'] == 300
    for meta in ({'prompt_tokens':9000,'completion_tokens':200},
                 {'promptTokenCount':9000,'candidatesTokenCount':200},
                 {'input_tokens':1,'cache_read_input_tokens':99,'output_tokens':200}):
        assert normalize_usage(event(usage=meta))['contribution_tokens'] == 300
    assert normalize_usage(event(usage={'total_tokens':10000}))['contribution_tokens'] == 0
    assert normalize_usage(event(usage={'output_tokens':20}))['contribution_tokens'] == 20
    for bad in ({'output_tokens':True}, {'input_tokens':-1}, {'secret':'x'}, {'input_tokens':float('nan')}):
        with pytest.raises(ValueError):
            event(usage=bad)


def test_grain_steps(tmp_path):
    from cove_pet_nest.ledger import record_usage
    s = make_store(tmp_path)
    s.adopt('cat','团团','cat',actor='user')
    def add(turn,n):
        return record_usage(s,event(user_turn_id=str(turn),reply_id=str(turn),new_user_utf8_bytes=n*3,
                                   final_visible_reply_utf8_bytes=0,usage={'input_tokens':n}))
    r = add(1,150)
    assert r['token_grains'] == 0 and r['baseline_grains'] == 3
    assert add(2,50)['token_grains'] == 1
    assert add(3,3800)['token_grains'] == 19
    assert add(4,800)['token_grains'] == 1
    assert add(5,15200)['token_grains'] == 19
    assert add(6,10000)['token_grains'] == 0
    assert s.state()['grains'] == 79


def test_revision_replay_and_cross_day(tmp_path):
    from cove_pet_nest.ledger import record_usage
    from cove_pet_nest.store import NestError
    s = make_store(tmp_path)
    s.adopt('cat','团团','cat',actor='user')
    assert record_usage(s,event())['credited_grains'] == 4
    assert record_usage(s,event())['credited_grains'] == 0
    r = record_usage(s,event(reply_id='r2',source_kind='regenerate',completed_at=1_800_086_400.0,
                            new_user_utf8_bytes=600))
    assert r['token_grains'] == 1 and r['baseline_grains'] == 0
    assert s.state()['grains'] == 41
    with pytest.raises(NestError,match='conflict'):
        record_usage(s,event(final_visible_reply_utf8_bytes=800))
    record_usage(s,event(reply_id='r2',revision=2,new_user_utf8_bytes=900))
    assert record_usage(s,event(reply_id='r2',revision=1,new_user_utf8_bytes=800))['credited_grains'] == 0
    assert record_usage(s,event(source_id='other'))['token_grains'] == 2


def test_ineligible_and_missing_usage(tmp_path):
    from cove_pet_nest.ledger import record_usage
    s = make_store(tmp_path)
    s.adopt('cat','团团','cat',actor='user')
    assert record_usage(s,event(has_error=True))['credited_grains'] == 0
    assert record_usage(s,event(usage={}))['credited_grains'] == 3
    assert record_usage(s,event(revision=1))['token_grains'] == 1
    with pytest.raises(ValueError):
        event(source_kind='background')
    with pytest.raises(ValueError):
        event(user_text='private text')


def test_concurrent_event_is_credited_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from cove_pet_nest.ledger import record_usage
    s = make_store(tmp_path)
    s.adopt('cat','团团','cat',actor='user')
    with ThreadPoolExecutor(4) as pool:
        results=list(pool.map(lambda _: record_usage(s,event()),range(8)))
    assert sum(r['credited_grains'] for r in results) == 4
