#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
venv_path="${repo_root}/.venv-chatterbox"
requirements_path="${repo_root}/tts/chatterbox/requirements.txt"

uv venv --python 3.11 "${venv_path}"
uv pip install --python "${venv_path}/bin/python" --requirement "${requirements_path}"

# PyPI serves a CPU-only torch wheel on Linux ARM64. DGX Spark/GB10 needs
# the CUDA 13 wheel from the official PyTorch index. Install it last because
# Chatterbox currently pins torch 2.6 in its package metadata.
uv pip install \
  --python "${venv_path}/bin/python" \
  --reinstall \
  "torch==2.11.0" \
  "torchaudio==2.11.0" \
  --index-url https://download.pytorch.org/whl/cu130

"${venv_path}/bin/python" -c \
  "import torch; assert torch.cuda.is_available(); print(f'Chatterbox GPU ready: {torch.__version__} / {torch.cuda.get_device_name(0)}')"
