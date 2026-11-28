/**
 * The door of a seat world (founder, 2026-11-28): while the
 * world's whole imagery warms, the seat's logo stands at the
 * door PULSING — the Living Tree's own pulse, not a spinner
 * (founder's correction the same hour: "just have the
 * pulsing logo as it appears on the tree"). The tree's
 * medallion glow breathes on a 1.65 s ease-in-out law
 * between opacity .10 and 1 (LivingSkyScene's paintGlowPulse);
 * the halo behind the logo here breathes on the same law,
 * tinted with the seat's colour so it reads on parchment.
 * Nothing of the world paints behind this gate: the scenes
 * mount only once everything nested is accessible.
 */
import './seat-gate.css'

export default function SeatGate({
  logo,
  color,
  label,
  testId,
}: {
  logo: string
  /** The seat's colour (SEAT_COLORS), for the breathing halo. */
  color: string
  label: string
  testId: string
}) {
  return (
    <div data-testid={testId} className="seat-gate" role="status" aria-label={label}>
      <div className="seat-gate-mark">
        <div className="seat-gate-halo" style={{ background: color }} />
        <img src={logo} alt="" className="seat-gate-logo" />
      </div>
      <p className="seat-gate-label">{label}</p>
    </div>
  )
}
