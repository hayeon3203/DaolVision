# Cosmos3-Nano T2V

Task 7.6 스파이크: LocalAI UI의 I2V 단발샷 카테고리를 대체하는 T2V 단발샷
카테고리(프롬프트 → 영상 1개, one-shot). Cosmos-Predict2-2B는 비교 대상에서
제외(사용자 지시) — Cosmos 3 Nano 단독 채택 여부만 확인한다.

## 확정된 역할

- 텍스트 프롬프트 1개 → 영상 1개, job과 무관한 단발 호출
- `POST /generate` (JSON) → `video/mp4` 바이트 응답
- 게이트웨이 `POST :8700/t2v`가 이 서버를 호출 (`langgraph/tools.py`
  `generate_t2v_cosmos3nano`)

## 설치

`nvidia/Cosmos3-Nano`의 `Cosmos3OmniPipeline`은 아직 diffusers PyPI
릴리스에 없어 git main이 필요하다. `setup.sh`는 `--system-site-packages`로
이미 검증된 CUDA 13 torch(이 GB10에서 동작 확인됨)를 재사용하고, diffusers/
transformers만 이 venv에 격리해서 새 버전을 깐다.

```bash
chmod +x t2v/cosmos3nano/setup.sh
./t2v/cosmos3nano/setup.sh
```

첫 실행 시 `nvidia/Cosmos3-Nano`(약 35GB)를 HF 캐시(`~/.cache/huggingface`)로
받는다. `hf auth login` 계정이 이미 접근 가능해야 한다(게이트 없음, 2026-08-02
확인).

## 로컬 API

```bash
./.venv-cosmos3nano/bin/python t2v/cosmos3nano/server.py

curl -fsS -X POST http://127.0.0.1:8505/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "a paper airplane gliding through a sunlit office"}' \
  --output test.mp4
```

`COSMOS3NANO_OFFLOAD=1`으로 `enable_sequential_cpu_offload()`를 켤 수 있다
(기본 꺼짐 — GB10 통합메모리에선 이득 없이 느려지기만 함, 실측은
`docs/model-selection-t2v.md` 참고).

게이트웨이 경유:

```bash
curl -fsS -X POST http://127.0.0.1:8700/t2v \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "a paper airplane gliding through a sunlit office"}'
```
