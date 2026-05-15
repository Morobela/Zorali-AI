export default function Topbar({ onPanelToggle, activePanel }) {
  const pills = [
    { id: 'status', label: 'Reality Scan' },
    { id: 'artifacts', label: 'Artifacts' },
    { id: 'memory', label: 'Memory' },
    { id: 'deepSearch', label: 'Deep Search' },
  ]
  return (
    <header className="topbar">
      <div className="topbar-left">
        <h1>Zorali AI</h1>
        <p>Chat · Code · Research · Project Status · Safe Tools</p>
      </div>
      <div className="pills">
        {pills.map(p => (
          <button
            key={p.id}
            className={`pill-btn${activePanel === p.id ? ' active' : ''}`}
            onClick={() => onPanelToggle(p.id)}
          >{p.label}</button>
        ))}
      </div>
    </header>
  )
}
