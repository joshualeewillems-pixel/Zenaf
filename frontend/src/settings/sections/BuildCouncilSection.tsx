import type { CurrentUser } from '../../auth/session'

type Props = {
  user: CurrentUser
  onOpen: () => void
}

/**
 * Owner-only: link to the build-council submit page. Rendered only
 * for admin users (the bootstrapped owner account carries is_admin).
 * The page itself gates again, and the R2 endpoint remains the real
 * owner enforcement, fail-closed.
 */
export function BuildCouncilSection({ user, onOpen }: Props) {
  if (!user.is_admin) return null

  return (
    <section className="border border-slate-700 rounded-lg p-4 space-y-3">
      <h2 className="text-lg font-semibold text-slate-100">Build council</h2>
      <p className="text-sm text-slate-400">
        Submit a build-council meeting request from inside the app, using this session.
        Paste the full request JSON on the submit page; it is validated before anything
        is sent, one POST per click, no automatic retries.
      </p>
      <button
        type="button"
        onClick={onOpen}
        className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50"
      >
        Open build-council submit page
      </button>
    </section>
  )
}
