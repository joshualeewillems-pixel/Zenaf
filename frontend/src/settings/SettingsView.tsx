import type { CurrentUser } from '../auth/session'
import { AccountSection } from './sections/AccountSection'
import { ModelConnectionsSection } from './sections/ModelConnectionsSection'
import { NotificationsSection } from './sections/NotificationsSection'
import { PrivacySection } from './sections/PrivacySection'
import { CouncilIntegrityReviewSection } from './sections/CouncilIntegrityReviewSection'
import { PermissionsSection } from './sections/PermissionsSection'

type Props = {
  user: CurrentUser
  onLogout: () => void
  onUserUpdated: (u: CurrentUser) => void
}

export function SettingsView({ user, onLogout, onUserUpdated }: Props) {
  return (
    <div className="flex-1 overflow-auto p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Settings</h1>
        <p className="text-sm text-slate-400 mt-1">Account, model connections, and notification preferences.</p>
      </div>
      <AccountSection user={user} onLogout={onLogout} onUserUpdated={onUserUpdated} />
      <PermissionsSection />
      <PrivacySection />
      <CouncilIntegrityReviewSection />
      <ModelConnectionsSection />
      <NotificationsSection />
    </div>
  )
}
