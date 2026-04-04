import { useVisionExecutionFocus } from './VisionExecutionFocusContext'
import { useVeVoiceRecording } from './veVoiceRecordingContext'

/**
 * Single control: circle = ready to record (when a field is focused), square = recording.
 * Tooltip carries the “Record” helper copy; no separate Record button elsewhere.
 */
export function FocusContextRecordButton() {
  const { focus, onBarPointerDownCapture } = useVisionExecutionFocus()
  const { voicePhase, startVoiceRecording, stopVoiceRecording } = useVeVoiceRecording()

  const canStart = Boolean(focus) && voicePhase === 'idle'
  const isRecording = voicePhase === 'recording'
  const isBusy = voicePhase === 'transcribing'

  const title = !focus
    ? 'Select a field below, then click to record voice into it'
    : isBusy
      ? 'Transcribing…'
      : isRecording
        ? 'Stop — transcribe and insert at cursor'
        : 'Record voice into the focused field'

  const onClick = () => {
    if (isBusy) return
    if (isRecording) {
      stopVoiceRecording()
      return
    }
    if (canStart) startVoiceRecording()
  }

  return (
    <button
      type="button"
      onPointerDownCapture={onBarPointerDownCapture}
      onClick={onClick}
      disabled={isBusy || (!focus && !isRecording)}
      title={title}
      aria-label={title}
      aria-pressed={isRecording}
      className={`shrink-0 flex items-center justify-center w-7 h-7 rounded-md border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/80 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-900 disabled:opacity-40 disabled:cursor-not-allowed ${
        isRecording
          ? 'border-red-400/80 bg-red-950/50 shadow-[0_0_14px_rgba(239,68,68,0.35)]'
          : focus
            ? 'border-red-500/50 bg-stone-900/80 hover:border-red-400/70 hover:bg-red-950/30'
            : 'border-stone-600 bg-stone-900/60'
      }`}
    >
      <span className="sr-only">{title}</span>
      {isRecording ? (
        <span
          className="block w-3 h-3 rounded-sm bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.75)]"
          aria-hidden
        />
      ) : (
        <span
          className={`block w-3 h-3 rounded-full ${
            focus ? 'bg-red-500 shadow-[0_0_12px_rgba(239,68,68,0.65)]' : 'bg-stone-500'
          }`}
          aria-hidden
        />
      )}
    </button>
  )
}
