# 외부 의존성 (git 비추적, 이 repo에 없음)

Task 3.7 (video_generator 백엔드 이전) 산출물. `inference_server/`의 코드는 이 repo에
**복제**돼 있다(video_generator 원본은 삭제하지 않고 그대로 유지 — 이전이 아니라
복제). 아래 항목은 용량(수십~수백GB)·라이선스(GPL) 때문에 git으로 옮기지 않고
명시적으로 외부 의존성으로 문서화한다. `git clone` 후 아래 경로에 배치(또는
env로 재지정)하면 inference_server/comfyui.service가 그대로 기동한다.

| 구성요소 | 현재 실제 경로 | 크기 | 무엇에 쓰이나 | 재배치 시 |
|---|---|---|---|---|
| HuggingFace 캐시 | `~/.cache/huggingface` | ~315GB | Wan2.2-TI2V-5B(:8500)·FLUX.1-schnell(:8501)·Nemotron 등 전 HF 모델. 표준 HF 캐시라 `HF_HOME`으로 재지정 가능 | 그대로 유지 권장(홈 디렉터리, repo 무관) |
| ComfyUI (앱+모델+커스텀노드) | `/home/admin/video_generator/ComfyUI` | ~150GB | :8188 — LTX-13B-distilled I2V, Stand-In 얼굴일관성, Flux Kontext I2I. GPL-3.0 vendored 설치본(자체 `.git` 없음, video_generator에서도 git 비추적) | `/home/admin/DaolVision/ComfyUI`로 물리 이동 가능(동일 파일시스템 `mv`), `comfyui.service`의 `WorkingDirectory` 갱신 필요. 실행 중 서비스라 이번 태스크에서는 미이동 |

미이동 사유: 위 세 항목 모두 gitignore 대상으로 이미 "vendored, 이 repo에서
추적 안 함" 처리돼 있었고(`video_generator/.gitignore` 참고), ComfyUI(:8188)는
현재 `comfyui.service`로 상시 가동 중인 라이브 서비스라 데이터를 옮기려면
서비스 중단이 필요하다 — 사용자 확인 없이 진행하지 않았다. 코드(`inference_server/`
Python 서버·deploy unit·모니터링)만 이번에 DaolVision으로 복제했다(video_generator
쪽 원본 그대로 유지).

## inference_server 서비스 2종 (이번에 DaolVision에도 복제됨)

| 서비스 | 포트 | 코드 | systemd unit | 상태(2026-07-31 확인) |
|---|---|---|---|---|
| Wan2.2-TI2V-5B (T2V/I2V) | :8500 | ~~inference_server/server.py~~(Task 6.5로 DaolVision에서 삭제, video_generator/hunyuan_server 원본은 유지) | ~~inference_server/deploy/wan.service~~ | Task 6.5로 DaolVision 사용 중단 |
| FLUX.1-schnell (T2I) | :8501 | `inference_server/flux_server.py` | `inference_server/deploy/flux.service` | 수동 실행 중(systemd 비활성) |

deploy unit 2종은 `WorkingDirectory`/`ExecStart`를 `/home/admin/DaolVision/inference_server`로
갱신했다(`sed` 일괄 치환). `~/.config/systemd/user/{wan,flux}.service` 설치본도
동일하게 갱신했으나, 둘 다 이전부터 `disabled`/`inactive`였고 이번에도
`daemon-reload`·`enable`·`restart`는 하지 않았다 — 현재 수동 실행 중인 프로세스는
그대로 video_generator 코드가 메모리에 로드된 채 계속 돈다. 다음 재시작(또는
`systemctl --user start wan.service`) 시점부터 새 DaolVision 경로로 뜬다.

**Wan2.2-Animate-14B(:8600)는 DaolVision에서 삭제**(`animate_server.py`·
`run_animate.sh`·`deploy/wan-animate.service`) — LangGraph가 :8600을 호출한 적
없음(Task 2.2.2, 2026-07-30부터 `wan-animate.service` 중지 상태), 죽은 코드로
판단해 제거. 설치돼 있던 `~/.config/systemd/user/wan-animate.service`도
disable 후 삭제(원래도 inactive/disabled). video_generator 쪽 `hunyuan_server/`
원본에는 그대로 남아 있음(중복 삭제 범위는 DaolVision만으로 한정).

`inference_server/weights/Z-Image-Turbo`(31GB, video_generator에 잔존)는 폐기된
선대 모델(`flux_server.py` 주석 참고, 현재는 FLUX.1-schnell로 대체)이라 이전
대상에서 제외했다.

`comfyui.service`는 `Restart=always`로 상시 가동 중인 유일한 systemd-managed
서비스라 이번 태스크에서 건드리지 않았다(`WorkingDirectory`도 그대로
`video_generator/ComfyUI`).
