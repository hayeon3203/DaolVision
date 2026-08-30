#!/usr/bin/env bash
# Deploy openwebui_function.py (repo -> Open WebUI DB function.content) and reload.
#
# Open WebUI Functions live in the DB (function table), not a mounted file, so
# deploying = updating function.content and restarting open-webui to recompile.
# This is the single source of truth for the "Wan2.2 TI2V-5B (inline)" model.
#
# 사용법: openwebui_function.py 수정 후  ./deploy_function.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/openwebui_function.py"
CONTAINER="open-webui"
FN_ID="hunyuanvideo_1_5"
PY="${PY:-python3}"

echo "▶ 1/4 문법 검증"
"$PY" -c "import ast; ast.parse(open('$REPO').read())"

echo "▶ 2/4 DB 백업 + 코드 주입"
docker cp "$REPO" "$CONTAINER:/tmp/new_function.py"
docker exec -i "$CONTAINER" python3 - "$FN_ID" <<'PY'
import sqlite3, time, sys, shutil
fn_id = sys.argv[1]
db = "/app/backend/data/webui.db"
shutil.copy(db, db + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
code = open("/tmp/new_function.py").read()
c = sqlite3.connect(db); cur = c.cursor()
cur.execute("UPDATE function SET content=?, updated_at=? WHERE id=?",
            (code, int(time.time()), fn_id))
if cur.rowcount != 1:
    raise SystemExit(f"function id {fn_id!r} not found (rows={cur.rowcount})")
c.commit()
print(f"  updated {cur.rowcount} row; content {len(code)} chars")
PY

echo "▶ 3/4 open-webui 재시작 (함수 재컴파일)"
docker restart "$CONTAINER" >/dev/null

echo "▶ 4/4 기동 대기"
for _ in $(seq 1 30); do
    if curl -s -m 3 -o /dev/null http://localhost:8080/health; then
        echo "✅ 배포 완료 — 함수 재컴파일됨"
        exit 0
    fi
    sleep 2
done
echo "⚠️  기동 확인 실패 — docker logs --tail 40 $CONTAINER 확인"
exit 1
