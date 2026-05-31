import { BrowserRouter, Routes, Route } from 'react-router-dom'
import EntryPage from '@/pages/EntryPage'
import LiveSession from '@/pages/LiveSession'
import VoiceprintRegister from '@/pages/VoiceprintRegister'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<EntryPage />} />
        <Route path="/register" element={<VoiceprintRegister />} />
        <Route path="/session/:id" element={<LiveSession />} />
      </Routes>
    </BrowserRouter>
  )
}
