# -*- coding: utf-8 -*-
"""Smoke-тесты AGA (pytest-совместимы; запускаются и как python3 tests/test_smoke.py)."""
from __future__ import annotations

import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from evolver.fitness import evaluate, gate  # noqa: E402
from tools.aga import load_rules, load_seaf, review_pr  # noqa: E402

PRS = PKG_ROOT / "golden" / "prs"


def _findings(pr, rules_dir=None):
    r = review_pr(PRS / pr, rules_dir)
    return {f["rule_id"]: f["severity"] for f in r["findings"]}, r["verdict"]


def test_rules_load():
    rules, policy = load_rules()
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), "дубли rule_id"
    assert len(rules) == 24, f"ожидалось 24 активных правила, получено {len(rules)}"
    for r in rules:
        for key in ("id", "statement", "severity", "scope", "source_ref", "provenance"):
            assert key in r, f"{r.get('id')}: нет поля {key}"
    assert policy["autonomy"]["auto_merge"] is False


def test_seaf_fixture():
    seaf = load_seaf()
    assert len(seaf) == 15
    assert seaf["AS-0009"].get("infra") is True
    assert seaf["AS-0011"]["target_status"] == "eliminate"


def test_pr01_clean_approve():
    f, verdict = _findings("pr-01")
    assert f == {}, f"на чистом PR не должно быть findings: {f}"
    assert verdict == "approve"


def test_pr08_minor_warnings():
    f, verdict = _findings("pr-08")
    assert f == {"DIAG-002": "minor", "DIAG-003": "minor"}, f
    assert verdict == "approve_with_warnings"


def test_pr09_adr_major():
    f, verdict = _findings("pr-09")
    assert f == {"ADR-001": "major", "ADR-002": "minor"}, f
    assert verdict == "request_changes_escalate"


def test_pr12_blocker():
    f, verdict = _findings("pr-12")
    assert f == {"SEAF-004": "blocker"}, f
    assert verdict == "request_changes_escalate"


def test_pr15_false_positive_on_v1():
    f, verdict = _findings("pr-15")
    assert f == {"PRIN-002": "major"}, f
    assert verdict == "request_changes_escalate"


def test_evolution_mutation_and_gate(tmp_path=None):
    """Демо-мутация add_exception: FP уходит, гейт проходит."""
    from scripts.run_evolution import apply_mutation

    tmp = Path(tmp_path) if tmp_path else PKG_ROOT / "build" / "test-candidate"
    mutation = {
        "type": "add_exception",
        "provenance": "precedent:0001",
        "rule_id": "PRIN-002",
        "exception": {
            "when": {"all": [
                {"field": "zone", "equals": "dmz"},
                {"field": "pattern", "equals": "file"},
                {"field": "transfer_mode", "equals": "batch"},
                {"field": "gateway_controlled", "equals": True},
                {"field": "approvals", "contains": "security"},
            ]},
            "rationale": "контролируемая batch-выгрузка через DMZ-шлюз",
            "provenance": "precedent:0001",
        },
    }
    apply_mutation(PKG_ROOT / "rules", tmp, mutation, "1.1.0")

    f, verdict = _findings("pr-15", tmp)
    assert f == {}, f"исключение должно подавить PRIN-002: {f}"
    assert verdict == "approve"

    r = review_pr(PRS / "pr-15", tmp)
    assert r["suppressed_by_exception"], "подавление должно логироваться"

    base, cand = evaluate(PKG_ROOT / "rules"), evaluate(tmp)
    assert base["weighted_cost"] > cand["weighted_cost"]
    assert cand["blocker_recall"] >= base["blocker_recall"] == 1.0
    passed, checks = gate(base, cand)
    assert passed, f"гейт должен пройти: {checks}"

    # блокер pr-12 не потерян после мутации
    f12, _ = _findings("pr-12", tmp)
    assert f12 == {"SEAF-004": "blocker"}

    # Неконтролируемый file-flow в DMZ не подпадает под узкое исключение.
    f16, _ = _findings("pr-16", tmp)
    assert f16 == {"PRIN-002": "major"}


def main():
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
