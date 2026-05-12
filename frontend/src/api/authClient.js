export async function demoLogin(){
  const res = await fetch('/api/auth/demo-login', { method: 'POST' })
  return res.json()
}
