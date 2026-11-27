#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=$(osascript -e 'POSIX path of (choose folder with prompt "选择原灵宠屋项目文件夹，或已安装灵宠屋的虚拟环境文件夹")') || exit 0
for envdir in "$project" "$project/.venv" "$project/venv"; do
  if [ -f "$envdir/pyvenv.cfg" ] && [ -x "$envdir/bin/python" ]; then
    exec "$envdir/bin/python" -I "$base/start.py" "$project"
  fi
done
osascript -e 'display dialog "此位置没有找到已安装的虚拟环境。请再次双击更新工具，选择原灵宠屋项目，或直接选择其虚拟环境文件夹。" buttons {"好"} default button "好"'
