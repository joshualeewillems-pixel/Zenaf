/**
 * Toggle between List and Timeline view for the Projects tab.
 */

export type ProjectsViewMode = 'list' | 'timeline'

export interface ProjectsViewModeToggleProps {
  value: ProjectsViewMode
  onChange: (mode: ProjectsViewMode) => void
  className?: string
}

export function ProjectsViewModeToggle({ value, onChange, className = '' }: ProjectsViewModeToggleProps) {
  return (
    <div className={`flex rounded-lg border border-slate-600 bg-slate-800/50 p-0.5 ${className}`}>
      <button
        type="button"
        onClick={() => onChange('list')}
        className={`px-3 py-1.5 text-sm rounded-md transition-colors ${value === 'list' ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
      >
        List
      </button>
      <button
        type="button"
        onClick={() => onChange('timeline')}
        className={`px-3 py-1.5 text-sm rounded-md transition-colors ${value === 'timeline' ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
      >
        Timeline
      </button>
    </div>
  )
}
