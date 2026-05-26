import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LiveSession from '@/pages/LiveSession'
import VoiceprintRegister from '@/pages/VoiceprintRegister'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/register" replace />} />
        <Route path="/register" element={<VoiceprintRegister />} />
        <Route path="/session/:id" element={<LiveSession />} />
      </Routes>
    </BrowserRouter>
  )
}
