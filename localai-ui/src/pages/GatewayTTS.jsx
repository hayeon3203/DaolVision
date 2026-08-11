import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import LoadingSpinner from '../components/LoadingSpinner'
import GatewayPageShell, { GatewayPanels } from '../components/GatewayPageShell'
import WaveformPlayer from '../components/audio/WaveformPlayer'
import MediaInput from '../components/biometrics/MediaInput'
import { gatewayApi } from '../utils/api'

// Task 6.3: 독립 TTS 카테고리. anim-agent 게이트웨이(:8700) POST /tts/clone만
// 호출한다(Chatterbox V3 zero-shot voice cloning). S1 Agent 파이프의 나레이션
// (/tts/narration, 고정 CC0 화자)과는 완전히 분리된 경로 — 다른 화자로 자동
// 폴백하지 않는다. LocalAI 자체 TTS 백엔드/음성 프로필은 쓰지 않는다.
//
// 참조 음성 입력은 MediaInput(mode="audio")을 재사용한다 — 녹음/중지 버튼,
// WAV 인코딩(useMediaCapture), 녹음 후 미리듣기 + X로 지우고 재녹음이 이미
// biometrics 페이지들에서 검증된 컴포넌트라 새로 안 만든다. "이걸 쓸지 다시
// 녹음할지"는 녹음 직후 자동으로 값이 채워지고(=쓰기), 마음에 안 들면 X로
// 지운 뒤 Record를 다시 누르면 재녹음되는 방식(clear-then-redo) — 별도
// "확정" 버튼을 추가하지 않는다.
export default function GatewayTTS() {
  const { t } = useTranslation('gateway')
  const [text, setText] = useState('')
  const [reference, setReference] = useState(null) // { blob, dataUrl, mime, source, name } | null
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [audioUrl, setAudioUrl] = useState(null)

  const handleGenerate = async (e) => {
    e.preventDefault()
    if (!text.trim() || !reference?.blob) return
    setLoading(true)
    setError(null)
    setAudioUrl(null)
    try {
      const blob = await gatewayApi.ttsClone(text.trim(), reference.blob)
      setAudioUrl(URL.createObjectURL(blob))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <GatewayPageShell
      eyebrow="VOICE CLONING"
      title="TTS (Clone)"
      description={t('tts.description')}
      icon="fa-headphones"
      models={[{ label: 'Chatterbox Multilingual V3 · Resemble AI', company: 'Resemble AI' }]}
      techniques={['Zero-shot Voice Cloning']}
      facts={[
        { icon: 'fa-microphone', title: t('tts.facts.record.title'), description: t('tts.facts.record.description') },
        { icon: 'fa-language', title: t('tts.facts.text.title'), description: t('tts.facts.text.description') },
        { icon: 'fa-wave-square', title: t('tts.facts.clone.title'), description: t('tts.facts.clone.description') },
      ]}
    >
      <GatewayPanels inputDescription={t('tts.inputDescription')} outputDescription={t('tts.outputDescription')}>
        <div>
        <form onSubmit={handleGenerate}>
          <div className="form-group">
            <MediaInput
              mode="audio"
              label={t('tts.referenceLabel')}
              value={reference}
              onChange={setReference}
              onError={(err) => setError(err.message)}
              idPrefix="tts-clone"
            />
          </div>
          <div className="form-group">
            <label className="form-label">{t('tts.textLabel')}</label>
            <textarea className="textarea" value={text} onChange={(e) => setText(e.target.value)} rows={5} placeholder={t('tts.textPlaceholder')} />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading || !text.trim() || !reference?.blob}>
            {loading ? <><LoadingSpinner size="sm" /> {t('tts.generating')}</> : <><i className="fas fa-headphones" /> {t('tts.generate')}</>}
          </button>
        </form>
        </div>
        <div className="media-result">
          {loading ? (
            <LoadingSpinner size="lg" />
          ) : error ? (
            <p style={{ color: 'var(--color-error)' }}>Error: {error}</p>
          ) : audioUrl ? (
            <div className="audio-result">
              <WaveformPlayer src={audioUrl} height={96} download="clone.wav" />
              <div className="result-quote">"{text}"</div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>
              <i className="fas fa-headphones" style={{ fontSize: '3rem', opacity: 0.4 }} />
            </div>
          )}
        </div>
      </GatewayPanels>
    </GatewayPageShell>
  )
}
