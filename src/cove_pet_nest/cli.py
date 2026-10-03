import argparse
import json
from pathlib import Path
from .config import load_settings
from .service import build_service


def main():
    parser=argparse.ArgumentParser(description='Local pet room and MCP server')
    subs=parser.add_subparsers(dest='command',required=True)
    serve=subs.add_parser('serve'); serve.add_argument('--port',type=int,default=8767)
    subs.add_parser('mcp'); subs.add_parser('doctor')
    backup=subs.add_parser('backup'); backup.add_argument('destination',type=Path)
    args=parser.parse_args()
    settings=load_settings()
    service=build_service(settings)
    if args.command=='mcp':
        from .mcp_server import create_mcp
        create_mcp(service).run(transport='stdio')
    elif args.command=='serve':
        import uvicorn
        from .auth import credentials
        from .http import create_app
        creds=credentials(settings)
        link=settings.data_dir/'browser-url.txt'
        link.write_text(f'http://127.0.0.1:{args.port}/#key='+creds['browser_token'])
        link.chmod(0o600)
        print('Local room ready. Open the URL in browser-url.txt inside your data directory. Do not share that file.')
        uvicorn.run(create_app(service),host='127.0.0.1',port=args.port,access_log=False)
    elif args.command=='doctor':
        print(json.dumps({'database':'ready','timezone':settings.timezone,'image_generation_configured':service.jobs.transport is not None}))
    else:
        from .backup import create_backup
        create_backup(service.store,args.destination)
