import { useEffect, useRef, useState } from 'react'
import PageHeader from '../components/PageHeader'
import LoadingSpinner from '../components/LoadingSpinner'
import StatusPill from '../components/StatusPill'
import { gatewayApi } from '../utils/api'

// Task 7.1: 자립 대시보드 — 오프라인 배지 + 실행트레이스 + GB10 메모리 게이지
// (docs/PRD.md R9). :8700 게이트웨이의 /dashboard/status(Task 4.3, langgraph/dashboard.py)만
// 폴링한다. 백엔드 계산이 아닌 프론트 표시 전용 페이지.
const POLL_MS = 5000

// R10: 전 모델 비중국/NVIDIA. dashboard.py의 MODEL_VENDORS가 분류하는 값 중 유일한
// 중국계는 alibaba(Qwen) — 다른 값은 nvidia/google/meta/black-forest-labs/lightricks/
// resemble-ai거나 미분류(unknown)다.
const CHINA_VENDORS = ['alibaba']

function memTone(percent) {
  if (percent >= 90) return 'error'
  if (percent >= 75) return 'warning'
  return 'success'
}

export default function GatewayDashboard() {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const timerRef = useRef(null)

  useEffect(() => {
    const poll = async () => {
      try {
        const data = await gatewayApi.dashboardStatus()
        setStatus(data)
        setError(null)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    poll()
    timerRef.current = setInterval(poll, POLL_MS)
    return () => clearInterval(timerRef.current)
  }, [])

  const trace = status?.trace || []
  const hasChinaVendor = trace.some((t) => CHINA_VENDORS.includes(t.vendor))
  const hasUnknownVendor = trace.some((t) => t.vendor === 'unknown')
  const vendorTone = hasChinaVendor ? 'error' : hasUnknownVendor ? 'warning' : 'success'
  const vendorLabel = hasChinaVendor ? '중국계 모델 감지' : hasUnknownVendor ? '국적 미분류 모델 있음' : '전 모델 비중국'

  const memPercent = status ? (status.gpu.used_gb / status.gpu.total_gb) * 100 : 0

  return (
    <div className="page page--wide">
      <PageHeader
        title={<><i className="fas fa-gauge-high" /> 자립 대시보드</>}
        supporting="External calls / 국적 컴플라이언스 / GB10 메모리 실시간 표시 (:8700 게이트웨이)"
      />

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--spacing-xl)' }}>
          <LoadingSpinner size="lg" />
        </div>
      ) : error ? (
        <p style={{ color: 'var(--color-error)' }}>Error: {error}</p>
      ) : (
        <>
          {/* 배지 3종: 오프라인 / External calls 실측 / 국적(R10) */}
          <div style={{ display: 'flex', gap: 'var(--spacing-sm)', flexWrap: 'wrap', marginBottom: 'var(--spacing-lg)' }}>
            <StatusPill status={status.offline ? 'online' : 'warning'} label={status.offline ? '오프라인' : '온라인'} />
            <StatusPill status={status.offline ? 'online' : 'warning'} label={`External calls: ${status.external_calls}`} />
            <StatusPill status={vendorTone} label={vendorLabel} />
          </div>

          {/* 실행트레이스 */}
          <div style={{ marginBottom: 'var(--spacing-lg)' }}>
            <h3 style={{ marginBottom: 'var(--spacing-sm)' }}>실행트레이스</h3>
            <table className="table">
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Model</th>
                  <th>Vendor</th>
                  <th>License</th>
                  <th>URL</th>
                </tr>
              </thead>
              <tbody>
                {trace.map((t) => (
                  <tr key={t.step}>
                    <td>{t.step}</td>
                    <td>{t.model}</td>
                    <td>{t.vendor}</td>
                    <td>{t.license}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8125rem' }}>{t.url}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 메모리게이지 */}
          <div>
            <h3 style={{ marginBottom: 'var(--spacing-sm)' }}>GB10 메모리</h3>
            <div className="biometrics-gauge__track" style={{ position: 'relative', height: 20, background: 'var(--color-bg-tertiary)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
              <div
                style={{
                  position: 'absolute', left: 0, top: 0, bottom: 0,
                  width: `${Math.min(100, memPercent)}%`,
                  background: `var(--color-${memTone(memPercent)})`,
                  transition: 'width 0.3s ease',
                }}
              />
            </div>
            <p className="form-field__hint" style={{ marginTop: 4 }}>
              {status.gpu.used_gb.toFixed(1)}GB / {status.gpu.total_gb.toFixed(1)}GB ({memPercent.toFixed(0)}%) ·
              {' '}util {status.gpu.util_percent.toFixed(0)}% · {status.gpu.temp_c.toFixed(0)}°C · {status.gpu.power_draw_w.toFixed(0)}W
            </p>
          </div>
        </>
      )}
    </div>
  )
}
