@echo off
setlocal
chcp 65001 >nul
set "COVE_UPDATE_ENTRY=%~dp0start.py"
powershell.exe -NoProfile -STA -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object Windows.Forms.FolderBrowserDialog; $d.Description='选择原灵宠屋项目或虚拟环境文件夹'; $d.ShowNewFolderButton=$false; if($d.ShowDialog() -ne 'OK'){exit 0}; foreach($root in @($d.SelectedPath, (Join-Path $d.SelectedPath '.venv'), (Join-Path $d.SelectedPath 'venv'))){$py=Join-Path $root 'Scripts/python.exe'; if((Test-Path -LiteralPath (Join-Path $root 'pyvenv.cfg')) -and (Test-Path -LiteralPath $py)){ & $py -I $env:COVE_UPDATE_ENTRY $d.SelectedPath; exit $LASTEXITCODE }}; [void][Windows.Forms.MessageBox]::Show('此文件夹未找到已有的虚拟环境，请重新选择原小屋项目。','Cove 灵宠屋'); exit 1"
