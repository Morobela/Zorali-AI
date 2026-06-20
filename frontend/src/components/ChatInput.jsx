export default function ChatInput({ value, onChange, onSend, disabled }) {
  return (
    <div className="composer-input-row">
      <textarea
        className="composer-textarea"
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend() } }}
        placeholder="Message Zorali…"
      />
      <button className="send-btn" onClick={onSend} disabled={disabled || !value.trim()}>Send</button>
    </div>
  )
}
