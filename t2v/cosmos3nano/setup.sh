#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
venv_path="${repo_root}/.venv-cosmos3nano"
requirements_path="${repo_root}/t2v/cosmos3nano/requirements.txt"

# --system-site-packages reuses the already-installed CUDA 13 torch build
# (verified working on this GB10 — see docs/model-selection-t2v.md) instead
# of pulling another multi-GB torch wheel. diffusers/transformers still get
# their own isolated versions inside this venv (Cosmos3OmniPipeline needs
# diffusers git main + transformers>=5.11, newer than what other services
# in this repo pin).
uv venv --python 3.12 --system-site-packages "${venv_path}"
uv pip install --python "${venv_path}/bin/python" --requirement "${requirements_path}"

"${venv_path}/bin/python" -c \
  "import torch; assert torch.cuda.is_available(); from diffusers import Cosmos3OmniPipeline; print(f'Cosmos3-Nano env ready: torch {torch.__version__} / {torch.cuda.get_device_name(0)}')"
