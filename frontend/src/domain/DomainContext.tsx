/**
 * Shared domain context: initiatives, projects, tasks, assets, inventory, inbox.
 * Hydrated from shared seed; consumed by Vision & Execution (e.g. asset merge fallback).
 */

import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { getSeedDomain } from './seedData'
import type { DomainData } from './domainTypes'

const DomainContext = createContext<DomainData | null>(null)

export function DomainProvider({ children }: { children: ReactNode }) {
  const value = useMemo(() => getSeedDomain(), [])
  return (
    <DomainContext.Provider value={value}>
      {children}
    </DomainContext.Provider>
  )
}

export function useDomain(): DomainData {
  const ctx = useContext(DomainContext)
  if (!ctx) throw new Error('useDomain must be used within DomainProvider')
  return ctx
}
