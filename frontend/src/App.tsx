import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import EntryPage from '@/pages/EntryPage'
import LiveSession from '@/pages/LiveSession'
import VoiceprintRegister from '@/pages/VoiceprintRegister'

export default function App() {
  return (
    <BrowserRouter>
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: 'var(--bg-secondary, #17140f)',
            color: 'var(--text-primary, #e5e5e5)',
            border: '1px solid var(--border-default, rgba(255,255,255,0.08))',
            fontSize: '14px',
          },
        }}
      />
      <Routes>
        <Route path="/" element={<EntryPage />} />
        <Route path="/register" element={<VoiceprintRegister />} />
        <Route path="/session/:id" element={<LiveSession />} />
      </Routes>
    </BrowserRouter>
  )
}
