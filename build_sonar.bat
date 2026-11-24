@echo off
setlocal
cd /d "%~dp0"
REM Put this file next to sonar.py (and sonar_icon.ico if you want the icon).
REM Everything else (Python packages, ffmpeg, ffprobe, VLC files) is fetched automatically.

if not exist sonar.py echo MISSING sonar.py - put it next to this file & pause & exit /b 1
if not exist _deps mkdir _deps

REM ---- Python
python --version >nul 2>&1
if errorlevel 1 goto nopython
goto pyok
:nopython
echo Python not found. Trying to install it with winget...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo Python was just installed. CLOSE this window and run build_sonar.bat again.
pause
exit /b 1
:pyok

REM ---- Python packages (same interpreter for pip and PyInstaller)
python -m pip install --upgrade pyinstaller customtkinter yt-dlp pillow python-vlc mutagen
if errorlevel 1 echo PIP FAILED & pause & exit /b 1

REM ---- ffmpeg + ffprobe
if exist ffmpeg.exe if exist ffprobe.exe goto ffok
echo Downloading ffmpeg (about 100-200 MB, one time)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $u='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip','https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'; foreach($x in $u){ try{ Invoke-WebRequest $x -OutFile '_deps\ffmpeg.zip' -UseBasicParsing; break }catch{} }; Expand-Archive '_deps\ffmpeg.zip' '_deps\ffmpeg' -Force; Get-ChildItem '_deps\ffmpeg' -Recurse -Include ffmpeg.exe,ffprobe.exe | Copy-Item -Destination '.' -Force"
if not exist ffmpeg.exe echo COULD NOT GET ffmpeg.exe - download it yourself and put ffmpeg.exe + ffprobe.exe here & pause & exit /b 1
if not exist ffprobe.exe echo COULD NOT GET ffprobe.exe & pause & exit /b 1
:ffok

REM ---- VLC (use installed 64-bit VLC if present, otherwise download the portable zip)
set "VLC=C:\Program Files\VideoLAN\VLC"
if exist "%VLC%\libvlc.dll" goto vlcok
set "VLC=%CD%\_deps\vlc"
if exist "%VLC%\libvlc.dll" goto vlcok
echo Downloading VLC files (about 75 MB, one time)...
if exist _deps\vlctmp rmdir /s /q _deps\vlctmp
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest 'https://get.videolan.org/vlc/3.0.21/win64/vlc-3.0.21-win64.zip' -OutFile '_deps\vlc.zip' -UseBasicParsing; Expand-Archive '_deps\vlc.zip' '_deps\vlctmp' -Force; $d=Get-ChildItem '_deps\vlctmp' -Directory | Select-Object -First 1; Move-Item $d.FullName '_deps\vlc' -Force"
if not exist "%VLC%\libvlc.dll" echo COULD NOT GET VLC - install 64-bit VLC from videolan.org and run this again & pause & exit /b 1
:vlcok

REM ---- Icon (optional)
set "ICON="
if exist sonar_icon.ico set "ICON=--icon sonar_icon.ico"
if not exist sonar_icon.ico echo Note: sonar_icon.ico not found, building without a custom exe icon.

REM ---- Build
python -m PyInstaller --clean --onefile --noconsole --name Sonar --collect-all customtkinter --collect-all yt_dlp --collect-all mutagen --add-binary "%VLC%\libvlc.dll;." --add-binary "%VLC%\libvlccore.dll;." --add-data "%VLC%\plugins;plugins" --add-binary "ffmpeg.exe;." --add-binary "ffprobe.exe;." sonar.py %ICON%
if errorlevel 1 echo BUILD FAILED - read the error above & pause & exit /b 1

echo.
echo Done. Your exe is in dist\Sonar.exe
pause
