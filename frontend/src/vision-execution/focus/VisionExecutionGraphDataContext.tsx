import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import type { VeGraphDataSnapshot } from './graphSliceTypes'

type GraphDataValue = {
  /** Latest VE entity lists from VisionExecutionView — drives `resolveGraphSliceVE` */
  snapshot: VeGraphDataSnapshot | null
  setSnapshot: (next: VeGraphDataSnapshot | null) => void
}

const VisionExecutionGraphDataContext = createContext<GraphDataValue | null>(null)

export function VisionExecutionGraphDataProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<VeGraphDataSnapshot | null>(null)
  const value = useMemo(() => ({ snapshot, setSnapshot }), [snapshot])
  return <VisionExecutionGraphDataContext.Provider value={value}>{children}</VisionExecutionGraphDataContext.Provider>
}

export function useVisionExecutionGraphDataOptional(): GraphDataValue | null {
  return useContext(VisionExecutionGraphDataContext)
}
