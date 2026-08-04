import { useNavigate } from 'react-router-dom'
import { useBranding } from '../contexts/BrandingContext'
import SectionHeading from '../components/SectionHeading'
import nvidiaLogo from '../../../NVIDIA.png'

const studios = [
  {
    path: '/app/gw-agent',
    icon: 'fa-wand-magic-sparkles',
    eyebrow: 'STORY STUDIO',
    title: '스토리 영상',
    description: '아이디어 한 줄에서 장면과 영상까지. 완성된 이야기로 연결합니다.',
    color: 'violet',
    preview: 'timeline',
    featured: true,
  },
  {
    path: '/app/gw-t2v',
    icon: 'fa-clapperboard',
    eyebrow: 'TEXT TO VIDEO',
    title: '영상 만들기',
    description: '텍스트로 장면을 설명하고 짧은 영상을 바로 생성하세요.',
    color: 'blue',
    preview: 'video',
  },
  {
    path: '/app/gw-i2i',
    icon: 'fa-palette',
    eyebrow: 'IMAGE TO IMAGE',
    title: '이미지 스타일링',
    description: '인물의 특징은 살리고 원하는 무드와 스타일로 새롭게 바꿉니다.',
    color: 'coral',
    preview: 'image',
  },
  {
    path: '/app/gw-tts',
    icon: 'fa-wave-square',
    eyebrow: 'VOICE STUDIO',
    title: '목소리 만들기',
    description: '짧은 음성 샘플로 자연스러운 한국어 내레이션을 만드세요.',
    color: 'mint',
    preview: 'audio',
  },
  {
    path: '/app/gw-t2i',
    icon: 'fa-image',
    eyebrow: 'TEXT TO IMAGE',
    title: '이미지 만들기',
    description: '상상을 문장으로 적으면 고품질 이미지로 빠르게 시각화합니다.',
    color: 'amber',
    preview: 'canvas',
  },
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

  return (
    <div className="home-page dv-home">
      <section className="dv-hero" aria-labelledby="dv-home-title">
        <div className="dv-hero-copy">
          <h1 id="dv-home-title" className="home-greeting">
            <span className="dv-headline-line">상상에만 집중하세요.</span>
            <span className="dv-headline-line dv-headline-line--accent">나머지는 로컬 AI가.</span>
          </h1>
          <p>
            이미지, 영상, 목소리와 스토리를 하나의 스튜디오에서 만드세요.
            데이터는 내 환경 안에 머물고, 사용량과 토큰 제한 없이 계속 창작할 수 있습니다.
          </p>
          <div className="dv-hero-actions home-quick-links">
            <button className="btn btn-primary dv-primary-cta" onClick={() => navigate('/app/gw-agent')}>
              지금 만들기 <i className="fas fa-arrow-right" />
            </button>
            <button className="dv-text-cta" onClick={() => document.getElementById('dv-studios')?.scrollIntoView({ behavior: 'smooth' })}>
              도구 둘러보기 <i className="fas fa-chevron-down" />
            </button>
          </div>
        </div>

        <div className="dv-hero-visual" aria-label="격리된 로컬 AI 제작 환경">
          <div className="dv-window">
            <div className="dv-window-bar"><span /><span /><span /><small>{branding.instanceName} Studio</small></div>
            <div className="dv-window-body">
              <div className="dv-window-rail"><i className="fas fa-wand-magic-sparkles" /><i className="fas fa-image" /><i className="fas fa-video" /><i className="fas fa-wave-square" /></div>
              <div className="dv-window-workspace">
                <div className="dv-workspace-head"><span>새로운 장면</span><small>안전한 환경에서 실행 중</small></div>
                <div className="dv-prompt-line"><span>노을이 지는 미래 도시를 걷는 여행자</span><i className="fas fa-arrow-up" /></div>
                <div className="dv-generated-grid"><span /><span /><span /></div>
              </div>
            </div>
          </div>
          <div className="dv-float-card dv-float-card--shield"><i className="fas fa-lock" /><span><strong>완전히 격리됨</strong>OpenShell sandbox</span></div>
          <div className="dv-float-card dv-float-card--token"><i className="fas fa-infinity" /><span><strong>토큰 제한 없음</strong>마음껏 생성하세요</span></div>
        </div>
      </section>

      <section className="dv-trust-row" aria-label="DaolVision의 장점">
        <div><i className="fas fa-box" /><span><strong>격리된 실행</strong>작업마다 안전한 샌드박스</span></div>
        <div><i className="fas fa-coins" /><span><strong>토큰 걱정 없이</strong>구독·사용량 제한 없는 로컬 생성</span></div>
        <div><i className="fas fa-hard-drive" /><span><strong>내 데이터는 내 안에</strong>외부 전송 없는 프라이빗 워크플로우</span></div>
        <div><i className="fas fa-bolt" /><span><strong>한 곳에서 완성</strong>이미지부터 영상·음성까지</span></div>
      </section>

      <section id="dv-studios" className="dv-studios">
        <div className="dv-section-head">
          <div>
            <span className="dv-section-kicker">CREATIVE SUITE</span>
            <h2>무엇을 만들어 볼까요?</h2>
            <p>목적에 맞는 스튜디오를 고르면 바로 시작할 수 있어요.</p>
          </div>
          <button className="dv-dashboard-link" onClick={() => navigate('/app/gw-dashboard')}>
            <i className="fas fa-chart-line" /> 운영 현황 보기
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
            <span>모든 생성 도구는 독립된 OpenShell 환경에서 준비됩니다.</span>
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
        <div><span>NO CLOUD. NO TOKEN METER.</span><h2>제한 없는 창작 환경을<br />지금 시작하세요.</h2></div>
        <button onClick={() => navigate('/app/gw-agent')}>첫 작품 만들기 <i className="fas fa-arrow-right" /></button>
      </section>
    </div>
  )
}
