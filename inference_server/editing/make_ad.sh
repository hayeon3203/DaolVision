#!/usr/bin/env bash
# =============================================================================
# make_ad.sh — HunyuanVideo 클립 편집 파이프라인 (ffmpeg)
#
#   1단계: 정규화 (해상도/fps/코덱 통일)
#   2단계: 이어붙이기 (concat)
#   3단계: 한글 자막 번인 + 배경음악
#
# 사용법:
#   ./make_ad.sh -o final.mp4 [옵션] clip1.mp4 clip2.mp4 ...
#
# 옵션:
#   -o FILE   출력 파일 (필수)
#   -s FILE   SRT 자막 파일 (한글 가능, 영상에 번인)
#   -m FILE   배경음악 (mp3/m4a/wav) — 영상 길이에 맞춰 루프/트림
#   -r WxH    목표 해상도 (기본 854x480)
#   -f FPS    목표 fps (기본 24)
#   -F NAME   자막 폰트 (기본 "Noto Sans CJK KR")
#   -z SIZE   자막 글자 크기 (기본 22)
#   -k        작업 임시폴더 보존 (디버그용)
#   -h        도움말
#
# 예시:
#   ./make_ad.sh -o ad.mp4 -s subs.srt -m bgm.mp3 s1.mp4 s2.mp4 s3.mp4 ending.mp4
# =============================================================================
set -euo pipefail

OUT=""; SRT=""; MUSIC=""; RES="854x480"; FPS="24"
FONT="Noto Sans CJK KR"; FSIZE="22"; KEEP=0

usage() { sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while getopts ":o:s:m:r:f:F:z:kh" opt; do
  case "$opt" in
    o) OUT="$OPTARG" ;;
    s) SRT="$OPTARG" ;;
    m) MUSIC="$OPTARG" ;;
    r) RES="$OPTARG" ;;
    f) FPS="$OPTARG" ;;
    F) FONT="$OPTARG" ;;
    z) FSIZE="$OPTARG" ;;
    k) KEEP=1 ;;
    h) usage 0 ;;
    :) echo "옵션 -$OPTARG 에 값이 필요합니다" >&2; exit 2 ;;
    \?) echo "알 수 없는 옵션 -$OPTARG" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
CLIPS=("$@")

# ---- 검증 -------------------------------------------------------------------
command -v ffmpeg >/dev/null || { echo "❌ ffmpeg 가 없습니다"; exit 1; }
[ -n "$OUT" ] || { echo "❌ -o 출력 파일을 지정하세요"; usage 2; }
[ "${#CLIPS[@]}" -ge 1 ] || { echo "❌ 클립을 1개 이상 지정하세요"; usage 2; }
for c in "${CLIPS[@]}"; do [ -f "$c" ] || { echo "❌ 클립 없음: $c"; exit 1; }; done
[ -z "$SRT" ]   || [ -f "$SRT" ]   || { echo "❌ 자막 파일 없음: $SRT"; exit 1; }
[ -z "$MUSIC" ] || [ -f "$MUSIC" ] || { echo "❌ 음악 파일 없음: $MUSIC"; exit 1; }
W="${RES%x*}"; H="${RES#*x}"

WORK="$(mktemp -d)"
cleanup() { [ "$KEEP" = "1" ] && echo "임시폴더 보존: $WORK" || rm -rf "$WORK"; }
trap cleanup EXIT

echo "▶ 출력: $OUT | 해상도: ${W}x${H} | fps: $FPS | 클립 ${#CLIPS[@]}개"
[ -n "$SRT" ]   && echo "  자막: $SRT (폰트 $FONT/$FSIZE)"
[ -n "$MUSIC" ] && echo "  음악: $MUSIC"

# ---- 1단계: 정규화 ----------------------------------------------------------
# 클립마다 해상도/fps/코덱이 달라 그냥 이어붙이면 깨짐. 동일 규격으로 통일하고
# (가로세로비 유지 + 레터박스 패딩) 오디오는 제거(나중에 음악만 입힘).
echo "── 1단계: 정규화 ──"
LIST="$WORK/list.txt"; : > "$LIST"
i=0
for c in "${CLIPS[@]}"; do
  n=$(printf "norm_%03d.mp4" "$i")
  echo "  [$((i+1))/${#CLIPS[@]}] $(basename "$c")"
  ffmpeg -y -loglevel error -i "$c" \
    -vf "scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=${FPS},format=yuv420p" \
    -c:v libx264 -preset medium -crf 18 -an \
    "$WORK/$n"
  echo "file '$WORK/$n'" >> "$LIST"
  i=$((i+1))
done

# ---- 2단계: 이어붙이기 ------------------------------------------------------
echo "── 2단계: 이어붙이기 ──"
ffmpeg -y -loglevel error -f concat -safe 0 -i "$LIST" -c copy "$WORK/combined.mp4"

# ---- 3단계: 자막 + 음악 -----------------------------------------------------
echo "── 3단계: 자막/음악 ──"
# subtitles 필터는 경로 특수문자에 민감 → 임시폴더로 복사해 단순 경로로 참조.
VF=""
if [ -n "$SRT" ]; then
  cp "$SRT" "$WORK/subs.srt"
  STYLE="FontName=${FONT},FontSize=${FSIZE},PrimaryColour=&H00FFFFFF&,OutlineColour=&H00000000&,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=40"
  VF="subtitles=subs.srt:fontsdir=/usr/share/fonts:force_style='${STYLE}'"
fi

# ffmpeg 인자 조립 (combined 와 subs 는 WORK 기준 상대경로로 실행)
ARGS=(-y -loglevel error -i combined.mp4)
[ -n "$MUSIC" ] && ARGS+=(-stream_loop -1 -i "$(readlink -f "$MUSIC")")
[ -n "$VF" ] && ARGS+=(-vf "$VF")
ARGS+=(-map 0:v)
[ -n "$MUSIC" ] && ARGS+=(-map 1:a -shortest)
if [ -n "$VF" ]; then ARGS+=(-c:v libx264 -preset medium -crf 18); else ARGS+=(-c:v copy); fi
[ -n "$MUSIC" ] && ARGS+=(-c:a aac -b:a 192k)
ARGS+=(-movflags +faststart "$(readlink -f "$OUT" 2>/dev/null || echo "$PWD/$OUT")")

( cd "$WORK" && ffmpeg "${ARGS[@]}" )

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT" 2>/dev/null || echo "?")
echo "✅ 완료: $OUT (${DUR}s)"
