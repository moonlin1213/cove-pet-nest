import importlib.util
from pathlib import Path
from test_http import client_for,login


def test_example_event_can_be_retried_without_extra_food(tmp_path):
    spec=importlib.util.spec_from_file_location('host_events',Path(__file__).parents[1]/'examples/host_events.py')
    example=importlib.util.module_from_spec(spec);spec.loader.exec_module(example)
    c,creds=client_for(tmp_path);login(c,creds)
    c.post('/api/adoptions',json={'kind':'cat','name':'团团','request_id':'cat'})
    import time
    stamp=time.time()
    first=example.submit('http://127.0.0.1:8767',creds['host_token'],completed_at=stamp,client=c)
    second=example.submit('http://127.0.0.1:8767',creds['host_token'],completed_at=stamp,client=c)
    assert first['credited_grains']==4 and second['credited_grains']==0
    assert c.get('/api/nest').json()['grains']==40
