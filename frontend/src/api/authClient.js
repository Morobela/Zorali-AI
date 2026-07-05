function extractDetail(data, fallback) {
  const detail = data?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || String(d)).join('; ')
  return fallback
}

async function post(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(extractDetail(data, `HTTP ${res.status}`))
  return data
}

export function storeTokens(data) {
  if (data?.access_token) localStorage.setItem('zorali_token', data.access_token)
  if (data?.refresh_token) localStorage.setItem('zorali_refresh_token', data.refresh_token)
}

export function clearTokens() {
  localStorage.removeItem('zorali_token')
  localStorage.removeItem('zorali_refresh_token')
}

export async function register(email, password) {
  const data = await post('/api/auth/register', { email, password })
  storeTokens(data)
  return data
}

export async function login(email, password) {
  const data = await post('/api/auth/login', { email, password })
  storeTokens(data)
  return data
}

/**
 * Exchange the stored refresh token for a fresh token pair.
 * Returns true on success; clears stale tokens and returns false otherwise.
 */
export async function refreshTokens() {
  const refreshToken = localStorage.getItem('zorali_refresh_token')
  if (!refreshToken) return false
  try {
    const data = await post('/api/auth/refresh', { refresh_token: refreshToken })
    storeTokens(data)
    return true
  } catch {
    clearTokens()
    return false
  }
}

/** Dev-only demo access — the backend returns 404 in production. */
export async function demoLogin() {
  const res = await fetch('/api/auth/demo-login', { method: 'POST' })
  return res.json()
}
