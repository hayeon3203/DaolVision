import { useTranslation } from 'react-i18next'

// Task 6.4: phase→스텝 하이라이트. langgraph/nodes.py가 실제로 세팅하는
// phase 값(planning/prompting/anchoring/generating/done) 순서와 1:1 매칭.
const BASE_STEPS = ['planning', 'prompting', 'anchoring', 'generating', 'done']
// M2(이미지 설명으로 생성)로 들어온 job만 앞에 붙는 리딩 스텝(phase=image_generating,
// node_rewrite_image_query/node_generate_image). "사진 첨부" job에는 없는 단계라
// imageGenUsed일 때만 조건부로 그린다.
const IMAGE_GEN_STEP = 'image_generating'

export default function AgentPhaseStepper({ phase, imageGenUsed }) {
  const { t } = useTranslation('gateway')
  const stepKeys = imageGenUsed ? [IMAGE_GEN_STEP, ...BASE_STEPS] : BASE_STEPS
  const steps = stepKeys.map((key) => ({ key, label: t(`phaseStepper.${key === 'image_generating' ? 'imageGenerating' : key}`) }))
  const activeIdx = steps.findIndex(s => s.key === phase)
  return (
    <ol className="phase-stepper" aria-label={t('phaseStepper.ariaLabel')}>
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
