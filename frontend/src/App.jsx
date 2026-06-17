import React, { useState } from 'react'
import ZoraliAI from './ZoraliAI.jsx'
import LoginPage from './pages/LoginPage.jsx'

export default function App() {
  const [launched, setLaunched] = useState(false)
  if (launched) return <ZoraliAI />
  return <LoginPage onLaunch={() => setLaunched(true)} />
}

