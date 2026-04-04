/**
 * Inline thread block: unresolved conversational suggestions when the user changes subject.
 */
type Item = { id: string; text: string }

type Props = {
  reviewId: string
  forSubjectLabel: string
  items: Item[]
  resolvedIds: Set<string>
  onCommitNow: (item: Item) => void
  onSaveNotes: (item: Item) => void
  onDismissItem: (item: Item) => void
  busyId: string | null
}

export function SubjectHandoffReview({
  reviewId,
  forSubjectLabel,
  items,
  resolvedIds,
  onCommitNow,
  onSaveNotes,
  onDismissItem,
  busyId,
}: Props) {
  const open = items.filter((i) => !resolvedIds.has(i.id))
  if (open.length === 0) {
    return (
      <p className="text-[11px] text-stone-500 italic" data-testid={`subject-handoff-done-${reviewId}`}>
        All set — nothing left to resolve from “{forSubjectLabel}”.
      </p>
    )
  }

  return (
    <ul className="space-y-3 mt-2" data-testid="subject-handoff-review">
      {open.map((item) => (
        <li
          key={item.id}
          className="rounded-md border border-stone-600/80 bg-stone-950/60 px-2 py-2"
          data-testid="subject-handoff-item"
        >
          <p className="text-xs text-stone-200 leading-snug mb-2">{item.text}</p>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px]">
            <button
              type="button"
              disabled={busyId === item.id}
              className="text-amber-200/90 hover:underline disabled:opacity-40"
              onClick={() => onCommitNow(item)}
            >
              Do this now
            </button>
            <button
              type="button"
              disabled={busyId === item.id}
              className="text-sky-300/90 hover:underline disabled:opacity-40"
              onClick={() => onSaveNotes(item)}
            >
              Save in notes for later
            </button>
            <button
              type="button"
              disabled={busyId === item.id}
              className="text-stone-500 hover:text-stone-300 hover:underline disabled:opacity-40"
              onClick={() => onDismissItem(item)}
            >
              Not this
            </button>
          </div>
        </li>
      ))}
    </ul>
  )
}
