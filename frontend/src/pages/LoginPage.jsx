import React, { useState } from 'react'
import logo from '../assets/zorali-logo.png'
import { demoLogin } from '../api/authClient.js'

export default function LoginPage({ onLaunch }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleLaunch() {
    setLoading(true)
    setError(null)
    try {
      const data = await demoLogin()
      if (data?.access_token) {
        localStorage.setItem('zorali_token', data.access_token)
        onLaunch()
      } else {
        setError('Login failed — no token received.')
      }
    } catch (err) {
      setError(`Cannot reach backend: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-splash">
      <div className="splash-glow" aria-hidden="true" />
      <div className="splash-content">
        <img src={logo} alt="Zorali" className="splash-logo" />
        <h1 className="splash-title">Zorali</h1>
        <p className="splash-tagline">Chat · Code · Research · Safe Tools</p>
        <button className="splash-btn" onClick={handleLaunch} disabled={loading}>
          {loading ? 'Connecting…' : 'Launch Zorali'}
        </button>
        {error && <p style={{ color: '#f87171', fontSize: 13, marginTop: 8 }}>{error}</p>}
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
            <span>Search Preview</span>
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
