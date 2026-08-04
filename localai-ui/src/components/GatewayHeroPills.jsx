import { apiUrl } from '../utils/basePath'

function HeroPill({ label, nvidia = false, technique = false }) {
  return (
    <span className="hf-chip">
      {nvidia ? (
        <img src={apiUrl('/nvidia_logo_icon.svg')} alt="" className="hf-chip__logo" />
      ) : (
        <i className={technique ? 'fas fa-diagram-project' : 'fas fa-microchip'} />
      )}
      {label}
    </span>
  )
}

export default function GatewayHeroPills({ models = [], techniques = [] }) {
  return (
    <div className="gateway-hero__pills" aria-label="사용 모델 및 기법">
      {models.map((model) => (
        <HeroPill
          key={model.label}
          label={model.label}
          nvidia={model.company === 'NVIDIA'}
        />
      ))}
      {techniques.map((technique) => (
        <HeroPill key={technique} label={technique} technique />
      ))}
    </div>
  )
}
