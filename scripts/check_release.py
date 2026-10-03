"""Inspect real distributions without printing matching secrets or private values."""
import argparse
import json
from io import BytesIO
from pathlib import PurePosixPath,Path
import re
import tarfile
import zipfile
from PIL import Image

PATTERNS={
    'secret': re.compile(r'(?:\bsk-[A-Za-z0-9_-]{20,}|\bAKIA[A-Z0-9]{16}\b|Bearer [A-Za-z0-9_-]{24,})'),
    'private_absolute_path': re.compile(r'(?:/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|[A-Z]:\\Users\\[A-Za-z0-9._-]+\\)'),
    'credential_literal':re.compile(r'''(?i)(?:api[_-]?key|password|host_token|browser_token|session_key)["']?\s*[:=]\s*["'][A-Za-z0-9_-]{24,}["']'''),
}


def scan_entry(name,payload,deny=()):
    findings=[]
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        findings.append('unsafe_path')
    if any(p in ('.git','.venv','.uv-cache','.superpowers','data','__pycache__') for p in path.parts):
        findings.append('private_or_runtime_directory')
    if path.name in ('.env','credentials.json','browser-url.txt') or path.suffix in ('.sqlite3','.sqlite','.db','.wal','.shm','.log','.pyc') or path.name.endswith(('-wal','-shm')):
        findings.append('runtime_file')
    if path.suffix.lower() in ('.png','.webp','.jpg','.jpeg'):
        try:
            with Image.open(BytesIO(payload)) as image:
                if image.getexif() or any(k in image.info for k in ('exif','xmp','XML:com.adobe.xmp','comment')):
                    findings.append('image_metadata')
        except (OSError,ValueError):
            findings.append('invalid_image')
    else:
        text=payload.decode('utf8',errors='replace')
        for kind,pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(kind)
        if any(value and value.casefold() in text.casefold() for value in deny):
            findings.append('private_identifier')
    return findings


def entries(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                if item.is_dir():continue
                if (item.external_attr>>16)&0o170000==0o120000:
                    yield item.filename,b'',True
                else:
                    yield item.filename,archive.read(item),False
    else:
        with tarfile.open(path,'r:*') as archive:
            for item in archive:
                if item.isdir():continue
                yield item.name,archive.extractfile(item).read() if item.isfile() else b'',not item.isfile()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--deny-file',type=Path)
    args=parser.parse_args()
    deny=args.deny_file.read_text().splitlines() if args.deny_file else ()
    report=[];count=0
    for name,payload,link in entries(args.artifact):
        count+=1
        findings=scan_entry(name,payload,deny)
        if link:findings.append('archive_link')
        if findings:
            safe='<invalid-path>' if 'unsafe_path' in findings else name
            report.append({'entry':safe,'categories':findings})
    print(json.dumps({'files_checked':count,'findings':report},ensure_ascii=False))
    raise SystemExit(1 if report else 0)


if __name__=='__main__':main()
