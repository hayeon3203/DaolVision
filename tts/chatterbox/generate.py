#!/usr/bin/env python3
"""Generate Korean speech with Chatterbox Multilingual V3."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import soundfile as sf
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE = (
    REPO_ROOT / "private" / "tts" / "voices" / "my_voice" / "reference.wav"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "out" / "tts" / "chatterbox" / "my_voice" / "generated.wav"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chatterbox Multilingual V3 한국어 음성 복제 테스트"
    )
    text_group = parser.add_mutually_exclusive_group(required=True)
    text_group.add_argument("--text", help="생성할 한국어 문장")
    text_group.add_argument(
        "--text-file",
        type=Path,
        help="생성할 문장이 담긴 UTF-8 텍스트 파일",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=DEFAULT_REFERENCE,
        help=f"참조 음성 WAV (기본값: {DEFAULT_REFERENCE})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"출력 WAV (기본값: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
    )
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    return parser.parse_args()


def read_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        text = args.text
    else:
        try:
            text = args.text_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"텍스트 파일을 읽을 수 없습니다: {exc}") from exc

    text = text.strip()
    if not text:
        raise SystemExit("생성할 문장이 비어 있습니다.")
    return text


def validate_reference(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(
            "참조 음성이 없습니다.\n"
            f"다음 위치에 WAV 파일을 넣으세요: {path}"
        )
    try:
        info = sf.info(path)
    except RuntimeError as exc:
        raise SystemExit(f"참조 음성을 읽을 수 없습니다: {exc}") from exc

    duration = info.frames / info.samplerate
    if duration < 3:
        raise SystemExit(
            f"참조 음성이 {duration:.1f}초로 너무 짧습니다. 10~30초를 권장합니다."
        )
    if duration > 60:
        print(
            f"주의: 참조 음성이 {duration:.1f}초입니다. 앞부분 10초만 조건 생성에 사용됩니다.",
            file=sys.stderr,
        )


def choose_device(requested: str) -> str:
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA를 요청했지만 CUDA 지원 PyTorch/GPU를 찾지 못했습니다.")
    return requested


def main() -> None:
    args = parse_args()
    text = read_text(args)
    reference = args.reference.expanduser().resolve()
    output = args.output.expanduser().resolve()
    validate_reference(reference)
    device = choose_device(args.device)

    torch.manual_seed(args.seed)
    if device == "cuda":
        torch.cuda.manual_seed_all(args.seed)

    print(f"Chatterbox Multilingual V3 로딩 중 ({device})...")
    model = ChatterboxMultilingualTTS.from_pretrained(
        device=device,
        t3_model="v3",
    )

    print(f"한국어 음성 생성 중: {reference}")
    with torch.inference_mode():
        wav = model.generate(
            text,
            language_id="ko",
            audio_prompt_path=str(reference),
            exaggeration=args.exaggeration,
            cfg_weight=args.cfg_weight,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, wav.squeeze().detach().cpu().numpy(), model.sr)
    print(f"생성 완료: {output}")


if __name__ == "__main__":
    main()
