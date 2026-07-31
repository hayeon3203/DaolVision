# TTS 선택

## 현재 결정

**Chatterbox Multilingual V3**를 두 경로에 사용한다.

- 영상 나레이션: 고정 CC0 한국어 화자 WAV를 사용하는 `/tts/narration`
- 독립 사용자 음성: 참조 WAV로 zero-shot clone하는 `/tts/clone`

캐나다 Resemble AI 모델이며 MIT 라이선스다. GB10에서 GPU 할당 약 3.0GiB를
실측했다. 사용자 음성 복제에는 음원 권리와 화자 동의가 별도로 필요하다.

## Kokoro를 사용하지 않는 이유

Kokoro-82M은 가볍고 한국어 G2P도 작동하지만 한국어 원어민 화자가 없다.
`af_heart`는 영문 화자이므로 한국어 음소를 입력해도 외국인 억양이 남았다.
G2P는 글자를 발음 기호로 바꿀 뿐 화자의 억양과 음색을 한국어 원어민으로
바꾸지 못한다. 따라서 자동 폴백 없이 Chatterbox 경로만 사용한다.

구현 세부사항: [`tts/chatterbox/README.md`](../tts/chatterbox/README.md)
