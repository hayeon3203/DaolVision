// Task 6.4: phase→스텝 하이라이트. langgraph/nodes.py가 실제로 세팅하는
// phase 값(planning/prompting/anchoring/generating/done) 순서와 1:1 매칭.
const BASE_STEPS = [
  { key: 'planning', label: '기획' },
  { key: 'prompting', label: '프롬프트' },
  { key: 'anchoring', label: '앵커링' },
  { key: 'generating', label: '생성' },
  { key: 'done', label: '완료' },
]
// M2(이미지 설명으로 생성)로 들어온 job만 앞에 붙는 리딩 스텝(phase=image_generating,
// node_rewrite_image_query/node_generate_image). "사진 첨부" job에는 없는 단계라
// imageGenUsed일 때만 조건부로 그린다.
const IMAGE_GEN_STEP = { key: 'image_generating', label: '이미지 생성' }

export default function AgentPhaseStepper({ phase, imageGenUsed }) {
  const steps = imageGenUsed ? [IMAGE_GEN_STEP, ...BASE_STEPS] : BASE_STEPS
  const activeIdx = steps.findIndex(s => s.key === phase)
  return (
    <ol className="phase-stepper" aria-label="진행 단계">
      {steps.map((step, i) => {
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
