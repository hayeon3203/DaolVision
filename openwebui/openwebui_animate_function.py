"""
title: Wan2.2 Animate 14B
author: local
version: 1.0.0
description: Animate a reference character from an attached driving video.
required_open_webui_version: 0.5.0
"""

import asyncio
import base64
import os
from typing import Any, Iterable, Optional

import requests
from pydantic import BaseModel, Field


def _log(message: str):
    print(f"[wan_animate] {message}", flush=True)


def _filename(item: dict) -> str:
    nested = item.get("file") if isinstance(item.get("file"), dict) else {}
    return str(
        item.get("filename") or item.get("name")
        or nested.get("filename") or nested.get("name") or ""
    )


def _mime(item: dict) -> str:
    nested = item.get("file") if isinstance(item.get("file"), dict) else {}
    return str(
        item.get("content_type") or item.get("type") or item.get("mime_type")
        or nested.get("content_type") or nested.get("mime_type") or ""
    ).lower()


def _reference(item: Any) -> Optional[str]:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    nested = item.get("file") if isinstance(item.get("file"), dict) else {}
    for source in (item, nested):
        value = (
            source.get("url") or source.get("image_url") or source.get("data")
            or source.get("content") or source.get("id")
        )
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            nested_value = value.get("url") or value.get("content")
            if isinstance(nested_value, str) and nested_value:
                return nested_value
    return None


def _attachments(body: dict, messages: list, injected_files: Any) -> Iterable[dict]:
    collections = [body.get("files"), injected_files]
    for message in messages:
        collections.extend([message.get("files"), message.get("images")])
        content = message.get("content")
        if isinstance(content, list):
            collections.append(content)
    for collection in collections:
        if not isinstance(collection, list):
            continue
        for item in collection:
            if isinstance(item, str):
                yield {"url": item}
            elif isinstance(item, dict):
                yield item


def _is_image(item: dict) -> bool:
    mime, name = _mime(item), _filename(item).lower()
    return mime.startswith("image/") or name.endswith(
        (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    ) or item.get("type") == "image_url"


def _is_video(item: dict) -> bool:
    mime, name = _mime(item), _filename(item).lower()
    return mime.startswith("video/") or name.endswith(
        (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
    ) or item.get("type") == "video_url"


def _download(ref: str, request: Any, webui_url: str) -> bytes:
    value = ref.strip()
    if value.startswith("data:"):
        return base64.b64decode(value.partition(",")[2])
    if value.startswith(("http://", "https://")):
        url = value
    elif value.startswith("/"):
        url = webui_url.rstrip("/") + value
    else:
        url = webui_url.rstrip("/") + f"/api/v1/files/{value}/content"
    headers = {}
    request_headers = getattr(request, "headers", None)
    if request_headers:
        authorization = request_headers.get("authorization")
        cookie = request_headers.get("cookie")
        if authorization:
            headers["Authorization"] = authorization
        if cookie:
            headers["Cookie"] = cookie
    response = requests.get(url, headers=headers, timeout=180)
    response.raise_for_status()
    return response.content


class Pipe:
    class Valves(BaseModel):
        SERVER_URL: str = Field(default="http://172.16.4.228:8600")
        VIDEO_BASE_URL: str = Field(default="http://172.16.4.228:8600")
        OPEN_WEBUI_URL: str = Field(default="http://localhost:8080")
        NUM_INFERENCE_STEPS: int = Field(default=20)
        GUIDANCE_SCALE: float = Field(default=1.0)
        FPS: int = Field(default=16)
        SEED: int = Field(default=-1, description="-1 uses a random seed")
        TIMEOUT_SECONDS: int = Field(default=3600)
        NEGATIVE_PROMPT: str = Field(
            default="distorted face, deformed hands, identity drift, flickering, blurry"
        )

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": "wan2-2-animate-14b", "name": "Wan2.2 Animate 14B"}]

    def _video_html(self, url: str) -> str:
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;background:transparent}"
            "video{width:100%;display:block;border-radius:8px}</style></head>"
            "<body><video controls loop playsinline autoplay muted>"
            f"<source src='{url}' type='video/mp4'></video></body></html>"
        )

    def _call_server(self, payload: dict) -> dict:
        response = requests.post(
            self.valves.SERVER_URL.rstrip("/") + "/animate",
            json=payload,
            timeout=self.valves.TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        return response.json()

    async def pipe(
        self,
        body: dict,
        __event_emitter__=None,
        __task__=None,
        __request__=None,
        __files__=None,
        **kwargs,
    ):
        if __task__:
            return "🎭 Wan Animate"

        messages = body.get("messages", []) if isinstance(body, dict) else []
        prompt = "A person performs the motion naturally."
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                prompt = content.strip()
            elif isinstance(content, list):
                text = " ".join(
                    part.get("text", "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ).strip()
                if text:
                    prompt = text
            break

        image_ref = None
        video_ref = None
        seen = list(_attachments(body, messages, __files__))
        for item in reversed(seen):
            ref = _reference(item)
            if not ref:
                continue
            if image_ref is None and _is_image(item):
                image_ref = ref
            elif video_ref is None and _is_video(item):
                video_ref = ref

        if not image_ref or not video_ref:
            return (
                "기준 인물 이미지 1개와 동작 영상 1개를 함께 첨부하세요. "
                "동작 영상은 한 명이 전신으로 보이는 5초 이내 영상이 가장 안정적입니다."
            )

        async def status(text: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": text, "done": done}}
                )

        try:
            await status("📎 기준 이미지와 동작 영상 읽는 중…")
            image_bytes, video_bytes = await asyncio.gather(
                asyncio.to_thread(
                    _download, image_ref, __request__, self.valves.OPEN_WEBUI_URL
                ),
                asyncio.to_thread(
                    _download, video_ref, __request__, self.valves.OPEN_WEBUI_URL
                ),
            )
            payload = {
                "image": base64.b64encode(image_bytes).decode("ascii"),
                "video": base64.b64encode(video_bytes).decode("ascii"),
                "prompt": prompt,
                "negative_prompt": self.valves.NEGATIVE_PROMPT or None,
                "num_inference_steps": self.valves.NUM_INFERENCE_STEPS,
                "guidance_scale": self.valves.GUIDANCE_SCALE,
                "fps": self.valves.FPS,
                "seed": None if self.valves.SEED < 0 else self.valves.SEED,
            }
            _log(f"request prompt={prompt!r}, image={len(image_bytes)}B, video={len(video_bytes)}B")
            await status("🦴 동작·표정 분석 후 캐릭터 영상 생성 중…")
            data = await asyncio.to_thread(self._call_server, payload)
        except Exception as exc:  # noqa: BLE001
            _log(f"generation failed: {exc}")
            await status(f"생성 실패: {exc}", True)
            return f"❌ Animate 생성 실패: {exc}"

        url = data.get("video_url", "")
        if url.startswith("/"):
            url = self.valves.VIDEO_BASE_URL.rstrip("/") + url
        await status("✅ 캐릭터 영상 생성 완료", True)
        if __event_emitter__ and url:
            await __event_emitter__(
                {"type": "embeds", "data": {"embeds": [self._video_html(url)]}}
            )
        seconds = data.get("seconds")
        suffix = f" ({seconds}초 소요)" if seconds else ""
        return f"🎭 Wan Animate 생성 완료{suffix}\n\n▶️ [영상 열기 / 다운로드]({url})"
