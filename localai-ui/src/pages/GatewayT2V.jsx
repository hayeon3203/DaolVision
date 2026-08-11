import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import LoadingSpinner from '../components/LoadingSpinner'
import GatewayPageShell, { GatewayPanels } from '../components/GatewayPageShell'
import { gatewayApi } from '../utils/api'

// Task 7.6: T2V 단발샷 카테고리 (이전 I2V 단발샷 대체). anim-agent 게이트웨이
// (:8700) POST /t2v만 호출한다 (Cosmos3-Nano, t2v/cosmos3nano 독립 서버). 사진
// 입력 없음 — 프롬프트만으로 영상 1개. LocalAI 자체 비디오 백엔드는 쓰지 않는다.
export default function GatewayT2V() {
  const { t } = useTranslation('gateway')
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
      description={t('t2v.description')}
      icon="fa-video"
      models={[{ label: 'Cosmos3-Nano · NVIDIA', company: 'NVIDIA' }]}
      techniques={['Diffusion']}
      facts={[
        { icon: 'fa-align-left', title: t('t2v.facts.prompt.title'), description: t('t2v.facts.prompt.description') },
        { icon: 'fa-dice', title: t('t2v.facts.seed.title'), description: t('t2v.facts.seed.description') },
        { icon: 'fa-clapperboard', title: t('t2v.facts.clip.title'), description: t('t2v.facts.clip.description') },
      ]}
    >
      <GatewayPanels inputDescription={t('t2v.inputDescription')} outputDescription={t('t2v.outputDescription')}>
        <div>
        <form onSubmit={handleGenerate}>
          <div className="form-group">
            <label className="form-label">{t('t2v.promptLabel')}</label>
            <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} placeholder={t('t2v.promptPlaceholder')} />
          </div>
          <div className="form-group">
            <label className="form-label">{t('t2v.seedLabel')}</label>
            <input className="input" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder={t('t2v.seedPlaceholder')} />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading || !prompt.trim()}>
            {loading ? <><LoadingSpinner size="sm" /> {t('t2v.generating')}</> : <><i className="fas fa-video" /> {t('t2v.generate')}</>}
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
