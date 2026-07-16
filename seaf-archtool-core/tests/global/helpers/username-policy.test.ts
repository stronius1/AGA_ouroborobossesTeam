import { MAX_LEN, UsernamePolicy } from "@global/helpers/username-policy";

describe("UsernamePolicy (TS)", () => {
  let policy: UsernamePolicy;
  beforeEach(() => {
    policy = new UsernamePolicy(["root", "reserved_name", "admin"]);
  });

  test("normalize null -> empty", () => {
    expect(policy.normalize(null)).toBe("");
  });
  test("normalize trims/lower/space->underscore/collapse/strip", () => {
    expect(policy.normalize("  __ HeLLo   WorLD  __ ")).toBe("hello_world");
  });
  test("normalize collapses multiple underscores", () => {
    expect(policy.normalize("a__b___c")).toBe("a_b_c");
  });
  test("normalize only underscores -> empty", () => {
    expect(policy.normalize("____")).toBe("");
  });

  test("isValid null -> false", () => {
    expect(policy.isValid(null)).toBe(false);
  });
  test("isValid too short -> false", () => {
    expect(policy.isValid("ab")).toBe(false);
  });
  test("isValid too long -> false", () => {
    expect(policy.isValid("abcdefghijklmnop")).toBe(false);
  });
  test("isValid bad chars / uppercase -> false", () => {
    expect(policy.isValid("abc-def")).toBe(false);
    expect(policy.isValid("abc.def")).toBe(false);
  });
  test("isValid starts with digit -> false", () => {
    expect(policy.isValid("1abc")).toBe(false);
  });
  test("isValid double underscore -> false", () => {
    expect(policy.isValid("ab__cd")).toBe(false);
  });
  test("isValid reserved -> false", () => {
    expect(policy.isValid("admin")).toBe(false);
  });
  test("isValid ok + boundary", () => {
    expect(policy.isValid("abc")).toBe(true);
    expect(policy.isValid("abcdefghijklmno")).toBe(true);
  });

  test("suggest returns base when valid and free", () => {
    expect(policy.suggest("Alice", new Set(), 42, 10)).toBe("alice");
  });

  test("suggest base empty -> user, throws when first suffix taken", () => {
    const seed = 12345; // first = 345
    const taken = new Set(["user", "user345"]);
    expect(() => policy.suggest("   ", taken, seed, 1)).toThrow(/No available username/);
  });

  test("suggest truncates prefix and returns valid candidate", () => {
    const desired = "aaaaaaaaaaaaaaaaaaaa";
    const seed = 999;
    const out = policy.suggest(desired, new Set(), seed, 50);
    expect(out.length).toBeLessThanOrEqual(MAX_LEN);
    expect(policy.isValid(out)).toBe(true);
    expect(out.length).toBe(15);
    expect(out.endsWith("99")).toBe(true);
  });

  test("suggest overload default maxAttempts", () => {
    const out = policy.suggest("abc", new Set(["abc"]), 7);
    expect(out).toBeTruthy();
    expect(policy.isValid(out)).toBe(true);
    expect(out).not.toBe("abc");
  });
});
