export default function ConnectorBar({ connectors, setConnectors }) {
  if (!connectors) return null
  return (
    <div className="connector-bar">
      {Object.entries(connectors).map(([name, active]) => (
        <button
          key={name}
          className={`conn-btn${active ? ' connected' : ''}`}
          onClick={() => setConnectors(prev => ({ ...prev, [name]: !active }))}
        >
          {active ? '●' : '○'} {name}
        </button>
      ))}
    </div>
  )
}
