import { useState } from 'react'
import { GATEWAY_BASE } from '../utils/api'

// checkpoint 3-5_clip_approval 리뷰 UI. 전에는 autoDecisionFor가 {action:'approve_all'}로
// 원클릭 승인해버려 생성된 클립을 한 번도 보여주지 않았다 — 백엔드(node_checkpoint_clip_approval)는
// {action:'regenerate', scene_ids:[...]}로 씬별 재생성도 지원하므로 그걸 그대로 노출한다.
export default function AgentClipPreview({ scenes, onApprove, onRegenerate }) {
  const [selected, setSelected] = useState(() => new Set())

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className="scene-preview">
      <p className="form-field__hint">클립 {scenes.length}개 생성됨 — 확인 후 승인하거나, low_quality 씬을 골라 재생성하세요.</p>
      <ol className="scene-preview__list">
        {scenes.map((s) => (
          <li key={s.id} className="scene-preview__card">
            <div className="scene-preview__clip-select">
              <input
                type="checkbox"
                checked={selected.has(s.id)}
                onChange={() => toggle(s.id)}
                aria-label={`씬 ${s.id} 재생성 대상으로 선택`}
              />
            </div>
            {s.clip_url ? (
              <video controls className="scene-preview__clip-video" src={`${GATEWAY_BASE}${s.clip_url}`} />
            ) : (
              <div className="scene-preview__thumb-empty"><i className="fas fa-video-slash" /></div>
            )}
            <div className="scene-preview__body">
              <div className="scene-preview__meta">
                <span className="scene-preview__badge">#{s.id}</span>
                {s.quality_flag && s.quality_flag !== 'pending' && (
                  <span className={`scene-preview__badge scene-preview__badge--${s.quality_flag}`}>{s.quality_flag}</span>
                )}
              </div>
              <p className="scene-preview__text">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="scene-preview__actions">
        <button type="button" className="btn btn-primary btn-full" onClick={onApprove}>
          <i className="fas fa-check" /> 전체 승인
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-full"
          disabled={selected.size === 0}
          onClick={() => onRegenerate([...selected])}
        >
          <i className="fas fa-rotate" /> 선택한 {selected.size}개 씬 재생성
        </button>
      </div>
    </div>
  )
}
