@echo off
chcp 65001 >nul
rem 在桌面创建「阅卷」快捷方式（无黑窗口启动）
set "DIR=%~dp0"
for /f "delims=" %%i in ('where pythonw 2^>nul') do (set "PYW=%%i" & goto found)
echo 没找到 pythonw.exe，请确认已安装 Python 并勾选了 Add to PATH
pause & exit /b
:found
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\'+[char]0x9605+[char]0x5377+'.lnk');$s.TargetPath='%PYW%';$s.Arguments='\"%DIR%start.pyw\"';$s.WorkingDirectory='%DIR%';$s.Save()"
echo 已在桌面创建「阅卷」快捷方式
pause
