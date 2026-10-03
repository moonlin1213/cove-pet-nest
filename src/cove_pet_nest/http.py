import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import Depends,FastAPI,HTTPException,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from .auth import bearer,credentials,session_value,valid_session
from .contracts import Adoption,Care,UsageEvent,RelationshipEvent,Retry
from .ledger import record_usage
from .relationships import record_relationship
from .store import NestError


def create_app(service):
    creds=credentials(service.settings)
    async def worker():
        while True:
            await service.tick()
            await asyncio.sleep(5)

    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(worker())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def boundaries(request,call_next):
        host=request.headers.get('host','')
        parsed=urlsplit('http://'+host)
        if parsed.hostname not in ('127.0.0.1','localhost','::1'):
            return JSONResponse({'error':'invalid_host'},403)
        origin=request.headers.get('origin')
        if origin and origin!=str(request.base_url).rstrip('/'):
            return JSONResponse({'error':'invalid_origin'},403)
        if request.method not in ('GET','HEAD'):
            limit=16*1024*1024 if request.url.path.startswith('/api/integration/assets/') else 65536
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>limit:
                    return JSONResponse({'error':'request_too_large'},413)
            request._body=bytes(body)
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                                 'Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.exception_handler(NestError)
    async def domain_error(request,exc):
        return JSONResponse({'error':exc.code},exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return JSONResponse({'error':'invalid_request'},422)

    def browser(request: Request):
        if not valid_session(request.cookies.get('nest_session'),creds['session_key']):
            raise HTTPException(401,'local_session_required')

    def host(request: Request):
        if not bearer(request,creds['host_token']):
            raise HTTPException(401,'host_credential_required')

    @app.post('/api/session')
    def login(request: Request):
        if not bearer(request,creds['browser_token']):
            raise HTTPException(401,'invalid_local_access_code')
        response=JSONResponse({'ok':True})
        response.set_cookie('nest_session',session_value(creds['session_key']),httponly=True,samesite='strict',max_age=12*3600)
        return response

    @app.get('/api/nest',dependencies=[Depends(browser)])
    def state(offset:int=0,limit:int=100):
        return service.state(offset=offset,limit=limit)

    @app.post('/api/adoptions',dependencies=[Depends(browser)])
    def adopt(body: Adoption):
        return service.adopt(**body.model_dump(),actor='user')

    @app.post('/api/care',dependencies=[Depends(browser)])
    def care(body: Care):
        return service.care(**body.model_dump(),actor='user')

    @app.get('/api/integration/nest',dependencies=[Depends(host)])
    def host_state(offset:int=0,limit:int=100):
        return service.state(offset=offset,limit=limit)

    @app.post('/api/integration/adoptions',dependencies=[Depends(host)])
    def host_adopt(body: Adoption):
        return service.adopt(**body.model_dump(),actor='assistant')

    @app.post('/api/integration/care',dependencies=[Depends(host)])
    def host_care(body: Care):
        return service.care(**body.model_dump(),actor='assistant')

    @app.post('/api/integration/usage',dependencies=[Depends(host)])
    def usage(body: UsageEvent):
        return record_usage(service.store,body)

    @app.post('/api/integration/relationship',dependencies=[Depends(host)])
    def relationship(body: RelationshipEvent):
        return record_relationship(service.store,body)

    @app.post('/api/integration/assets/{pet_id}',dependencies=[Depends(host)])
    async def import_asset(pet_id:str,request:Request,request_id:str):
        return service.jobs.import_asset(pet_id,await request.body(),request_id)

    @app.get('/api/jobs/{job_id}',dependencies=[Depends(browser)])
    def job(job_id:str):
        return service.jobs.get(job_id)

    @app.post('/api/jobs/{job_id}/retry',dependencies=[Depends(browser)])
    def retry(job_id:str,body:Retry):
        return service.jobs.retry(job_id,**body.model_dump())

    @app.get('/api/assets/{ref}',dependencies=[Depends(browser)])
    def asset(ref:str):
        path=service.jobs.asset_path(ref)
        if not path.is_file():
            raise HTTPException(404,'asset_not_found')
        return FileResponse(path,media_type='image/webp')

    root=Path(__file__).parent
    app.mount('/static',StaticFiles(directory=root/'web',check_dir=False),name='static')
    app.mount('/starter',StaticFiles(directory=root/'assets',check_dir=False),name='starter')

    @app.get('/')
    def index():
        return FileResponse(root/'web/index.html')
    return app
