import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { GATEWAY_BASE } from '../utils/api'

// checkpoint 1-4_scene_split 리뷰 UI. 백엔드(nodes.py:node_checkpoint_scene_approval)는
// {approved:true, scenes:[...]}면 그대로 진행, {approved:false, revised_script_text}면
// 씬 분할을 재시도한다 — 이 두 경로만 지원하면 되고 씬 텍스트 인라인 편집은 범위 밖.
const MOOD_KEYS = { neutral: 'neutral', calm: 'calm', excited: 'excited', tense: 'tense', sad: 'sad', happy: 'happy' }

export default function AgentScenePreview({ scenes, jobId, onApprove, onReject }) {
  const { t } = useTranslation('gateway')
  const [revising, setRevising] = useState(false)
  const [revisedText, setRevisedText] = useState('')

  return (
    <div className="scene-preview">
      <p className="form-field__hint">{t('scenePreview.hint', { count: scenes.length })}</p>
      <ol className="scene-preview__list">
        {scenes.map((s) => (
          <li key={s.id} className="scene-preview__card">
            <div className="scene-preview__thumb">
              {s.matched_image ? (
                <img src={`${GATEWAY_BASE}/files/${jobId}/refs/${s.matched_image}`} alt={t('scenePreview.refAlt', { id: s.id })} />
              ) : (
                <div className="scene-preview__thumb-empty"><i className="fas fa-video" /></div>
              )}
            </div>
            <div className="scene-preview__body">
              <div className="scene-preview__meta">
                <span className="scene-preview__badge">#{s.id}</span>
                <span className="scene-preview__badge">{t(`scenePreview.mood.${MOOD_KEYS[s.mood] || ''}`, { defaultValue: s.mood })}</span>
                <span className="scene-preview__badge">{s.duration}s</span>
                {s.subject_type && <span className="scene-preview__badge">{t(s.subject_type === 'human' ? 'scenePreview.subjectHuman' : 'scenePreview.subjectNonHuman')}</span>}
              </div>
              <p className="scene-preview__text">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>

      {!revising ? (
        <div className="scene-preview__actions">
          <button type="button" className="btn btn-primary btn-full" onClick={() => onApprove({ approved: true })}>
            <i className="fas fa-check" /> {t('scenePreview.approve')}
          </button>
          <button type="button" className="btn btn-secondary btn-full" onClick={() => setRevising(true)}>
            <i className="fas fa-rotate" /> {t('scenePreview.revise')}
          </button>
        </div>
      ) : (
        <div className="form-group">
          <label className="form-label">{t('scenePreview.revisedLabel')}</label>
          <textarea
            className="textarea"
            rows={5}
            value={revisedText}
            onChange={(e) => setRevisedText(e.target.value)}
            placeholder={t('scenePreview.revisedPlaceholder')}
          />
          <div className="scene-preview__actions">
            <button
              type="button"
              className="btn btn-primary btn-full"
              disabled={!revisedText.trim()}
              onClick={() => onReject(revisedText.trim())}
            >
              {t('scenePreview.resplit')}
            </button>
            <button type="button" className="btn btn-secondary btn-full" onClick={() => setRevising(false)}>
              {t('scenePreview.cancel')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
