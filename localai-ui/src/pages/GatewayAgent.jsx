import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import LoadingSpinner from '../components/LoadingSpinner'
import AgentPhaseStepper from '../components/AgentPhaseStepper'
import AgentScenePreview from '../components/AgentScenePreview'
import AgentClipPreview from '../components/AgentClipPreview'
import AgentImagePreview from '../components/AgentImagePreview'
import RefImageThumbs from '../components/RefImageThumbs'
import GatewayHeroPills from '../components/GatewayHeroPills'
import { gatewayApi, GATEWAY_BASE, fileToBase64 } from '../utils/api'

// Task 6.3: Agent 카테고리(S1 — 텍스트 스토리 → 캐릭터 일관 영상 + 나레이션).
// anim-agent 게이트웨이(:8700)의 /jobs·/jobs/{id}/status·/jobs/{id}/resume만
// 호출한다. 영상 나레이션은 그래프 내부에서 /tts/narration(고정 CC0 화자)으로
// 이미 배선돼 있다 — 이 페이지가 별도로 TTS를 호출하지 않는다. LocalAI 자체
// 추론 백엔드는 쓰지 않는다. phase→스텝 하이라이트는 AgentPhaseStepper(Task 6.4).
const POLL_MS = 3000
const JOB_STORAGE_KEY = 'gwAgentJobId'
const AGENT_NODE_KEYS = [
  { key: 'planning', icon: 'fa-align-left', step: '01' },
  { key: 'prompting', icon: 'fa-table-cells-large', step: '02' },
  { key: 'anchoring', icon: 'fa-user-check', step: '03' },
  { key: 'generating', icon: 'fa-clapperboard', step: '04' },
  { key: 'done', icon: 'fa-wand-magic-sparkles', step: '05' },
]

export default function GatewayAgent() {
  const { t } = useTranslation('gateway')
  const AGENT_NODES = AGENT_NODE_KEYS.map((n) => ({
    ...n,
    title: t(`agent.nodes.${n.key}.title`),
    description: t(`agent.nodes.${n.key}.description`),
  }))
  // 'describe' = 인물은 프롬프트로 생성 + 제품 사진 첨부(6.22 조합) / 'noref' = 시나리오만.
  //
  // 2026-08-13: 'upload'(시나리오 + 인물사진 첨부) 모드를 제거했다. 제품 광고 흐름에서
  // 첨부는 캐릭터 참조가 아니라 **제품**이고, 인물은 프롬프트로 생성하는 게 표준이 됐다.
  // upload는 첨부 이미지를 인물 참조로 쓰는 옛 경로라 제품 사진을 넣으면 얼굴 자리에
  // 병 사진이 들어간다 — 남겨두면 잘못 고르기 쉬운 선택지다.
  const [inputMode, setInputMode] = useState('describe')
  const [scriptText, setScriptText] = useState('')
  const [refFiles, setRefFiles] = useState([])
  const [imageRequest, setImageRequest] = useState('')
  const [jobId, setJobId] = useState(null)
  const [status, setStatus] = useState(null)
  const [manualPayload, setManualPayload] = useState('{}')
  const [scenarioText, setScenarioText] = useState('')
  const [error, setError] = useState(null)
  const [starting, setStarting] = useState(false)
  const timerRef = useRef(null)

  const stopPolling = () => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
  }

  useEffect(() => {
    const saved = localStorage.getItem(JOB_STORAGE_KEY)
    if (!saved) return
    setJobId(saved)
    ;(async () => {
      await poll(saved)
      if (!timerRef.current) timerRef.current = setInterval(() => poll(saved), POLL_MS)
    })()
    return stopPolling
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const poll = async (id) => {
    try {
      const data = await gatewayApi.jobStatus(id)
      setStatus(data)
      if (data.status === 'done' || data.status === 'error' || data.status === 'cancelled') stopPolling()
    } catch (err) {
      setError(err.message)
      stopPolling()
    }
  }

  const handleStart = async (e) => {
    e.preventDefault()
    if (inputMode === 'describe' ? !imageRequest.trim() : !scriptText.trim()) return
    setStarting(true)
    setError(null)
    try {
      let requestScript = ''
      let requestRefImages = []
      let requestImageDescription = ''

      const toDataUris = (files) =>
        Promise.all(files.map(async (f) => `data:${f.type};base64,${await fileToBase64(f)}`))

      if (inputMode === 'describe') {
        // 6.22: 생성과 첨부는 배타가 아니다 — "인물은 생성하고 제품 사진은 첨부"가
        // 이 조합이다. 첨부분은 게이트웨이가 그대로 ref_images로 받고, 생성분은
        // 이미지 승인 게이트에서 gen_N으로 병합된다(nodes.node_checkpoint_image_approval).
        // 시나리오는 여기서 안 보낸다 — 이미지 승인 뒤 2-4 게이트에서 입력한다.
        requestImageDescription = imageRequest.trim()
        requestRefImages = await toDataUris(refFiles)
      } else if (inputMode === 'noref') {
        requestScript = scriptText.trim()
      }

      const { job_id } = await gatewayApi.startJob(requestScript, requestRefImages, requestImageDescription)
      setJobId(job_id)
      localStorage.setItem(JOB_STORAGE_KEY, job_id)
      await poll(job_id)
      timerRef.current = setInterval(() => poll(job_id), POLL_MS)
    } catch (err) {
      setError(err.message)
    } finally {
      setStarting(false)
    }
  }

  const handleApprove = async (payload) => {
    if (!jobId) return
    try {
      await gatewayApi.resumeJob(jobId, payload)
      await poll(jobId)
      if (!timerRef.current) timerRef.current = setInterval(() => poll(jobId), POLL_MS)
    } catch (err) {
      setError(err.message)
    }
  }

  const handleReset = async () => {
    stopPolling()
    if (jobId && status?.status !== 'done' && status?.status !== 'error') {
      try { await gatewayApi.cancelJob(jobId) } catch { /* best-effort — job may already be finished */ }
    }
    localStorage.removeItem(JOB_STORAGE_KEY)
    setJobId(null)
    setStatus(null)
    setError(null)
    setScriptText('')
    setRefFiles([])
    setImageRequest('')
    setScenarioText('')
  }

  const checkpoint = status?.status === 'waiting_for_approval' ? status.checkpoint : null
  const activeNodeIndex = AGENT_NODES.findIndex((node) => node.key === status?.phase)

  return (
    <div className="agent-workspace">
      <header className="agent-hero">
        <div className="agent-hero__copy">
          <span className="agent-hero__eyebrow"><i className="fas fa-sparkles" /> AI VIDEO WORKFLOW</span>
          <h1>Agent</h1>
          <p>{t('agent.taglineStory')} <i className="fas fa-arrow-right" /> {t('agent.taglineSplit')} <i className="fas fa-arrow-right" /> {t('agent.taglineVideo')}</p>
          <GatewayHeroPills
            models={[
              { label: 'Gemma 4 · Google', company: 'Google' },
              { label: 'FLUX.1 Schnell · Black Forest Labs', company: 'Black Forest Labs' },
              { label: 'LTX-Video · Lightricks', company: 'Lightricks' },
            ]}
            techniques={['LangGraph Workflow', 'Character Consistency']}
          />
        </div>
        <div className="agent-hero__mark" aria-hidden="true"><i className="fas fa-robot" /></div>
      </header>

      <section className="agent-nodes" aria-label={t('agent.nodesAriaLabel')}>
        {AGENT_NODES.map((node, index) => {
          const nodeState = activeNodeIndex < 0 ? '' : index < activeNodeIndex ? ' is-done' : index === activeNodeIndex ? ' is-active' : ''
          return (
            <article className={`agent-node${nodeState}`} key={node.key}>
              <div className="agent-node__top">
                <span className="agent-node__icon"><i className={`fas ${node.icon}`} /></span>
                <span className="agent-node__step">NODE {node.step}</span>
              </div>
              <h2>{node.title}</h2>
              <p>{node.description}</p>
              <span className="agent-node__status">{nodeState === ' is-done' ? t('agent.nodeStatus.done') : nodeState === ' is-active' ? t('agent.nodeStatus.active') : t('agent.nodeStatus.waiting')}</span>
            </article>
          )
        })}
      </section>

      <div className="media-layout agent-media-layout">
        <div className="media-controls agent-panel agent-panel--controls">
          <div className="agent-panel__heading">
            <span className="agent-panel__number">01</span>
            <div><h2>{t('shared.process')}</h2><p>{t('agent.processHeading')}</p></div>
          </div>
        {!jobId ? (
          <form onSubmit={handleStart}>
            <div className="segmented">
              <button type="button" className={`segmented__item${inputMode === 'describe' ? ' is-active' : ''}`} onClick={() => setInputMode('describe')}>
                <i className="fas fa-wand-magic-sparkles" /> {t('agent.modeDescribe')}
              </button>
              <button type="button" className={`segmented__item${inputMode === 'noref' ? ' is-active' : ''}`} onClick={() => setInputMode('noref')}>
                <i className="fas fa-pen-nib" /> {t('agent.modeNoref')}
              </button>
            </div>
            {inputMode === 'describe' ? (
              <>
                <div className="form-group">
                  <label className="form-label">{t('agent.personLabel')}</label>
                  <textarea className="textarea" value={imageRequest} onChange={(e) => setImageRequest(e.target.value)} rows={5} placeholder={t('agent.personPlaceholder')} />
                  <span className="form-field__hint">{t('agent.personHint')}</span>
                </div>
                {/* 6.22: 생성과 첨부 동시 입력. 인물은 위에서 프롬프트로 생성하고,
                    광고할 제품은 여기 첨부한다. */}
                <div className="form-group">
                  <label className="form-label">{t('agent.productLabel')}</label>
                  <input className="input" type="file" accept="image/*" multiple onChange={(e) => setRefFiles(Array.from(e.target.files || []))} />
                  <RefImageThumbs files={refFiles} />
                  <span className="form-field__hint">{t('agent.productHint')}</span>
                  {refFiles.length > 0 && <span className="form-field__hint">{t('agent.refImagesAttached', { count: refFiles.length })}</span>}
                </div>
              </>
            ) : (
              <div className="form-group">
                <label className="form-label">{t('agent.storyLabel')}</label>
                <textarea className="textarea" value={scriptText} onChange={(e) => setScriptText(e.target.value)} rows={5} placeholder={t('agent.storyPlaceholder')} />
                <span className="form-field__hint">{t('agent.norefHint')}</span>
              </div>
            )}
            <button
              type="submit"
              className="btn btn-primary btn-full"
              disabled={starting || (inputMode === 'describe' ? !imageRequest.trim() : !scriptText.trim())}
            >
              {starting ? <><LoadingSpinner size="sm" /> {t('agent.starting')}</> : <><i className="fas fa-play" /> {t('agent.start')}</>}
            </button>
          </form>
        ) : (
          <div>
            <AgentPhaseStepper phase={status?.phase} imageGenUsed={status?.image_gen_used} />
            <div className="agent-jobbar">
              <p className="form-field__hint">{t('agent.jobId', { id: jobId })}</p>
              <button type="button" className="btn btn-secondary" onClick={handleReset}>
                <i className="fas fa-rotate-left" /> {t('agent.startOver')}
              </button>
            </div>
            {status?.status === 'done' && (
              <div className="form-group">
                <p className="form-field__hint"><i className="fas fa-circle-check" /> {t('agent.done')}</p>
                <button type="button" className="btn btn-primary btn-full" onClick={handleReset}>
                  <i className="fas fa-plus" /> {t('agent.newVideo')}
                </button>
              </div>
            )}
            {checkpoint && checkpoint.checkpoint?.startsWith('2-3') ? (
              <AgentImagePreview
                imageUrls={checkpoint.gen_image_urls || []}
                imageQueries={checkpoint.image_queries || []}
                historyUrls={checkpoint.gen_image_history_urls || []}
                onApprove={handleApprove}
                onRegenerate={(feedback) => handleApprove({ feedback })}
              />
            ) : checkpoint && checkpoint.checkpoint?.startsWith('1-4') ? (
              <AgentScenePreview
                scenes={checkpoint.scenes || []}
                jobId={jobId}
                onApprove={handleApprove}
                onReject={(revisedText) => handleApprove({ approved: false, revised_script_text: revisedText })}
              />
            ) : checkpoint && checkpoint.checkpoint?.startsWith('3-5') ? (
              <AgentClipPreview
                scenes={checkpoint.scenes || []}
                onApprove={() => handleApprove({ action: 'approve_all' })}
                onRegenerate={(sceneIds) => handleApprove({ action: 'regenerate', scene_ids: sceneIds })}
              />
            ) : checkpoint && checkpoint.checkpoint?.startsWith('2-4') ? (
              <div className="form-group">
                <p><strong>{checkpoint.message || t('agent.imageApprovedDefault')}</strong></p>
                <textarea
                  className="textarea"
                  value={scenarioText}
                  onChange={(e) => setScenarioText(e.target.value)}
                  rows={5}
                  placeholder={t('agent.scenarioPlaceholder')}
                />
                <button
                  type="button"
                  className="btn btn-primary btn-full"
                  disabled={!scenarioText.trim()}
                  onClick={() => { handleApprove({ script_text: scenarioText.trim() }); setScenarioText('') }}
                >
                  {t('agent.submit')}
                </button>
              </div>
            ) : checkpoint && (
              <div className="form-group">
                <p><strong>{t('agent.waitingForApproval', { checkpoint: checkpoint.checkpoint })}</strong></p>
                {checkpoint.message && <p>{checkpoint.message}</p>}
                <textarea className="textarea" value={manualPayload} onChange={(e) => setManualPayload(e.target.value)} rows={4} />
                <button
                  type="button"
                  className="btn btn-primary btn-full"
                  onClick={() => { try { handleApprove(JSON.parse(manualPayload)) } catch { setError(t('agent.invalidPayload')) } }}
                >
                  {t('agent.submit')}
                </button>
              </div>
            )}
          </div>
        )}
        </div>
        <div className="media-preview agent-panel agent-panel--result">
          <div className="agent-panel__heading">
            <span className="agent-panel__number">02</span>
            <div><h2>{t('shared.result')}</h2><p>{t('agent.resultHeading')}</p></div>
          </div>
        <div className="media-result">
          {status?.input_message && (
            <div className="agent-result-prompt">
              <span className="agent-result-prompt__label"><i className="fas fa-message" /> {t('agent.inputMessageLabel')}</span>
              <p>{status.input_message}</p>
            </div>
          )}
          {error ? (
            <p style={{ color: 'var(--color-error)' }}>Error: {error}</p>
          ) : !status ? (
            <div style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>
              <i className="fas fa-robot" style={{ fontSize: '3rem', opacity: 0.4 }} />
            </div>
          ) : status.status === 'done' ? (
            <video controls className="media-result" style={{ minHeight: 0 }} src={`${GATEWAY_BASE}${status.final_video_url}`} />
          ) : status.status === 'error' ? (
            <p style={{ color: 'var(--color-error)' }}>{status.error}</p>
          ) : checkpoint && checkpoint.checkpoint?.startsWith('2-3') && (checkpoint.gen_image_urls || []).length > 0 ? (
            <img
              src={`${GATEWAY_BASE}${checkpoint.gen_image_urls[0]}${checkpoint.image_queries?.[0] ? `?v=${encodeURIComponent(checkpoint.image_queries[0])}` : ''}`}
              alt={t('agent.generatedImageAlt')}
              style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
            />
          ) : (
            <div style={{ width: '100%' }}>
              <p><LoadingSpinner size="sm" /> phase: {status.phase || status.status}</p>
              {typeof status.clips_total === 'number' && <p>{t('agent.clipsProgress', { done: status.clips_done, total: status.clips_total })}</p>}
              {(status.clips || []).map(c => (
                <video key={c.scene_id} controls className="media-result" style={{ minHeight: 0, marginBottom: 'var(--spacing-sm)' }} src={`${GATEWAY_BASE}${c.url}`} />
              ))}
            </div>
          )}
        </div>
        </div>
      </div>
    </div>
  )
}
