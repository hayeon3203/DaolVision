import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useBranding } from '../contexts/BrandingContext'
import SectionHeading from '../components/SectionHeading'
import nvidiaLogo from '../../../NVIDIA.png'

const STUDIO_KEYS = [
  { path: '/app/gw-agent', icon: 'fa-wand-magic-sparkles', eyebrow: 'STORY STUDIO', key: 'story', color: 'violet', preview: 'timeline', featured: true },
  { path: '/app/gw-t2v', icon: 'fa-clapperboard', eyebrow: 'TEXT TO VIDEO', key: 'video', color: 'blue', preview: 'video' },
  { path: '/app/gw-i2i', icon: 'fa-palette', eyebrow: 'IMAGE TO IMAGE', key: 'styling', color: 'coral', preview: 'image' },
  { path: '/app/gw-tts', icon: 'fa-wave-square', eyebrow: 'VOICE STUDIO', key: 'voice', color: 'mint', preview: 'audio' },
  { path: '/app/gw-t2i', icon: 'fa-image', eyebrow: 'TEXT TO IMAGE', key: 'image', color: 'amber', preview: 'canvas' },
]

function StudioPreview({ type }) {
  if (type === 'timeline') return (
    <div className="dv-preview dv-preview--timeline" aria-hidden="true">
      <div className="dv-scene dv-scene--one"><i className="fas fa-mountain-sun" /></div>
      <div className="dv-scene dv-scene--two"><i className="fas fa-person-walking" /></div>
      <div className="dv-scene dv-scene--three"><i className="fas fa-city" /></div>
    </div>
  )
  if (type === 'video') return (
    <div className="dv-preview dv-preview--video" aria-hidden="true">
      <span className="dv-orbit" /><i className="fas fa-play" />
      <div className="dv-video-line"><span /></div>
    </div>
  )
  if (type === 'audio') return (
    <div className="dv-preview dv-preview--audio" aria-hidden="true">
      {[4, 8, 13, 7, 18, 12, 21, 9, 15, 6, 11, 5].map((height, i) => <span key={i} style={{ height }} />)}
    </div>
  )
  if (type === 'image') return (
    <div className="dv-preview dv-preview--image" aria-hidden="true">
      <div><i className="fas fa-user" /></div><i className="fas fa-arrow-right" /><div><i className="fas fa-user-astronaut" /></div>
    </div>
  )
  return (
    <div className="dv-preview dv-preview--canvas" aria-hidden="true">
      <i className="fas fa-mountain-sun" /><span className="dv-spark dv-spark--one">✦</span><span className="dv-spark dv-spark--two">✦</span>
    </div>
  )
}

export default function Home() {
  const navigate = useNavigate()
  const branding = useBranding()
  const { t } = useTranslation('home')
  const studios = STUDIO_KEYS.map((s) => ({
    ...s,
    title: t(`landing.studios.${s.key}.title`),
    description: t(`landing.studios.${s.key}.description`),
  }))

  return (
    <div className="home-page dv-home">
      <section className="dv-hero" aria-labelledby="dv-home-title">
        <div className="dv-hero-copy">
          <h1 id="dv-home-title" className="home-greeting">
            <span className="dv-headline-line">{t('landing.headlineLine1')}</span>
            <span className="dv-headline-line dv-headline-line--accent">{t('landing.headlineLine2')}</span>
          </h1>
          <p>
            {t('landing.intro')}
          </p>
          <div className="dv-hero-actions home-quick-links">
            <button className="btn btn-primary dv-primary-cta" onClick={() => navigate('/app/gw-agent')}>
              {t('landing.primaryCta')} <i className="fas fa-arrow-right" />
            </button>
            <button className="dv-text-cta" onClick={() => document.getElementById('dv-studios')?.scrollIntoView({ behavior: 'smooth' })}>
              {t('landing.exploreCta')} <i className="fas fa-chevron-down" />
            </button>
          </div>
        </div>

        <div className="dv-hero-visual" aria-label={t('landing.heroVisualAriaLabel')}>
          <div className="dv-window">
            <div className="dv-window-bar"><span /><span /><span /><small>{branding.instanceName} Studio</small></div>
            <div className="dv-window-body">
              <div className="dv-window-rail"><i className="fas fa-wand-magic-sparkles" /><i className="fas fa-image" /><i className="fas fa-video" /><i className="fas fa-wave-square" /></div>
              <div className="dv-window-workspace">
                <div className="dv-workspace-head"><span>{t('landing.workspaceHead')}</span><small>{t('landing.workspaceSub')}</small></div>
                <div className="dv-prompt-line"><span>{t('landing.promptExample')}</span><i className="fas fa-arrow-up" /></div>
                <div className="dv-generated-grid"><span /><span /><span /></div>
              </div>
            </div>
          </div>
          <div className="dv-float-card dv-float-card--shield"><i className="fas fa-lock" /><span><strong>{t('landing.shieldTitle')}</strong>{t('landing.shieldDesc')}</span></div>
          <div className="dv-float-card dv-float-card--token"><i className="fas fa-infinity" /><span><strong>{t('landing.tokenTitle')}</strong>{t('landing.tokenDesc')}</span></div>
        </div>
      </section>

      <section className="dv-trust-row" aria-label={t('landing.trustAriaLabel')}>
        <div><i className="fas fa-box" /><span><strong>{t('landing.trust1Title')}</strong>{t('landing.trust1Desc')}</span></div>
        <div><i className="fas fa-coins" /><span><strong>{t('landing.trust2Title')}</strong>{t('landing.trust2Desc')}</span></div>
        <div><i className="fas fa-hard-drive" /><span><strong>{t('landing.trust3Title')}</strong>{t('landing.trust3Desc')}</span></div>
        <div><i className="fas fa-bolt" /><span><strong>{t('landing.trust4Title')}</strong>{t('landing.trust4Desc')}</span></div>
      </section>

      <section id="dv-studios" className="dv-studios">
        <div className="dv-section-head">
          <div>
            <span className="dv-section-kicker">CREATIVE SUITE</span>
            <h2>{t('landing.studiosHeading')}</h2>
            <p>{t('landing.studiosSubheading')}</p>
          </div>
          <button className="dv-dashboard-link" onClick={() => navigate('/app/gw-dashboard')}>
            <i className="fas fa-chart-line" /> {t('landing.dashboardLink')}
          </button>
        </div>

        <div className="dv-studio-grid">
          {studios.map((studio) => (
            <button
              key={studio.path}
              className={`dv-studio-card dv-studio-card--${studio.color} ${studio.featured ? 'dv-studio-card--featured' : ''}`}
              onClick={() => navigate(studio.path)}
            >
              <div className="dv-card-top">
                <span className="dv-card-icon"><i className={`fas ${studio.icon}`} /></span>
                <span className="dv-card-arrow"><i className="fas fa-arrow-up-right-from-square" /></span>
              </div>
              <StudioPreview type={studio.preview} />
              <span className="dv-card-eyebrow">{studio.eyebrow}</span>
              <strong>{studio.title}</strong>
              <p>{studio.description}</p>
            </button>
          ))}
        </div>
      </section>

      <section className="dv-runtime-note">
        <div className="dv-runtime-copy">
          <span className="dv-runtime-kicker">MODEL RUNTIME</span>
          <SectionHeading>Active models</SectionHeading>
          <div className="dv-runtime-status">
            <span className="dv-live-dot" aria-hidden="true" />
            <span>{t('landing.runtimeStatus')}</span>
          </div>
        </div>
        <div className="dv-runtime-brand" aria-label="NVIDIA accelerated computing">
          <span>ACCELERATED BY</span>
          <span className="dv-runtime-logo">
            <img src={nvidiaLogo} alt="NVIDIA" />
          </span>
        </div>
      </section>

      <section className="dv-bottom-cta">
        <div><span>NO CLOUD. NO TOKEN METER.</span><h2>{t('landing.bottomCtaLine1')}<br />{t('landing.bottomCtaLine2')}</h2></div>
        <button onClick={() => navigate('/app/gw-agent')}>{t('landing.bottomCtaButton')} <i className="fas fa-arrow-right" /></button>
      </section>
    </div>
  )
}
