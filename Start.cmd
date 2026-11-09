@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0" || exit /b 1
set "UV_CACHE_DIR=%CD%\.uv-cache"
set "UV_PYTHON_INSTALL_DIR=%CD%\.python"
if not exist "data\tmp" mkdir "data\tmp"
set "TEMP=%CD%\data\tmp"
set "TMP=%TEMP%"
set "UV=uv.exe"
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
"%UV%" --version >nul 2>&1
if errorlevel 1 (
    echo Install uv / 请安装 uv: https://docs.astral.sh/uv/
    goto failed
)
"%UV%" sync --locked --no-dev --python 3.14 --no-install-package openai-codex-cli-bin
if errorlevel 1 goto failed
powershell.exe -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; Start-Process -FilePath '.\.venv\Scripts\python.exe' -ArgumentList '-m','quizchirp.app' -WorkingDirectory (Get-Location).Path -WindowStyle Hidden"
if errorlevel 1 goto failed
popd
exit /b 0

:failed
echo Startup stopped / 启动已停止。
pause
popd
exit /b 1
