const MIN_LEN = 3;
const MAX_LEN = 15;
const ALLOWED = /^[a-z0-9_]+$/;

export class UsernamePolicy {
  private reserved: Set<string>;
  constructor(reserved?: Iterable<string>) {
    this.reserved = reserved ? new Set(reserved) : new Set();
  }

  normalize(name: unknown): string {
    if (name == null) return "";
    let s = String(name).trim().toLowerCase().replace(/ /g, "_");
    s = s.replace(/_+/g, "_");
    if (s.startsWith("_")) s = s.slice(1);
    if (s.endsWith("_") && s.length) s = s.slice(0, -1);
    return s;
  }

  isValid(name: unknown): boolean {
    if (name == null) return false;
    const s = String(name).trim().toLowerCase();
    const len = s.length;
    if (len < MIN_LEN || len > MAX_LEN) return false;
    if (!ALLOWED.test(s)) return false;
    if (/^\d/.test(s)) return false;
    if (s.includes("__")) return false;
    return !this.reserved.has(s);
  }

  suggest(desired: unknown, taken?: Iterable<string>, seed?: number, maxAttempts = 2000): string {
    const takenSet = taken ? new Set(taken) : new Set<string>();
    let base = this.normalize(desired);
    if (!base) base = "user";
    if (this.isValid(base) && !takenSet.has(base)) return base;

    const prefix = base.length > MAX_LEN - 2 ? base.slice(0, MAX_LEN - 2) : base;
    const first = Math.abs(Number(seed) % 1000) | 0;
    for (let i = 0; i < maxAttempts; i++) {
      const suffix = i === 0 ? first : i;
      let candidate = `${prefix}${suffix}`;
      if (candidate.length > MAX_LEN) candidate = candidate.slice(0, MAX_LEN);
      if (this.isValid(candidate) && !takenSet.has(candidate)) return candidate;
    }
    throw new Error(`No available username found in ${maxAttempts} attempts`);
  }
}

export { MIN_LEN, MAX_LEN };
