import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import LoadingSpinner from '../components/LoadingSpinner'
import WaveformPlayer from '../components/audio/WaveformPlayer'
import { gatewayApi } from '../utils/api'

// Task 6.3: 독립 TTS 카테고리. anim-agent 게이트웨이(:8700) POST /tts/clone만
// 호출한다(Chatterbox V3 zero-shot voice cloning). S1 Agent 파이프의 나레이션
// (/tts/narration, 고정 CC0 화자)과는 완전히 분리된 경로 — 다른 화자로 자동
// 폴백하지 않는다. LocalAI 자체 TTS 백엔드/음성 프로필은 쓰지 않는다.
export default function GatewayTTS() {
  const [text, setText] = useState('')
  const [referenceFile, setReferenceFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [audioUrl, setAudioUrl] = useState(null)

  const handleGenerate = async (e) => {
    e.preventDefault()
    if (!text.trim() || !referenceFile) return
    setLoading(true)
    setError(null)
    setAudioUrl(null)
    try {
      const blob = await gatewayApi.ttsClone(text.trim(), referenceFile)
      setAudioUrl(URL.createObjectURL(blob))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="media-layout">
      <div className="media-controls">
        <PageHeader title={<><i className="fas fa-headphones" /> 독립 TTS</>} supporting="내 목소리 클론 (Chatterbox V3, :8700 게이트웨이)" />
        <form onSubmit={handleGenerate}>
          <div className="form-group">
            <label className="form-label">참조 음성 (WAV, 본인 소유/사용 허가)</label>
            <input className="input" type="file" accept="audio/wav" onChange={(e) => setReferenceFile(e.target.files[0] || null)} />
          </div>
          <div className="form-group">
            <label className="form-label">텍스트</label>
            <textarea className="textarea" value={text} onChange={(e) => setText(e.target.value)} rows={5} placeholder="한국어 텍스트를 입력하세요" />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading || !text.trim() || !referenceFile}>
            {loading ? <><LoadingSpinner size="sm" /> 생성 중...</> : <><i className="fas fa-headphones" /> 생성</>}
          </button>
        </form>
      </div>
      <div className="media-preview">
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
      </div>
    </div>
  )
}
