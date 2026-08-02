import { useState } from 'react'
import { GATEWAY_BASE } from '../utils/api'

// checkpoint 1-4_scene_split 리뷰 UI. 백엔드(nodes.py:node_checkpoint_scene_approval)는
// {approved:true, scenes:[...]}면 그대로 진행, {approved:false, revised_script_text}면
// 씬 분할을 재시도한다 — 이 두 경로만 지원하면 되고 씬 텍스트 인라인 편집은 범위 밖.
const MOOD_LABEL = {
  neutral: '중립', calm: '차분', excited: '흥분', tense: '긴장', sad: '슬픔', happy: '기쁨',
}

export default function AgentScenePreview({ scenes, jobId, onApprove, onReject }) {
  const [revising, setRevising] = useState(false)
  const [revisedText, setRevisedText] = useState('')

  return (
    <div className="scene-preview">
      <p className="form-field__hint">씬 {scenes.length}개로 분할됨 — 확인 후 승인하세요.</p>
      <ol className="scene-preview__list">
        {scenes.map((s) => (
          <li key={s.id} className="scene-preview__card">
            <div className="scene-preview__thumb">
              {s.matched_image ? (
                <img src={`${GATEWAY_BASE}/files/${jobId}/refs/${s.matched_image}`} alt={`씬 ${s.id} 참조`} />
              ) : (
                <div className="scene-preview__thumb-empty"><i className="fas fa-video" /></div>
              )}
            </div>
            <div className="scene-preview__body">
              <div className="scene-preview__meta">
                <span className="scene-preview__badge">#{s.id}</span>
                <span className="scene-preview__badge">{MOOD_LABEL[s.mood] || s.mood}</span>
                <span className="scene-preview__badge">{s.duration}s</span>
                {s.subject_type && <span className="scene-preview__badge">{s.subject_type === 'human' ? '인물' : '비인물'}</span>}
              </div>
              <p className="scene-preview__text">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>

      {!revising ? (
        <div className="scene-preview__actions">
          <button type="button" className="btn btn-primary btn-full" onClick={() => onApprove({ approved: true })}>
            <i className="fas fa-check" /> 승인
          </button>
          <button type="button" className="btn btn-secondary btn-full" onClick={() => setRevising(true)}>
            <i className="fas fa-rotate" /> 스토리 수정 후 다시 분할
          </button>
        </div>
      ) : (
        <div className="form-group">
          <label className="form-label">수정된 스토리</label>
          <textarea
            className="textarea"
            rows={5}
            value={revisedText}
            onChange={(e) => setRevisedText(e.target.value)}
            placeholder="씬 분할이 마음에 안 들면 스토리를 고쳐서 다시 분할할 수 있습니다"
          />
          <div className="scene-preview__actions">
            <button
              type="button"
              className="btn btn-primary btn-full"
              disabled={!revisedText.trim()}
              onClick={() => onReject(revisedText.trim())}
            >
              다시 분할 요청
            </button>
            <button type="button" className="btn btn-secondary btn-full" onClick={() => setRevising(false)}>
              취소
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
