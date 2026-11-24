/**
 * A faithful port of Python's `random.Random` (MT19937) and of
 * `zlib.crc32`, so the Bench's growth grammar runs with the canonical
 * machinery's own seeds and produces the canonical geometry.
 *
 * The canonical seed is `seed_rng(*parts)` from stills_v2.py:
 * `random.Random(zlib.crc32("|".join(str(p) for p in parts).encode())
 * & 0xFFFFFFFF)`. CPython seeds an int < 2**32 via init_by_array with
 * the single-word key [seed]. Every generator method used by the
 * growth and painting machinery is ported with CPython's exact draw
 * semantics — `random` (genrand_res53), `uniform`, `choice`
 * (_randbelow over getrandbits), `randint`, and `gauss` (the polar
 * method with its cached second value) — because the geometry is a
 * function of the draw sequence, not just the seed.
 *
 * Equivalence is proven in growth.test.ts against values dumped from
 * CPython by growthHarness.py.
 */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c >>> 0
  }
  return table
})()

/** zlib.crc32 of the UTF-8 bytes of `text`, as an unsigned 32-bit int. */
export function crc32(text: string): number {
  const bytes = new TextEncoder().encode(text)
  let crc = 0xffffffff
  for (let i = 0; i < bytes.length; i++) {
    crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8)
  }
  return (crc ^ 0xffffffff) >>> 0
}

const N = 624
const M = 397
const MATRIX_A = 0x9908b0df
const UPPER_MASK = 0x80000000
const LOWER_MASK = 0x7fffffff

export class PythonRandom {
  private mt = new Uint32Array(N)
  private index = N + 1
  private gaussNext: number | null = null

  constructor(seed: number) {
    this.initByArray([seed >>> 0])
  }

  private initGenrand(s: number) {
    const mt = this.mt
    mt[0] = s >>> 0
    for (let i = 1; i < N; i++) {
      const prev = mt[i - 1]
      mt[i] = (Math.imul(1812433253, prev ^ (prev >>> 30)) + i) >>> 0
    }
    this.index = N
  }

  private initByArray(key: number[]) {
    this.initGenrand(19650218)
    const mt = this.mt
    let i = 1
    let j = 0
    let k = Math.max(N, key.length)
    for (; k > 0; k--) {
      const prev = mt[i - 1]
      mt[i] = ((mt[i] ^ Math.imul(prev ^ (prev >>> 30), 1664525)) + key[j] + j) >>> 0
      i++
      j++
      if (i >= N) {
        mt[0] = mt[N - 1]
        i = 1
      }
      if (j >= key.length) j = 0
    }
    for (k = N - 1; k > 0; k--) {
      const prev = mt[i - 1]
      mt[i] = ((mt[i] ^ Math.imul(prev ^ (prev >>> 30), 1566083941)) - i) >>> 0
      i++
      if (i >= N) {
        mt[0] = mt[N - 1]
        i = 1
      }
    }
    mt[0] = 0x80000000
  }

  /** genrand_int32: one tempered 32-bit draw (twists in blocks of N). */
  int32(): number {
    if (this.index >= N) this.twist()
    let y = this.mt[this.index++]
    y ^= y >>> 11
    y ^= (y << 7) & 0x9d2c5680
    y ^= (y << 15) & 0xefc60000
    y ^= y >>> 18
    return y >>> 0
  }

  private twist() {
    const mt = this.mt
    for (let kk = 0; kk < N - M; kk++) {
      const y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK)
      mt[kk] = (mt[kk + M] ^ (y >>> 1) ^ (y & 1 ? MATRIX_A : 0)) >>> 0
    }
    for (let kk = N - M; kk < N - 1; kk++) {
      const y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK)
      mt[kk] = (mt[kk + (M - N)] ^ (y >>> 1) ^ (y & 1 ? MATRIX_A : 0)) >>> 0
    }
    const y = (mt[N - 1] & UPPER_MASK) | (mt[0] & LOWER_MASK)
    mt[N - 1] = (mt[M - 1] ^ (y >>> 1) ^ (y & 1 ? MATRIX_A : 0)) >>> 0
    this.index = 0
  }

  /** CPython random(): genrand_res53. */
  random(): number {
    const a = this.int32() >>> 5
    const b = this.int32() >>> 6
    return (a * 67108864.0 + b) / 9007199254740992.0
  }

  uniform(a: number, b: number): number {
    return a + (b - a) * this.random()
  }

  private getrandbits(k: number): number {
    if (k <= 0) return 0
    if (k <= 32) return (this.int32() >>> (32 - k)) >>> 0
    // General path (not exercised by the machinery, kept faithful):
    let result = 0
    let shift = 0
    let remaining = k
    while (remaining > 0) {
      const take = Math.min(32, remaining)
      const word = take === 32 ? this.int32() : this.int32() >>> (32 - take)
      result += word * 2 ** shift
      shift += take
      remaining -= take
    }
    return result
  }

  private randbelow(n: number): number {
    const k = n.toString(2).length // bit_length
    let r = this.getrandbits(k)
    while (r >= n) r = this.getrandbits(k)
    return r
  }

  choice<T>(seq: readonly T[]): T {
    return seq[this.randbelow(seq.length)]
  }

  randint(a: number, b: number): number {
    return a + this.randbelow(b - a + 1)
  }

  /** CPython random.gauss: polar method, second value cached. */
  gauss(mu: number, sigma: number): number {
    let z = this.gaussNext
    this.gaussNext = null
    if (z === null) {
      const x2pi = this.random() * (2 * Math.PI)
      const g2rad = Math.sqrt(-2.0 * Math.log(1.0 - this.random()))
      z = Math.cos(x2pi) * g2rad
      this.gaussNext = Math.sin(x2pi) * g2rad
    }
    return mu + z * sigma
  }
}

/** stills_v2.seed_rng: crc32 of the parts joined with "|". */
export function seedRng(...parts: Array<string | number>): PythonRandom {
  return new PythonRandom(crc32(parts.map((p) => String(p)).join('|')))
}
