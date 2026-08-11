import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import LoadingSpinner from '../components/LoadingSpinner'
import GatewayPageShell, { GatewayPanels } from '../components/GatewayPageShell'
import { gatewayApi } from '../utils/api'

// Task 6.3: 독립 T2I 카테고리. anim-agent 게이트웨이(:8700) POST /t2i만 호출한다 —
// LocalAI 자체 T2I 백엔드/모델 레지스트리는 쓰지 않는다.
export default function GatewayT2I() {
  const { t } = useTranslation('gateway')
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
      description={t('t2i.description')}
      icon="fa-image"
      models={[{ label: 'FLUX.1 Schnell · Black Forest Labs', company: 'Black Forest Labs' }]}
      techniques={['Distilled Diffusion']}
      facts={[
        { icon: 'fa-pen-nib', title: t('t2i.facts.prompt.title'), description: t('t2i.facts.prompt.description') },
        { icon: 'fa-expand', title: t('t2i.facts.resolution.title'), description: t('t2i.facts.resolution.description') },
        { icon: 'fa-bolt', title: t('t2i.facts.speed.title'), description: t('t2i.facts.speed.description') },
      ]}
    >
      <GatewayPanels inputDescription={t('t2i.inputDescription')} outputDescription={t('t2i.outputDescription')}>
        <div>
        <form onSubmit={handleGenerate}>
          <div className="form-group">
            <label className="form-label">{t('t2i.promptLabel')}</label>
            <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} placeholder="a cinematic shot of..." />
          </div>
          <div className="form-grid-2col">
            <div className="form-group">
              <label className="form-label">{t('t2i.widthLabel')}</label>
              <input className="input" type="number" value={width} onChange={(e) => setWidth(parseInt(e.target.value, 10) || 1024)} />
            </div>
            <div className="form-group">
              <label className="form-label">{t('t2i.heightLabel')}</label>
              <input className="input" type="number" value={height} onChange={(e) => setHeight(parseInt(e.target.value, 10) || 1024)} />
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">{t('t2i.seedLabel')}</label>
            <input className="input" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder={t('t2i.seedPlaceholder')} />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading || !prompt.trim()}>
            {loading ? <><LoadingSpinner size="sm" /> {t('t2i.generating')}</> : <><i className="fas fa-wand-magic-sparkles" /> {t('t2i.generate')}</>}
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
