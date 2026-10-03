"""Conservative newly visible contribution, never total provider billing."""
from .contracts import UsageEvent


def normalize_usage(event: UsageEvent) -> dict:
    u = event.usage
    if 'input_tokens' in u:
        inp = u['input_tokens'] + u.get('cache_read_input_tokens',0) + u.get('cache_creation_input_tokens',0)
    else:
        inp = u.get('prompt_tokens',u.get('promptTokenCount',0))
    out = u.get('output_tokens',u.get('completion_tokens',u.get('candidatesTokenCount',0)))
    return {'contribution_tokens': min((event.new_user_utf8_bytes+2)//3,inp) + min((event.final_visible_reply_utf8_bytes+2)//3,out),
            'measurement':'bounded_visible_estimate_v1'}
