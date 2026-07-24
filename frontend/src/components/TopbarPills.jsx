import React from 'react'
import NotificationBell from './NotificationBell.jsx'

// Topbar panel switcher, extracted from Zorali.jsx when the notification
// bell landed so new surfaces stop growing the main component.
export default function TopbarPills({ panel, togglePanel }) {
  const pills = [
    ['status', 'Reality Scan'],
    ['artifacts', 'Artifacts'],
    ['memory', 'Memory'],
    ['deepSearch', 'Deep Search'],
  ]
  return (
    <div className="pills">
      {pills.map(([key, label]) => (
        <button
          key={key}
          className={`pill-btn${panel === key ? ' active' : ''}`}
          onClick={() => togglePanel(key)}
        >{label}</button>
      ))}
      <NotificationBell />
    </div>
  )
}
