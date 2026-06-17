import React from 'react'
import logo from '../assets/zorali-logo.png'

export default function LoginPage({ onLaunch }) {
  return (
    <div className="login-splash">
      <div className="splash-glow" aria-hidden="true" />
      <div className="splash-content">
        <img src={logo} alt="Zorali AI" className="splash-logo" />
        <h1 className="splash-title">Zorali AI</h1>
        <p className="splash-tagline">Chat · Code · Research · Safe Tools</p>
        <button className="splash-btn" onClick={onLaunch}>
          Launch Zorali
        </button>
        <div className="splash-features">
          <div className="splash-feature">
            <span className="splash-feature-icon">🧠</span>
            <span>Local LLM</span>
          </div>
          <div className="splash-feature">
            <span className="splash-feature-icon">💻</span>
            <span>Code Assist</span>
          </div>
          <div className="splash-feature">
            <span className="splash-feature-icon">🔎</span>
            <span>Deep Research</span>
          </div>
          <div className="splash-feature">
            <span className="splash-feature-icon">🛡️</span>
            <span>Safe Tools</span>
          </div>
        </div>
        <p className="splash-version">Your local J.A.R.V.I.S.</p>
      </div>
    </div>
  )
}
