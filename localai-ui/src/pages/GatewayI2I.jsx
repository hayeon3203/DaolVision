import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import LoadingSpinner from '../components/LoadingSpinner'
import MediaInput from '../components/biometrics/MediaInput'
import { gatewayApi } from '../utils/api'

// Task 6.1/6.3: I2I 카테고리(얼굴사진→스타일 변환). anim-agent 게이트웨이(:8700)
// POST /i2i만 호출한다(Flux Kontext dev, style_presets.py 6종). LocalAI 자체
// 이미지 백엔드는 쓰지 않는다. 결과는 6.2의 S2→S1 연결(ref_images)에 그대로
// 쓸 수 있는 base64 PNG — Agent 카테고리에서 참조 이미지로 재업로드해 쓴다.
const STYLES = [
  { key: 'cinematic', label: '시네마틱' },
  { key: 'anime', label: '애니메이션' },
  { key: 'cyberpunk', label: '사이버펑크' },
  { key: 'lowpoly', label: '로우폴리' },
  { key: 'claymation', label: '클레이메이션' },
  { key: 'watercolor', label: '수채화' },
]

// 업로드 vs 웹캠 촬영 선택 + 촬영본 미리보기/재촬영은 MediaInput(biometrics에서
// 이미 검증된 컴포넌트)이 탭 UI로 제공한다 — 별도 팝업 없이 같은 UX.
async function toBlob(photo) {
  if (photo.blob) return photo.blob
  const res = await fetch(photo.dataUrl)
  return res.blob()
}

export default function GatewayI2I() {
  const [sourcePhoto, setSourcePhoto] = useState(null)
  const [style, setStyle] = useState('cinematic')
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
    <div className="media-layout">
      <div className="media-controls">
        <PageHeader title={<><i className="fas fa-palette" /> I2I 스타일 변환</>} supporting="얼굴사진 → 스타일 변환 (Flux.1 Kontext, :8700 게이트웨이)" />
        <form onSubmit={handleGenerate}>
          <MediaInput
            mode="image"
            label="얼굴 사진"
            value={sourcePhoto}
            onChange={setSourcePhoto}
            onError={(err) => setError(err.message)}
            idPrefix="gw-i2i"
          />
          <div className="form-group">
            <label className="form-label">스타일</label>
            <select className="input btn-full" value={style} onChange={(e) => setStyle(e.target.value)}>
              {STYLES.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">시드 (선택)</label>
            <input className="input" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="랜덤" />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading || !sourcePhoto}>
            {loading ? <><LoadingSpinner size="sm" /> 변환 중...</> : <><i className="fas fa-wand-magic-sparkles" /> 변환</>}
          </button>
        </form>
        {image && (
          <p className="form-field__hint">
            생성된 이미지를 저장해뒀다가 Agent 카테고리에서 참조 이미지로 올리면
            이 캐릭터로 S1 영상을 만들 수 있어요 (S2→S1 연결).
          </p>
        )}
      </div>
      <div className="media-preview">
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
      </div>
    </div>
  )
}
