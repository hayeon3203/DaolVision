#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/openwebui_animate_function.py"
CONTAINER="open-webui"
FN_ID="wan2_2_animate_14b"

python3 -c "import ast; ast.parse(open('$REPO').read())"
docker cp "$REPO" "$CONTAINER:/tmp/openwebui_animate_function.py"
docker exec -i "$CONTAINER" python3 - "$FN_ID" <<'PY'
import json
import shutil
import sqlite3
import sys
import time

fn_id = sys.argv[1]
db = "/app/backend/data/webui.db"
shutil.copy(db, db + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
code = open("/tmp/openwebui_animate_function.py").read()
now = int(time.time())
conn = sqlite3.connect(db)
cur = conn.cursor()
columns = {row[1] for row in cur.execute("PRAGMA table_info(function)")}
existing = cur.execute("SELECT 1 FROM function WHERE id=?", (fn_id,)).fetchone()
if existing:
    cur.execute("UPDATE function SET content=?, updated_at=? WHERE id=?", (code, now, fn_id))
else:
    values = {
        "id": fn_id,
        "user_id": "",
        "name": "Wan2.2 Animate 14B",
        "type": "pipe",
        "content": code,
        "meta": json.dumps({"description": "Reference image + driving video character animation"}),
        "is_active": 1,
        "is_global": 1,
        "created_at": now,
        "updated_at": now,
    }
    # Copy ownership from the existing local Wan function where required.
    owner = cur.execute(
        "SELECT user_id FROM function WHERE id=?", ("hunyuanvideo_1_5",)
    ).fetchone()
    if owner:
        values["user_id"] = owner[0]
    selected = {key: value for key, value in values.items() if key in columns}
    names = ",".join(selected)
    placeholders = ",".join("?" for _ in selected)
    cur.execute(
        f"INSERT INTO function ({names}) VALUES ({placeholders})",
        tuple(selected.values()),
    )
conn.commit()
print(f"deployed {fn_id} ({len(code)} chars)")
PY

docker restart "$CONTAINER" >/dev/null
for _ in $(seq 1 60); do
    if curl -s -m 3 -o /dev/null http://localhost:8080/health; then
        echo "Animate Function deployed"
        exit 0
    fi
    sleep 2
done
echo "Open WebUI health check failed" >&2
exit 1
