import { useState } from 'react'
import { Activity, User, MessageSquare } from 'lucide-react'
import ProfilePanel from '@/components/profile/ProfilePanel'
import type { Profile } from '@/types'
import type { ReactNode } from 'react'

export type MobileLayoutProps = {
  profile: Profile | null
  insightStream: ReactNode
  transcriptPanel: ReactNode
  connectionStatus: ReactNode
  audioControls: ReactNode
}

export default function MobileLayout({
  profile,
  insightStream,
  transcriptPanel,
  connectionStatus,
  audioControls,
}: MobileLayoutProps) {
  const [activeTab, setActiveTab] = useState<'insights' | 'profile' | 'transcript'>('insights')

  return (
    <div className="flex md:hidden flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="px-4 h-12 shrink-0 flex items-center justify-between border-b border-border-color bg-bg-primary">
        <div className="flex items-center gap-3">
          <div className="text-base font-semibold text-ink-primary tracking-tight">实时会谈</div>
          {connectionStatus}
        </div>
        {audioControls}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'insights' && (
          <div className="h-full overflow-auto">
            {/* Mobile profile summary */}
            {profile && (
              <div className="px-4 pt-4">
                <ProfilePanel profile={profile} compact />
              </div>
            )}
            <div className="px-4 py-4">{insightStream}</div>
          </div>
        )}
        {activeTab === 'profile' && (
          <div className="h-full overflow-auto px-4 py-4">
            <ProfilePanel profile={profile} />
          </div>
        )}
        {activeTab === 'transcript' && (
          <div className="h-full overflow-auto px-4 py-4">{transcriptPanel}</div>
        )}
      </div>

      {/* Bottom Tab Bar */}
      <nav className="flex border-t border-border-color bg-bg-secondary shrink-0">
        <button
          onClick={() => setActiveTab('insights')}
          className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm transition-colors ${
            activeTab === 'insights'
              ? 'text-ink-primary bg-bg-tertiary border-t-2 border-accent -mt-px'
              : 'text-ink-muted hover:text-ink-primary'
          }`}
        >
          <Activity className="w-4 h-4" />
          洞察
        </button>
        <button
          onClick={() => setActiveTab('profile')}
          className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm transition-colors ${
            activeTab === 'profile'
              ? 'text-ink-primary bg-bg-tertiary border-t-2 border-accent -mt-px'
              : 'text-ink-muted hover:text-ink-primary'
          }`}
        >
          <User className="w-4 h-4" />
          画像
        </button>
        <button
          onClick={() => setActiveTab('transcript')}
          className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm transition-colors ${
            activeTab === 'transcript'
              ? 'text-ink-primary bg-bg-tertiary border-t-2 border-accent -mt-px'
              : 'text-ink-muted hover:text-ink-primary'
          }`}
        >
          <MessageSquare className="w-4 h-4" />
          转写
        </button>
      </nav>
    </div>
  )
}
