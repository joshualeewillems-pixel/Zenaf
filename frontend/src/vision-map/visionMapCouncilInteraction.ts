import type { MapTriadDevelopmentalSnapshot } from '../developmentalGuidance/types'
import type { MapNodePayload } from './ontology'
import type { VEWorkspaceTabId } from '../vision-execution/VisionExecutionView'

/** Left chat + thread — vision map drives conversation-first flows. */
export type VisionMapCouncilInteraction =
  | {
      type: 'seed'
      payload: MapNodePayload
      guideTexts: string[]
      resetThread?: boolean
      /** Same snapshot as council_preflight / App mapDevelopmentalSnapshot — avoids null prompt_id race. */
      developmentalSnapshotForPrompt?: MapTriadDevelopmentalSnapshot | null
    }
  | { type: 'focus_council_input' }
  /** Prefill left council question box (Vision Map triad); does not send a message. */
  | { type: 'suggest_council_prefill'; text: string }
  | { type: 'run_council'; payload: MapNodePayload; question: string }
  /** Open Vision & Execution tab (Team, Meeting Capture, Assets) — UI only. */
  | { type: 'open_execution_tab'; tab: VEWorkspaceTabId }
  /** Open Vision & Execution focused on the map row (inspector escape hatch; selection from inspected ref). */
  | { type: 'open_inspected_in_ve'; node: MapNodePayload }
