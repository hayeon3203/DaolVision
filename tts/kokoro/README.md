# Kokoro Korean narration

S1 영상 파이프의 일반 한국어 나레이션 전용 서비스다. 사용자 음성 복제는
담당하지 않으며 Chatterbox V3 경로와 자동 폴백하지 않는다.

```bash
./tts/kokoro/setup.sh
install -m 0644 tts/kokoro/kokoro.service ~/.config/systemd/user/kokoro.service
systemctl --user daemon-reload
systemctl --user enable --now kokoro.service
```

직접 확인:

```bash
curl -fsS -X POST http://127.0.0.1:8503/generate \
  -H 'Content-Type: application/json' \
  -d '{"text":"안녕하세요","language":"ko","speed":1.0}' \
  --output /tmp/kokoro.wav
```

게이트웨이는 `AGENT_KOKORO_URL`(기본 `http://127.0.0.1:8503`)을 통해 이
서비스를 호출하고 `POST /tts/narration`에서 WAV를 반환한다.
