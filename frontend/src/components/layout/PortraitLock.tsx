import { useState, useEffect } from 'react'
import { Smartphone } from 'lucide-react'

export default function PortraitLock() {
  const [isLandscapeMobile, setIsLandscapeMobile] = useState(false)

  useEffect(() => {
    const checkOrientation = () => {
      const isMobileWidth = window.innerWidth < 768
      const matchLandscape = window.matchMedia('(orientation: landscape)').matches
      setIsLandscapeMobile(isMobileWidth && matchLandscape)
    }

    checkOrientation()
    window.addEventListener('resize', checkOrientation)
    window.screen.orientation?.addEventListener?.('change', checkOrientation)

    return () => {
      window.removeEventListener('resize', checkOrientation)
      window.screen.orientation?.removeEventListener?.('change', checkOrientation)
    }
  }, [])

  if (!isLandscapeMobile) return null

  return (
    <div className="fixed inset-0 z-50 bg-bg-primary flex flex-col items-center justify-center gap-4 p-8">
      <Smartphone className="w-12 h-12 text-accent animate-pulse" />
      <h2 className="text-lg font-semibold text-ink-primary text-center">请旋转设备</h2>
      <p className="text-sm text-ink-secondary text-center">
        为获得最佳体验，请将手机旋转至竖屏模式
      </p>
    </div>
  )
}
