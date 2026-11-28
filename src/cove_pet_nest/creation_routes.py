from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import Field, StrictBool

from .contracts import StrictModel
from .creation_setup import SettingsPatch, offline_diagnostic, public_settings, save_creation_settings


class Trial(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    confirmed: Literal[True]


class RetryJob(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    acknowledge_unknown: StrictBool = False


def router(service, browser):
    routes = APIRouter()
    local = APIRouter(prefix='/api/creation', dependencies=[Depends(browser)])
    web = Path(__file__).parent/'web'

    @routes.get('/creation')
    def setup_page():
        return FileResponse(web/'creation.html')

    @routes.get('/creation/guide')
    def guide():
        return FileResponse(web/'creation-guide.md',media_type='text/plain; charset=utf-8')

    @local.get('/settings')
    def settings():
        return public_settings(service)

    @local.post('/settings')
    def save(body: SettingsPatch):
        return save_creation_settings(service, body)

    @local.post('/diagnostic')
    def diagnose():
        return offline_diagnostic(service)

    @local.post('/trial')
    async def trial(body: Trial):
        return await service.creation.trial(body.request_id)

    @local.get('/jobs')
    def jobs():
        return service.creation.status()

    @local.post('/jobs/{job_id}/retry')
    def retry(job_id: str,body: RetryJob):
        return service.creation.retry(job_id,body.request_id,body.acknowledge_unknown)

    routes.include_router(local)
    return routes
