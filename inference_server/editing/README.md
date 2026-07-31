# 편집 파이프라인 (make_ad.sh)

HunyuanVideo 클립들을 이어붙여 한글 자막·배경음악이 들어간 광고 영상으로 만듭니다.
서버와 무관하게 셸에서 독립 실행됩니다.

## 단계
1. 정규화 — 클립별 해상도/fps/코덱을 통일 (가로세로비 유지 + 레터박스)
2. 이어붙이기 — concat
3. 한글 자막 번인 (Noto Sans CJK KR) + 배경음악 (길이에 맞춰 루프/트림)

## 사용법
```bash
cd ~/video_generator/hunyuan_server/editing

./make_ad.sh -o final.mp4 \
  -s subs.srt \          # (선택) 한글 자막 SRT
  -m bgm.mp3 \           # (선택) 배경음악
  clip1.mp4 clip2.mp4 clip3.mp4 ending.mp4   # 순서대로 클립 나열
```

옵션: -r 854x480(해상도) -f 24(fps) -F "폰트명" -z 22(자막크기) -k(임시폴더보존) -h(도움말)

## 자막 파일(SRT) 형식 — sample_subs.srt 참고
```
1
00:00:00,000 --> 00:00:02,400
첫 자막 줄

2
00:00:02,500 --> 00:00:05,000
두 번째 자막 줄
```
시간은 `시:분:초,밀리초`. 장면 길이에 맞춰 타임코드를 적으면 됩니다.

## 생성 클립 위치
`~/video_generator/hunyuan_server/outputs/` — 파일명이 `날짜_시각_ID.mp4` 라 시간순 구분 가능.
