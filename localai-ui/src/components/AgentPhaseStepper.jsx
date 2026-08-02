// Task 6.4: phase→스텝 하이라이트. langgraph/nodes.py가 실제로 세팅하는
// phase 값(planning/prompting/anchoring/generating/done) 순서와 1:1 매칭.
const STEPS = [
  { key: 'planning', label: '기획' },
  { key: 'prompting', label: '프롬프트' },
  { key: 'anchoring', label: '앵커링' },
  { key: 'generating', label: '생성' },
  { key: 'done', label: '완료' },
]

export default function AgentPhaseStepper({ phase }) {
  const activeIdx = STEPS.findIndex(s => s.key === phase)
  return (
    <ol className="phase-stepper" aria-label="진행 단계">
      {STEPS.map((step, i) => {
        const state = activeIdx < 0 ? '' : i < activeIdx ? 'done' : i === activeIdx ? 'active' : ''
        return (
          <li key={step.key} className={`phase-stepper__step ${state ? `phase-stepper__step--${state}` : ''}`}>
            <span className="phase-stepper__dot">{state === 'done' ? <i className="fas fa-check" /> : i + 1}</span>
            <span className="phase-stepper__label">{step.label}</span>
          </li>
        )
      })}
    </ol>
  )
}
