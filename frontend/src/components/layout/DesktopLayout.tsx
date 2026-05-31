import ProfilePanel from '@/components/profile/ProfilePanel'
import type { Profile } from '@/types'
import type { ReactNode } from 'react'

export type DesktopLayoutProps = {
  profile: Profile | null
  insightStream: ReactNode
  transcriptPanel: ReactNode
}

export default function DesktopLayout({
  profile,
  insightStream,
  transcriptPanel,
}: DesktopLayoutProps) {
  return (
    <div className="hidden md:flex flex-1 overflow-hidden">
      {/* 左：当事人画像展板 (260px 固定) */}
      <div className="w-[260px] shrink-0 flex flex-col bg-bg-secondary border-r border-border-color">
        <ProfilePanel profile={profile} />
      </div>

      {/* 中：洞察流 (自适应) */}
      {insightStream}

      {/* 右：精简转写参考 (280px，可折叠) */}
      {transcriptPanel}
    </div>
  )
}
