import React from 'react'

// Dropdown list of proactive notifications (capability map U4). Rows are
// produced by backend routines (the reality engine); this panel only shows
// and acknowledges them. Data + actions come from the parent bell so the
// unread badge and the list can never disagree.
export default function NotificationPanel({ notifications, onMarkRead, onMarkAllRead, onClose }) {
  return (
    <div className="notif-panel" role="dialog" aria-label="Notifications">
      <div className="notif-panel-head">
        <strong>Notifications</strong>
        <span>
          {notifications.some(n => !n.read) && (
            <button className="notif-link" onClick={onMarkAllRead}>Mark all read</button>
          )}
          <button className="notif-link" onClick={onClose} aria-label="Close notifications">✕</button>
        </span>
      </div>
      {notifications.length === 0 && (
        <div className="notif-empty">Nothing yet — Zorali will post here when it notices something.</div>
      )}
      {notifications.map(n => (
        <div key={n.id} className={`notif-row${n.read ? '' : ' unread'}`}>
          <div className="notif-row-main">
            <div className="notif-title">{n.title}</div>
            {n.body && <div className="notif-body">{n.body}</div>}
            <div className="notif-time">{n.created_at ? new Date(n.created_at).toLocaleString() : ''}</div>
          </div>
          {!n.read && (
            <button className="notif-link" onClick={() => onMarkRead(n.id)} title="Mark read">✓</button>
          )}
        </div>
      ))}
    </div>
  )
}
