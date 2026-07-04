import React, { useState } from 'react'
import logo from '../assets/zorali-logo.png'
import { demoLogin, login, register, storeTokens } from '../api/authClient.js'
import { useUserStore } from '../store/userStore.js'

export default function LoginPage({ onLaunch }) {
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const setUser = useUserStore((s) => s.setUser)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!email.trim() || !password) {
      setError('Enter your email and password.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = mode === 'register'
        ? await register(email.trim(), password)
        : await login(email.trim(), password)
      setUser({ email: email.trim(), role: data?.role || 'user' })
      onLaunch()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleDemo() {
    setLoading(true)
    setError(null)
    try {
      const data = await demoLogin()
      if (data?.access_token) {
        storeTokens(data)
        setUser({ email: 'demo-owner', role: 'owner' })
        onLaunch()
      } else {
        setError('Demo access is disabled on this server.')
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

        <form className="splash-form" onSubmit={handleSubmit}>
          <input
            className="splash-input"
            type="email"
            autoComplete="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={loading}
          />
          <input
            className="splash-input"
            type="password"
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            placeholder={mode === 'register' ? 'Password (min 8 characters)' : 'Password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={loading}
          />
          <button className="splash-btn" type="submit" disabled={loading}>
            {loading ? 'Connecting…' : mode === 'register' ? 'Create account' : 'Sign in'}
          </button>
        </form>

        <button
          type="button"
          className="splash-link"
          onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null) }}
          disabled={loading}
        >
          {mode === 'login' ? 'No account yet? Create one' : 'Already registered? Sign in'}
        </button>
        <button type="button" className="splash-link splash-link-dim" onClick={handleDemo} disabled={loading}>
          Try the demo (dev servers only)
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
