import { useState } from 'react'
import { GATEWAY_BASE } from '../utils/api'

// checkpoint 2-3_image_approval 리뷰 UI. 전에는 autoDecisionFor가 '2-3'을 원클릭 승인해버려
// M2(이미지 설명으로 생성)에서 나온 결과물을 한 번도 보여주지 않았다 — 백엔드
// (nodes.py:node_checkpoint_image_approval)는 {approved:true}면 그대로 진행,
// {feedback:"..."}면 원 요청에 피드백을 누적해 M2-1(rewrite)부터 전체 재생성한다.
export default function AgentImagePreview({ imageUrls, imageQueries, onApprove, onRegenerate }) {
  const [revising, setRevising] = useState(false)
  const [feedback, setFeedback] = useState('')

  return (
    <div className="scene-preview">
      <p className="form-field__hint">이미지 {imageUrls.length}장 생성됨 — 확인 후 승인하거나 수정 요청을 입력하세요.</p>
      <ol className="scene-preview__list">
        {imageUrls.map((url, i) => (
          <li key={url} className="scene-preview__card">
            <div className="scene-preview__thumb">
              <img src={`${GATEWAY_BASE}${url}`} alt={`생성 이미지 ${i + 1}`} />
            </div>
            <div className="scene-preview__body">
              <div className="scene-preview__meta">
                <span className="scene-preview__badge">#{i + 1}</span>
              </div>
              {imageQueries[i] && <p className="scene-preview__text">{imageQueries[i]}</p>}
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
            <i className="fas fa-rotate" /> 수정 요청 후 재생성
          </button>
        </div>
      ) : (
        <div className="form-group">
          <label className="form-label">수정 요청</label>
          <textarea
            className="textarea"
            rows={3}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="예: 배경을 더 밝게, 인물을 더 젊게"
          />
          <div className="scene-preview__actions">
            <button
              type="button"
              className="btn btn-primary btn-full"
              disabled={!feedback.trim()}
              onClick={() => onRegenerate(feedback.trim())}
            >
              재생성 요청
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
