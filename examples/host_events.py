"""One synthetic completed-chat event; run only against a new test instance."""
import os
import time
import httpx


def submit(base_url,host_token,*,completed_at=None,client=None):
    payload={'source_id':'demo-app','conversation_id':'demo-chat','user_turn_id':'demo-turn-1','reply_id':'demo-reply-1',
             'completed_at':completed_at if completed_at is not None else time.time(),'new_user_utf8_bytes':300,
             'final_visible_reply_utf8_bytes':600,'usage':{'input_tokens':9000,'output_tokens':200}}
    response=(client or httpx).post(base_url+'/api/integration/usage',headers={'Authorization':'Bearer '+host_token},json=payload)
    response.raise_for_status()
    return response.json()


if __name__=='__main__':
    # Run once; for network retries persist and reuse the entire event, including its timestamp.
    print(submit(os.environ.get('PET_NEST_URL','http://127.0.0.1:8767'),os.environ['PET_NEST_HOST_TOKEN']))
