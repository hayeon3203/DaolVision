import { useTranslation } from 'react-i18next'
import nvidiaLogo from '../../../nvidia_logo_icon.png'

function HeroPill({ label, nvidia = false, technique = false }) {
  return (
    <span className="hf-chip">
      {nvidia ? (
        <img src={nvidiaLogo} alt="" className="hf-chip__logo" />
      ) : (
        <i className={technique ? 'fas fa-diagram-project' : 'fas fa-microchip'} />
      )}
      {label}
    </span>
  )
}

export default function GatewayHeroPills({ models = [], techniques = [] }) {
  const { t } = useTranslation('gateway')
  return (
    <div className="gateway-hero__pills" aria-label={t('shared.pillsAriaLabel')}>
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
