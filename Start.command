#!/bin/sh
set -eu
cd "$(dirname "$0")"
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.python"
APP_DATA="$HOME/Library/Application Support/QuizChirp"
mkdir -p "$APP_DATA/tmp"
export TMPDIR="$APP_DATA/tmp"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    echo 'Install uv / 请安装 uv: https://docs.astral.sh/uv/'
    read -r reply
    exit 1
fi
if ! uv sync --locked --no-dev --python 3.14 --no-install-package openai-codex-cli-bin; then
    echo 'Setup failed / 环境安装失败'
    read -r reply
    exit 1
fi
nohup .venv/bin/python -m quizchirp.app >>"$APP_DATA/launcher.log" 2>&1 </dev/null &
