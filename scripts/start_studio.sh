#!/usr/bin/env bash
# DaolVision 스튜디오 기동 (Task 8.2 / 8.2.1)
#
# 모델 서버를 OpenShell 샌드박스에서 띄우고, 기존 localhost 포트로
# forward 해서 langgraph/tools.py 는 코드 변경 없이 그대로 쓰게 한다.
#
# 설계 요지 — 웨이트는 호스트에 남는다:
#   openshell 0.0.96 의 docker 드라이버가 호스트 bind mount 를 정식 지원한다.
#   샌드박스마다 `--driver-config-json` 으로 마운트를 주면 복사도 스테이징도
#   없다. 게이트웨이 쪽에서 한 번만 열어주면 된다:
#
#     ~/.config/openshell/gateway.toml
#       [openshell.drivers.docker]
#       enable_bind_mounts = true
#     ~/.config/openshell/gateway.env
#       OPENSHELL_GATEWAY_CONFIG=/home/admin/.config/openshell/gateway.toml
#     systemctl --user restart openshell-gateway
#
#   (unit 이 EnvironmentFile=-%E/openshell/gateway.env 를 이미 읽으므로
#    unit 파일 자체는 건드릴 필요가 없다.)
#
#   안 열려 있으면 create 가 "... requires enable_bind_mounts = true in
#   [openshell.drivers.docker]" 로 명확히 죽는다. 그래서 따로 점검하지 않는다.
#
# 사용법:
#   ./scripts/start_studio.sh --check        # 아무것도 안 바꾸고 전제조건만 점검
#   ./scripts/start_studio.sh --smoke        # 호스트 venv 가 이미지 안에서 도는지 검증
#   ./scripts/start_studio.sh --up           # 샌드박스 + forward
#   ./scripts/start_studio.sh --down         # forward 해제 + 샌드박스 삭제
#
# --up 은 호스트에서 같은 포트를 이미 쓰고 있으면 거부한다. 돌고 있는 서버를
# 죽이는 건 이 스크립트의 일이 아니다. 정말 바꿀 거면 그 프로세스를 먼저
# 내리고 다시 실행할 것.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERFILE="${REPO_ROOT}/docker/Dockerfile.runtime"

HF_HUB="/home/admin/.cache/huggingface/hub"
# 서비스별 landlock 정책 YAML 을 여기 생성한다(write_policy 참고).
POLICY_DIR="${REPO_ROOT}/docker/policies"

# name | port | gpu | workdir | command | env(공백구분) | mounts(공백구분, 호스트 절대경로)
#
# 마운트는 서비스가 실제로 읽는 것만 준다. HF 캐시 348GB 를 통째로 물리면
# 격리하는 의미가 없어서 모델 디렉토리 단위로 끊었다. 마운트 경로는 샌드박스
# 안에서도 호스트와 **동일한 절대경로**여야 한다 — venv 의 shebang 과
# pyvenv.cfg 가 절대경로로 박혀 있기 때문.
#
# 기본은 읽기전용이다. bind mount 는 호스트 원본 그 자체라 쓰기 가능하게
# 물리면 샌드박스가 호스트 웨이트를 그대로 덮어쓸 수 있다. 쓰기가 실제로
# 필요한 경로만 `rw:` 를 붙인다:
#   comfyui  — output/ temp/ user/ 에 결과물을 쓴다
#   ollama   — pull 시 blobs/manifests 를 쓴다
#
# 읽기전용 venv 는 "런타임에 자기 site-packages 에 쓰는" 라이브러리를 깨뜨린다.
# chatterbox 의 librosa→numba 가 그렇다(실측: "cannot cache function '__o_fold':
# no locator available for .../librosa/core/notation.py"). 캐시 경로를 정책상
# 쓰기 가능한 /tmp 로 돌려서 푼다 — venv 를 rw 로 여는 게 아니라.
#
# 같은 이유로 $HOME 도 맞춰줘야 한다. 샌드박스의 로그인 유저는 sandbox 라
# HOME 이 /home/sandbox 인데 거긴 정책상 못 쓴다. ollama 는 첫 기동에
# $HOME/.ollama 에 키를 만들므로 그대로면 죽는다(실측: "could not create
# directory mkdir /home/sandbox/.ollama: permission denied"). HOME 을
# /home/admin 으로 돌려 rw 로 물린 .ollama 를 쓰게 한다.
#
# ollama 는 바이너리 하나로 끝나지 않는다. 추론 러너가 /usr/local/lib/ollama 로
# 분리돼 있어서(llama-server + libggml*.so + cuda_v12/v13) /usr/local/bin/ollama
# 만 마운트하면 서버는 뜨고 /api/tags 도 200 을 돌려주는데 실제 추론은 전부
# 죽는다: "error starting llama-server: llama-server binary not found". 모델
# 목록만 보고 판정하면 못 잡는 실패다 — 반드시 generate/embeddings 로 확인할 것.
#
# comfyui 의 models/{vae,diffusion_models,...} 밑에는 HF 캐시로 심볼릭 링크된
# 체크포인트가 섞여 있다(subject_ref/Face-ID 경로가 쓰는 Kijai/WanVideo_comfy,
# BowenXue/Stand-In). ComfyUI의 object_info(모델 목록 스캔)는 심볼릭 링크
# "이름"만 보고 뜨므로 마운트 안 돼 있어도 정상으로 보이지만, 실제 로드 시점의
# folder_paths.get_full_path_or_raise 가 링크 타깃을 못 찾아
# FileNotFoundError 로 죽는다(2026-08-12, 로고+GB10 일관성 스파이크 Task 2에서
# 최초 재현 — subject_ref 경로가 OpenShell 전환(Task 8.2.1) 이후 처음
# 실행됐다는 뜻이기도 하다). 두 HF_HUB 경로를 마운트해서 해소.
# 2026-08-13: comfyui에서 `--highvram` 제거. GB10은 통합메모리라 "VRAM이 남으니
# 안 내린다"는 전제가 성립하지 않는다 — 모델을 계속 상주시키면 CUDA가 보는 여유가
# 말라 VAE 디코드 시점에 축출이 터지고, 하필 축출 대상이 GGUF 양자화 모델이라
# 텐서 4400개를 CPU에서 하나씩 역양자화한다(py-spy 실측: free_memory →
# partially_unload → _quantized_apply, GPU 1%로 40분 정체, job 92a9a76b 씬1).
# 재로드 +50~80초(docs/spikes/3.6)가 그 축출보다 압도적으로 싸다.
read -r -d '' SERVICES <<EOF || true
comfyui|8188|yes|/home/admin/video_generator/ComfyUI|/home/admin/.venv/bin/python main.py --cache-classic --listen 0.0.0.0|HF_HUB_OFFLINE=1|rw:/home/admin/video_generator/ComfyUI /home/admin/.venv ${HF_HUB}/models--Kijai--WanVideo_comfy ${HF_HUB}/models--BowenXue--Stand-In
t2i|8501|yes|/home/admin/DaolVision/inference_server|/home/admin/huyuan-env/bin/python flux_server.py|HYV_HOST=0.0.0.0 HYV_PORT=8501 FLUX_KEEP_RESIDENT=1 HF_HOME=/home/admin/.cache/huggingface HF_HUB_OFFLINE=1|/home/admin/DaolVision/inference_server rw:/home/admin/DaolVision/inference_server/outputs /home/admin/huyuan-env ${HF_HUB}/models--black-forest-labs--FLUX.1-schnell
kokoro|8503|no|/home/admin/DaolVision|/home/admin/DaolVision/.venv-kokoro/bin/python tts/kokoro/server.py|KOKORO_HOST=0.0.0.0 KOKORO_PORT=8503 HF_HUB_OFFLINE=1|/home/admin/DaolVision/tts/kokoro /home/admin/DaolVision/.venv-kokoro ${HF_HUB}/models--onnx-community--Kokoro-82M-v1.0-ONNX-timestamped
chatterbox|8504|yes|/home/admin/DaolVision|/home/admin/DaolVision/.venv-chatterbox/bin/python tts/chatterbox/server.py|CHATTERBOX_HOST=0.0.0.0 CHATTERBOX_PORT=8504 NUMBA_CACHE_DIR=/tmp HF_HUB_OFFLINE=1|/home/admin/DaolVision/tts/chatterbox /home/admin/DaolVision/.venv-chatterbox /home/admin/.local/share/uv/python ${HF_HUB}/models--ResembleAI--chatterbox
ollama|11434|yes|/home/admin|/usr/local/bin/ollama serve|HOME=/home/admin OLLAMA_HOST=0.0.0.0:11434 OLLAMA_MAX_LOADED_MODELS=2 OLLAMA_MODELS=/usr/share/ollama/.ollama/models|/usr/local/bin/ollama /usr/local/lib/ollama rw:/home/admin/.ollama /usr/share/ollama/.ollama/models
EOF

die() { echo "ERROR: $*" >&2; exit 1; }

# 인자로 서비스 이름을 주면 그것만 대상으로 한다. 6종을 한 번에 전환하면
# 실패했을 때 원인 서비스를 못 가리므로 단계적 전환이 기본 사용법이다.
#   ./scripts/start_studio.sh --up chatterbox
FILTER=()
each_service() {
    printf '%s\n' "$SERVICES" | grep -v '^[[:space:]]*$' | {
        if [ ${#FILTER[@]} -eq 0 ]; then cat
        else grep -E "^($(IFS='|'; echo "${FILTER[*]}"))\|"
        fi
    }
}

# 마운트 항목은 "/경로"(읽기전용) 또는 "rw:/경로"(쓰기 허용).
mnt_path() { printf '%s' "${1#rw:}"; }

# 포트를 쥔 프로세스가 systemd 유닛이면 유닛 이름을 돌려준다. 그냥 kill 하면
# systemd 가 곧바로 되살려서 전환이 조용히 실패한다(실측: comfyui.service 가
# --up 도중 :8188 을 다시 잡아 forward 가 dead 로 죽었는데, 포트는 여전히
# 200 을 응답해서 성공처럼 보였다).
port_unit() {
    local port="$1" pid unit
    pid=$(ss -tlnpH "sport = :$port" 2>/dev/null \
          | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
    [ -n "$pid" ] || return 1
    # user 유닛은 .../app.slice/<unit>.service, 시스템 유닛은 /system.slice/<unit>.service
    unit=$(grep -oE '[A-Za-z0-9@._-]+\.service' "/proc/$pid/cgroup" 2>/dev/null | tail -1)
    [ -n "$unit" ] || return 1
    printf '%s' "$unit"
}

# ---------------------------------------------------------------- preflight

check() {
    local rc=0

    openshell status >/dev/null 2>&1 || { echo "  [x] openshell 게이트웨이 응답 없음"; rc=1; }
    [ -f "$DOCKERFILE" ] || { echo "  [x] $DOCKERFILE 없음"; rc=1; }

    # 모델·venv·코드 경로가 실재하는지
    while IFS='|' read -r name port gpu workdir cmd env mounts; do
        for m in $mounts; do
            p="$(mnt_path "$m")"
            [ -e "$p" ] || { echo "  [x] $name: 마운트 원본 없음 — $p"; rc=1; }
        done
    done < <(each_service)

    # 호스트에서 같은 포트를 이미 쓰고 있으면 --up 은 못 간다
    local busy=0
    while IFS='|' read -r name port gpu workdir cmd env mounts; do
        if ss -tln 2>/dev/null | grep -qE "[:.]${port}[[:space:]]"; then
            unit="$(port_unit "$port" || true)"
            if [ -n "$unit" ]; then
                # kill 로는 안 된다. stop 만 하면 재부팅·재시작 때 되살아나므로
                # disable 까지 안내한다.
                echo "  [!] :$port ($name) — systemd 유닛 $unit 가 점유 중"
                echo "        systemctl --user stop $unit && systemctl --user disable $unit"
                echo "        (시스템 유닛이면 --user 대신 sudo)"
            else
                echo "  [!] :$port ($name) 호스트에서 사용 중 — 전환하려면 먼저 내려야 함"
            fi
            busy=1
        fi
    done < <(each_service)

    echo "  [i] 메모리 available: $(free -g | awk '/^Mem:/{print $7}') GiB"
    [ "$busy" = 0 ] && echo "  [i] 포트 전부 비어 있음 — --up 가능"
    [ "$rc" = 0 ] && echo "  [ok] 전제조건 통과"
    # 0=이상없음, 1=전제조건 실패, 2=전제조건은 OK지만 포트가 호스트에 물려 있음
    [ "$rc" = 0 ] && [ "$busy" = 1 ] && return 2
    return $rc
}

# ------------------------------------------------------------ 샌드박스 기동

# docker 드라이버의 mounts 배열을 만든다. 경로를 셸 문자열로 이어붙이지 않고
# python 에 위치인자로 넘겨 JSON 인코딩을 맡긴다.
driver_json() {
    python3 -c '
import json, sys
mounts = []
for entry in sys.argv[1].split():
    rw = entry.startswith("rw:")
    src = entry[3:] if rw else entry
    # 호스트 경로 그대로가 샌드박스 경로다. venv 의 shebang·pyvenv.cfg 가
    # 절대경로라 다른 위치에 붙이면 인터프리터 사슬이 끊긴다.
    mounts.append({"type": "bind", "source": src, "target": src, "read_only": not rw})
json.dump({"docker": {"mounts": mounts}}, sys.stdout)
' "$1"
}

sandbox_up() {
    while IFS='|' read -r name port gpu workdir cmd env mounts; do
        echo "==> $name (:$port)"

        # 정책은 create 시점에 준다. 살아있는 샌드박스에 policy set 으로
        # 범위를 좁히는 건 서버가 거부한다(실측: "filesystem read_write path
        # '/dev/null' cannot be removed on a live sandbox"). 그래서 매번 지우고
        # 정책과 함께 새로 만든다 — 상태 드리프트도 같이 없어진다.
        write_policy "$name" "$workdir" "$gpu" "$mounts"
        openshell sandbox delete "$name" >/dev/null 2>&1 || true

        local gpuflag=()
        [ "$gpu" = yes ] && gpuflag=(--gpu)
        local envflags=()
        [ "$env" != "-" ] && for kv in $env; do envflags+=(--env "$kv"); done

        # create 에는 --workdir 가 없다. 커맨드는 CLI 가 argv 로 그대로
        # 넘겨주므로 sh -c 안에서 cd 하면 된다(실측: 따옴표·$변수 정상 동작).
        # --no-tty 없으면 비대화 세션(nohup/setsid/CI)에서 PTY 할당을 시도하다
        # 시그널로 스크립트째 죽는다 — 로그가 create 출력에서 뚝 끊긴다.
        # create 는 샌드박스가 Ready 가 된 뒤에도 커맨드에 계속 붙어 있으므로
        # setsid + stdin 차단으로 떼어놓고 Ready 를 직접 기다린다.
        # 서비스가 죽으면 create 프로세스도 같이 끝난다. 출력을 버리면 왜
        # 죽었는지가 통째로 사라지므로(실측: chatterbox 의 numba 캐시 오류가
        # 조용히 사라졌다) 서비스별 로그로 남긴다.
        setsid openshell sandbox create --name "$name" "${gpuflag[@]}" --no-tty \
            --policy "${POLICY_DIR}/${name}.yaml" \
            --driver-config-json "$(driver_json "$mounts")" \
            "${envflags[@]}" \
            --from "$DOCKERFILE" \
            -- sh -c "cd '$workdir' && exec $cmd" \
            < /dev/null > "/tmp/start_studio-${name}.log" 2>&1 &
        wait_ready "$name" || die "$name 이 Ready 가 되지 않음"

        # forward start 는 포그라운드로 붙잡는다(Ctrl+C 대기). --background 필수.
        # --background 가 남기는 ssh 데몬이 이 스크립트의 stdout 을 물려받는다.
        # 그대로 두면 파이프가 안 닫혀서 `./start_studio.sh --up | tail` 이
        # 영원히 안 끝난다(실측). 데몬 쪽 fd 를 끊어준다.
        openshell forward start --background "$port" "$name" >/dev/null 2>&1

        # forward 가 붙었는지 확인한다. 포트로 curl 만 해보면 안 된다 —
        # 호스트가 같은 포트를 다시 잡았을 때 그쪽이 200 을 돌려주므로
        # 전환 실패가 성공으로 보인다(실측: comfyui). forward 상태를 본다.
        sleep 2
        if openshell forward list 2>/dev/null \
           | awk -v n="$name" -v p="$port" '$1==n && $3==p {print $NF}' \
           | grep -q running; then
            echo "  기동 완료 (마운트 $(echo $mounts | wc -w)개)"
        else
            die "$name forward 가 붙지 않았다 (:$port). 호스트가 포트를 다시 잡았는지 확인할 것 — ./scripts/start_studio.sh --check $name"
        fi
    done < <(each_service)
}

# 샌드박스는 landlock 파일시스템 정책으로 /sandbox·/tmp·/usr 정도만 열어둔다.
# 마운트를 붙여도 정책에 없으면 못 읽는다 — /home 은 755 root:root 인데도
# `ls /home` 이 Permission denied 로 막혔다(실측). 그래서 마운트 경로를 그대로
# 정책에도 등록해야 한다. rw 마운트만 read_write, 나머지는 read_only.
write_policy() {
    local name="$1" workdir="$2" gpu="$3" mounts="$4"
    mkdir -p "$POLICY_DIR"
    {
        echo "version: 1"
        echo "filesystem_policy:"
        echo "  include_workdir: true"
        echo "  read_only:"
        # 기본 정책이 열어두는 것들. 여기서 새로 쓰므로 다시 나열해야 한다.
        for p in /usr /lib /proc /dev/urandom /app /etc /var/log; do echo "  - $p"; done
        # CUDA 초기화가 /sys 의 디바이스 토폴로지를 읽는다.
        [ "$gpu" = yes ] && echo "  - /sys"
        echo "  - $workdir"
        for m in $mounts; do
            case "$m" in rw:*) ;; *) echo "  - $m" ;; esac
        done
        echo "  read_write:"
        for p in /sandbox /tmp /dev/null; do echo "  - $p"; done
        # torch 의 shared-memory 와 NVIDIA 디바이스 노드는 쓰기가 필요하다.
        [ "$gpu" = yes ] && for p in /dev/shm /dev/nvidiactl /dev/nvidia0 \
                                     /dev/nvidia-uvm /dev/nvidia-uvm-tools; do echo "  - $p"; done
        for m in $mounts; do
            case "$m" in rw:*) echo "  - ${m#rw:}" ;; esac
        done
        echo "landlock:"
        echo "  compatibility: best_effort"
        echo "process:"
        echo "  run_as_user: sandbox"
        echo "  run_as_group: sandbox"
    } > "${POLICY_DIR}/${name}.yaml"
}

wait_ready() {
    local name="$1" i=0
    while [ $i -lt 120 ]; do
        openshell sandbox list 2>/dev/null | grep -E "^${name}[[:space:]]" | grep -q Ready && return 0
        sleep 5; i=$((i+1))
    done
    return 1
}

# 이 설계의 유일한 가정 — "호스트 venv 를 원래 경로에 마운트하면 얇은 이미지
# 안에서 그대로 돈다" — 를 실제로 검증한다. GPU 도 포트도 모델도 안 건드리고
# import 만 하므로 돌아가는 서비스에 영향이 없다. 이미지를 손볼 때마다 이걸
# 먼저 돌릴 것. 깨지면 --up 은 100% 실패한다.
smoke() {
    local img="${RUNTIME_IMAGE:-daolvision/runtime:1}" rc=0
    docker image inspect "$img" >/dev/null 2>&1 \
        || docker build -q -f "$DOCKERFILE" -t "$img" "$(dirname "$DOCKERFILE")" >/dev/null

    # venv경로|인터프리터|import할 모듈|추가마운트
    while IFS='|' read -r venv py mods extra; do
        local args=(-v "${venv}:${venv}:ro")
        [ -n "$extra" ] && args+=(-v "${extra}:${extra}:ro")
        if out=$(docker run --rm "${args[@]}" "$img" "$py" -c \
                 "import sys,$mods; print(sys.version.split()[0])" 2>&1 | tail -1); then
            echo "  [ok] $venv → python $out"
        else
            echo "  [x]  $venv → $out"; rc=1
        fi
    done <<EOF
/home/admin/.venv|/home/admin/.venv/bin/python|torch,torchvision|
/home/admin/huyuan-env|/home/admin/huyuan-env/bin/python|torch,diffusers|
/home/admin/DaolVision/.venv-kokoro|/home/admin/DaolVision/.venv-kokoro/bin/python|onnxruntime,pykokoro|
/home/admin/DaolVision/.venv-cosmos3nano|/home/admin/DaolVision/.venv-cosmos3nano/bin/python|torch,diffusers|
/home/admin/DaolVision/.venv-chatterbox|/home/admin/DaolVision/.venv-chatterbox/bin/python|torch|/home/admin/.local/share/uv/python
EOF
    [ "$rc" = 0 ] && echo "  [ok] 호스트 venv 5종 전부 이미지 안에서 import 성공"
    return $rc
}

down() {
    while IFS='|' read -r name port gpu workdir cmd env mounts; do
        openshell forward stop "$port" 2>/dev/null || true
        openshell sandbox delete "$name" 2>/dev/null || true
        echo "  내림: $name (:$port)"
    done < <(each_service)
}

mode="${1:---check}"
shift || true

# 남은 인자는 서비스 이름 필터. 테이블에 없는 이름은 여기서 거른다 — 그대로
# grep 패턴에 들어가므로 정규식 메타문자를 통과시키면 안 된다.
for want in "$@"; do
    # -F -x 로 고정문자열 완전일치. 여기서 정규식이 새면 `--down '.*'` 이
    # 한 서비스만 내리려던 명령을 6종 전체로 넓힌다.
    printf '%s\n' "$SERVICES" | cut -d'|' -f1 | grep -qxF "$want" \
        || die "그런 서비스 없음: $want"
    FILTER+=("$want")
done

case "$mode" in
    # 포트가 물려 있는 건 --check 입장에선 정상 상태(보고만 한다)라 exit 0.
    --check) rc=0; check || rc=$?; [ "$rc" = 1 ] && exit 1; exit 0 ;;
    --smoke) smoke ;;
    --up)
        # check 는 --check 에서 정보 출력용으로도 쓰이므로 여기서만 2를 막는다.
        rc=0; check || rc=$?
        [ "$rc" = 1 ] && die "전제조건 실패"
        [ "$rc" = 2 ] && die "호스트가 같은 포트를 쓰고 있다. 해당 프로세스를 먼저 내리고 다시 실행할 것 — 이 스크립트는 남의 서버를 죽이지 않는다."
        sandbox_up ;;
    --down)  down ;;
    *)       die "사용법: $0 [--check|--smoke|--up|--down]" ;;
esac
