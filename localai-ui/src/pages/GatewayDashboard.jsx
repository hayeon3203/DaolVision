import { useEffect, useRef, useState } from 'react'
import PageHeader from '../components/PageHeader'
import LoadingSpinner from '../components/LoadingSpinner'
import { gatewayApi } from '../utils/api'
import { apiUrl } from '../utils/basePath'

// Task 7.1: 모니터링 대시보드 — 실행트레이스 + GB10 메모리 게이지 (docs/PRD.md R9).
// /dashboard/status(Task 4.3, langgraph/dashboard.py)만 폴링한다. 백엔드 계산이 아닌
// 프론트 표시 전용 페이지.
const POLL_MS = 5000
const HISTORY_MAX = 60 // 5000ms 폴링 * 60 = 5분 창

// hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M → NVIDIA-Nemotron-3-Nano-4B-GGUF
function shortModelName(model) {
  return model.replace(/^hf\.co\/[^/]+\//, '').split(':')[0]
}

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

// HF 모델카드 칩(아이콘+텍스트, 옅은 배경+테두리 pill). tone은 아이콘 색만 바꾼다 —
// 텍스트는 항상 중립(데이터 색을 텍스트에 입히지 않는다).
function HfChip({ icon, label, tone = 'muted' }) {
  return (
    <span className={`hf-chip hf-chip--${tone}`}>
      <i className={icon} />
      {label}
    </span>
  )
}

// HF 모델카드 헤더(nvidia 로고 + org/모델명)와 같은 형식. trace에서 vendor가 nvidia인
// 첫 스텝을 뽑아 보여준다 — 하드코딩 모델명 금지(모델 스왑 잦음, model-selection.md 참고).
function ModelIdentity({ trace }) {
  const step = trace.find((t) => t.vendor === 'nvidia')
  if (!step) return null
  const quant = step.model.includes(':') ? step.model.split(':')[1] : null
  return (
    <div style={{ marginBottom: 'var(--spacing-md)' }}>
      <div className="model-identity">
        <img src={apiUrl('/nvidia_logo_icon.svg')} alt="nvidia" className="model-identity__logo" />
        <span className="model-identity__org">nvidia</span>
        <span className="model-identity__sep">/</span>
        <strong className="model-identity__name">{shortModelName(step.model)}</strong>
      </div>
      <div className="hf-chip-row">
        <HfChip icon="fas fa-comments" label={step.step} />
        <HfChip icon="fas fa-building" label={step.vendor} />
        <HfChip icon="fas fa-file-lines" label={`License: ${step.license}`} />
        {quant && <HfChip icon="fas fa-layer-group" label={quant} />}
      </div>
    </div>
  )
}

// 단일 계열 line chart(크로스헤어+툴팁). 값 하나짜리 지표라 legend 없이 title이 정체성을
// 대신한다(dataviz 스킬: "단일 계열은 legend 박스 불필요").
function LineChart({ title, unit, data, valueKey, height = 90 }) {
  const width = 600
  const [hoverIdx, setHoverIdx] = useState(null)
  const n = data.length
  const values = data.map((d) => d[valueKey])
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 1)
  const pad = (max - min) * 0.15 || 1
  const yMin = Math.max(0, min - pad)
  const yMax = max + pad
  const x = (i) => (n <= 1 ? width : (i / (n - 1)) * width)
  const y = (v) => height - ((v - yMin) / (yMax - yMin || 1)) * height
  const path = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(d[valueKey]).toFixed(1)}`).join(' ')

  const handleMove = (e) => {
    if (n === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * width
    setHoverIdx(Math.max(0, Math.min(n - 1, Math.round((px / width) * (n - 1)))))
  }

  const last = n > 0 ? data[n - 1] : null
  const shown = hoverIdx != null ? data[hoverIdx] : last

  return (
    <div className="line-chart">
      <div className="line-chart__title">{title}</div>
      <svg
        viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none"
        onMouseMove={handleMove} onMouseLeave={() => setHoverIdx(null)}
        style={{ width: '100%', height, display: 'block', cursor: n > 1 ? 'crosshair' : 'default' }}
      >
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={width} y1={height * f} y2={height * f} className="line-chart__grid" />
        ))}
        {n > 1 && <path d={path} className="line-chart__path" />}
        {shown && (
          <>
            {hoverIdx != null && <line x1={x(hoverIdx)} x2={x(hoverIdx)} y1={0} y2={height} className="line-chart__crosshair" />}
            <circle cx={x(hoverIdx ?? n - 1)} cy={y(shown[valueKey])} r={4} className="line-chart__dot" />
          </>
        )}
      </svg>
      <div className="line-chart__tooltip">
        <strong>{shown ? `${shown[valueKey].toFixed(1)}${unit}` : '—'}</strong>
        <span>{shown ? new Date(shown.t).toLocaleTimeString('ko-KR', { hour12: false }) : ''}</span>
      </div>
    </div>
  )
}

export default function GatewayDashboard() {
  const [status, setStatus] = useState(null)
  const [history, setHistory] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const timerRef = useRef(null)

  useEffect(() => {
    const poll = async () => {
      try {
        const data = await gatewayApi.dashboardStatus()
        setStatus(data)
        setError(null)
        setHistory((prev) => [
          ...prev,
          { t: Date.now(), util: data.gpu.util_percent, power: data.gpu.power_draw_w, temp: data.gpu.temp_c },
        ].slice(-HISTORY_MAX))
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
        .chart-row {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: var(--spacing-md);
          margin-bottom: var(--spacing-lg);
        }
        .line-chart {
          background: var(--color-bg-secondary);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
          padding: var(--spacing-sm) var(--spacing-md);
        }
        .line-chart__title {
          font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
          color: var(--color-text-muted); margin-bottom: 4px;
        }
        .line-chart__grid { stroke: var(--color-border-subtle); stroke-width: 1; }
        .line-chart__path { fill: none; stroke: var(--color-primary); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
        .line-chart__dot { fill: var(--color-primary); stroke: var(--color-bg-secondary); stroke-width: 2; }
        .line-chart__crosshair { stroke: var(--color-text-muted); stroke-width: 1; stroke-dasharray: 2,2; }
        .line-chart__tooltip {
          display: flex; justify-content: space-between; align-items: baseline;
          margin-top: 4px; font-size: 0.8125rem;
        }
        .line-chart__tooltip strong { color: var(--color-text-primary); font-size: 1rem; }
        .line-chart__tooltip span { color: var(--color-text-muted); font-size: 0.75rem; }
        .model-identity { display: flex; align-items: center; gap: 8px; margin-bottom: var(--spacing-xs); }
        .model-identity__logo { width: 22px; height: 22px; }
        .model-identity__org { color: var(--color-text-muted); font-size: 0.875rem; }
        .model-identity__sep { color: var(--color-text-muted); }
        .model-identity__name { color: var(--color-text-primary); font-weight: 700; font-size: 1.0625rem; }
        .hf-chip-row { display: flex; flex-wrap: wrap; gap: var(--spacing-xs); }
        .hf-chip {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 3px 10px;
          border-radius: var(--radius-full);
          border: 1px solid var(--color-border-subtle);
          background: var(--color-bg-secondary);
          font-size: 0.75rem;
          color: var(--color-text-secondary);
          white-space: nowrap;
        }
        .hf-chip i { font-size: 0.7rem; color: var(--color-text-muted); }
        .hf-chip--success i { color: var(--color-success); }
        .hf-chip--warning i { color: var(--color-warning); }
        .hf-chip--error i { color: var(--color-error); }
      `}</style>

      <PageHeader
        title={<><i className="fas fa-gauge-high" /> 모니터링 대시보드</>}
        supporting="External calls / GB10 메모리·전력·온도 실시간 표시"
      />

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--spacing-xl)' }}>
          <LoadingSpinner size="lg" />
        </div>
      ) : error ? (
        <p style={{ color: 'var(--color-error)' }}>Error: {error}</p>
      ) : (
        <>
          <ModelIdentity trace={trace} />

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

          {/* 실시간 추이 (5분 창, 5초 간격) — GPU 사용률/전력/온도 */}
          <div className="chart-row">
            <LineChart title="GPU 사용률" unit="%" data={history} valueKey="util" />
            <LineChart title="전력" unit="W" data={history} valueKey="power" />
            <LineChart title="온도" unit="°C" data={history} valueKey="temp" />
          </div>

          {/* 배지: 오프라인 / External calls 실측 (HF 칩 디자인 통일) */}
          <div className="hf-chip-row" style={{ marginBottom: 'var(--spacing-lg)' }}>
            <HfChip
              icon={status.offline ? 'fas fa-circle-check' : 'fas fa-triangle-exclamation'}
              tone={status.offline ? 'success' : 'warning'}
              label={status.offline ? '오프라인' : '온라인'}
            />
            <HfChip
              icon="fas fa-arrow-right-arrow-left"
              tone={status.offline ? 'success' : 'warning'}
              label={`External calls: ${status.external_calls}`}
            />
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
