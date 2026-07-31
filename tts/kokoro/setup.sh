#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
venv_path="${repo_root}/.venv-kokoro"
requirements_path="${repo_root}/tts/kokoro/requirements.txt"

if [[ ! -x "${venv_path}/bin/python" ]]; then
  uv venv --python 3.12 "${venv_path}"
fi
uv pip install --python "${venv_path}/bin/python" --requirement "${requirements_path}"

"${venv_path}/bin/python" -c \
  "from pykokoro.constants import SUPPORTED_LANGUAGES; assert SUPPORTED_LANGUAGES['ko'] == 'ko'; print('Kokoro Korean G2P ready')"
