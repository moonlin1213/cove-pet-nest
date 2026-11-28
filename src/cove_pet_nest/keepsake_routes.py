from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import Field, StrictBool

from .contracts import StrictModel
from .keepsakes import Collection


class ToyUpdate(StrictModel):
    form: int | None = Field(default=None, ge=0, le=3, strict=True)
    placed: StrictBool | None = None
    x: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class Play(StrictModel):
    pet_id: str = Field(min_length=1,max_length=128)
    request_id: str = Field(min_length=1,max_length=128)


class NoteFlags(StrictModel):
    is_read: StrictBool | None = None
    favorite: StrictBool | None = None


class Decor(StrictModel):
    kind: Literal['hide','stone','fern','toy']
    toy_id: str | None = Field(default=None,max_length=128)
    x: float = Field(ge=0,le=1,allow_inf_nan=False)
    y: float = Field(ge=0,le=1,allow_inf_nan=False)
    scale: float = Field(ge=.5,le=1.5,allow_inf_nan=False)


class Layout(StrictModel):
    theme: Literal['warm_stone','moss_forest']
    decor: list[Decor] = Field(max_length=20)
    revision: int = Field(ge=0,strict=True)


def collection_router(store, browser):
    collection = Collection(store)
    routes = APIRouter(prefix='/api', dependencies=[Depends(browser)])

    @routes.get('/keepsakes')
    def contents():
        return collection.contents()

    @routes.patch('/toys/{toy}')
    def change_toy(toy:str, body:ToyUpdate):
        return collection.change_toy(toy,body.model_dump(exclude_none=True))

    @routes.post('/toys/{toy}/play')
    def play(toy:str, body:Play):
        return collection.play(toy,body.pet_id,body.request_id)

    @routes.patch('/notes/{note}')
    def flag_note(note:str, body:NoteFlags):
        return collection.flag_note(note,body.model_dump(exclude_none=True))

    @routes.get('/habitats/{pet}')
    def habitat(pet:str):
        return collection.habitat(pet)

    @routes.put('/habitats/{pet}')
    def save_habitat(pet:str, body:Layout):
        return collection.save_habitat(pet, **body.model_dump(exclude_none=True))

    return routes
