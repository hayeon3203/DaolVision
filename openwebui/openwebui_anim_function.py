"""
title: Animation Video Agent
author: video_generator
description: LangGraph 기반 애니메이션 영상 생성 에이전트. 시나리오 → 씬분할(승인) → 클립생성(승인)
    → 편집·자막(승인) → 최종본. 3개 사람 승인 체크포인트를 한 대화에서 멀티턴으로 진행한다.
version: 0.3.0
"""
import os
import re
import json
import time
import asyncio
import base64
import html
import tempfile

import requests
from pydantic import BaseModel, Field

# 예전 버전이 메시지 끝에 심던 상태 주석 — OWU가 글자 그대로 노출해서 파일 저장으로 교체했다.
# 옛 대화를 이어받을 수 있도록 읽기(복원)만 남긴다. 새로 쓰지는 않는다.
_MARKER = re.compile(r"<!--anim:([0-9a-f\-]+):([^\-]+-\d+[^>]*)-->")
_SCENES_MARKER = re.compile(r"<!--anim-scenes:([A-Za-z0-9_=-]+)-->")

# 대화 상태 저장소: chat_id → {"job_id": ..., "scenes": [...]}.
# OWU 컨테이너에선 /app/backend/data(볼륨)라 재시작에도 유지된다. 로컬 테스트는 tempdir.
_STATE_FILE = os.path.join(
    "/app/backend/data" if os.path.isdir("/app/backend/data") else tempfile.gettempdir(),
    "anim_agent_state.json")
_ZW0 = "\u200b"
_ZW1 = "\u200c"
_ZW_START = "\u2060\u200b\u200c\u2060"
_ZW_END = "\u2060\u200c\u200b\u2060"


def _state_load(chat_id: str | None) -> dict:
    if not chat_id:
        return {}
    try:
        with open(_STATE_FILE) as f:
            return json.load(f).get(chat_id, {})
    except (OSError, json.JSONDecodeError):
        return {}


def _state_save(chat_id: str | None, **fields):
    """chat_id 엔트리에 fields를 병합. 값 None이면 그 키를 지운다.
    ponytail: 파일 하나 read-modify-write, 락 없음 — 채팅당 파이프 호출은 직렬이라 충분."""
    if not chat_id:
        return
    try:
        with open(_STATE_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    entry = data.setdefault(chat_id, {})
    entry.update(fields)
    for k in [k for k, v in entry.items() if v is None]:
        del entry[k]
    with open(_STATE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)


def _body_vars(body: dict | None) -> dict:
    if not isinstance(body, dict):
        return {}
    info = body.get("m" + "\x65\x74\x61" + "data", {})
    return info if isinstance(info, dict) else {}


def _first_str(sources: list[dict], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        for src in sources:
            if isinstance(src, dict):
                value = src.get(key)
                if value:
                    return str(value)
    return None


def _state_key(body: dict | None, job_id: str | None = None) -> str | None:
    info = _body_vars(body)
    variables = info.get("variables")
    sources = [
        info,
        variables if isinstance(variables, dict) else {},
        body if isinstance(body, dict) else {},
    ]
    chat_id = _first_str(sources, ("chat_id", "session_id", "conversation_id", "thread_id"))
    if chat_id:
        return f"chat:{chat_id}"
    return f"job:{job_id}" if job_id else None


def _hidden_state(job_id: str | None) -> str:
    """대화 id가 빠지는 OWU 경로까지 이어가기 위한 zero-width job_id 백업."""
    if not job_id:
        return ""
    raw = json.dumps({"job_id": job_id}, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    bits = "".join(format(ord(ch), "08b") for ch in encoded)
    return _ZW_START + "".join(_ZW1 if bit == "1" else _ZW0 for bit in bits) + _ZW_END


def _read_hidden_state(text: str) -> dict:
    start = text.rfind(_ZW_START)
    end = text.rfind(_ZW_END)
    if start < 0 or end <= start:
        return {}
    encoded_bits = text[start + len(_ZW_START):end]
    bits = "".join("1" if ch == _ZW1 else "0" for ch in encoded_bits if ch in (_ZW0, _ZW1))
    if len(bits) < 8:
        return {}
    chars = [chr(int(bits[i:i + 8], 2)) for i in range(0, len(bits) - len(bits) % 8, 8)]
    try:
        raw = base64.urlsafe_b64decode("".join(chars).encode())
        data = json.loads(raw.decode())
    except (ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _with_hidden_state(text: str, job_id: str | None) -> str:
    return text + _hidden_state(job_id)


# 승인어. 영어/짧은 감탄사는 단어경계(\b)로, 여러 글자 한글 승인어는 부분일치로 잡는다
# (한글은 \b가 잘 안 걸리고 조사·활용이 붙어 '진행해/오케이요'처럼 변형되기 때문).
# ponytail: 키워드 매칭. '진행 순서 바꿔'처럼 승인어가 다른 뜻으로 쓰인 문장은 승인으로 오인할 수 있음
#           — 문제되면 문장 위치/길이 기반 판별로 승격.
_APPROVE = re.compile(
    r"\b(approve[d]?|ok(ay)?|yes|go)\b"          # 영어
    r"|\b(네|예|응|굿)\b"                          # 짧은 한글 감탄사(단어경계)
    r"|오케이|오키|승인|확정|진행|좋아|좋습니다|그래|고고|콜|가자",  # 여러 글자 한글(부분일치)
    re.I)
_REGEN = re.compile(r"(regen|regenerate|재생성|다시)", re.I)
_REVISE = re.compile(
    r"(revise|edit|change|replace|remove|add|수정|변경|바꿔|바꾸|교체|삭제|추가|"
    r"더\s*.{0,20}(?:해|만들))", re.I)
_IMG_KW = re.compile(r"(사진|이미지|그림|img)", re.I)
_CHARACTER_KW = re.compile(r"(마스코트|캐릭터|로봇|제품|상품|사물|동물|비인간|character|mascot|product|object)", re.I)
_HUMAN_KW = re.compile(r"(사람|인물|인간|여성|남성|직장인|배우|human|person|woman|man)", re.I)
_START_KW = re.compile(r"(첫\s*프레임|시작\s*(?:사진|이미지|장면|프레임)|구도\s*(?:그대로|동일))", re.I)
# M2 이미지 생성 의도: 참조 미첨부일 때 "이미지 그려줘/생성" 요청을 이미지 분기로 태운다.
_IMG_GEN_KW = re.compile(r"(그려\s*줘|그려줘|(?:이미지|그림|사진|캐릭터|마스코트).{0,8}(?:생성|만들|그려|뽑아))", re.I)
# 한글 서수 → ref_images 인덱스(0-based)
_KO_ORD = {"첫": 0, "두": 1, "둘": 1, "세": 2, "셋": 2, "네": 3, "넷": 3, "다섯": 4}


class Pipe:
    class Valves(BaseModel):
        # 컨테이너 → 호스트 에이전트 API
        AGENT_URL: str = Field(default="http://172.16.4.228:8700")
        # 브라우저가 /files 영상을 로드할 때 쓰는 URL (보통 AGENT_URL과 동일)
        BROWSER_URL: str = Field(default="http://172.16.4.228:8700")
        TIMEOUT: int = Field(default=900)

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": "anim-video-agent", "name": "Animation Video Agent"}]

    # ── 대화 상태 복원 (예전 마커 대화 호환용) ─────────────────
    def _find_job(self, messages: list) -> tuple[str | None, str | None]:
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                text = _text(msg.get("content", ""))
                hidden = _read_hidden_state(text)
                if hidden.get("job_id"):
                    return hidden["job_id"], None
                m = _MARKER.search(text)
                if m:
                    return m.group(1), m.group(2)
        return None, None

    def _find_pending_scenes(self, messages: list) -> list[dict] | None:
        """마지막 수정 프리뷰에 보관된 미승인 씬을 복원한다."""
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            m = _SCENES_MARKER.search(_text(msg.get("content", "")))
            if m:
                try:
                    raw = base64.urlsafe_b64decode(m.group(1).encode())
                    scenes = json.loads(raw.decode())
                    return scenes if isinstance(scenes, list) else None
                except (ValueError, json.JSONDecodeError):
                    return None
        return None

    def _render_scene_preview(self, resp: dict, scenes: list[dict]) -> tuple[str, list[str]]:
        """그래프를 resume하지 않고 수정된 씬을 다시 보여준다 (보관은 _state_save가 담당)."""
        preview = dict(resp)
        preview["checkpoint"] = {**resp["checkpoint"], "scenes": scenes,
                                 "message": "수정된 씬입니다. 확인 후 approve 해주세요."}
        return self._render(preview)

    def _extract_images(self, msg: dict) -> list[str]:
        images = []
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url:
                        images.append(url)
        for url in msg.get("images", []) or []:
            images.append(url)
        return images

    # ── 1-4 승인 시 '씬 N에 K번째 사진' 자연어 해석 ────────────
    def _resolve_image(self, text: str, n_refs: int) -> tuple:
        """text에서 이미지 지정을 뽑아 (ref 인덱스, 그 부분을 지운 나머지) 반환. 못 찾으면 (None, text).
        ponytail: 규칙 기반 파서. 표현이 더 다양해지면 LLM 파싱으로 승격."""
        m = re.search(r"img[_\s]?(\d+)", text, re.I)          # 명시적 img_0
        if m:
            return int(m.group(1)), text[:m.start()] + text[m.end():]
        m = re.search(r"(\d+)\s*번?째?\s*(?:사진|이미지|그림)", text)  # 'N번째 사진'
        if m:
            return int(m.group(1)) - 1, text[:m.start()] + text[m.end():]
        m = re.search(r"(첫|두|둘|세|셋|네|넷|다섯)\s*번?째?\s*(?:사진|이미지|그림)", text)  # 한글 서수
        if m:
            return _KO_ORD[m.group(1)], text[:m.start()] + text[m.end():]
        return None, text

    def _image_mentions(self, text: str, n_refs: int) -> list[tuple[int, int, int]]:
        found = []
        pattern = re.compile(r"img[_\s]?(\d+)(?:\.[a-z0-9]+)?|(?:첫|두|둘|세|셋|네|넷|다섯|\d+)[ ]*번?째?[ ]*(?:사진|이미지|그림)", re.I)
        for m in pattern.finditer(text):
            token = m.group(0)
            explicit = re.search(r"img[_\s]?(\d+)", token, re.I)
            numeric = re.match(r"(\d+)", token)
            korean = re.match(r"(첫|두|둘|세|셋|네|넷|다섯)", token)
            idx = int(explicit.group(1)) if explicit else int(numeric.group(1)) - 1 if numeric else _KO_ORD[korean.group(1)]
            if 0 <= idx < n_refs:
                found.append((m.start(), m.end(), idx))
        return found

    def _declared_image_roles(self, text: str, n_refs: int) -> dict[int, str]:
        mentions = self._image_mentions(text, n_refs)
        roles = {}
        for pos, (_, end, idx) in enumerate(mentions):
            next_start = mentions[pos + 1][0] if pos + 1 < len(mentions) else len(text)
            context = text[end:next_start]
            if _CHARACTER_KW.search(context): roles[idx] = "character_ref"
            elif _HUMAN_KW.search(context): roles[idx] = "ref"
        return roles

    def _assignment_clauses(self, text: str, n_refs: int):
        clauses = []
        for part in re.split(r"[.!?。\n]+", text):
            sm = re.search(r"씬\s*([0-9\s,，·와과및]+?)\s*(?:번\s*)?에", part)
            if not sm: continue
            ids = [int(n) for n in re.findall(r"\d+", sm.group(1))]
            mentions = self._image_mentions(part[sm.end():], n_refs)
            if ids and mentions: clauses.append((ids, mentions[-1][2], part))
        return clauses

    def _try_assign_images(self, base: str, job_id: str, text: str, current_scenes=None):
        """사용자가 선언한 이미지 종류와 씬 매핑만 반영한다."""
        try:
            st = requests.get(f"{base}/jobs/{job_id}/state", timeout=30).json()
        except requests.RequestException:
            return None
        vals = st.get("values", {})
        scenes = current_scenes or vals.get("scenes") or []
        refs = vals.get("ref_images") or []
        assignments = self._assignment_clauses(text, len(refs))
        if not scenes or not refs or not assignments: return None
        valid_ids = {s.get("id") for s in scenes}
        if any(i not in valid_ids for ids, _, _ in assignments for i in ids): return None
        roles = self._declared_image_roles(f"{vals.get('script_text', '')}\n{text}", len(refs))
        if any(ref_idx not in roles for _, ref_idx, _ in assignments): return None
        updates = {}
        for ids, ref_idx, clause in assignments:
            role = "start" if _START_KW.search(clause) else roles[ref_idx]
            for scene_id in ids: updates[scene_id] = (refs[ref_idx], role)
        return [{**scene, "matched_image": updates[scene["id"]][0], "image_role": updates[scene["id"]][1]}
                if scene.get("id") in updates else scene for scene in scenes]

    def _revise_scenes(self, base: str, job_id: str, text: str, current_scenes=None):
        """1-4 게이트: 자연어 수정 지시를 백엔드로 보내 재구조화된 scenes를 받는다. 실패 시 None.
        규칙 기반으로 못 잡는 자유형 수정('씬 2를 더 밝게', '마지막 씬 삭제')을 LLM에 위임한다."""
        try:
            r = requests.post(f"{base}/jobs/{job_id}/revise", timeout=200,
                              json={"instruction": text, "scenes": current_scenes})
            r.raise_for_status()
            scenes = r.json().get("scenes")
        except requests.RequestException:
            return None
        return scenes or None

    def _is_approval_only(self, text: str) -> bool:
        """승인어만 있는 턴과 '수정 ... approve'를 구분한다."""
        return bool(re.fullmatch(
            r"\s*(?:approve[d]?|ok(?:ay)?|yes|go|네|예|응|굿|오케이|오키|승인|확정|"
            r"진행|좋아|좋습니다|그래|고고|콜|가자)(?:해|해줘|합니다|요)?[.!?\s]*",
            text, re.I))

    def _classify_approval_intent(self, base: str, checkpoint: str, text: str) -> str:
        """백엔드 LLM 분류를 사용하고, API 장애 시에는 명시적 표현만 보수적으로 판정한다."""
        try:
            r = requests.post(f"{base}/approval-intent", timeout=200,
                              json={"checkpoint": checkpoint, "text": text})
            r.raise_for_status()
            intent = r.json().get("intent")
            if intent in {"approve", "revise", "reject", "ambiguous"}:
                return intent
        except (requests.RequestException, ValueError, AttributeError):
            pass
        if re.fullmatch(r"\s*(?:approve[d]?|승인|확정|ok(?:ay)?|yes)(?:해|해줘|합니다|요)?[.!?\s]*",
                        text, re.I):
            return "approve"
        if re.fullmatch(r"\s*(?:reject|cancel|취소|거절|중단)(?:해|해줘|합니다|요)?[.!?\s]*",
                        text, re.I):
            return "reject"
        if _REGEN.search(text) or _REVISE.search(text):
            return "revise"
        return "ambiguous"

    # ── resume payload 파싱 ──────────────────────────────────
    def _parse_resume(self, checkpoint: str, text: str, intent: str | None = None) -> dict:
        if checkpoint.startswith("2-4"):
            # 시나리오 입력 게이트: 입력 텍스트 전체가 시나리오
            return {"script_text": text}
        if checkpoint.startswith("2-3"):
            # 이미지 승인 게이트: 승인어면 승인, 아니면 수정 텍스트를 feedback으로
            if intent == "approve" or (intent is None and _APPROVE.search(text)):
                return {"approved": True}
            return {"feedback": text}
        if checkpoint.startswith("1-4"):
            if intent == "approve" or (intent is None and _APPROVE.search(text)):
                return {"approved": True}
            return {"approved": False, "revised_script_text": text}
        if checkpoint.startswith("3-5"):
            ids = [int(n) for n in re.findall(r"\d+", text)]
            if intent == "revise" or (intent is None and (_REGEN.search(text) or (ids and not _APPROVE.search(text)))):
                return {"action": "regenerate", "scene_ids": ids}
            return {"action": "approve_all"}
        if checkpoint.startswith("4-5"):
            return {"approved": intent == "approve" if intent is not None else bool(_APPROVE.search(text))}
        return {}

    # ── URL 변환 ─────────────────────────────────────────────
    def _file_url(self, job_id: str, local_path: str) -> str:
        name = local_path.rsplit("/", 1)[-1]
        return f"{self.valves.BROWSER_URL}/files/{job_id}/{name}"

    # ── 렌더 ─────────────────────────────────────────────────
    def _render(self, resp: dict) -> tuple[str, list[str]]:
        """(마크다운 텍스트, embeds용 인라인 영상 HTML 목록)을 반환한다.
        raw <video>는 OWU가 이스케이프해 글자로 노출되므로 영상은 embeds로만 재생."""
        job_id = resp["job_id"]
        vids: list[str] = []
        if resp["status"] != "waiting_for_approval":
            if resp.get("status") == "done":
                url = self.valves.BROWSER_URL + (resp.get("final_video_url") or "")
                vids.append(_video_html(url, "최종 영상"))
                return (f"### ✅ 최종 영상 완성\n\n[⬇ 최종 영상 다운로드]({url})", vids)
            if resp.get("status") == "error":
                return (f"❌ 생성 실패: {resp.get('error')}", vids)
            return (f"진행 중… (phase={resp.get('phase')})", vids)

        cp = resp["checkpoint"]
        name = cp["checkpoint"]
        scenes = cp.get("scenes", [])
        out = [f"### 🎬 {cp.get('message','승인이 필요합니다.')}\n"]

        if name.startswith("2-3"):
            paths = cp.get("gen_image_paths") or ([cp["gen_image_path"]] if cp.get("gen_image_path") else [])
            queries = cp.get("image_queries") or ([cp["image_query"]] if cp.get("image_query") else [])
            for i, img in enumerate(paths):
                url = self._file_url(job_id, img) if img else None
                q = queries[i] if i < len(queries) else ""
                if url:  # 이미지는 markdown 이미지로 인라인 렌더(영상과 달리 이스케이프 안 됨)
                    # 파일명(gen_img_N.png) 고정 → 재생성해도 URL 동일 → 뷰어가 옛 이미지 캐시.
                    # 프롬프트가 바뀔 때마다 쿼리스트링을 바꿔 캐시 무효화.
                    url += f"?v={abs(hash(q)) & 0xffffffff}"
                    out.append(f"![생성 이미지 {i+1}]({url})\n")
                out.append(f"프롬프트 {i+1}: `{q}`\n")
            out.append("**`approve`** 로 이 이미지(들)로 진행 · 수정하려면 원하는 변경을 "
                       "텍스트로 입력 (예: **`더 파랗게 해줘`**, 전체 다시 생성됩니다).")
        elif name.startswith("2-4"):
            out.append("이 이미지로 만들 영상의 **시나리오를 입력**해주세요. "
                       "입력한 시나리오를 기준으로 씬을 나눕니다.")
        elif name.startswith("1-4"):
            out.append("| # | 씬 | 무드 | ref |")
            out.append("|---|---|---|---|")
            for s in scenes:
                out.append(f"| {s['id']} | {s['text']} | {s.get('mood','')} "
                           f"| {s.get('matched_image') or '—'} |")
            out.append("\n**`approve`** 로 승인 · 시나리오를 다시 쓰려면 수정 텍스트 입력 · "
                       "예: **`첫번째 사진은 사람이고 두번째 사진은 마스코트야. 씬 1,2,4에 첫번째 사진(img_0.png) 써줘. 씬 3에 두번째 사진(img_1.png) 써줘.`**")
        elif name.startswith("3-5"):
            for s in scenes:
                url = self._file_url(job_id, s["clip_path"]) if s.get("clip_path") else None
                link = f"[▶ 클립]({url})" if url else "(생성 안됨)"
                if url:
                    vids.append(_video_html(url, f"씬 {s['id']} 클립"))
                out.append(f"- **씬 {s['id']}** ({s.get('mode','?')}): {s['text']}  {link}")
            out.append("\n**`approve`** 전체 승인 · **`재생성 2,4`** 특정 씬만 다시 생성.")
        elif name.startswith("4-5"):
            preview = cp.get("preview_path")
            url = self._file_url(job_id, preview) if preview else None
            if url:
                vids.append(_video_html(url, "편집본"))
            out.append(f"[⬇ 편집본 다운로드]({url})" if url else "(미리보기 없음)")
            out.append("\n**`approve`** 로 최종 확정. 그 외 입력 시 편집을 다시 시도합니다.")

        return "\n".join(out), vids

    # ── 진행상황 폴링 ────────────────────────────────────────
    @staticmethod
    def _comfy_status(comfy) -> str:
        """/status의 comfyui 필드(씬별 큐 상태) → ' · 씬 2 렌더링 중 · 씬 3,4 대기'.
        ComfyUI 경로(STANDIN/SUBJECT_REF) 씬만 잡힌다. :8500 경로 씬은 표시 안 됨."""
        rows = (comfy or {}).get("scenes") or []
        running = [str(r["scene_id"]) for r in rows if r.get("status") == "running"]
        queued = [str(r["scene_id"]) for r in rows if r.get("status") == "queued"]
        parts = ([f"씬 {','.join(running)} 렌더링 중"] if running else []) \
              + ([f"씬 {','.join(queued)} 대기"] if queued else [])
        return (" · " + " · ".join(parts)) if parts else ""

    async def _poll(self, base: str, job_id: str, status, message=None, embed=None) -> dict | None:
        """status가 running이 아니게 될 때까지 폴링하며 진행상황을 흘려보낸다.
        생성이 백그라운드로 도는 동안 OWU 연결을 살려 무한로딩을 방지한다.
        message(채팅 append 이미터)가 있으면 완성된 클립을 즉시 인라인 영상으로 내보낸다.
        반환: 최종 status dict(waiting_for_approval|done|error|idle) 또는 None(타임아웃)."""
        deadline = time.time() + self.valves.TIMEOUT
        shown: set = set()   # 이미 인라인으로 내보낸 씬 id
        while time.time() < deadline:
            try:
                s = await asyncio.to_thread(
                    lambda: requests.get(f"{base}/jobs/{job_id}/status", timeout=30).json())
            except requests.RequestException:
                await asyncio.sleep(3)
                continue
            if s.get("status") != "running":
                return s
            total, done = s.get("clips_total"), s.get("clips_done")
            # 완성된 클립은 전체 완료를 기다리지 않고 채팅에 바로 흘려보낸다.
            if message:
                for c in s.get("clips") or []:
                    sid, url = c.get("scene_id"), c.get("url")
                    if url and sid not in shown:
                        shown.add(sid)
                        video_url = self.valves.BROWSER_URL + url if url.startswith("/") else url
                        await message(f"\n**🎞 씬 {sid} 완성**\n"
                                      f"[▶ 클립 열기 / 다운로드]({video_url})\n")
                        if embed:
                            await embed(_video_html(video_url, f"씬 {sid} 클립"))
            await status(f"🎬 클립 생성 중… {done}/{total}"
                         f"{self._comfy_status(s.get('comfyui'))}"
                         if total else "🎬 장면 구성 중…")
            await asyncio.sleep(4)
        return None

    # ── 메인 ─────────────────────────────────────────────────
    async def pipe(self, body: dict, __event_emitter__=None, __task__=None, **kwargs) -> str:
        if __task__:  # OWU 백그라운드(제목/태그/후속질문 생성)는 이 모델을 재사용 → 스킵
            return "🎬 Animation Video Agent"

        messages = body.get("messages", []) if isinstance(body, dict) else []
        if not messages:
            return "시나리오 텍스트를 입력해 새 영상 작업을 시작하세요."
        last = messages[-1]
        user_text = _text(last.get("content", "")).strip()

        job_id, _ = self._find_job(messages)
        state_key = _state_key(body, job_id)
        state = _state_load(state_key)
        job_id = state.get("job_id") or job_id
        if job_id and not state_key:
            state_key = _state_key(body, job_id)
            state = _state_load(state_key)
            job_id = state.get("job_id") or job_id
        base = self.valves.AGENT_URL

        async def status(msg: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": msg, "done": done}})

        async def message(md: str):
            """어시스턴트 메시지에 내용을 즉시 append (완성 클립 인라인용)."""
            if __event_emitter__:
                await __event_emitter__({"type": "message", "data": {"content": md}})

        async def embed(video_html: str):
            if __event_emitter__:
                await __event_emitter__({"type": "embeds", "data": {"embeds": [video_html]}})

        async def render_response(resp: dict) -> str:
            md, embeds = self._render(resp)
            key = _state_key(body, resp.get("job_id"))
            cp = (resp.get("checkpoint") or {}).get("checkpoint")
            _state_save(key, job_id=resp.get("job_id"), checkpoint=cp)
            for video_html in embeds:
                await embed(video_html)
            return _with_hidden_state(md, resp.get("job_id"))

        # 1) 킥오프. 이제 /jobs·/resume 는 즉시 running을 반환(생성은 에이전트 백그라운드).
        try:
            if not job_id:
                images = self._extract_images(last)
                # M2 진입 분기: 첨부 있으면 기존 경로, 없고 이미지 생성 요청이면 이미지 분기
                payload = {"script_text": user_text, "ref_images": images}
                if not images and _IMG_GEN_KW.search(user_text):
                    payload["image_request"] = user_text
                    await status("🎨 이미지 생성 작업 시작…")
                else:
                    await status("🎬 작업 시작…")
                r = await asyncio.to_thread(
                    lambda: requests.post(f"{base}/jobs", timeout=60, json=payload))
                r.raise_for_status()
                job_id = r.json().get("job_id", job_id)
                state_key = _state_key(body, job_id)
                _state_save(state_key, job_id=job_id, pending_scenes=None)
            else:
                cur = await asyncio.to_thread(
                    lambda: requests.get(f"{base}/jobs/{job_id}/status", timeout=30).json())
                # running 중 입력도 버리지 않는다. 다음 승인 게이트까지 기다린 뒤 같은 입력을 처리한다.
                if cur.get("status") == "running":
                    waited = await self._poll(base, job_id, status, message, embed)
                    if waited is None:
                        await status("입력 보존 중 — 작업이 계속 진행 중", True)
                        _state_save(state_key, job_id=job_id, checkpoint="running-0")
                        return _with_hidden_state(
                            "⏱️ 입력을 보존했지만 아직 승인 단계에 도달하지 못했습니다. "
                            "같은 요청을 다시 보내주세요.",
                            job_id)
                    cur = waited
                if cur.get("status") == "waiting_for_approval":
                    cp = cur["checkpoint"]["checkpoint"]
                    approval_gate = cp.startswith(("2-3", "1-4", "3-5", "4-5"))
                    intent = None
                    if approval_gate:
                        await status("🧠 응답 의도 확인 중…")
                        intent = await asyncio.to_thread(
                            self._classify_approval_intent, base, cp, user_text)
                        if intent in ("reject", "ambiguous"):
                            await status("승인 의사 확인 필요", True)
                            _state_save(state_key, job_id=job_id, checkpoint=cp)
                            guide = ("요청을 취소하거나 거절하셨습니다. 결과는 승인되지 않았습니다. "
                                     "계속하려면 승인 또는 수정 의사를 명확히 입력해주세요."
                                     if intent == "reject" else
                                     "승인 의도를 확실히 판단하지 못했습니다. 진행하려면 승인 의사를, "
                                     "수정하려면 변경할 내용을 구체적으로 입력해주세요.")
                            return _with_hidden_state(f"⚠️ {guide}", job_id)
                    stored = _state_load(state_key)
                    pending = stored.get("pending_scenes") if cp.startswith("1-4") else None
                    if pending is None and cp.startswith("1-4"):
                        pending = self._find_pending_scenes(messages)
                    payload = None
                    if cp.startswith("1-4") and intent == "revise":
                        edited = None
                        if _IMG_KW.search(user_text):
                            edited = await asyncio.to_thread(
                                self._try_assign_images, base, job_id, user_text, pending)
                        if edited is None:
                            await status("✏️ 씬 수정 반영 중…")
                            edited = await asyncio.to_thread(
                                self._revise_scenes, base, job_id, user_text, pending)
                        if edited is None:
                            await status("씬 수정 실패 — 기존 씬 유지", True)
                            _state_save(state_key, job_id=job_id, checkpoint=cp)
                            return _with_hidden_state(
                                "⚠️ 씬 수정 내용을 적용하지 못했습니다. 기존 씬은 변경하지 않았습니다. "
                                "이미지 유형과 씬 번호를 확인해 다시 입력해주세요.",
                                job_id)
                        await status("수정된 씬 확인 대기", True)
                        _state_save(state_key, job_id=job_id, checkpoint=cp, pending_scenes=edited)
                        md, embeds = self._render_scene_preview(cur, edited)
                        for video_html in embeds:
                            await embed(video_html)
                        return _with_hidden_state(md, job_id)
                    if cp.startswith("1-4") and pending is not None:
                        payload = {"approved": True, "scenes": pending}
                    if payload is None:
                        payload = self._parse_resume(cp, user_text, intent=intent)
                    await status("⏳ 처리 중…")
                    r = await asyncio.to_thread(
                        lambda: requests.post(f"{base}/jobs/{job_id}/resume", timeout=60,
                                              json={"payload": payload}))
                    r.raise_for_status()
                    if cp.startswith("1-4") and payload.get("approved"):
                        _state_save(state_key, job_id=job_id, pending_scenes=None)
                elif cur.get("status") in ("done", "error", "idle"):
                    await status("완료", True)
                    return await render_response(cur)
        except requests.RequestException as e:
            await status(f"에이전트 오류: {e}", True)
            return f"⚠️ 에이전트 서버 오류: {e}"

        # 2) 폴링하며 진행상황 스트리밍 → 끝나면 결과 렌더
        resp = await self._poll(base, job_id, status, message, embed)
        if resp is None:
            await status("시간 초과", True)
            _state_save(state_key, job_id=job_id, checkpoint="running-0")
            return _with_hidden_state(
                "⏱️ 생성이 예상보다 오래 걸립니다. 잠시 후 아무 메시지나 보내면 "
                "현재 상태를 다시 확인합니다. (작업은 계속 진행 중)",
                job_id)
        await status("완료", True)
        return await render_response(resp)


def _video_html(url: str, title: str = "영상") -> str:
    """OWU embeds 이벤트에 싣는 iframe 문서. assistant 본문에는 넣지 않는다."""
    safe_url = html.escape(url, quote=True)
    safe_title = html.escape(title, quote=True)
    return (
        "<!DOCTYPE html><html><head>"
        f"<title>{safe_title}</title>"
        "<style>html,body{margin:0;padding:0;background:transparent}"
        "video{width:100%;display:block;border-radius:8px}</style></head>"
        "<body>"
        "<video controls playsinline preload='auto'>"
        f"<source src='{safe_url}' type='video/mp4'></video>"
        "<script>function rh(){parent.postMessage({type:'iframe:height',"
        "height:document.documentElement.scrollHeight},'*');}"
        "window.addEventListener('load',rh);"
        "new ResizeObserver(rh).observe(document.body);</script>"
        "</body></html>"
    )


def _text(content) -> str:
    """OWU 메시지 content(문자열 또는 멀티모달 리스트)에서 텍스트만 뽑는다."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    return ""


if __name__ == "__main__":  # 파서 자체점검: python openwebui_anim_function.py
    p = Pipe()
    idx, rest = p._resolve_image("씬 2랑 4에 첫번째 사진 써줘", 2)
    assert idx == 0 and set(re.findall(r"\d+", rest)) == {"2", "4"}, (idx, rest)
    idx, _ = p._resolve_image("2,4에 img_0 적용", 2); assert idx == 0
    idx, _ = p._resolve_image("씬 3에 두번째 이미지", 2); assert idx == 1
    idx, rest = p._resolve_image("1번째 사진을 2,4에", 2)
    assert idx == 0 and set(re.findall(r"\d+", rest)) == {"2", "4"}, (idx, rest)
    assert p._resolve_image("그냥 승인", 2)[0] is None
    print("parser self-check ok")
