export default function StatusCard({ data }) {
  if (!data) return <p style={{ color: 'var(--zorali-muted)', fontSize: 13 }}>No status data yet.</p>
  return <pre className="status-pre">{JSON.stringify(data, null, 2)}</pre>
}
