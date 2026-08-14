import { useState } from 'react'
import { useTranslation } from 'react-i18next'

// checkpoint 2-3_image_approval 리뷰 UI. 전에는 autoDecisionFor가 '2-3'을 원클릭 승인해버려
// M2(이미지 설명으로 생성)에서 나온 결과물을 한 번도 보여주지 않았다 — 백엔드
// (nodes.py:node_checkpoint_image_approval)는 {approved:true}면 그대로 진행,
// {feedback:"..."}면 원 요청에 피드백을 누적해 M2-1(rewrite)부터 전체 재생성한다.
// 실제 이미지는 오른쪽 결과물 패널(GatewayAgent.jsx의 media-result)에 크게 표시된다 —
// 여기서는 승인/재생성 컨트롤만 다룬다(64x64 썸네일 중복 표시하지 않음).
export default function AgentImagePreview({ imageUrls, imageQueries, historyUrls = [], onApprove, onRegenerate }) {
  const { t } = useTranslation('gateway')
  const [revising, setRevising] = useState(false)
  const [feedback, setFeedback] = useState('')
  // 재생성 시도가 2회 이상일 때만 비교 스트립을 보여준다. 마지막 항목은 지금 오른쪽
  // 패널에 크게 떠 있는 현재 후보라 여기서는 이전 시도들만 나열한다.
  const previous = historyUrls.slice(0, -1)

  return (
    <div className="scene-preview">
      <p className="form-field__hint">{t('imagePreview.hint', { count: imageUrls.length })}</p>
      {imageQueries[0] && <p className="scene-preview__text">{imageQueries[0]}</p>}

      {previous.length > 0 && (
        <div className="form-group">
          <label className="form-label">{t('imagePreview.previousAttempts', { count: previous.length })}</label>
          <div className="agent-attempt-strip">
            {previous.map((url, i) => (
              <figure key={url} className="agent-attempt">
                <img src={url} alt={t('imagePreview.attemptAlt', { n: i + 1 })} />
                <figcaption>{t('imagePreview.attemptLabel', { n: i + 1 })}</figcaption>
              </figure>
            ))}
            <figure className="agent-attempt is-current">
              <img src={imageUrls[0]} alt={t('imagePreview.attemptAlt', { n: previous.length + 1 })} />
              <figcaption>{t('imagePreview.attemptCurrent', { n: previous.length + 1 })}</figcaption>
            </figure>
          </div>
          <span className="form-field__hint">{t('imagePreview.approveAppliesToCurrent')}</span>
        </div>
      )}

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
