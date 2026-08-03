import { useState } from 'react'
import LoadingSpinner from '../components/LoadingSpinner'
import GatewayPageShell, { GatewayPanels } from '../components/GatewayPageShell'
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
    <GatewayPageShell
      eyebrow="TEXT TO VIDEO"
      title="Text to Video"
      description="한 줄의 아이디어를 움직이는 장면으로"
      icon="fa-video"
      facts={[
        { icon: 'fa-align-left', title: '텍스트 프롬프트', description: '만들고 싶은 장면과 움직임을 자연어로 설명합니다.' },
        { icon: 'fa-dice', title: '재현 가능한 시드', description: '시드를 고정해 같은 조건의 결과를 다시 생성합니다.' },
        { icon: 'fa-clapperboard', title: '단일 영상 클립', description: 'Cosmos3-Nano가 바로 재생 가능한 영상을 완성합니다.' },
      ]}
    >
      <GatewayPanels inputDescription="장면 설명과 생성 조건을 입력하세요." outputDescription="완성된 영상 클립을 확인하세요.">
        <div>
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
      </GatewayPanels>
    </GatewayPageShell>
  )
}
