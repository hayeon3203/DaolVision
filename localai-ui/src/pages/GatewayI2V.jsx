import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import LoadingSpinner from '../components/LoadingSpinner'
import { gatewayApi } from '../utils/api'

// Task 6.3: I2V 단발샷 카테고리. anim-agent 게이트웨이(:8700) POST /i2v만 호출한다
// (LTX-13B-distilled, Face-ID 없이 사진 1장을 첫 프레임으로). LocalAI 자체 I2V
// 백엔드/모델 레지스트리는 쓰지 않는다.
export default function GatewayI2V() {
  const [prompt, setPrompt] = useState('')
  const [imageFile, setImageFile] = useState(null)
  const [seed, setSeed] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [video, setVideo] = useState(null)

  const handleGenerate = async (e) => {
    e.preventDefault()
    if (!prompt.trim() || !imageFile) return
    setLoading(true)
    setError(null)
    setVideo(null)
    try {
      const data = await gatewayApi.i2v(prompt.trim(), imageFile, seed)
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
        <PageHeader title={<><i className="fas fa-video" /> I2V 단발샷</>} supporting="사진 1장 + 프롬프트 → 영상 (LTX-13B-distilled, :8700 게이트웨이)" />
        <form onSubmit={handleGenerate}>
          <div className="form-group">
            <label className="form-label">사진</label>
            <input className="input" type="file" accept="image/*" onChange={(e) => setImageFile(e.target.files[0] || null)} />
          </div>
          <div className="form-group">
            <label className="form-label">프롬프트</label>
            <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} placeholder="camera slowly pushing in..." />
          </div>
          <div className="form-group">
            <label className="form-label">시드 (선택)</label>
            <input className="input" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="랜덤" />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading || !prompt.trim() || !imageFile}>
            {loading ? <><LoadingSpinner size="sm" /> 생성 중... (수 십초)</> : <><i className="fas fa-video" /> 생성</>}
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
            <video controls className="media-result" style={{ minHeight: 0 }} src={`data:video/webp;base64,${video}`} />
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
