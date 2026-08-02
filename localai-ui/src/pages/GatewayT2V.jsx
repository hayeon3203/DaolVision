import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import LoadingSpinner from '../components/LoadingSpinner'
import { gatewayApi } from '../utils/api'

// Task 7.6: T2V 단발샷 카테고리 (이전 I2V 단발샷 대체). anim-agent 게이트웨이
// (:8700) POST /t2v만 호출한다 (Cosmos3-Nano, t2v/cosmos3nano 독립 서버). 사진
// 입력 없음 — 프롬프트만으로 영상 1개. LocalAI 자체 비디오 백엔드는 쓰지 않는다.
export default function GatewayT2V() {
  const [prompt, setPrompt] = useState('')
  const [seed, setSeed] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [video, setVideo] = useState(null)

  const handleGenerate = async (e) => {
    e.preventDefault()
    if (!prompt.trim()) return
    setLoading(true)
    setError(null)
    setVideo(null)
    try {
      const data = await gatewayApi.t2v(prompt.trim(), seed)
      setVideo(data.video_base64 || data.b64_json)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="media-layout">
      <div className="media-controls">
        <PageHeader title={<><i className="fas fa-video" /> T2V 단발샷</>} supporting="프롬프트 → 영상 (Cosmos3-Nano, :8700 게이트웨이)" />
        <form onSubmit={handleGenerate}>
          <div className="form-group">
            <label className="form-label">프롬프트</label>
            <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} placeholder="a paper airplane gliding through a sunlit office..." />
          </div>
          <div className="form-group">
            <label className="form-label">시드 (선택)</label>
            <input className="input" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="랜덤" />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading || !prompt.trim()}>
            {loading ? <><LoadingSpinner size="sm" /> 생성 중... (수 분)</> : <><i className="fas fa-video" /> 생성</>}
          </button>
        </form>
      </div>
      <div className="media-preview">
        <div className="media-result">
          {loading ? (
            <LoadingSpinner size="lg" />
          ) : error ? (
            <p style={{ color: 'var(--color-error)' }}>Error: {error}</p>
          ) : video ? (
            <video controls className="media-result" style={{ minHeight: 0 }} src={`data:video/mp4;base64,${video}`} />
          ) : (
            <div style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>
              <i className="fas fa-video" style={{ fontSize: '3rem', opacity: 0.4 }} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
