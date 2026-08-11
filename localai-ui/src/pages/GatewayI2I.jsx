import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import LoadingSpinner from '../components/LoadingSpinner'
import GatewayPageShell, { GatewayPanels } from '../components/GatewayPageShell'
import MediaInput from '../components/biometrics/MediaInput'
import { gatewayApi } from '../utils/api'

// Task 6.1/6.3: I2I 카테고리(얼굴사진→스타일 변환). anim-agent 게이트웨이(:8700)
// POST /i2i만 호출한다(Flux Kontext dev, style_presets.py 6종). LocalAI 자체
// 이미지 백엔드는 쓰지 않는다. 결과는 6.2의 S2→S1 연결(ref_images)에 그대로
// 쓸 수 있는 base64 PNG — Agent 카테고리에서 참조 이미지로 재업로드해 쓴다.
const STYLE_KEYS = ['claymation', 'anime', 'watercolor', 'lowpoly']

// 업로드 vs 웹캠 촬영 선택 + 촬영본 미리보기/재촬영은 MediaInput(biometrics에서
// 이미 검증된 컴포넌트)이 탭 UI로 제공한다 — 별도 팝업 없이 같은 UX.
async function toBlob(photo) {
  if (photo.blob) return photo.blob
  const res = await fetch(photo.dataUrl)
  return res.blob()
}

export default function GatewayI2I() {
  const { t } = useTranslation('gateway')
  const [sourcePhoto, setSourcePhoto] = useState(null)
  const [style, setStyle] = useState('claymation')
  const [seed, setSeed] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [image, setImage] = useState(null)

  const handleGenerate = async (e) => {
    e.preventDefault()
    if (!sourcePhoto) return
    setLoading(true)
    setError(null)
    setImage(null)
    try {
      const imageBlob = await toBlob(sourcePhoto)
      const data = await gatewayApi.i2i(style, imageBlob, seed)
      setImage(data.image_base64 || data.b64_json)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <GatewayPageShell
      eyebrow="IMAGE TO IMAGE"
      title="Image to Image"
      description={t('i2i.description')}
      icon="fa-palette"
      models={[{ label: 'FLUX.1 Kontext Dev · Black Forest Labs', company: 'Black Forest Labs' }]}
      techniques={['Reference Conditioning']}
      facts={[
        { icon: 'fa-camera', title: t('i2i.facts.photo.title'), description: t('i2i.facts.photo.description') },
        { icon: 'fa-swatchbook', title: t('i2i.facts.styles.title'), description: t('i2i.facts.styles.description') },
        { icon: 'fa-user-check', title: t('i2i.facts.character.title'), description: t('i2i.facts.character.description') },
      ]}
    >
      <GatewayPanels inputDescription={t('i2i.inputDescription')} outputDescription={t('i2i.outputDescription')}>
        <div>
        <form onSubmit={handleGenerate}>
          <MediaInput
            mode="image"
            label={t('i2i.photoLabel')}
            value={sourcePhoto}
            onChange={setSourcePhoto}
            onError={(err) => setError(err.message)}
            idPrefix="gw-i2i"
          />
          <div className="form-group">
            <label className="form-label">{t('i2i.styleLabel')}</label>
            <select className="input btn-full" value={style} onChange={(e) => setStyle(e.target.value)}>
              {STYLE_KEYS.map(key => <option key={key} value={key}>{t(`i2i.styles.${key}`)}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">{t('i2i.seedLabel')}</label>
            <input className="input" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder={t('i2i.seedPlaceholder')} />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading || !sourcePhoto}>
            {loading ? <><LoadingSpinner size="sm" /> {t('i2i.converting')}</> : <><i className="fas fa-wand-magic-sparkles" /> {t('i2i.convert')}</>}
          </button>
        </form>
        {image && (
          <p className="form-field__hint">
            {t('i2i.resultHint')}
          </p>
        )}
        </div>
        <div className="media-result">
          {loading ? (
            <LoadingSpinner size="lg" />
          ) : error ? (
            <p style={{ color: 'var(--color-error)' }}>Error: {error}</p>
          ) : image ? (
            <img src={`data:image/png;base64,${image}`} alt={style} style={{ maxWidth: '100%' }} />
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
