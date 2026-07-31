#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
voice_dir="${repo_root}/private/tts/voices/narrator_cc0"
source_dir="${voice_dir}/source"
api_json="${source_dir}/wikimedia-api.json"
concat_list="${source_dir}/concat.txt"
user_agent="DaolVision/1.0 (local TTS reference builder)"

mkdir -p "${source_dir}"

curl -fsSG -A "${user_agent}" "https://commons.wikimedia.org/w/api.php" \
  --data-urlencode "action=query" \
  --data-urlencode "generator=categorymembers" \
  --data-urlencode "gcmtitle=Category:Lingua Libre pronunciation by CHK2605" \
  --data-urlencode "gcmtype=file" \
  --data-urlencode "gcmlimit=10" \
  --data-urlencode "prop=imageinfo" \
  --data-urlencode "iiprop=url|mime|size" \
  --data-urlencode "format=json" \
  --output "${api_json}"

: >"${concat_list}"
jq -r '.query.pages[] | select(.imageinfo[0].mime == "audio/wav")
       | [.title, .imageinfo[0].url] | @tsv' "${api_json}" \
  | sort \
  | while IFS=$'\t' read -r title url; do
      filename="${title#File:}"
      if [[ ! -s "${source_dir}/${filename}" ]]; then
        curl -fsSL -A "${user_agent}" --retry 5 --retry-all-errors \
          --retry-delay 2 "${url}" --output "${source_dir}/${filename}"
        sleep 0.5
      fi
      printf "file '%s'\n" "${source_dir}/${filename}" >>"${concat_list}"
    done

ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "${concat_list}" \
  -ar 24000 -ac 1 -c:a pcm_s16le \
  "${voice_dir}/reference.wav"

ffprobe -v error \
  -show_entries format=duration \
  -show_entries stream=codec_name,sample_rate,channels \
  -of default=noprint_wrappers=1 \
  "${voice_dir}/reference.wav"
