import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import LiveSession from '@/pages/LiveSession'
import VoiceprintRegister from '@/pages/VoiceprintRegister'

function EntryPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)

  const handleStart = async () => {
    setLoading(true)
    try {
      const resp = await fetch('http://localhost:8000/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const { session_id } = await resp.json()
      navigate(`/session/${session_id}`)
    } catch (e) {
      alert('创建会话失败: ' + (e as Error).message)
      setLoading(false)
    }
  }

  return (
    <div className="relative flex flex-col items-center justify-center h-screen bg-background text-foreground gap-8 overflow-hidden">
      {/* Subtle ambient background to break flat black */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse 60% 50% at 50% 40%, rgba(212,168,83,0.08) 0%, transparent 70%)',
        }}
      />

      <div className="relative z-10 flex flex-col items-center gap-6 text-center max-w-md px-6">
        <h1 className="text-4xl font-semibold tracking-tight text-primary">
          法律 AI 辅助会谈
        </h1>
        <p className="text-base text-muted-foreground leading-relaxed">
          实时转写、智能分析、风险识别，<br />做您会谈中的第二大脑。
        </p>
        <Button size="lg" onClick={handleStart} disabled={loading} className="w-full max-w-[240px] text-base mt-2">
          {loading ? '创建中…' : '开始新会谈'}
        </Button>
        <Button variant="ghost" onClick={() => navigate('/register')} className="text-sm text-muted-foreground hover:text-foreground">
          声纹注册
        </Button>
      </div>
    </div>
  )
}

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
