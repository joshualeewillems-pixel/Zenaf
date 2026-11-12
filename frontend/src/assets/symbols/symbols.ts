/**
 * Conversation symbols — the 24 pickable emblems from the founder's
 * symbol sheet (2026-11-12). Each PNG is a crop of one numbered circle
 * from the sheet (6 columns x 4 rows, ~158px each); the silver-on-black
 * art reads as-is on the app's dark surfaces.
 *
 * A conversation is identified by its color + symbol, not by a text
 * title (founder, 2026-11-12): the history list renders the emblem,
 * never a generated title.
 */
import symbol01 from './symbol-01.png'
import symbol02 from './symbol-02.png'
import symbol03 from './symbol-03.png'
import symbol04 from './symbol-04.png'
import symbol05 from './symbol-05.png'
import symbol06 from './symbol-06.png'
import symbol07 from './symbol-07.png'
import symbol08 from './symbol-08.png'
import symbol09 from './symbol-09.png'
import symbol10 from './symbol-10.png'
import symbol11 from './symbol-11.png'
import symbol12 from './symbol-12.png'
import symbol13 from './symbol-13.png'
import symbol14 from './symbol-14.png'
import symbol15 from './symbol-15.png'
import symbol16 from './symbol-16.png'
import symbol17 from './symbol-17.png'
import symbol18 from './symbol-18.png'
import symbol19 from './symbol-19.png'
import symbol20 from './symbol-20.png'
import symbol21 from './symbol-21.png'
import symbol22 from './symbol-22.png'
import symbol23 from './symbol-23.png'
import symbol24 from './symbol-24.png'

/** Symbol numbers are 1-based, matching the founder's sheet. */
export const SYMBOL_COUNT = 24

export const SYMBOL_URLS: Record<number, string> = {
  1: symbol01,
  2: symbol02,
  3: symbol03,
  4: symbol04,
  5: symbol05,
  6: symbol06,
  7: symbol07,
  8: symbol08,
  9: symbol09,
  10: symbol10,
  11: symbol11,
  12: symbol12,
  13: symbol13,
  14: symbol14,
  15: symbol15,
  16: symbol16,
  17: symbol17,
  18: symbol18,
  19: symbol19,
  20: symbol20,
  21: symbol21,
  22: symbol22,
  23: symbol23,
  24: symbol24,
}

export function symbolUrl(n: number | null | undefined): string | null {
  if (!n || n < 1 || n > SYMBOL_COUNT) return null
  return SYMBOL_URLS[n] ?? null
}
