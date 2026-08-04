import { useEffect, useRef, useState } from 'react'
import LoadingSpinner from '../components/LoadingSpinner'
import AgentPhaseStepper from '../components/AgentPhaseStepper'
import AgentScenePreview from '../components/AgentScenePreview'
import AgentClipPreview from '../components/AgentClipPreview'
import AgentImagePreview from '../components/AgentImagePreview'
import GatewayHeroPills from '../components/GatewayHeroPills'
import { gatewayApi, GATEWAY_BASE, fileToBase64 } from '../utils/api'

// Task 6.3: Agent 카테고리(S1 — 텍스트 스토리 → 캐릭터 일관 영상 + 나레이션).
// anim-agent 게이트웨이(:8700)의 /jobs·/jobs/{id}/status·/jobs/{id}/resume만
// 호출한다. 영상 나레이션은 그래프 내부에서 /tts/narration(고정 CC0 화자)으로
// 이미 배선돼 있다 — 이 페이지가 별도로 TTS를 호출하지 않는다. LocalAI 자체
// 추론 백엔드는 쓰지 않는다. phase→스텝 하이라이트는 AgentPhaseStepper(Task 6.4).
const POLL_MS = 3000
const JOB_STORAGE_KEY = 'gwAgentJobId'
const AGENT_NODES = [
  { key: 'planning', icon: 'fa-align-left', step: '01', title: '스토리 분석', description: '이야기의 흐름과 핵심 장면을 정리합니다.' },
  { key: 'prompting', icon: 'fa-table-cells-large', step: '02', title: '씬 분할', description: '스토리를 영상에 맞는 씬 단위로 나눕니다.' },
  { key: 'anchoring', icon: 'fa-user-check', step: '03', title: '캐릭터 앵커', description: '인물의 외형과 화풍을 장면마다 고정합니다.' },
  { key: 'generating', icon: 'fa-clapperboard', step: '04', title: '영상 생성', description: '각 씬을 움직이는 영상 클립으로 만듭니다.' },
  { key: 'done', icon: 'fa-wand-magic-sparkles', step: '05', title: '최종 합성', description: '클립과 나레이션을 하나의 영상으로 완성합니다.' },
]

export default function GatewayAgent() {
  // 'upload'=시나리오+인물사진 / 'describe'=이미지 설명으로 생성 후 시나리오 /
  // 'noref'=참조 없이 시나리오만. noref는 upload에 파일 0장과 페이로드가 같지만,
  // 결과가 다른 경로(캐릭터 시트로 인물 고정)라 사용자가 명시적으로 고르게 한다.
  const [inputMode, setInputMode] = useState('upload')
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
      const refImages = inputMode === 'upload'
        ? await Promise.all(refFiles.map(async (f) => `data:${f.type};base64,${await fileToBase64(f)}`))
        : []
      const { job_id } = await gatewayApi.startJob(
        inputMode === 'describe' ? '' : scriptText.trim(),
        refImages,
        inputMode === 'describe' ? imageRequest.trim() : '',
      )
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
          <p>스토리 <i className="fas fa-arrow-right" /> 씬 분할 <i className="fas fa-arrow-right" /> 캐릭터 일관 영상</p>
          <GatewayHeroPills
            models={[
              { label: 'Nemotron 3 Nano · NVIDIA', company: 'NVIDIA' },
              { label: 'Gemma 4 · Google', company: 'Google' },
              { label: 'FLUX.1 Schnell · Black Forest Labs', company: 'Black Forest Labs' },
              { label: 'LTX-Video · Lightricks', company: 'Lightricks' },
            ]}
            techniques={['LangGraph Workflow', 'Character Consistency']}
          />
        </div>
        <div className="agent-hero__mark" aria-hidden="true"><i className="fas fa-robot" /></div>
      </header>

      <section className="agent-nodes" aria-label="Agent 작업 노드">
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
              <span className="agent-node__status">{nodeState === ' is-done' ? '완료' : nodeState === ' is-active' ? '진행 중' : '대기'}</span>
            </article>
          )
        })}
      </section>

      <div className="media-layout agent-media-layout">
        <div className="media-controls agent-panel agent-panel--controls">
          <div className="agent-panel__heading">
            <span className="agent-panel__number">01</span>
            <div><h2>프로세스</h2><p>스토리와 캐릭터 정보를 입력하세요.</p></div>
          </div>
        {!jobId ? (
          <form onSubmit={handleStart}>
            <div className="segmented">
              <button type="button" className={`segmented__item${inputMode === 'upload' ? ' is-active' : ''}`} onClick={() => setInputMode('upload')}>
                <i className="fas fa-paperclip" /> 사진 첨부
              </button>
              <button type="button" className={`segmented__item${inputMode === 'describe' ? ' is-active' : ''}`} onClick={() => setInputMode('describe')}>
                <i className="fas fa-wand-magic-sparkles" /> 이미지 설명으로 생성
              </button>
              <button type="button" className={`segmented__item${inputMode === 'noref' ? ' is-active' : ''}`} onClick={() => setInputMode('noref')}>
                <i className="fas fa-pen-nib" /> 시나리오만
              </button>
            </div>
            {inputMode === 'upload' ? (
              <>
                <div className="form-group">
                  <label className="form-label">스토리</label>
                  <textarea className="textarea" value={scriptText} onChange={(e) => setScriptText(e.target.value)} rows={5} placeholder="한 우주비행사가 노을 지는 발사대에서 로켓을 타고 이륙한다..." />
                </div>
                <div className="form-group">
                  <label className="form-label">캐릭터 참조 이미지 (선택 — I2I 카테고리에서 만든 우주비행사 등)</label>
                  <input className="input" type="file" accept="image/*" multiple onChange={(e) => setRefFiles(Array.from(e.target.files || []))} />
                  {refFiles.length > 0 && <span className="form-field__hint">{refFiles.length}장 첨부됨</span>}
                </div>
              </>
            ) : inputMode === 'describe' ? (
              <div className="form-group">
                <label className="form-label">이미지 설명</label>
                <textarea className="textarea" value={imageRequest} onChange={(e) => setImageRequest(e.target.value)} rows={5} placeholder="우주복을 입은 우주비행사가 노을 지는 발사대 앞에 서있는 모습, 시네마틱..." />
                <span className="form-field__hint">참조 사진 없이 설명만으로 캐릭터 이미지를 생성합니다(T2I, FLUX.1-schnell). 승인하면 그 이미지로 시나리오를 이어서 입력합니다.</span>
              </div>
            ) : (
              <div className="form-group">
                <label className="form-label">스토리</label>
                <textarea className="textarea" value={scriptText} onChange={(e) => setScriptText(e.target.value)} rows={5} placeholder="한 우주비행사가 노을 지는 발사대에서 로켓을 타고 이륙한다..." />
                <span className="form-field__hint">참조 이미지 없이 시나리오만으로 영상을 만듭니다. 인물이 등장하면 장면마다 같은 외형이 유지되도록 자동으로 설정합니다.</span>
              </div>
            )}
            <button
              type="submit"
              className="btn btn-primary btn-full"
              disabled={starting || (inputMode === 'describe' ? !imageRequest.trim() : !scriptText.trim())}
            >
              {starting ? <><LoadingSpinner size="sm" /> 시작 중...</> : <><i className="fas fa-play" /> 시작</>}
            </button>
          </form>
        ) : (
          <div>
            <AgentPhaseStepper phase={status?.phase} imageGenUsed={status?.image_gen_used} />
            <div className="agent-jobbar">
              <p className="form-field__hint">job_id: {jobId}</p>
              <button type="button" className="btn btn-secondary" onClick={handleReset}>
                <i className="fas fa-rotate-left" /> 새로 시작
              </button>
            </div>
            {status?.status === 'done' && (
              <div className="form-group">
                <p className="form-field__hint"><i className="fas fa-circle-check" /> 완료됐습니다.</p>
                <button type="button" className="btn btn-primary btn-full" onClick={handleReset}>
                  <i className="fas fa-plus" /> 새 영상 만들기
                </button>
              </div>
            )}
            {checkpoint && checkpoint.checkpoint?.startsWith('2-3') ? (
              <AgentImagePreview
                imageUrls={checkpoint.gen_image_urls || []}
                imageQueries={checkpoint.image_queries || []}
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
                <p><strong>{checkpoint.message || '이미지가 승인되었습니다. 시나리오를 입력해주세요.'}</strong></p>
                <textarea
                  className="textarea"
                  value={scenarioText}
                  onChange={(e) => setScenarioText(e.target.value)}
                  rows={5}
                  placeholder="이 이미지로 만들 영상의 시나리오를 입력하세요..."
                />
                <button
                  type="button"
                  className="btn btn-primary btn-full"
                  disabled={!scenarioText.trim()}
                  onClick={() => { handleApprove({ script_text: scenarioText.trim() }); setScenarioText('') }}
                >
                  제출
                </button>
              </div>
            ) : checkpoint && (
              <div className="form-group">
                <p><strong>승인 대기: {checkpoint.checkpoint}</strong></p>
                {checkpoint.message && <p>{checkpoint.message}</p>}
                <textarea className="textarea" value={manualPayload} onChange={(e) => setManualPayload(e.target.value)} rows={4} />
                <button
                  type="button"
                  className="btn btn-primary btn-full"
                  onClick={() => { try { handleApprove(JSON.parse(manualPayload)) } catch { setError('payload가 유효한 JSON이 아닙니다') } }}
                >
                  제출
                </button>
              </div>
            )}
          </div>
        )}
        </div>
        <div className="media-preview agent-panel agent-panel--result">
          <div className="agent-panel__heading">
            <span className="agent-panel__number">02</span>
            <div><h2>결과물</h2><p>생성 중인 장면과 완성 영상을 확인하세요.</p></div>
          </div>
        <div className="media-result">
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
              alt="생성 이미지"
              style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
            />
          ) : (
            <div style={{ width: '100%' }}>
              <p><LoadingSpinner size="sm" /> phase: {status.phase || status.status}</p>
              {typeof status.clips_total === 'number' && <p>클립 {status.clips_done}/{status.clips_total}</p>}
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
