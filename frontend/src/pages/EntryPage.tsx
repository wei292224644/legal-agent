import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Mic, Shield, Brain, ArrowRight } from 'lucide-react'

export default function EntryPage() {
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
    <div className="relative flex flex-col md:flex-row h-screen bg-bg-primary text-ink-primary overflow-hidden">
      {/* Ambient background */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse 60% 50% at 50% 40%, rgba(124,156,191,0.06) 0%, transparent 70%)',
        }}
      />

      {/* Left: Product intro */}
      <div className="relative z-10 flex-1 flex flex-col justify-center px-8 md:px-16 py-12">
        <div className="max-w-lg">
          <div className="flex items-center gap-2 mb-6">
            <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center">
              <Brain className="w-4 h-4 text-accent" />
            </div>
            <span className="text-sm font-medium text-accent">法律 AI 辅助会谈</span>
          </div>

          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-primary mb-4">
            实时转写、智能分析、<br />风险识别
          </h1>
          <p className="text-base text-ink-secondary leading-relaxed mb-8">
            做您会谈中的第二大脑。基于大语言模型的实时法律分析，
            帮助律师在会谈中快速识别风险、引用法规、把握当事人心理。
          </p>

          <div className="space-y-4">
            {[
              { icon: Mic, text: '实时语音转写，自动区分律师与当事人' },
              { icon: Brain, text: '智能洞察生成，法规引用与风险提示' },
              { icon: Shield, text: '当事人画像构建，情绪与主张追踪' },
            ].map((feature, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-md bg-bg-tertiary flex items-center justify-center shrink-0">
                  <feature.icon className="w-4 h-4 text-accent" />
                </div>
                <span className="text-sm text-ink-secondary">{feature.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right: Action area */}
      <div className="relative z-10 md:w-[420px] shrink-0 flex flex-col justify-center px-8 md:px-12 py-12 bg-bg-secondary border-t md:border-t-0 md:border-l border-border-color">
        <div className="max-w-sm mx-auto w-full">
          <h2 className="text-xl font-semibold text-ink-primary mb-2">开始会谈</h2>
          <p className="text-sm text-ink-muted mb-8">
            创建加密会话，所有数据仅保存在本地与您的服务器中。
          </p>

          <Button
            size="lg"
            onClick={handleStart}
            disabled={loading}
            className="w-full h-12 text-base bg-accent text-bg-primary hover:bg-accent-hover mb-4"
          >
            {loading ? '创建中…' : (
              <>
                开始新会谈
                <ArrowRight className="w-4 h-4 ml-2" />
              </>
            )}
          </Button>

          <Button
            variant="ghost"
            onClick={() => navigate('/register')}
            className="w-full text-sm text-ink-muted hover:text-ink-primary"
          >
            声纹注册
          </Button>
        </div>
      </div>
    </div>
  )
}
