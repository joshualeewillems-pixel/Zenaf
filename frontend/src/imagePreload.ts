/**
 * The seat-world preload (founder, 2026-11-28): "Can we
 * preload everything? Just have the seats spinning logo
 * until everything nested is accessible" — extended the
 * same hour to every seat, with the tree's pulsing logo at
 * the door instead of a spinner.
 *
 * Each seat world owns painted imagery that used to arrive
 * level by level, painting its scenes in pieces as the
 * visitor descended. Now each world's whole set warms once
 * — requested and decoded — behind its door, and the door
 * (components/SeatGate) shows the seat's logo pulsing with
 * the Living Tree's own pulse law while it does. Once warm,
 * the set stays warm for the session: re-entering a world
 * never waits again.
 *
 * A failed image settles its slot rather than trapping the
 * visitor at the door: the world opens with what it has,
 * and the missing image behaves as images always have.
 */
import { useEffect, useState } from 'react'

/** Loads one image to decoded readiness; never rejects. */
export type ImageLoader = (url: string) => Promise<void>

export const loadImageDecoded: ImageLoader = (url) =>
  new Promise((resolve) => {
    const img = new Image()
    let settled = false
    const finish = () => {
      if (!settled) {
        settled = true
        resolve()
      }
    }
    const decoded = () => {
      if (typeof img.decode === 'function') {
        img.decode().then(finish, finish)
      } else {
        finish()
      }
    }
    img.onload = decoded
    img.onerror = finish
    img.src = url
    // Already cached (warm from earlier in this session):
    // the load event may never fire.
    if (img.complete) {
      if (img.naturalWidth > 0) decoded()
      else finish()
    }
  })

export interface ImagePreloader {
  readonly urls: readonly string[]
  /** Warm every image. Idempotent: one promise per session. */
  preload: (loader?: ImageLoader) => Promise<void>
  /** Whether the warm-up has settled in this session. */
  ready: () => boolean
}

export function createImagePreloader(urls: readonly string[]): ImagePreloader {
  let cached: Promise<void> | null = null
  let isReady = false
  return {
    urls,
    preload: (loader: ImageLoader = loadImageDecoded) => {
      if (!cached) {
        cached = Promise.all(urls.map((url) => loader(url).catch(() => undefined))).then(() => {
          isReady = true
        })
      }
      return cached
    },
    ready: () => isReady,
  }
}

/**
 * The door hook: false while the world's imagery warms,
 * true once it settles. The ceiling is a mercy, not the
 * design — if an asset stalls on a bad connection the door
 * opens anyway after a long wait rather than trapping the
 * visitor outside their own world.
 */
export function useImagePreloadGate(preloader: ImagePreloader, ceilingMs = 20000): boolean {
  const [ready, setReady] = useState<boolean>(() => preloader.ready())
  useEffect(() => {
    if (ready) return
    let live = true
    const ceiling = setTimeout(() => {
      if (live) setReady(true)
    }, ceilingMs)
    void preloader.preload().then(() => {
      if (live) {
        clearTimeout(ceiling)
        setReady(true)
      }
    })
    return () => {
      live = false
      clearTimeout(ceiling)
    }
  }, [ready, preloader])
  return ready
}
