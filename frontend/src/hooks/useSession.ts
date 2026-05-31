import { useContext } from 'react'
import { SessionContext } from '@/context/session-context'

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used within SessionProvider')
  return ctx
}
