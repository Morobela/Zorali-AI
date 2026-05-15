export default function DeepSearchPanel({ steps }) {
  return (
    <div className="panel-body">
      {(steps || ['Planning research path', 'Browsing sources', 'Cross-checking memory', 'Synthesizing answer']).map((s, i) => (
        <div key={i} className="step-item">{i + 1}. {s}</div>
      ))}
    </div>
  )
}
