"""
OWU Function(openwebui_anim_function.py) 검증 — OWU UI 없이 멀티턴 대화를 시뮬레이션.

1) 순수 로직(상태 복원, resume 파싱) 단위 assert
2) 라이브 API(:8700)에 3턴 대화: 시작 → approve → approve → 최종본 (4-5 자막편집 게이트 제외)

  ./.venv/bin/python test_anim_function.py            # 순수 로직만
  ./.venv/bin/python test_anim_function.py --live      # 라이브 멀티턴(영상 생성, 수 분)
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools

FUNC = (Path(__file__).resolve().parents[2]
        / "openwebui" / "openwebui_anim_function.py")
spec = importlib.util.spec_from_file_location("anim_fn", FUNC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
Pipe = mod.Pipe


def test_pure():
    p = Pipe()
    # resume 파싱
    assert p._parse_resume("1-4_scene_split", "approve") == {"approved": True}
    # 다양한 승인 표현도 알아듣는다
    for ok in ("그냥 오케이", "진행해", "ㅇㅋ 콜", "좋습니다 가자", "go go"):
        assert p._parse_resume("1-4_scene_split", ok) == {"approved": True}, ok
    assert p._parse_resume("1-4_scene_split", "고양이 이야기로 바꿔") == {
        "approved": False, "revised_script_text": "고양이 이야기로 바꿔"}
    assert p._parse_resume("3-5_clip_approval", "approve") == {"action": "approve_all"}
    assert p._parse_resume("3-5_clip_approval", "재생성 2,4") == {
        "action": "regenerate", "scene_ids": [2, 4]}
    assert p._parse_resume("3-5_clip_approval", "2 4 다시") == {
        "action": "regenerate", "scene_ids": [2, 4]}
    assert p._parse_resume("4-5_edit_review", "승인") == {"approved": True}
    # LLM이 판정한 자연어 의도는 네 승인 게이트의 기존 payload로 변환된다.
    assert p._parse_resume("2-3_image_approval", "마음에 들어, 계속해", "approve") == {
        "approved": True}
    assert p._parse_resume("1-4_scene_split", "이대로 진행해", "approve") == {
        "approved": True}
    assert p._parse_resume("3-5_clip_approval", "문제없어 다음으로", "approve") == {
        "action": "approve_all"}
    assert p._parse_resume("3-5_clip_approval", "2번을 새로 만들어줘", "revise") == {
        "action": "regenerate", "scene_ids": [2]}
    assert p._parse_resume("4-5_edit_review", "좋아", "approve") == {"approved": True}
    # 2-4 시나리오 입력 게이트(M3-1): 입력 전체가 시나리오
    assert p._parse_resume("2-4_scenario_input", "로봇이 산책하다 친구를 만난다") == {
        "script_text": "로봇이 산책하다 친구를 만난다"}
    # zero-width 상태 복원 + 옛 HTML 주석 마커 읽기 호환
    convo = [
        {"role": "user", "content": "시나리오"},
        {"role": "assistant", "content": mod._with_hidden_state("표...", "abc-123")},
    ]
    assert p._find_job(convo) == ("abc-123", None)
    legacy = [{"role": "assistant", "content": "표...\n<!--anim:abc-123:3-5_clip_approval-->"}]
    assert p._find_job(legacy) == ("abc-123", "3-5_clip_approval")
    assert p._find_job([{"role": "user", "content": "hi"}]) == (None, None)
    # 텍스트 추출(멀티모달)
    assert mod._text([{"type": "text", "text": "hello"},
                      {"type": "image_url", "image_url": {"url": "data:..."}}]) == "hello"
    print("PASS: 순수 로직")


def test_approval_intent_classifier():
    """LLM 정상 분류와 파싱 실패 시 보수적 폴백."""
    original = tools.call_llm

    async def answer(value):
        async def fake_call(_system, _user):
            return value
        tools.call_llm = fake_call
        return await tools.classify_approval_intent("1-4_scene_split", "이대로 진행해")

    try:
        result = asyncio.run(answer('{"intent":"approve"}'))
        assert result == {"intent": "approve", "source": "llm"}, result
        result = asyncio.run(answer('{"intent":"unknown"}'))
        assert result == {"intent": "ambiguous", "source": "fallback"}, result
        result = asyncio.run(answer('not json'))
        assert result == {"intent": "ambiguous", "source": "fallback"}, result
    finally:
        tools.call_llm = original

    assert tools.approval_intent_fallback("2-3_image_approval", "승인") == "approve"
    assert tools.approval_intent_fallback("3-5_clip_approval", "재생성 2,4") == "revise"
    assert tools.approval_intent_fallback("4-5_edit_review", "취소") == "reject"
    assert tools.approval_intent_fallback("4-5_edit_review", "글쎄") == "ambiguous"
    print("PASS: 승인 의도 LLM 분류 + 보수적 폴백")


def test_progress_render():
    """SC2·SC4: 본문에는 raw HTML/마커가 없고 video는 embeds로만 렌더."""
    p = Pipe()
    # 씬별 큐 상태 (ComfyUI 경로)
    info = p._comfy_status({"scenes": [
        {"scene_id": 1, "status": "completed"},
        {"scene_id": 2, "status": "running"},
        {"scene_id": 3, "status": "queued"},
        {"scene_id": 4, "status": "queued"}]})
    assert "씬 2 렌더링 중" in info and "씬 3,4 대기" in info, info
    assert p._comfy_status(None) == "" and p._comfy_status({"scenes": []}) == ""
    # 2-4 시나리오 입력(M3-1)
    scen_md, scen_embeds = p._render({"job_id": "x", "status": "waiting_for_approval",
                                      "checkpoint": {"checkpoint": "2-4_scenario_input"}})
    assert "시나리오" in scen_md and "<!--" not in scen_md, scen_md
    assert scen_embeds == []
    # 1-4 씬분할
    split_md, split_embeds = p._render({"job_id": "x", "status": "waiting_for_approval",
                                        "checkpoint": {"checkpoint": "1-4_scene_split",
                                                       "scenes": [{"id": 1,
                                                                   "text": "문을 연다",
                                                                   "mood": "calm"}]}})
    assert "<video" not in split_md and "<!--" not in split_md, split_md
    assert split_embeds == []
    # 최종본 인라인
    done_md, done_embeds = p._render({"job_id": "x", "status": "done",
                                      "final_video_url": "/files/x/final.mp4"})
    assert "<video" not in done_md and "<!--" not in done_md, done_md
    assert len(done_embeds) == 1 and "<video" in done_embeds[0] and "final.mp4" in done_embeds[0]
    # 3-5 클립 인라인
    clips_md, clips_embeds = p._render({"job_id": "x", "status": "waiting_for_approval",
                                        "checkpoint": {"checkpoint": "3-5_clip_approval",
                                                       "scenes": [{"id": 1, "mode": "i2v",
                                                                   "text": "달린다",
                                                                   "clip_path": "/abs/clip1.mp4"}]}})
    assert "<video" not in clips_md and "<!--" not in clips_md, clips_md
    assert len(clips_embeds) == 1 and "clip1.mp4" in clips_embeds[0]
    # 4-5 편집본 인라인
    edit_md, edit_embeds = p._render({"job_id": "x", "status": "waiting_for_approval",
                                      "checkpoint": {"checkpoint": "4-5_edit_review",
                                                     "preview_path": "/abs/preview.mp4"}})
    assert "<video" not in edit_md and "<!--" not in edit_md, edit_md
    assert len(edit_embeds) == 1 and "/files/x/preview.mp4" in edit_embeds[0]
    print("PASS: 진행상태 표기 + 인라인 렌더")


def test_poll_inline():
    """SC3: 폴링 중 완성 클립을 message+embeds 이벤트로 1회씩(중복 없이) 방출."""
    p = Pipe()
    seq = [
        {"status": "running", "clips_total": 2, "clips_done": 0, "clips": [],
         "comfyui": {"scenes": [{"scene_id": 1, "status": "running"},
                                {"scene_id": 2, "status": "queued"}]}},
        {"status": "running", "clips_total": 2, "clips_done": 1,
         "clips": [{"scene_id": 1, "url": "/files/j/clip1.mp4"}],
         "comfyui": {"scenes": [{"scene_id": 1, "status": "completed"},
                                {"scene_id": 2, "status": "running"}]}},
        # 같은 클립이 다시 와도 중복 방출하지 않아야 함
        {"status": "running", "clips_total": 2, "clips_done": 1,
         "clips": [{"scene_id": 1, "url": "/files/j/clip1.mp4"}], "comfyui": {}},
        {"status": "waiting_for_approval", "checkpoint": {"checkpoint": "3-5_clip_approval"}},
    ]

    class _SeqRequests:
        RequestException = mod.requests.RequestException
        def get(self, url, **kw):
            return _FakeResp(seq.pop(0))

    class _FastAsyncio:  # sleep(4) 대기 없이 루프 진행
        to_thread = staticmethod(asyncio.to_thread)
        @staticmethod
        async def sleep(_):
            pass

    statuses, messages, embeds = [], [], []
    async def status(msg, done=False): statuses.append(msg)
    async def message(md): messages.append(md)
    async def embed(video_html): embeds.append(video_html)

    orig_req, orig_aio = mod.requests, mod.asyncio
    mod.requests, mod.asyncio = _SeqRequests(), _FastAsyncio
    try:
        final = asyncio.run(p._poll("http://x", "j", status, message, embed))
    finally:
        mod.requests, mod.asyncio = orig_req, orig_aio

    assert final["status"] == "waiting_for_approval", final
    assert len(messages) == 1 and "clip1.mp4" in messages[0] and "씬 1" in messages[0], messages
    assert "<video" not in messages[0] and "<!--" not in messages[0], messages[0]
    assert len(embeds) == 1 and "<video" in embeds[0] and "clip1.mp4" in embeds[0], embeds
    assert "0/2" in statuses[0] and "씬 1 렌더링 중" in statuses[0] \
        and "씬 2 대기" in statuses[0], statuses[0]
    assert "1/2" in statuses[1] and "남음" not in statuses[1], statuses[1]
    print("PASS: 폴링 인라인 방출(중복 없음)")


class _FakeResp:
    def __init__(self, data): self._data = data
    def json(self): return self._data
    def raise_for_status(self): pass


class _FakeRequests:
    """1-4 승인대기 → 자연어 수정 → revise → resume 흐름을 서버 없이 재현."""
    RequestException = mod.requests.RequestException

    def __init__(self):
        self.resume_payload = "MISSING"
        self.revise_called_with = None

    def get(self, url, **kw):
        if url.endswith("/status"):
            if self.resume_payload == "MISSING":  # resume 전 = 승인대기(1-4)
                return _FakeResp({"job_id": "abc-123", "status": "waiting_for_approval",
                                  "checkpoint": {"checkpoint": "1-4_scene_split"}})
            return _FakeResp({"job_id": "abc-123", "status": "done", "phase": "done",
                              "final_video_url": "/files/abc-123/final.mp4"})
        return _FakeResp({})

    def post(self, url, **kw):
        if url.endswith("/approval-intent"):
            text = kw["json"]["text"]
            intent = "approve" if text == "approve" else "revise"
            return _FakeResp({"intent": intent, "source": "llm"})
        if url.endswith("/revise"):
            self.revise_called_with = kw["json"]["instruction"]
            return _FakeResp({"scenes": [{"id": 1, "text": "밝은 방", "duration": 3, "mood": "bright"}]})
        if url.endswith("/resume"):
            self.resume_payload = kw["json"]["payload"]
            return _FakeResp({"job_id": "abc-123", "status": "running"})
        return _FakeResp({})


def test_revise_routing():
    """1-4 게이트: 자연어 수정 → revise 프리뷰(보류, resume 안 함) →
    다음 턴 approve 시 수정된 scenes를 실어 resume."""
    p = Pipe()
    fake = _FakeRequests()
    orig = mod.requests
    mod.requests = fake
    try:
        convo = [
            {"role": "user", "content": "강아지 이야기"},
            {"role": "assistant", "content": mod._with_hidden_state("표", "abc-123")},
            {"role": "user", "content": "씬 2를 더 밝고 경쾌하게 바꿔줘"},
        ]
        preview = asyncio.run(p.pipe({"messages": convo}))
        assert fake.revise_called_with == "씬 2를 더 밝고 경쾌하게 바꿔줘", fake.revise_called_with
        assert fake.resume_payload == "MISSING", "프리뷰 단계에서 resume하면 안 됨"
        assert "<!--" not in preview and "<video" not in preview, preview[:200]
        assert "수정된 씬" in preview, preview[:200]
        convo += [{"role": "assistant", "content": preview},
                  {"role": "user", "content": "approve"}]
        asyncio.run(p.pipe({"messages": convo}))
    finally:
        mod.requests = orig
    assert fake.resume_payload == {
        "approved": True,
        "scenes": [{"id": 1, "text": "밝은 방", "duration": 3, "mood": "bright"}],
    }, fake.resume_payload
    print("PASS: 자연어 수정 → 프리뷰 보류 → 승인 시 수정 씬 resume")


def test_ambiguous_does_not_resume():
    """모호하거나 거절한 응답은 그래프를 resume하지 않는다."""
    class _IntentRequests(_FakeRequests):
        def post(self, url, **kw):
            if url.endswith("/approval-intent"):
                return _FakeResp({"intent": "ambiguous", "source": "llm"})
            return super().post(url, **kw)

    p, fake = Pipe(), _IntentRequests()
    orig = mod.requests
    mod.requests = fake
    try:
        convo = [
            {"role": "assistant", "content": mod._with_hidden_state("표", "abc-123")},
            {"role": "user", "content": "글쎄"},
        ]
        reply = asyncio.run(p.pipe({"messages": convo}))
    finally:
        mod.requests = orig
    assert fake.resume_payload == "MISSING", fake.resume_payload
    assert "판단하지 못했습니다" in reply, reply
    print("PASS: 모호한 승인 응답은 진행 차단")


def test_live():
    p = Pipe()
    p.valves.AGENT_URL = "http://127.0.0.1:8700"
    p.valves.BROWSER_URL = "http://127.0.0.1:8700"
    messages = [{"role": "user", "content": "강아지가 공원에서 뛰어놀다 지쳐 잔디에 눕는다."}]

    def turn(user_text=None):
        if user_text is not None:
            messages.append({"role": "user", "content": user_text})
        reply = asyncio.run(p.pipe({"messages": messages}))
        messages.append({"role": "assistant", "content": reply})
        return reply

    r1 = turn()
    print("\n[턴1 시작]\n", r1[:400])
    assert "<!--" not in r1 and "<video" not in r1, "1-4 응답에 raw 마커/HTML 노출"
    assert "approve" in r1, "1-4 체크포인트 안내 없음"

    r2 = turn("approve")
    print("\n[턴2 씬승인→클립]\n", r2[:400])
    assert "3-5" in r2 and "/files/" in r2, "3-5 클립 링크 없음"

    r3 = turn("approve")
    print("\n[턴3 클립승인→최종]\n", r3[:300])
    assert "최종 영상" in r3 and "/files/" in r3, "최종본 링크 없음"
    print("\nPASS: 라이브 멀티턴 (시작→2승인→최종본, 4-5 자막편집 게이트 제외)")


if __name__ == "__main__":
    test_pure()
    test_approval_intent_classifier()
    test_progress_render()
    test_poll_inline()
    test_revise_routing()
    test_ambiguous_does_not_resume()
    if "--live" in sys.argv:
        test_live()
