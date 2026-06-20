import React, { useState } from 'react'
import Zorali from './Zorali.jsx'
import LoginPage from './pages/LoginPage.jsx'

export default function App() {
  const [launched, setLaunched] = useState(false)
  if (launched) return <Zorali />
  return <LoginPage onLaunch={() => setLaunched(true)} />
}

