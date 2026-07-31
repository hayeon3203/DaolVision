"""
스타일 셀렉터 프롬프트 프리픽스 (Task 4.5, docs/PRD.md R7).

S1(영상)·S2(이미지) 씬은 같은 scene["prompt"] 문자열을 공유한다(FLUX.1-schnell T2I 앵커 +
LTX/Wan I2V 클립, nodes.py node_generate_scene_anchors 참조) — prefix 하나면 두 백엔드
모두 커버된다.

FLUX.1-schnell은 guidance_scale=0(CFG 꺼짐, inference_server/flux_server.py)이라
negative prompt가 안 먹는다 — 여기 prefix는 순수 긍정 서술만 담는다. LTX/Wan은 이미
첫 프레임(앵커 이미지) 조건으로 외형이 고정되므로, prefix는 외형 재서술 대신 렌더링
기법/질감/조명 톤만 맡는다.
"""

STYLE_PREFIXES: dict[str, str] = {
    "cinematic": (
        "cinematic film photography, anamorphic lens flare, volumetric lighting, "
        "shallow depth of field, subtle film grain"
    ),
    "anime": (
        "clean cel-shaded anime illustration, crisp linework, vibrant saturated "
        "palette, soft painterly background bokeh"
    ),
    "cyberpunk": (
        "cyberpunk aesthetic, neon-drenched night scene, magenta and cyan rim "
        "lighting, holographic ambient glow, rain-slick reflections"
    ),
    "lowpoly": (
        "low-poly 3D render, flat-shaded geometric faces, simple gradient "
        "lighting, isometric game aesthetic"
    ),
    "claymation": (
        "stop-motion claymation, tactile clay texture, visible fingerprint "
        "imperfections, soft studio lighting"
    ),
    "watercolor": (
        "soft watercolor illustration, visible paper texture, gentle color "
        "bleed, storybook art style"
    ),
}


def style_prefix(style: str | None) -> str:
    """style 키 → prefix 문자열. 미선택/미지원 키는 빈 문자열(기존 LLM 자동 style_bible 유지)."""
    if not style:
        return ""
    return STYLE_PREFIXES.get(style, "")


if __name__ == "__main__":  # 자체 점검
    assert set(STYLE_PREFIXES) == {
        "cinematic", "anime", "cyberpunk", "lowpoly", "claymation", "watercolor",
    }
    for key, prefix in STYLE_PREFIXES.items():
        assert style_prefix(key) == prefix
        assert "no " not in prefix.lower(), f"{key}: negative-prompt 문구 금지(FLUX CFG=0)"
    assert style_prefix(None) == ""
    assert style_prefix("") == ""
    assert style_prefix("does-not-exist") == ""
    print("style_presets self-check ok")
