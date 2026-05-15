function authHeaders(extra = {}) {
  const h = { ...extra }
  const token = localStorage.getItem('zorali_token')
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

async function request(method, path, body) {
  const headers = authHeaders({ 'Content-Type': 'application/json' })
  const init = { method, headers }
  if (body !== undefined) init.body = JSON.stringify(body)
  const res = await fetch(path, init)
  if (!res.ok) throw new Error(await res.text().catch(() => `HTTP ${res.status}`))
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

export const apiGet = (path) => request('GET', path)
export const apiPost = (path, body) => request('POST', path, body)
export const apiPut = (path, body) => request('PUT', path, body)
export const apiDelete = (path) => request('DELETE', path)

/** Multipart file upload — body must be a FormData instance */
export async function apiUpload(path, formData) {
  const headers = authHeaders()
  const res = await fetch(path, { method: 'POST', headers, body: formData })
  if (!res.ok) throw new Error(await res.text().catch(() => `HTTP ${res.status}`))
  return res.json()
}

