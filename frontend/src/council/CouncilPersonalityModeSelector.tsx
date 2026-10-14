/**
 * CouncilPersonalityModeSelector — compact Base / Mirror / Blend segmented
 * control for the council view. Which version of a seat to use is the
 * user's decision, per purpose.
 */
import React from 'react'
import {
  COUNCIL_PERSONALITY_MODES,
  COUNCIL_PERSONALITY_MODE_LABELS,
  COUNCIL_PERSONALITY_MODE_HINTS,
  type CouncilPersonalityMode,
} from './councilPersonalityMode'

export function CouncilPersonalityModeSelector({
  value,
  onChange,
  disabled,
}: {
  value: CouncilPersonalityMode
  onChange: (mode: CouncilPersonalityMode) => void
  disabled?: boolean
}): React.ReactElement {
  return (
    <div>
      <p className="block text-xs text-stone-500 mb-1">Council version</p>
      <div
        role="radiogroup"
        aria-label="Which version of the council seats to use"
        className="grid grid-cols-3 gap-1 rounded-lg bg-stone-900 border border-stone-700 p-1"
      >
        {COUNCIL_PERSONALITY_MODES.map((mode) => {
          const selected = value === mode
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={selected}
              title={COUNCIL_PERSONALITY_MODE_HINTS[mode]}
              disabled={disabled}
              onClick={() => onChange(mode)}
              className={`min-h-[44px] rounded-md px-2 text-sm font-medium transition-colors disabled:opacity-50 ${
                selected
                  ? 'bg-yellow-700 text-stone-50'
                  : 'text-stone-300 hover:bg-stone-800 hover:text-stone-100'
              }`}
            >
              {COUNCIL_PERSONALITY_MODE_LABELS[mode]}
            </button>
          )
        })}
      </div>
      <p className="mt-1 text-[11px] text-stone-500 leading-snug">
        {COUNCIL_PERSONALITY_MODE_HINTS[value]}
      </p>
    </div>
  )
}
