/**
 * The Scroll preload (founder, 2026-11-28 — the seat-wide
 * preload): Jynx's world warms its room, desk, fabric and
 * stamp imagery at the door, behind the Fox's pulsing logo,
 * before the first scene paints. The list names the same
 * asset files the view renders (Vite resolves both imports
 * to the same URLs); when a scroll image is added to the
 * view, add it here too — the aggregation test counts the
 * set.
 */
import { createImagePreloader } from '../imagePreload'
import scrollDesk from './assets/scroll-desk.png'
import scrollFabric from './assets/scroll-fabric.png'
import scrollRoomDark from './assets/scroll-room-dark.png'
import scrollGround from './assets/scroll-ground.png'
import scrollRoom from './assets/scroll-room.png'
import scrollEnd from './assets/scroll-end.png'
import scrollEndRight from './assets/scroll-end-right.png'
import scrollTask from './assets/scroll-task.png'
import scrollWall2 from './assets/scroll-wall2.jpg'
import stampArc from './assets/arc.png'
import stampCaret from './assets/caret.png'
import stampCrescent from './assets/crescent.png'
import stampFork from './assets/fork.png'
import stampFrame from './assets/frame.png'
import stampLeaf from './assets/leaf.png'
import stampRing from './assets/ring.png'
import stampSlash from './assets/slash.png'
import stampTriangle from './assets/triangle.png'
import stampWave from './assets/wave.png'

export const SCROLL_ASSET_URLS: string[] = [
  scrollDesk,
  scrollFabric,
  scrollRoomDark,
  scrollGround,
  scrollRoom,
  scrollEnd,
  scrollEndRight,
  scrollTask,
  scrollWall2,
  stampArc,
  stampCaret,
  stampCrescent,
  stampFork,
  stampFrame,
  stampLeaf,
  stampRing,
  stampSlash,
  stampTriangle,
  stampWave,
]

export const scrollPreloader = createImagePreloader(SCROLL_ASSET_URLS)
