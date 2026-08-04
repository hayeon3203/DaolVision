import { useState } from 'react'
import LoadingSpinner from '../components/LoadingSpinner'
import GatewayPageShell, { GatewayPanels } from '../components/GatewayPageShell'
import { gatewayApi } from '../utils/api'

// Task 6.3: 독립 T2I 카테고리. anim-agent 게이트웨이(:8700) POST /t2i만 호출한다 —
// LocalAI 자체 T2I 백엔드/모델 레지스트리는 쓰지 않는다.
export default function GatewayT2I() {
  const [prompt, setPrompt] = useState('')
  const [width, setWidth] = useState(1024)
  const [height, setHeight] = useState(1024)
  const [seed, setSeed] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [image, setImage] = useState(null)

  const handleGenerate = async (e) => {
    e.preventDefault()
    if (!prompt.trim()) return
    setLoading(true)
    setError(null)
    setImage(null)
    try {
      const body = { prompt: prompt.trim(), width, height }
      if (seed !== '') body.seed = parseInt(seed, 10)
      const data = await gatewayApi.t2i(body)
      setImage(data.image_base64 || data.b64_json)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <GatewayPageShell
      eyebrow="TEXT TO IMAGE"
      title="Text to Image"
      description="상상한 장면을 선명한 이미지 한 장으로"
      icon="fa-image"
      models={[{ label: 'FLUX.1 Schnell · Black Forest Labs', company: 'Black Forest Labs' }]}
      techniques={['Distilled Diffusion']}
      facts={[
        { icon: 'fa-pen-nib', title: '자유로운 프롬프트', description: '원하는 피사체, 분위기, 조명을 자연어로 묘사합니다.' },
        { icon: 'fa-expand', title: '맞춤 해상도', description: '가로와 세로 크기를 콘텐츠 용도에 맞게 설정합니다.' },
        { icon: 'fa-bolt', title: '빠른 이미지 생성', description: 'Flux.1-schnell이 아이디어를 빠르게 시각화합니다.' },
      ]}
    >
      <GatewayPanels inputDescription="이미지 설명과 크기를 입력하세요." outputDescription="완성된 이미지를 확인하세요.">
        <div>
        <form onSubmit={handleGenerate}>
          <div className="form-group">
            <label className="form-label">프롬프트</label>
            <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} placeholder="a cinematic shot of..." />
          </div>
          <div className="form-grid-2col">
            <div className="form-group">
              <label className="form-label">가로</label>
              <input className="input" type="number" value={width} onChange={(e) => setWidth(parseInt(e.target.value, 10) || 1024)} />
            </div>
            <div className="form-group">
              <label className="form-label">세로</label>
              <input className="input" type="number" value={height} onChange={(e) => setHeight(parseInt(e.target.value, 10) || 1024)} />
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">시드 (선택)</label>
            <input className="input" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="랜덤" />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading || !prompt.trim()}>
            {loading ? <><LoadingSpinner size="sm" /> 생성 중...</> : <><i className="fas fa-wand-magic-sparkles" /> 생성</>}
          </button>
        </form>
        </div>
        <div className="media-result">
          {loading ? (
            <LoadingSpinner size="lg" />
          ) : error ? (
            <p style={{ color: 'var(--color-error)' }}>Error: {error}</p>
          ) : image ? (
            <img src={`data:image/png;base64,${image}`} alt={prompt} style={{ maxWidth: '100%' }} />
          ) : (
            <div style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>
              <i className="fas fa-image" style={{ fontSize: '3rem', opacity: 0.4 }} />
            </div>
          )}
        </div>
      </GatewayPanels>
    </GatewayPageShell>
  )
}
