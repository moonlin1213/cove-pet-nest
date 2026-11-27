"""Build an offline update ZIP from the release wheel and redistributable dependencies."""
import argparse
import hashlib
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parent
LAUNCHERS=('start.py','Update-macOS.command','Update-Windows.cmd','Update-Linux.sh')


def build(wheel,pip,tzdata,destination,recovery_wheel=None):
    old=recovery_wheel or ROOT.parent/'dist'/'cove_pet_nest-0.1.0-py3-none-any.whl'
    if not old.is_file():
        raise ValueError('Download the official v0.1.0 wheel and pass --recovery-wheel.')
    if hashlib.sha256(old.read_bytes()).hexdigest()!='342eade7d1ce849c402dc81592182d7ad14e4d61342392311a16fbe0f4fa66ad':
        raise ValueError('Missing the verified v0.1.0 recovery wheel')
    wheels=((old,r'cove_pet_nest-0\.1\.0-py3-none-any\.whl'),(wheel,r'cove_pet_nest-0\.3\.0-py3-none-any\.whl'),
            (pip,r'pip-[0-9.]+-py3-none-any\.whl'),
            (tzdata,r'tzdata-[0-9.]+-py2\.py3-none-any\.whl'))
    for path,pattern in wheels:
        if not re.fullmatch(pattern,path.name) or not zipfile.is_zipfile(path):
            raise ValueError('Unexpected wheel '+path.name)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as out:
        for name in LAUNCHERS:
            out.write(ROOT/'update'/name,'Cove-Pet-Nest-Update/'+name)
        checks=[]
        for path,_ in wheels:
            out.write(path,'Cove-Pet-Nest-Update/'+path.name,compress_type=zipfile.ZIP_STORED)
            checks.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name)
        out.writestr('Cove-Pet-Nest-Update/SHA256.txt','\n'.join(checks)+'\n')
        out.writestr('Cove-Pet-Nest-Update/使用说明.txt',
                     '先完整解压，在安装了原小屋的电脑上双击对应的 Update 启动器。\n'
                     '选择原项目文件夹，再选择含 pets.sqlite3 和 credentials.json 的原小屋数据文件夹。\n'
                     '保持启动窗口打开即可同步，关闭启动窗口会停止小屋。日常也可以用原来的方式启动。\n'
                     'Linux 若显示脚本内容，可在文件属性中允许作为程序执行，然后选择运行。\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel',type=Path)
    parser.add_argument('--pip-wheel',required=True,type=Path)
    parser.add_argument('--tzdata-wheel',required=True,type=Path)
    parser.add_argument('--recovery-wheel',type=Path,help='Official v0.1.0 wheel used for rollback')
    parser.add_argument('--output',type=Path,default=ROOT.parent/'dist/Cove-Pet-Nest-Update.zip')
    args=parser.parse_args()
    build(args.wheel,args.pip_wheel,args.tzdata_wheel,args.output,args.recovery_wheel)
