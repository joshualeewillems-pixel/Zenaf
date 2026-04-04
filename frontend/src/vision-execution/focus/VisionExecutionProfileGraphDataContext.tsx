import { createContext, useContext, useMemo, type ReactNode } from 'react'
import type { ProfileGraphDataSnapshot } from './graphSliceTypes'

type Value = {
  snapshot: ProfileGraphDataSnapshot
}

const VisionExecutionProfileGraphDataContext = createContext<Value | null>(null)

const EMPTY_SNAPSHOT: ProfileGraphDataSnapshot = { profiles: [], activeProfileId: null }

/**
 * Supplies profile-list + active profile id for `resolveGraphSliceProfile` (parallel to VE graph).
 */
export function VisionExecutionProfileGraphDataProvider({
  snapshot,
  children,
}: {
  snapshot: ProfileGraphDataSnapshot
  children: ReactNode
}) {
  const value = useMemo(() => ({ snapshot }), [snapshot])
  return (
    <VisionExecutionProfileGraphDataContext.Provider value={value}>{children}</VisionExecutionProfileGraphDataContext.Provider>
  )
}

export function useVisionExecutionProfileGraphOptional(): ProfileGraphDataSnapshot {
  const ctx = useContext(VisionExecutionProfileGraphDataContext)
  return ctx?.snapshot ?? EMPTY_SNAPSHOT
}
