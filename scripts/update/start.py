"""Double-click updater for an already installed private Cove Pet Nest environment."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import tempfile
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parent
VERSION = '0.3.2'


class Cancelled(Exception):
    pass


def dialog(action, message, initial=None):
    """Native prompts also work when the selected venv has no Tk installation."""
    base = str(initial or Path.home())
    if sys.platform == 'darwin':
        actions = {
            'choose': 'return POSIX path of (choose folder with prompt msg default location (POSIX file initialDir))',
            'confirm': 'display dialog msg with title "Cove 灵宠屋" buttons {"取消", "继续"} default button "继续" cancel button "取消"',
            'info': 'display dialog msg with title "Cove 灵宠屋" buttons {"好"} default button "好"',
        }
        script = 'on run argv\nset msg to item 1 of argv\nset initialDir to item 2 of argv\n' + actions[action] + '\nend run'
        command = ['osascript', '-e', script, message, base]
        env = None
    elif os.name == 'nt':
        actions = {
            'choose': "$d=New-Object Windows.Forms.FolderBrowserDialog; $d.Description=$env:COVE_PROMPT; $d.SelectedPath=$env:COVE_FOLDER; $d.ShowNewFolderButton=$false; if($d.ShowDialog() -ne 'OK'){exit 1}; $d.SelectedPath",
            'confirm': "if([Windows.Forms.MessageBox]::Show($env:COVE_PROMPT,'Cove 灵宠屋','OKCancel') -ne 'OK'){exit 1}",
            'info': "[void][Windows.Forms.MessageBox]::Show($env:COVE_PROMPT,'Cove 灵宠屋')",
        }
        script = "Add-Type -AssemblyName System.Windows.Forms; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); " + actions[action]
        command = ['powershell.exe', '-NoProfile', '-STA', '-Command', script]
        env = dict(os.environ, COVE_PROMPT=message, COVE_FOLDER=base)
    elif shutil.which('zenity'):
        args = {'choose': ['--file-selection', '--directory', '--filename', base + '/','--title',message],
                'confirm': ['--question','--text',message], 'info': ['--info','--text',message]}
        command = ['zenity', *([] if action=='choose' else ['--no-markup']), *args[action]]
        env = None
    elif shutil.which('kdialog'):
        args = {'choose': ['--getexistingdirectory',base,'--title',message],
                'confirm': ['--yesno',message], 'info': ['--msgbox',message]}
        command = ['kdialog', *args[action]]
        env = None
    else:
        import tkinter as tk
        from tkinter import filedialog, messagebox
        window=tk.Tk()
        window.withdraw()
        try:
            if action=='choose':
                path=filedialog.askdirectory(parent=window,title=message,initialdir=base,mustexist=True)
                if not path:raise Cancelled()
                return Path(path)
            if action=='confirm' and not messagebox.askokcancel('Cove 灵宠屋',message,parent=window):raise Cancelled()
            if action=='info':messagebox.showinfo('Cove 灵宠屋',message,parent=window)
            return
        finally:window.destroy()
    result=subprocess.run(command,env=env,capture_output=True,encoding='utf-8',errors='replace')
    if result.returncode:raise Cancelled()
    if action=='choose':return Path(result.stdout.rstrip('\r\n'))


def existing_room(data):
    path=data/'pets.sqlite3'
    if not path.is_file():return False
    try:
        from contextlib import closing
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('SELECT id FROM pets LIMIT 1').fetchone()
        return True
    except sqlite3.Error:
        return False


def existing_environment(project):
    for candidate in (project,project/'.venv',project/'venv'):
        python=candidate/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if (candidate/'pyvenv.cfg').is_file() and python.is_file():
            return python
    raise ValueError('此文件夹里没有找到原小屋的虚拟环境。请选原项目文件夹，或直接选安装灵宠屋的虚拟环境文件夹。')


def select_data(project):
    candidates=[]
    if os.environ.get('PET_NEST_DATA_DIR'):
        candidates.append(Path(os.environ['PET_NEST_DATA_DIR']).expanduser())
    if (project/'pyvenv.cfg').exists():project=project.parent
    candidates.extend((project/'data',Path.home()/'.local/share/cove-pet-nest'))
    default=next((d.resolve() for d in candidates if existing_room(d)),project)
    while True:
        data=dialog('choose','请选择原灵宠屋的数据文件夹（里面有 pets.sqlite3 和 credentials.json）',default)
        if existing_room(data) and (data/'credentials.json').is_file():
            return data.resolve()
        dialog('info','这里没有完整的原灵宠屋。请选含 pets.sqlite3 和 credentials.json 的旧数据文件夹。')


def saved_port(data):
    try:
        url=urlsplit((data/'browser-url.txt').read_text(encoding='utf-8').strip())
        if url.scheme=='http' and url.hostname in ('localhost','127.0.0.1') and url.port:
            return url.port
    except (OSError,ValueError):
        pass
    return 8767


def occupied(port):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1',port))==0


def verified_file(folder, pattern):
    matches=[p for p in folder.glob(pattern) if p.is_file() and not p.is_symlink()]
    if len(matches)!=1:raise ValueError('升级包文件不完整，请重新下载并完整解压。')
    path=matches[0]
    lines=(folder/'SHA256.txt').read_text(encoding='ascii').splitlines()
    expected=[line.split('  ')[0] for line in lines if re.fullmatch(r'[a-f0-9]{64}  '+re.escape(path.name),line)]
    if expected!=[hashlib.sha256(path.read_bytes()).hexdigest()]:
        raise ValueError('升级包的校验值不符，请重新下载。')
    return path


def verified_wheel(folder):
    return verified_file(folder,'cove_pet_nest-'+VERSION+'-py3-none-any.whl')


def verify_snapshot(folder):
    files=json.loads((folder/'manifest.json').read_text())['files']
    if not isinstance(files,dict) or 'pets.sqlite3' not in files:
        raise ValueError('原小屋备份缺少数据库。')
    for name,digest in files.items():
        if name!='pets.sqlite3' and not re.fullmatch(r'assets/[a-f0-9]{64}\.webp',name):
            raise ValueError('备份清单含有意外的文件。')
        file=folder/name
        if file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:
            raise ValueError('备份校验失败，更新已停止。')
    with sqlite3.connect((folder/'pets.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
        if conn.execute('PRAGMA quick_check').fetchone()!=('ok',):
            raise ValueError('备份数据库校验失败。')


def backup_v01(folder,data):
    recovery=Path(tempfile.mkdtemp(prefix='Cove-Pet-Nest-v0.1-backup-',dir=data.parent))
    old_wheel=verified_file(folder,'cove_pet_nest-0.1.0-py3-none-any.whl')
    shutil.copy2(old_wheel,recovery/old_wheel.name)
    subprocess.run([sys.executable,'-I','-m','cove_pet_nest','backup',str(recovery/'snapshot')],
                   env=dict(os.environ,PET_NEST_DATA_DIR=str(data)),check=True)
    verify_snapshot(recovery/'snapshot')
    print(f'升级前备份与旧版安装包已保存在 {recovery}',flush=True)
    return recovery


def install(folder):
    if sys.version_info<(3,11) or sys.prefix==sys.base_prefix:
        raise ValueError('请在原灵宠屋的独立环境中更新。')
    try:dist=importlib.metadata.distribution('cove-pet-nest')
    except importlib.metadata.PackageNotFoundError:raise ValueError('选中的环境尚未安装灵宠屋，请重新选择原小屋的安装位置。') from None
    if not Path(dist.locate_file('')).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise ValueError('此小屋安装在共享环境。请选择原项目专用的虚拟环境。')
    if dist.version not in ('0.1.0','0.2.0','0.3.0','0.3.1',VERSION):
        raise ValueError('此版本的更新包不适用于当前小屋，请检查发布页。')
    wheel=verified_wheel(folder)
    wheels=[] if dist.version==VERSION else [wheel]
    from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
    try:ZoneInfo(os.environ.get('PET_NEST_TIMEZONE','Asia/Shanghai'))
    except ZoneInfoNotFoundError:wheels.append(verified_file(folder,'tzdata-*-py2.py3-none-any.whl'))
    if not wheels:return
    pip=verified_file(folder,'pip-*-py3-none-any.whl')
    run_pip="import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('pip',run_name='__main__')"
    subprocess.run([sys.executable,'-I','-c',run_pip,str(pip),'--isolated','--disable-pip-version-check','--no-input',
                    'install','--no-index','--no-deps','--no-user',*[str(w) for w in wheels]],check=True)


def run_room(folder, data, *, open_browser=webbrowser.open):
    port=saved_port(data)
    while occupied(port):
        dialog('confirm',f'电脑上的端口 {port} 正在使用。请先用原来的方式关闭旧小屋和旧连接助手；关闭后点「继续」。选「取消」会退出。')
    dialog('confirm',f'将更新当前灵宠屋并使用这个数据文件夹：\n\n{data}\n\n请确认这是原来的小屋，并关闭仍在使用它的其他小屋进程。')
    if importlib.metadata.version("cove-pet-nest")=="0.1.0":
        dialog("confirm","旧版需要升级相册数据。请先关闭连接小屋的 AI 客户端和 MCP 服务。继续后会先在数据目录旁备份宠物及原图并校验，再升级。")
        backup_v01(folder,data)
    install(folder)
    env=dict(os.environ,PET_NEST_DATA_DIR=str(data))
    child=subprocess.Popen([sys.executable,'-I','-m','cove_pet_nest','serve','--port',str(port)],env=env)
    url=f'http://127.0.0.1:{port}/passport'
    client=build_opener(ProxyHandler({}))
    try:
        for _ in range(150):
            if child.poll() is not None:raise RuntimeError('小屋未能启动，请查看启动窗口或重新检查端口。')
            try:
                with client.open(url,timeout=.6) as r:
                    if r.status==200:break
            except OSError:pass
            time.sleep(.2)
        else:raise RuntimeError('小屋未能及时打开，请检查本机端口后重试。')
        print(f'灵宠屋正在运行。请保留此窗口。\n配对页面 {url}',flush=True)
        open_browser(url)
        return child.wait()
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    if len(sys.argv)==1:
        project=dialog('choose','选择已安装灵宠屋的项目或虚拟环境文件夹')
        python=existing_environment(project)
        return subprocess.call([str(python),'-I',str(ROOT/'start.py'),str(project)])
    project=Path(sys.argv[1])
    data=select_data(project)
    return run_room(ROOT,data)


if __name__=='__main__':
    try:sys.exit(main())
    except (Cancelled,KeyboardInterrupt):pass
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        dialog('info','未完成本次操作。'+str(error))
        sys.exit(1)
