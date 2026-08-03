export default function GatewayPageShell({ eyebrow, title, description, icon, facts, children }) {
  return (
    <div className="gateway-workspace">
      <header className="gateway-hero">
        <div className="gateway-hero__copy">
          <span className="gateway-hero__eyebrow"><i className="fas fa-sparkles" /> {eyebrow}</span>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        <div className="gateway-hero__mark" aria-hidden="true"><i className={`fas ${icon}`} /></div>
      </header>

      <section className="gateway-facts" aria-label={`${title} 주요 정보`}>
        {facts.map((fact, index) => (
          <article className="gateway-fact" key={fact.title}>
            <div className="gateway-fact__top">
              <span className="gateway-fact__icon"><i className={`fas ${fact.icon}`} /></span>
              <span className="gateway-fact__step">INFO 0{index + 1}</span>
            </div>
            <h2>{fact.title}</h2>
            <p>{fact.description}</p>
          </article>
        ))}
      </section>

      {children}
    </div>
  )
}

export function GatewayPanels({ inputDescription, outputDescription, children }) {
  return (
    <div className="media-layout gateway-media-layout">
      <div className="media-controls gateway-panel gateway-panel--controls">
        <GatewayPanelHeading number="01" title="프로세스" description={inputDescription} />
        {children[0]}
      </div>
      <div className="media-preview gateway-panel gateway-panel--result">
        <GatewayPanelHeading number="02" title="결과물" description={outputDescription} />
        {children[1]}
      </div>
    </div>
  )
}

function GatewayPanelHeading({ number, title, description }) {
  return (
    <div className="gateway-panel__heading">
      <span className="gateway-panel__number">{number}</span>
      <div><h2>{title}</h2><p>{description}</p></div>
    </div>
  )
}
