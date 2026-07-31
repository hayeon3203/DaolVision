"""
스타일 셀렉터 프롬프트 프리픽스 (Task 4.5, docs/PRD.md R7).

S2 I2I(얼굴사진 → 스타일 변환, Flux Kontext/ComfyUI :8188)용 프리픽스. S1(T2I 앵커/I2V)에는
배선하지 않는다 — S1은 씬마다 LLM이 만드는 style_bible을 그대로 쓴다. S2 /i2i 엔드포인트가
아직 이 레포에 없어 실제 주입 지점은 그 엔드포인트 구현 시 정한다.

순수 긍정 서술로만 써라 — FLUX 계열(Kontext 포함)은 distilled 저스텝 구성에서 negative
prompt 효과가 약하거나 아예 없는 경우가 많다.
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
        assert "no " not in prefix.lower(), f"{key}: negative-prompt 문구 금지(순수 긍정 서술)"
    assert style_prefix(None) == ""
    assert style_prefix("") == ""
    assert style_prefix("does-not-exist") == ""
    print("style_presets self-check ok")
