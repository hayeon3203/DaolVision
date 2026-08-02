import { useEffect, useRef, useState } from 'react'
import PageHeader from '../components/PageHeader'
import LoadingSpinner from '../components/LoadingSpinner'
import AgentPhaseStepper from '../components/AgentPhaseStepper'
import { gatewayApi, GATEWAY_BASE, fileToBase64 } from '../utils/api'

// Task 6.3: Agent 카테고리(S1 — 텍스트 스토리 → 캐릭터 일관 영상 + 나레이션).
// anim-agent 게이트웨이(:8700)의 /jobs·/jobs/{id}/status·/jobs/{id}/resume만
// 호출한다. 영상 나레이션은 그래프 내부에서 /tts/narration(고정 CC0 화자)으로
// 이미 배선돼 있다 — 이 페이지가 별도로 TTS를 호출하지 않는다. LocalAI 자체
// 추론 백엔드는 쓰지 않는다. phase→스텝 하이라이트는 AgentPhaseStepper(Task 6.4).
const POLL_MS = 3000

// driver.py _auto_decision과 같은 매핑 — 흔한 게이트는 원클릭 승인.
function autoDecisionFor(checkpointName) {
  if (checkpointName?.startsWith('1-4')) return { approved: true }
  if (checkpointName?.startsWith('3-5')) return { action: 'approve_all' }
  if (checkpointName?.startsWith('2-3')) return { approved: true }
  return null
}

export default function GatewayAgent() {
  const [scriptText, setScriptText] = useState('')
  const [refFiles, setRefFiles] = useState([])
  const [jobId, setJobId] = useState(null)
  const [status, setStatus] = useState(null)
  const [manualPayload, setManualPayload] = useState('{}')
  const [error, setError] = useState(null)
  const [starting, setStarting] = useState(false)
  const timerRef = useRef(null)

  const stopPolling = () => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
  }

  useEffect(() => stopPolling, [])

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
    if (!scriptText.trim()) return
    setStarting(true)
    setError(null)
    try {
      const refImages = await Promise.all(refFiles.map(async (f) => `data:${f.type};base64,${await fileToBase64(f)}`))
      const { job_id } = await gatewayApi.startJob(scriptText.trim(), refImages)
      setJobId(job_id)
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

  const checkpoint = status?.status === 'waiting_for_approval' ? status.checkpoint : null
  const auto = checkpoint ? autoDecisionFor(checkpoint.checkpoint) : null

  return (
    <div className="media-layout">
      <div className="media-controls">
        <PageHeader title={<><i className="fas fa-robot" /> Agent</>} supporting="스토리 → 씬분할 → 캐릭터 일관 영상 + 나레이션 (S1, :8700 게이트웨이)" />
        {!jobId ? (
          <form onSubmit={handleStart}>
            <div className="form-group">
              <label className="form-label">스토리</label>
              <textarea className="textarea" value={scriptText} onChange={(e) => setScriptText(e.target.value)} rows={5} placeholder="한 우주비행사가 노을 지는 발사대에서 로켓을 타고 이륙한다..." />
            </div>
            <div className="form-group">
              <label className="form-label">캐릭터 참조 이미지 (선택 — I2I 카테고리에서 만든 우주비행사 등)</label>
              <input className="input" type="file" accept="image/*" multiple onChange={(e) => setRefFiles(Array.from(e.target.files || []))} />
              {refFiles.length > 0 && <span className="form-field__hint">{refFiles.length}장 첨부됨</span>}
            </div>
            <button type="submit" className="btn btn-primary btn-full" disabled={starting || !scriptText.trim()}>
              {starting ? <><LoadingSpinner size="sm" /> 시작 중...</> : <><i className="fas fa-play" /> 시작</>}
            </button>
          </form>
        ) : (
          <div>
            <AgentPhaseStepper phase={status?.phase} />
            <p className="form-field__hint">job_id: {jobId}</p>
            {checkpoint && (
              <div className="form-group">
                <p><strong>승인 대기: {checkpoint.checkpoint}</strong></p>
                {checkpoint.message && <p>{checkpoint.message}</p>}
                {auto ? (
                  <button type="button" className="btn btn-primary btn-full" onClick={() => handleApprove(auto)}>
                    <i className="fas fa-check" /> 승인
                  </button>
                ) : (
                  <>
                    <textarea className="textarea" value={manualPayload} onChange={(e) => setManualPayload(e.target.value)} rows={4} />
                    <button
                      type="button"
                      className="btn btn-primary btn-full"
                      onClick={() => { try { handleApprove(JSON.parse(manualPayload)) } catch { setError('payload가 유효한 JSON이 아닙니다') } }}
                    >
                      제출
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="media-preview">
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
  )
}
