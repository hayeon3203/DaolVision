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

// ponytail: GB10은 power_limit_w/온도 스로틀 지점이 드라이버(580.142)에 미노출돼
// 절대 정격값을 못 읽는다 — 아래 warn/error 문턱은 관찰 기반 근사치. 실측 스로틀링
// 지점이 확인되면 이 상수만 교체.
const THRESHOLDS = {
  mem: { warn: 75, error: 90 },
  power: { warn: 100, error: 140 },
  temp: { warn: 70, error: 85 },
}

function scoreTone(value, { warn, error }) {
  if (value >= error) return 'error'
  if (value >= warn) return 'warning'
  return 'success'
}

// Grafana stat 패널(colorMode: background)과 같은 형식 — 값이 곧 배경색.
function ScoreCard({ label, value, unit, tone }) {
  return (
    <div className={`score-card score-card--${tone}`}>
      <div className="score-card__label">{label}</div>
      <div className="score-card__value">{value}<span className="score-card__unit">{unit}</span></div>
    </div>
  )
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
      <style>{`
        .score-card-row {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
          gap: var(--spacing-md);
          margin-bottom: var(--spacing-lg);
        }
        .score-card {
          border-radius: var(--radius-lg);
          padding: var(--spacing-lg) var(--spacing-md);
          color: #fff;
          text-shadow: 0 1px 2px rgba(0,0,0,0.25);
        }
        .score-card--success { background: var(--color-success); }
        .score-card--warning { background: var(--color-warning); }
        .score-card--error { background: var(--color-error); }
        .score-card__label {
          font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
          opacity: 0.85; margin-bottom: 4px;
        }
        .score-card__value { font-size: 2rem; font-weight: 700; line-height: 1; }
        .score-card__unit { font-size: 1rem; font-weight: 500; margin-left: 4px; opacity: 0.85; }
      `}</style>

      <PageHeader
        title={<><i className="fas fa-gauge-high" /> 자립 대시보드</>}
        supporting="External calls / 국적 컴플라이언스 / GB10 메모리·전력·온도 실시간 표시 (:8700 게이트웨이)"
      />

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--spacing-xl)' }}>
          <LoadingSpinner size="lg" />
        </div>
      ) : error ? (
        <p style={{ color: 'var(--color-error)' }}>Error: {error}</p>
      ) : (
        <>
          {/* 최상단 스코어카드: 메모리 / 전력 / 온도 (grafana stat 패널 형식) */}
          <div className="score-card-row">
            <ScoreCard
              label="GB10 메모리"
              value={`${status.gpu.used_gb.toFixed(1)} / ${status.gpu.total_gb.toFixed(1)}`}
              unit="GB"
              tone={scoreTone(memPercent, THRESHOLDS.mem)}
            />
            <ScoreCard
              label="전력"
              value={status.gpu.power_draw_w.toFixed(0)}
              unit="W"
              tone={scoreTone(status.gpu.power_draw_w, THRESHOLDS.power)}
            />
            <ScoreCard
              label="온도"
              value={status.gpu.temp_c.toFixed(0)}
              unit="°C"
              tone={scoreTone(status.gpu.temp_c, THRESHOLDS.temp)}
            />
          </div>

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
            <p className="form-field__hint">GPU util {status.gpu.util_percent.toFixed(0)}%</p>
          </div>
        </>
      )}
    </div>
  )
}
