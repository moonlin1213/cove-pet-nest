from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
import math

UsageCount = int
USAGE_KEYS = {'input_tokens','output_tokens','prompt_tokens','completion_tokens','total_tokens',
              'cache_read_input_tokens','cache_creation_input_tokens','cached_tokens','reasoning_tokens',
              'thinking_tokens','promptTokenCount','candidatesTokenCount','totalTokenCount'}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class UsageEvent(StrictModel):
    source_id: str = Field(min_length=1,max_length=128)
    conversation_id: str = Field(min_length=1,max_length=128)
    user_turn_id: str = Field(min_length=1,max_length=128)
    reply_id: str = Field(min_length=1,max_length=128)
    completed_at: float = Field(ge=0,allow_inf_nan=False)
    source_kind: Literal['chat','shared_chat','regenerate','edit'] = 'chat'
    has_error: bool = False
    revision: StrictInt = Field(default=0,ge=0,le=1_000_000_000)
    new_user_utf8_bytes: StrictInt = Field(ge=0,le=1_000_000_000)
    final_visible_reply_utf8_bytes: StrictInt = Field(ge=0,le=1_000_000_000)
    usage: dict = Field(default_factory=dict)

    @field_validator('usage')
    @classmethod
    def counters(cls, value):
        for key,n in value.items():
            if key not in USAGE_KEYS or type(n) is not int or not 0<=n<=1_000_000_000:
                raise ValueError('Only non-negative provider counters are accepted')
        return value


class RelationshipEvent(StrictModel):
    event_id: str = Field(min_length=1,max_length=128)
    occurred_at: float = Field(ge=0,allow_inf_nan=False)
    summary: str = Field(default='',max_length=600)
    signals: dict[str,float] = Field(default_factory=dict)

    @field_validator('signals',mode='before')
    @classmethod
    def bounded_signals(cls,value):
        if not isinstance(value,dict):
            raise ValueError('Invalid signals')
        for key,n in value.items():
            if key not in ('affection','reading','watching','listening','exploration') or type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=3:
                raise ValueError('Invalid bounded signal')
        return value


class Adoption(StrictModel):
    kind: Literal['cat','dog','parrot','snow_leopard','snake','lizard','egg']
    name: str = Field(min_length=1,max_length=32)
    request_id: str = Field(min_length=1,max_length=128)


class Care(StrictModel):
    action: Literal['feed','play','comfort']
    request_id: str = Field(min_length=1,max_length=128)
    pet_ids: list[str] | None = Field(default=None,max_length=500)
    scope: Literal['selected','all'] = 'selected'


class Retry(StrictModel):
    request_id: str = Field(min_length=1,max_length=128)
    acknowledge_unknown: bool = False
