import React, { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from '../api/httpClient.js'
import NotificationPanel from './NotificationPanel.jsx'

const POLL_MS = 30000

// Unread badge + dropdown for proactive notifications (capability map U4).
// Polls the unread count so Zorali-initiated messages surface without any
// user action; every fetch fails soft — a dead backend must never break
// the topbar.
export default function NotificationBell() {
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [notifications, setNotifications] = useState([])
  const openRef = useRef(false)
  openRef.current = open

  const refreshCount = useCallback(async () => {
    try {
      const res = await apiGet('/api/notifications/unread-count')
      setUnread(res.unread || 0)
    } catch {
      /* backend unreachable — keep the last known badge */
    }
  }, [])

  const refreshList = useCallback(async () => {
    try {
      setNotifications(await apiGet('/api/notifications?limit=50'))
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    refreshCount()
    const timer = setInterval(() => {
      refreshCount()
      if (openRef.current) refreshList()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [refreshCount, refreshList])

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (next) await refreshList()
  }

  const markRead = async (id) => {
    try {
      await apiPost(`/api/notifications/${id}/read`)
      setNotifications(list => list.map(n => (n.id === id ? { ...n, read: true } : n)))
      setUnread(u => Math.max(0, u - 1))
    } catch {
      /* ignore */
    }
  }

  const markAllRead = async () => {
    try {
      await apiPost('/api/notifications/read-all')
      setNotifications(list => list.map(n => ({ ...n, read: true })))
      setUnread(0)
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="notif-bell-wrap">
      <button
        className={`pill-btn notif-bell${open ? ' active' : ''}`}
        onClick={toggle}
        title="Notifications"
        aria-label={`Notifications (${unread} unread)`}
      >
        🔔{unread > 0 && <span className="notif-badge">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <NotificationPanel
          notifications={notifications}
          onMarkRead={markRead}
          onMarkAllRead={markAllRead}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  )
}
