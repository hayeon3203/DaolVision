"""
title: Wan2.2 TI2V-5B
author: local
version: 2.0.0
description: Wan2.2-TI2V-5B text/image-to-video with an LLM director. A planner LLM
  decides single-shot vs multi-cut, rewrites each scene into a detailed cinematic
  prompt (with character lock), generates on the host GPU, stitches cuts, and renders
  inline in chat.
required_open_webui_version: 0.5.0
"""

# Internal Pipe Function (paste into Admin → Functions). Runs inside Open WebUI so it
# receives __event_emitter__ (inline <video> via "embeds") and __task__ (to skip
# background title/tag/follow-up generations). Consolidated single source of truth —
# the external Pipelines variant is retired in favour of this.

import asyncio
import base64
import json
from typing import List, Optional

import requests
from pydantic import BaseModel, Field


def _log(msg: str):
    # print (not logging.info) so it reliably reaches `docker logs open-webui`
    # regardless of Open WebUI's logging config.
    print(f"[wan_director] {msg}", flush=True)


def _extract_image_url(messages: List[dict]) -> Optional[str]:
    """Most recent attached image (data URI or http URL) from chat messages."""
    for msg in reversed(messages or []):
        if msg.get("role") != "user":
            continue
        images = msg.get("images")
        if isinstance(images, list) and images:
            last = images[-1]
            if isinstance(last, str):
                return last
            if isinstance(last, dict):
                return last.get("url") or last.get("image_url")
        content = msg.get("content")
        if isinstance(content, list):
            for part in reversed(content):
                if isinstance(part, dict) and part.get("type") == "image_url":
                    img = part.get("image_url")
                    if isinstance(img, dict) and img.get("url"):
                        return img["url"]
                    if isinstance(img, str):
                        return img
        break
    return None


def _to_base64(image_ref: str) -> str:
    ref = image_ref.strip()
    if ref.startswith("data:") or not ref.startswith(("http://", "https://")):
        return ref
    resp = requests.get(ref, timeout=60)
    resp.raise_for_status()
    return base64.b64encode(resp.content).decode("ascii")


class Pipe:
    class Valves(BaseModel):
        SERVER_URL: str = Field(default="http://172.16.4.228:8500")
        # URL the *browser* uses to load the video inside the iframe.
        VIDEO_BASE_URL: str = Field(default="http://172.16.4.228:8500")
        NUM_FRAMES: int = Field(default=33)                # 4k+1 (Wan VAE temporal=4)
        NUM_INFERENCE_STEPS: int = Field(default=20)       # Wan2.2-TI2V-5B base (~20 sweet spot)
        I2V_NUM_INFERENCE_STEPS: int = Field(default=20)
        FPS: int = Field(default=24)
        NEGATIVE_PROMPT: str = Field(
            default="distorted, deformed, morphing, warped text, glitch, "
                    "flickering, low quality, blurry, artifacts"
        )
        AUTOPLAY: bool = Field(default=True)
        TIMEOUT_SECONDS: int = Field(default=1800)
        # --- LLM director (Ollama on the same host as the GPU server) ---
        OLLAMA_URL: str = Field(default="http://172.16.4.228:11434/api/chat")
        ENHANCE_PROMPT: bool = Field(default=True)         # rough scenario -> cinematic prompt
        ENHANCE_MODEL: str = Field(default="qwen2.5:7b")
        MULTI_CUT: bool = Field(default=True)              # planner: single-shot vs multi-cut reel
        PLAN_MODEL: str = Field(default="exaone3.5:32b")
        MAX_SCENES: int = Field(default=5)
        # Character lock: fix the main person's traits across cuts. Empty = off.
        CHARACTER_SHEET: str = Field(default="")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": "wan2-2-ti2v-5b", "name": "Wan2.2 TI2V-5B (inline)"}]

    # ---------- LLM director ----------
    _PLAN_SYSTEM = (
        "You are a video director. Break the user's request into ordered scenes and output "
        'JSON: {"scenes": ["<scene 1>", "<scene 2>", ...]}.\n'
        "RULES:\n"
        "- If the user describes a SINGLE action, moment, or shot (even a detailed one), "
        "output EXACTLY ONE scene. Do NOT invent extra cuts.\n"
        "- Use MULTIPLE scenes (2-5) ONLY when the user explicitly asks for an ad / story / "
        "sequence, or clearly describes several distinct events or a progression.\n"
        "- Write EVERY scene in KOREAN. Never use Chinese or any other language.\n"
        "- Each scene is a short concrete visual description of that one cut.\n"
        "Examples:\n"
        "User: 고양이가 잔디밭을 걷는다\n"
        '  {"scenes": ["고양이가 잔디밭을 걷는다"]}\n'
        "User: 피곤한 영업사원이 머리를 지끈거린다\n"
        '  {"scenes": ["피곤한 영업사원이 책상에서 머리를 감싸쥔다"]}\n'
        "User: 다올퓨전 광고 만들어줘: 데이터에 파묻힌 직원이 AI로 구원받아 성공한다\n"
        '  {"scenes": ["혼돈의 데이터 화면 앞에서 좌절하는 40대 여성 사업가", '
        '"AI 데이터센터가 뒤엉킨 데이터를 정리해 흐름이 정돈되는 장면", '
        '"밝아진 표정으로 회의실에서 성공적으로 발표하는 그녀"]}'
    )

    _ENHANCE_SYSTEM = (
    "You rewrite a user's short scenario into ONE long, dense, highly detailed 3D animation prompt "
    "for the Wan text-to-video model, strictly matching the style of the reference image 'woman_infront.png'. "
    "LONGER, more specific prompts yield higher quality. Always pack in, in this order: "
    "(1) SUBJECT matching the 3D animated character style of 'woman_infront.png' with consistent traits — "
    "age, ethnicity, expression, and stylized details: smooth subsurface scattering skin, large expressive cartoon-style eyes "
    "with detailed iris reflections, flawlessly rendered volumetric dark hair strands, sharp suit fabric textures, and clean creases; "
    "(2) PRECISE LIGHTING DESIGN — named sources, direction, color temperature, and quality (e.g., warm rim lighting, soft ambient fill, "
    "or volumetric light shafts matching the mood), plus clean stylized rendering shadows; "
    "(3) CAMERA & LENS — cinematic virtual camera, focal length (e.g., 50mm Anamorphic, 85mm), cinematic shallow depth of field, "
    "and smooth camera movement (tracking/pan); "
    "(4) QUALITY TAGS — 3D animated feature film, Disney Pixar style, highly detailed 3D render, Unreal Engine 5 look, cinematic lighting.\n"
    "Write 60-100 words, one paragraph, no line breaks.\n"
    "Example of the required level of extreme detail:\n"
    "User Input: 피곤한 영업사원이 머리를 지끈거린다\n"
    "Output Prompt: A portrait of a tired Asian office worker in his late 40s massaging his temples, "
    "visible skin pores, subtle eye wrinkles, messy hair, loose tie, illuminated by cold fluorescent office lighting "
    "and the soft blue glow of a laptop screen, shot on Sony A7R IV, 85mm lens, f/1.8 aperture, shallow depth of field, "
    "RAW photo, photorealistic, ultra-detailed.\n"
    "(Note: For the main character, always adapt this extreme detail to the 3D animation style of 'woman_infront.png' instead of realism.)\n"
    'Respond ONLY as JSON: {"prompt_en": "..."}'
    )

    def _ollama_json(self, model: str, system: str, user: str, schema: dict, temp: float):
        r = requests.post(
            self.valves.OLLAMA_URL,
            json={
                "model": model, "stream": False, "format": schema,
                "options": {"temperature": temp},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
            },
            timeout=120,
        )
        r.raise_for_status()
        return json.loads(r.json()["message"]["content"])

    def _plan(self, brief: str) -> list:
        """Break a brief into ordered scenes. Returns [brief] (single) on any failure."""
        if not self.valves.MULTI_CUT:
            return [brief]
        try:
            schema = {"type": "object",
                      "properties": {"scenes": {"type": "array", "items": {"type": "string"}}},
                      "required": ["scenes"]}
            scenes = self._ollama_json(self.valves.PLAN_MODEL, self._PLAN_SYSTEM, brief,
                                       schema, 0.3).get("scenes") or []
            scenes = [s.strip() for s in scenes if isinstance(s, str) and s.strip()]
            scenes = scenes[: self.valves.MAX_SCENES] if scenes else [brief]
            _log(f"plan {len(scenes)} cut(s) for {brief[:50]!r}: {scenes}")
            return scenes
        except Exception as e:  # noqa: BLE001 - planner is best-effort
            _log(f"plan failed ({e}), single cut")
            return [brief]

    def _enhance_prompt(self, raw: str) -> str:
        """Rough scenario -> detailed cinematic prompt. Returns raw on any failure."""
        if not self.valves.ENHANCE_PROMPT:
            return raw
        system = self._ENHANCE_SYSTEM
        sheet = self.valves.CHARACTER_SHEET.strip()
        if sheet:
            system += (" CHARACTER LOCK — if the scene contains the main person, render them "
                       "with EXACTLY these fixed, unchanging traits every time, verbatim: "
                       f"{sheet}. Keep face, age, hair, and wardrobe identical.")
        try:
            schema = {"type": "object", "properties": {"prompt_en": {"type": "string"}},
                      "required": ["prompt_en"]}
            expanded = self._ollama_json(self.valves.ENHANCE_MODEL, system, raw,
                                         schema, 0.4).get("prompt_en", "").strip()
            if expanded:
                # Keep the complete enhanced prompt in the Open WebUI container log.
                # JSON encoding guarantees one unambiguous log line even if a model
                # unexpectedly returns quotes or newline characters.
                _log(
                    "enhanced_prompt="
                    + json.dumps(expanded, ensure_ascii=False)
                )
                return expanded
            return raw
        except Exception as e:  # noqa: BLE001
            _log(f"enhance failed ({e}), raw used")
            return raw

    # ---------- rendering ----------
    def _video_html(self, url: str) -> str:
        autoplay = "autoplay muted" if self.valves.AUTOPLAY else ""
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;background:transparent}"
            "video{width:100%;display:block;border-radius:8px}</style></head>"
            "<body>"
            f"<video controls loop playsinline {autoplay}>"
            f"<source src='{url}' type='video/mp4'></video>"
            "<script>function rh(){parent.postMessage({type:'iframe:height',"
            "height:document.documentElement.scrollHeight},'*');}"
            "window.addEventListener('load',rh);"
            "new ResizeObserver(rh).observe(document.body);</script>"
            "</body></html>"
        )

    def _generate(self, endpoint: str, payload: dict) -> dict:
        """Blocking HTTP call — runs in a worker thread to not block the loop."""
        r = requests.post(
            f"{self.valves.SERVER_URL}{endpoint}",
            json=payload,
            timeout=self.valves.TIMEOUT_SECONDS,
        )
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    async def _finish(self, endpoint, payload, status, emitter, scenes_info=None):
        try:
            data = await asyncio.to_thread(self._generate, endpoint, payload)
        except Exception as e:  # noqa: BLE001
            await status(f"생성 실패: {e}", True)
            return f"❌ 생성 실패: {e}"
        url = data.get("video_url", "")
        if url.startswith("/"):
            url = self.valves.VIDEO_BASE_URL.rstrip("/") + url
        await status("✅ 영상 생성 완료", True)
        if emitter and url:
            await emitter({"type": "embeds", "data": {"embeds": [self._video_html(url)]}})
        secs = data.get("seconds")
        scenes = data.get("scenes")
        info = []
        if scenes:
            info.append(f"{scenes}컷")
        if secs:
            info.append(f"{secs}초")
        suffix = f" ({', '.join(info)})" if info else ""
        
        message = f"🎬 영상 생성 완료{suffix}\n\n▶️ [영상 새 탭에서 열기 / 다운로드]({url})"
        
        if scenes_info and self.valves.ENHANCE_PROMPT:
            details_md = "\n\n<details>\n<summary><b>🔍 정교화된 프롬프트 (Enhanced Prompt) 보기</b></summary>\n<div style='margin-top: 10px; padding: 10px; background-color: rgba(0,0,0,0.05); border-left: 4px solid #3b82f6; border-radius: 4px;'>\n"
            for item in scenes_info:
                idx = item["idx"]
                raw = item["raw"]
                enhanced = item["enhanced"]
                if len(scenes_info) > 1:
                    details_md += f"**🎬 {idx}컷** (원문: `{raw}`)\n"
                else:
                    details_md += f"**원문:** `{raw}`\n"
                details_md += f"> {enhanced}\n\n"
            details_md += "</div>\n</details>"
            message += details_md
            
        return message

    async def pipe(self, body: dict, __event_emitter__=None, __task__=None, **kwargs):
        # Background tasks (title / tags / follow-up) reuse this model — skip them.
        if __task__:
            return "🎬 HunyuanVideo"

        messages = body.get("messages", []) if isinstance(body, dict) else []
        prompt = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str):
                    prompt = c.strip()
                elif isinstance(c, list):
                    prompt = " ".join(
                        p.get("text", "") for p in c
                        if isinstance(p, dict) and p.get("type") == "text"
                    ).strip()
                break
        if not prompt:
            return "프롬프트를 입력하세요 (생성할 영상을 묘사)."

        async def status(msg: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": msg, "done": done}}
                )

        image_ref = _extract_image_url(messages)

        # ----- multi-cut branch (text-only): planner decides single vs multi-cut -----
        if self.valves.MULTI_CUT and not image_ref:
            await status("🎬 장면 구성 중… (플래너)")
            scenes = await asyncio.to_thread(self._plan, prompt)
            if len(scenes) > 1:
                await status(f"🎬 멀티컷 {len(scenes)}컷 생성 중… (수 분 소요)")
                enhanced = []
                for s in scenes:
                    enhanced.append(await asyncio.to_thread(self._enhance_prompt, s))
                payload = {
                    "scenes": [{"prompt": p} for p in enhanced],
                    "num_frames": self.valves.NUM_FRAMES,
                    "num_inference_steps": self.valves.NUM_INFERENCE_STEPS,
                    "fps": self.valves.FPS,
                }
                if self.valves.NEGATIVE_PROMPT:
                    payload["negative_prompt"] = self.valves.NEGATIVE_PROMPT
                return await self._finish("/generate_reel", payload, status, __event_emitter__)

        # ----- single clip -----
        if image_ref:
            await status("🖼️ 이미지→영상(I2V) 생성 중… (수 분 소요)")
            try:
                image_b64 = await asyncio.to_thread(_to_base64, image_ref)
            except Exception as e:  # noqa: BLE001
                await status(f"이미지 로드 실패: {e}", True)
                return f"❌ 첨부 이미지 로드 실패: {e}"
            payload = {
                "image": image_b64, "prompt": prompt,
                "num_frames": self.valves.NUM_FRAMES,
                "num_inference_steps": self.valves.I2V_NUM_INFERENCE_STEPS,
                "fps": self.valves.FPS,
            }
            endpoint = "/generate_i2v"
        else:
            await status("✍️ 프롬프트 정교화 중…")
            prompt = await asyncio.to_thread(self._enhance_prompt, prompt)
            await status("🎬 텍스트→영상(T2V) 생성 중… (수 분 소요)")
            payload = {
                "prompt": prompt,
                "num_frames": self.valves.NUM_FRAMES,
                "num_inference_steps": self.valves.NUM_INFERENCE_STEPS,
                "fps": self.valves.FPS,
            }
            endpoint = "/generate"
        if self.valves.NEGATIVE_PROMPT:
            payload["negative_prompt"] = self.valves.NEGATIVE_PROMPT

        return await self._finish(endpoint, payload, status, __event_emitter__)
