from test_http import client_for,login


def test_room_and_starter_images_are_self_contained(tmp_path):
    c,creds=client_for(tmp_path)
    r=c.get('/')
    assert r.status_code==200
    assert '我们的小窝' in r.text
    assert '成长相册' not in r.text and '音乐日记' not in r.text
    for path in ('/static/nest.js','/static/nest.css','/starter/room-light.webp','/starter/cat-sprites-light.webp','/starter/dog-sprites-light.webp','/starter/egg-sprites-light.webp'):
        assert c.get(path).status_code==200
    login(c,creds)
    for kind in ('cat','dog','egg','parrot'):
        assert c.post('/api/adoptions',json={'kind':kind,'name':'宝宝','request_id':kind}).status_code==200
    assert c.get('/api/nest').json()['total']==4
