#!/usr/bin/env bash
# DaolVision 스튜디오 기동 (Task 8.2 / 8.2.1)
#
# 모델 서버 6종을 OpenShell 샌드박스에서 띄우고, 기존 localhost 포트로
# forward 해서 langgraph/tools.py 는 코드 변경 없이 그대로 쓰게 한다.
#
# 설계 요지 — 웨이트는 호스트에 남는다:
#   openshell CLI 엔 호스트 디렉토리 마운트 플래그가 없다(--upload = 복사뿐).
#   대신 클러스터 컨테이너의 도커 볼륨이 양쪽에서 보이고
#     호스트     /var/lib/docker/volumes/openshell-cluster-openshell/_data
#     컨테이너   /var/lib/rancher/k3s
#   모델과 이 볼륨이 같은 파일시스템(ext4, /dev/nvme0n1p2)이라 하드링크로
#   0바이트 스테이징이 된다. 그 뒤 Sandbox CR 에 hostPath 로 물린다.
#
#   서로 다른 bind mount 사이의 link(2) 는 커널이 EXDEV 로 막는다
#   (do_linkat 의 old_path.mnt != new_path.mnt 검사). 그래서 스테이징은
#   반드시 호스트 루트를 단일 마운트로 넣은 컨테이너 안에서 수행한다.
#
# 사용법:
#   ./scripts/start_studio.sh --check        # 아무것도 안 바꾸고 전제조건만 점검
#   ./scripts/start_studio.sh --smoke        # 호스트 venv 가 이미지 안에서 도는지 검증
#   ./scripts/start_studio.sh --stage        # 하드링크 스테이징만
#   ./scripts/start_studio.sh --up           # 스테이징 + 샌드박스 + forward
#   ./scripts/start_studio.sh --down         # forward 해제 + 샌드박스 삭제
#
# --up 은 호스트에서 같은 포트를 이미 쓰고 있으면 거부한다. 돌고 있는 서버를
# 죽이는 건 이 스크립트의 일이 아니다. 정말 바꿀 거면 그 프로세스를 먼저
# 내리고 다시 실행할 것.
set -euo pipefail

CLUSTER_CTR="${OPENSHELL_CLUSTER_CTR:-openshell-cluster-openshell}"
VOLUME="${OPENSHELL_CLUSTER_VOLUME:-openshell-cluster-openshell}"
NAMESPACE="${OPENSHELL_NAMESPACE:-openshell}"
# 스테이징 뿌리. 컨테이너 안에선 /var/lib/rancher/k3s/daol 로 보인다.
STAGE_IN_CTR="/var/lib/rancher/k3s/daol"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERFILE="${REPO_ROOT}/docker/Dockerfile.runtime"

HF_HUB="/home/admin/.cache/huggingface/hub"
# 서비스별 landlock 정책 YAML 을 여기 생성한다(write_policy 참고).
POLICY_DIR="${REPO_ROOT}/docker/policies"

# name | port | gpu | workdir | command | env(공백구분) | mounts(공백구분, 호스트 절대경로)
#
# 마운트는 서비스가 실제로 읽는 것만 준다. HF 캐시 348GB 를 통째로 물리면
# 격리하는 의미가 없어서 모델 디렉토리 단위로 끊었다. 마운트 경로는 파드
# 안에서도 호스트와 **동일한 절대경로**여야 한다 — venv 의 shebang 과
# pyvenv.cfg 가 절대경로로 박혀 있기 때문.
#
# 기본은 읽기전용이다. 하드링크 스테이징은 사본이 아니라 같은 inode 라서,
# 쓰기 가능하게 물리면 샌드박스가 호스트 웨이트를 그대로 덮어쓸 수 있다.
# 쓰기가 실제로 필요한 경로만 `rw:` 를 붙인다:
#   comfyui  — output/ temp/ user/ 에 결과물을 쓴다
#   ollama   — pull 시 blobs/manifests 를 쓴다
read -r -d '' SERVICES <<EOF || true
comfyui|8188|yes|/home/admin/video_generator/ComfyUI|/home/admin/.venv/bin/python main.py --cache-classic --highvram --listen 0.0.0.0|-|rw:/home/admin/video_generator/ComfyUI /home/admin/.venv
t2i|8501|yes|/home/admin/DaolVision/inference_server|/home/admin/huyuan-env/bin/python flux_server.py|HYV_HOST=0.0.0.0 HYV_PORT=8501|/home/admin/DaolVision/inference_server /home/admin/huyuan-env ${HF_HUB}/models--black-forest-labs--FLUX.1-schnell
kokoro|8503|no|/home/admin/DaolVision|/home/admin/DaolVision/.venv-kokoro/bin/python tts/kokoro/server.py|KOKORO_HOST=0.0.0.0 KOKORO_PORT=8503|/home/admin/DaolVision/tts/kokoro /home/admin/DaolVision/.venv-kokoro ${HF_HUB}/models--onnx-community--Kokoro-82M-v1.0-ONNX-timestamped
chatterbox|8504|yes|/home/admin/DaolVision|/home/admin/DaolVision/.venv-chatterbox/bin/python tts/chatterbox/server.py|CHATTERBOX_HOST=0.0.0.0 CHATTERBOX_PORT=8504|/home/admin/DaolVision/tts/chatterbox /home/admin/DaolVision/.venv-chatterbox /home/admin/.local/share/uv/python ${HF_HUB}/models--ResembleAI--chatterbox
cosmos3nano|8505|yes|/home/admin/DaolVision|/home/admin/DaolVision/.venv-cosmos3nano/bin/python t2v/cosmos3nano/server.py|COSMOS3NANO_HOST=0.0.0.0 COSMOS3NANO_PORT=8505 COSMOS3NANO_IDLE_TIMEOUT=86400|/home/admin/DaolVision/t2v/cosmos3nano /home/admin/DaolVision/.venv-cosmos3nano ${HF_HUB}/models--nvidia--Cosmos3-Nano
ollama|11434|yes|/home/admin|/usr/local/bin/ollama serve|OLLAMA_HOST=0.0.0.0:11434 OLLAMA_MAX_LOADED_MODELS=2|/usr/local/bin/ollama rw:/home/admin/.ollama
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

# ---------------------------------------------------------------- preflight

check() {
    local rc=0

    openshell status >/dev/null 2>&1 || { echo "  [x] openshell 게이트웨이 응답 없음"; rc=1; }
    [ "$(docker inspect -f '{{.State.Running}}' "$CLUSTER_CTR" 2>/dev/null)" = "true" ] \
        || { echo "  [x] 클러스터 컨테이너 $CLUSTER_CTR 안 돌고 있음"; rc=1; }
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
            echo "  [!] :$port ($name) 호스트에서 사용 중 — 전환하려면 먼저 내려야 함"
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

# ------------------------------------------------------------ 하드링크 스테이징

stage() {
    # 스테이징 대상 = 전 서비스 마운트 원본의 합집합.
    local paths=()
    while IFS='|' read -r name port gpu workdir cmd env mounts; do
        for m in $mounts; do paths+=("$(mnt_path "$m")"); done
    done < <(each_service)
    # 중복 제거 (HF 캐시 하위처럼 여러 서비스가 같은 경로를 쓰는 경우)
    mapfile -t paths < <(printf '%s\n' "${paths[@]}" | sort -u)

    echo "==> 하드링크 스테이징 (복사 아님, 0바이트)"
    # cp -a 로 디렉토리 트리·심볼릭링크·권한을 살리고, -l 로 일반 파일은
    # 하드링크만 만든다. -n 은 이미 있는 건 건너뛰어 재실행을 idempotent 하게
    # 만든다 — 호스트에 모델을 새로 받았을 때 이 스크립트를 다시 돌리면
    # 새 파일만 링크된다.
    # ponytail: 갱신은 append-only. 호스트에서 지운 파일이 스테이징에 남는다.
    # 정합성이 문제되면 rsync -a --delete --link-dest 로 올릴 것.
    #
    # 볼륨을 `-v VOLUME:/vol` 로 따로 물리면 안 된다. 그러면 원본(/hostfs)과
    # 목적지(/vol)가 서로 다른 마운트가 돼서 link(2) 가 EXDEV 로 죽는다
    # (실측: "cp: can't create ...: Cross-device link"). 반드시 /hostfs 하나만
    # 물리고 그 **안에서** 볼륨 실경로를 찾아가야 같은 마운트가 된다.
    local vol_mount
    vol_mount=$(docker volume inspect "$VOLUME" -f '{{.Mountpoint}}')
    [ -n "$vol_mount" ] || die "볼륨 $VOLUME 을 찾을 수 없음"

    # 경로는 sh -c 문자열에 끼워넣지 않고 위치인자로 넘긴다 — 이 컨테이너는
    # 호스트 루트를 쥐고 있어서 문자열 보간 사고의 대가가 크다.
    docker run --rm -v /:/hostfs alpine sh -c '
        set -e
        stage="/hostfs$1"; shift
        mkdir -p "$stage"
        for p in "$@"; do
            dst="${stage}${p}"
            # 목적지 부모까지만 만들고 leaf 는 cp 가 만들게 둔다. dst 를 미리
            # 만들어두고 `cp -a src dst` 하면 dst/leaf 로 한 겹 더 파묻힌다.
            mkdir -p "$(dirname "$dst")"
            cp -aln "/hostfs${p}" "$(dirname "$dst")/"
            echo "  linked $p"
        done' _ "${vol_mount}/daol" "${paths[@]}"
}

# ------------------------------------------------------------ 샌드박스 기동

sandbox_up() {
    while IFS='|' read -r name port gpu workdir cmd env mounts; do
        echo "==> $name (:$port)"

        # 정책은 반드시 create 시점에 준다. CR 을 재생성하면 openshell 서버가
        # 그 샌드박스의 spec 을 잃어버려서 이후 `policy set` 이
        # "sandbox has no spec" 으로 실패한다(실측). 그래서 매번 지우고
        # 정책과 함께 새로 만든다 — 상태 드리프트도 같이 없어진다.
        write_policy "$name" "$workdir" "$gpu" "$mounts"
        openshell sandbox delete "$name" >/dev/null 2>&1 || true

        # CLI 로 만들어야 openshell.ai/sandbox-id 라벨과 로컬 메타데이터가
        # 남는다. kubectl 로 CR 을 직접 만들면 `openshell sandbox list` 에
        # 안 잡혀서 8.2.1 acceptance 가 깨진다.
        local gpuflag=()
        [ "$gpu" = yes ] && gpuflag=(--gpu)
        # 이미지를 게이트웨이로 밀어넣는 데 5분이 넘게 걸리면 CLI 가
        # provisioning timeout 으로 실패를 반환한다 — 그래도 샌드박스는
        # 계속 올라온다. 여기서 죽으면 뒤 단계가 통째로 날아가므로
        # 실패를 삼키고 Ready 를 직접 기다린다.
        # --no-tty 없으면 비대화 세션(nohup/setsid/CI)에서 PTY 할당을 시도하다
        # 시그널로 스크립트째 죽는다 — 로그가 create 출력에서 뚝 끊긴다.
        # create 는 `-- sleep infinity` 를 줘도 샌드박스 로그인 셸에 붙는다.
        # 그 셸이 터미널을 만지면서 호출한 스크립트까지 시그널로 죽인다
        # (로그가 "Requesting compute..." 에서 끊김). setsid 로 세션을 끊고
        # stdin 을 막아 격리한다.
        setsid openshell sandbox create --name "$name" "${gpuflag[@]}" --no-tty \
            --policy "${POLICY_DIR}/${name}.yaml" \
            --from "$DOCKERFILE" -- sleep infinity < /dev/null || true
        wait_ready "$name" || die "$name 이 Ready 가 되지 않음"

        patch_cr "$name" "$workdir" "$cmd" "$env" "$mounts"
        # forward start 는 포그라운드로 붙잡는다(Ctrl+C 대기). --background 필수.
        openshell forward start --background "$port" "$name"
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

# CR 의 podTemplate 에 hostPath 마운트·환경변수·실행커맨드를 주입한다.
# CRD 는 strategic merge 를 안 쓰므로 배열이 통째로 갈린다 — 현재 CR 을 읽어
# 병합한 뒤 apply 하는 방식이어야 supervisor 볼륨(openshell-supervisor-bin,
# TLS secret, workspace PVC)이 살아남는다.
patch_cr() {
    local name="$1" workdir="$2" cmd="$3" env="$4" mounts="$5"
    local tmp; tmp=$(mktemp); trap 'rm -f "$tmp"' RETURN
    docker exec "$CLUSTER_CTR" kubectl get sandbox "$name" -n "$NAMESPACE" -o json \
    | python3 -c '
import json, os, sys
name, workdir, cmd, envstr, mountstr, stage = sys.argv[1:7]
cr = json.load(sys.stdin)
spec = cr["spec"]["podTemplate"]["spec"]
ctr = next(c for c in spec["containers"] if c["name"] == "agent")

vols = {v["name"]: v for v in spec.get("volumes", [])}
mnts = {m["mountPath"]: m for m in ctr.get("volumeMounts", [])}
for i, entry in enumerate(mountstr.split()):
    # "rw:" 가 붙은 것만 쓰기 가능. 하드링크 스테이징은 호스트 파일과 같은
    # inode 라서 기본 readOnly 가 웨이트 보호선이다.
    writable = entry.startswith("rw:")
    host_path = entry[3:] if writable else entry
    vname = "daol-%d" % i
    vols[vname] = {"name": vname,
                   "hostPath": {"path": stage + host_path,
                                "type": "Directory" if os.path.isdir(host_path) else "File"}}
    mnts[host_path] = {"name": vname, "mountPath": host_path, "readOnly": not writable}
spec["volumes"] = list(vols.values())
ctr["volumeMounts"] = list(mnts.values())

envs = {e["name"]: e for e in ctr.get("env", [])}
if envstr != "-":
    for kv in envstr.split():
        k, _, v = kv.partition("=")
        envs[k] = {"name": k, "value": v}
# supervisor 는 이 값을 공백으로 단순 분해해 argv 로 exec 한다. 셸이 아니라
# 따옴표를 이해하지 못하므로 `sh -c '...'` 로 감싸면 깨진다
# (실측: "/home/admin/DaolVision: 1: Syntax error: Unterminated quoted string").
# 그래서 cd 는 커맨드에 넣지 않고 파드 workingDir 로 처리한다.
ctr["workingDir"] = workdir
envs["OPENSHELL_SANDBOX_COMMAND"] = {"name": "OPENSHELL_SANDBOX_COMMAND", "value": cmd}
ctr["env"] = list(envs.values())

# 서버가 재발급하는 필드를 털어내야 다시 apply 할 수 있다.
for junk in ("resourceVersion", "uid", "creationTimestamp", "generation",
             "managedFields", "selfLink"):
    cr["metadata"].pop(junk, None)
cr.pop("status", None)
json.dump(cr, sys.stdout)
' "$name" "$workdir" "$cmd" "$env" "$mounts" "$STAGE_IN_CTR" > "$tmp"

    # podTemplate 을 고쳐도 컨트롤러가 파드를 굴려주지 않는다. 파드만 지우면
    # 컨트롤러가 **옛 템플릿으로** 다시 만든다(실측). CR 자체를 지우고 다시
    # 만들어야 새 템플릿이 반영된다. 라벨(openshell.ai/sandbox-id)을 그대로
    # 들고 가므로 CLI 쪽 메타데이터는 유지된다.
    # 지우기 전에 새로 쓸 CR 이 손에 있는지 확인한다. get/python 이 실패하면
    # 살아있는 CR 만 날리고 복구할 게 없다.
    [ -s "$tmp" ] || die "$name CR 생성 실패 — 삭제하지 않고 중단"
    docker exec "$CLUSTER_CTR" kubectl delete sandbox "$name" -n "$NAMESPACE" --wait=true >/dev/null
    docker exec -i "$CLUSTER_CTR" kubectl apply -f - < "$tmp" >/dev/null
    echo "  CR 재생성 완료 (마운트 $(echo $mounts | wc -w)개)"
    wait_ready "$name" || die "$name 패치 후 Ready 실패"
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
    --stage) stage ;;
    --up)
        # check 는 --check 에서 정보 출력용으로도 쓰이므로 여기서만 2를 막는다.
        rc=0; check || rc=$?
        [ "$rc" = 1 ] && die "전제조건 실패"
        [ "$rc" = 2 ] && die "호스트가 같은 포트를 쓰고 있다. 해당 프로세스를 먼저 내리고 다시 실행할 것 — 이 스크립트는 남의 서버를 죽이지 않는다."
        stage; sandbox_up ;;
    --down)  down ;;
    *)       die "사용법: $0 [--check|--stage|--up|--down]" ;;
esac
