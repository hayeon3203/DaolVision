import { useState } from 'react'
import { useTranslation } from 'react-i18next'

// checkpoint 2-3_image_approval 리뷰 UI. 전에는 autoDecisionFor가 '2-3'을 원클릭 승인해버려
// M2(이미지 설명으로 생성)에서 나온 결과물을 한 번도 보여주지 않았다 — 백엔드
// (nodes.py:node_checkpoint_image_approval)는 {approved:true}면 그대로 진행,
// {feedback:"..."}면 원 요청에 피드백을 누적해 M2-1(rewrite)부터 전체 재생성한다.
// 실제 이미지는 오른쪽 결과물 패널(GatewayAgent.jsx의 media-result)에 크게 표시된다 —
// 여기서는 승인/재생성 컨트롤만 다룬다(64x64 썸네일 중복 표시하지 않음).
export default function AgentImagePreview({ imageUrls, imageQueries, onApprove, onRegenerate }) {
  const { t } = useTranslation('gateway')
  const [revising, setRevising] = useState(false)
  const [feedback, setFeedback] = useState('')

  return (
    <div className="scene-preview">
      <p className="form-field__hint">{t('imagePreview.hint', { count: imageUrls.length })}</p>
      {imageQueries[0] && <p className="scene-preview__text">{imageQueries[0]}</p>}

      {!revising ? (
        <div className="scene-preview__actions">
          <button type="button" className="btn btn-primary btn-full" onClick={() => onApprove({ approved: true })}>
            <i className="fas fa-check" /> {t('imagePreview.approve')}
          </button>
          <button type="button" className="btn btn-secondary btn-full" onClick={() => setRevising(true)}>
            <i className="fas fa-rotate" /> {t('imagePreview.revise')}
          </button>
        </div>
      ) : (
        <div className="form-group">
          <label className="form-label">{t('imagePreview.feedbackLabel')}</label>
          <textarea
            className="textarea"
            rows={3}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder={t('imagePreview.feedbackPlaceholder')}
          />
          <div className="scene-preview__actions">
            <button
              type="button"
              className="btn btn-primary btn-full"
              disabled={!feedback.trim()}
              onClick={() => onRegenerate(feedback.trim())}
            >
              {t('imagePreview.regenerate')}
            </button>
            <button type="button" className="btn btn-secondary btn-full" onClick={() => setRevising(false)}>
              {t('imagePreview.cancel')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
