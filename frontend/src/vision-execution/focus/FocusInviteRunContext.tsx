import { createContext, useContext, type ReactNode } from 'react'
import type { FocusContextCore } from './types'
import type { FocusInvite } from './focusInviteTypes'

export type FocusInviteRunHandler = (invite: FocusInvite, core: FocusContextCore) => void

const FocusInviteRunContext = createContext<FocusInviteRunHandler | null>(null)

export function FocusInviteRunProvider({
  value,
  children,
}: {
  value: FocusInviteRunHandler
  children: ReactNode
}) {
  return <FocusInviteRunContext.Provider value={value}>{children}</FocusInviteRunContext.Provider>
}

export function useFocusInviteRunOptional(): FocusInviteRunHandler | null {
  return useContext(FocusInviteRunContext)
}
