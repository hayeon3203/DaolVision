# Chatterbox Multilingual V3

이 디렉터리는 S1 영상 파이프의 고정 CC0 한국어 나레이션과 독립 TTS
카테고리의 사용자 음성 기반 한국어 생성을 담당한다.

## 확정된 역할

- 영상 생성 파이프: Chatterbox V3 + 고정 CC0 한국어 화자 (`POST /tts/narration`)
- 독립 사용자 음성: Chatterbox Multilingual V3 (`POST /tts/clone`)
- 두 경로 사이 자동 폴백 없음
- 2026-07-31 실제 참조 음성 청취 테스트에서 clone의 화자 유사도 통과

## 설치

DGX Spark/GB10의 ARM64 환경에서는 일반 PyPI가 CPU 전용 PyTorch를 설치한다.
`setup.sh`는 Python 3.11 환경을 만든 뒤 CUDA 13용 PyTorch로 교체하고 GPU를
검증한다.

```bash
chmod +x tts/chatterbox/setup.sh
./tts/chatterbox/setup.sh
```

## 음성 준비

아래 두 파일은 Git에서 제외되는 `private/` 아래에 둔다.

```text
private/tts/voices/my_voice/
├── reference.wav
└── reference.txt
```

- `reference.wav`: 잡음과 배경음악이 없는 한 명의 한국어 음성 10~30초
- `reference.txt`: 녹음에서 실제로 말한 정확한 UTF-8 대본

현재 Chatterbox 추론에는 `reference.txt`가 필요하지 않지만, 원본 검증과 다른
모델 비교를 위해 함께 보관한다.

## 생성

```bash
./.venv-chatterbox/bin/python tts/chatterbox/generate.py \
  --text "안녕하세요. 제 목소리를 기반으로 생성한 테스트 음성입니다."
```

기본 출력은 다음 위치에 저장된다.

```text
out/tts/chatterbox/my_voice/generated.wav
```

## 로컬 API

```bash
./.venv-chatterbox/bin/python tts/chatterbox/server.py

curl -fsS -X POST http://127.0.0.1:8504/generate \
  -F 'text=안녕하세요' \
  -F 'reference=@private/tts/voices/my_voice/reference.wav;type=audio/wav' \
  --output clone.wav
```

게이트웨이 `POST :8700/tts/clone`도 같은 multipart 필드(`text`,
`reference`)를 받습니다. 출력은 24kHz mono PCM 16-bit WAV입니다. Chatterbox
장애 시 다른 화자나 엔진으로 자동 전환하지 않습니다.

다른 참조 음성과 출력 위치를 쓰려면:

```bash
./.venv-chatterbox/bin/python tts/chatterbox/generate.py \
  --reference private/tts/voices/speaker_02/reference.wav \
  --text-file target.txt \
  --output out/tts/chatterbox/speaker_02/test.wav
```
