import type { CurrentUser } from '../auth/session'
import { Accordion, type AccordionItemSpec } from './Accordion'
import { AccountSection } from './sections/AccountSection'
import { IdentitySection } from './sections/IdentitySection'
import { ModelConnectionsSection } from './sections/ModelConnectionsSection'
import { NotificationsSection } from './sections/NotificationsSection'
import { PrivacySection } from './sections/PrivacySection'
import { CouncilIntegrityReviewSection } from './sections/CouncilIntegrityReviewSection'
import { PermissionsSection } from './sections/PermissionsSection'
import { InvitesSection } from './sections/InvitesSection'
import { BuildCouncilSection } from './sections/BuildCouncilSection'

type Props = {
  user: CurrentUser
  onLogout: () => void
  onUserUpdated: (u: CurrentUser) => void
  onOpenBuildCouncilSubmit: () => void
  /** Navigate to the Today deck (R6 Review in the permissions surface). */
  onOpenToday: () => void
}

export function SettingsView({ user, onLogout, onUserUpdated, onOpenBuildCouncilSubmit, onOpenToday }: Props) {
  const items: AccordionItemSpec[] = [
    {
      id: 'account',
      title: 'Account',
      content: <AccountSection user={user} onLogout={onLogout} onUserUpdated={onUserUpdated} />,
    },
    { id: 'identity', title: 'Identity', content: <IdentitySection /> },
    {
      id: 'permissions',
      title: 'Data permissions',
      content: <PermissionsSection onOpenToday={onOpenToday} />,
    },
    { id: 'privacy', title: 'Privacy mode', content: <PrivacySection /> },
    {
      id: 'council-integrity',
      title: 'Council synthesis integrity (review)',
      content: <CouncilIntegrityReviewSection />,
    },
    {
      id: 'model-connections',
      title: 'Model connections',
      content: <ModelConnectionsSection />,
    },
    { id: 'notifications', title: 'Notifications', content: <NotificationsSection /> },
  ]
  if (user.is_admin) {
    items.push(
      { id: 'invites', title: 'Invites', content: <InvitesSection user={user} /> },
      {
        id: 'build-council',
        title: 'Build council',
        content: <BuildCouncilSection user={user} onOpen={onOpenBuildCouncilSubmit} />,
      },
    )
  }
  return (
    <div className="flex-1 overflow-auto p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Settings</h1>
        <p className="text-sm text-slate-400 mt-1">Account, model connections, and notification preferences.</p>
      </div>
      <Accordion items={items} />
    </div>
  )
}
