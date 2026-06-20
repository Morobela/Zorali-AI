import React, { useState } from 'react'
import Zorali from './Zorali.jsx'
import LoginPage from './pages/LoginPage.jsx'

export default function App() {
  // If a token already exists in localStorage, skip the login splash
  const [launched, setLaunched] = useState(() => !!localStorage.getItem('zorali_token'))
  if (launched) return <Zorali />
  return <LoginPage onLaunch={() => setLaunched(true)} />
}
