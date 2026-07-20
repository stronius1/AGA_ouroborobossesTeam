# AGA self-evolution: локальный runbook

## Prerequisites

- clean pinned Ouroboros `6.64.1` source commit
  `554b3eeeca345298d6dcc5711195ea9acec450bd` — если Ouroboros ещё не собран
  из исходников, сначала выполни (полное объяснение и security-инварианты:
  `docs/OUROBOROS-MVP-INTEGRATION-GUIDE.md`, §6):

  ```bash
  git clone --depth 1 --branch v6.64.1 \
    https://github.com/razzant/ouroboros.git ouroboros-v6.64.1
  cd ouroboros-v6.64.1
  test "$(git rev-parse HEAD)" = "554b3eeeca345298d6dcc5711195ea9acec450bd"
  python3.11 -m venv .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install -r requirements.txt
  python -m pip install -e . --no-deps
  ```

- initialized clean gitlinks `seaf-archtool-core` и
  `architecture/vendor/seaf-core` на pins из `README.md`;
- owner-only (`0600`) OpenRouter key в изолированном профиле, hard cap не выше
  `50 USD`, модель `deepseek/deepseek-v4-pro` на всех routes;
- запущенный loopback runtime: `make ouroboros-start`;
- минимум `0.50 USD` remaining перед каждой paid stage.

Free/local demo (`make demo-verify`, `make self-evolution-ui`) этого шага
не требует — Ouroboros из исходников нужен только для Live/paid-режима.

## Запуск

Оба контура одной командой:

```bash
make self-evolution
```

Только Architecture-as-Code loop:

```bash
make architecture-self-evolution
```

Только Loop A для эволюции rules/version/precedent:

```bash
make loop-a-local-candidate
```

Production-like review произвольных immutable local revisions:

```bash
python3 scripts/ouroboros_profile.py exec -- python3 scripts/run_ouroboros_live_review.py \
  --repository /path/to/clean/repository \
  --repository-id safe-non-path-id \
  --base FULL_40_HEX_SHA \
  --head FULL_40_HEX_SHA \
  --idempotency-key safe-logical-review-id
```

Repository path остаётся host-only. В MCP/model передаются только registered
ID, full SHA, opaque digests и synthetic-public artifacts.

## Результаты и повторный запуск

- sanitized architecture evidence:
  `docs/evidence/ouroboros-self-evolution-v1.json`;
- приватные checkpoints/receipts/worktrees: ignored `.aga-runs/`;
- architecture outcome: отдельная `aga/architecture-*` branch и commit;
- Loop A outcome: отдельная `skill/evolution-*` branch и commit;
- повтор с тем же correlation key повторно проверяет checkpoints и использует
  те же task/branch/commit, не создавая paid duplicate;
- после двух одинаковых transport/tool failures третий запуск блокируется до
  исправления причины или нового осознанного correlation key.

Ни один контур не вызывает remote API, push, approve или merge. Локальная
ветка — не открытый PR; `draft_pr_url` всегда `null`.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | trusted local candidate готов, human review обязателен |
| `2` | runtime/key/model/MCP/pin не настроены |
| `3` | Git, schema, receipt, sanitization или local contract failure |
| `4` | incomplete, remediation gate failure или budget stop |

При failure проверьте typed `code`, sanitized failed-batch budget и owner-only
receipt journal. Не запускайте старый 16-case holdout: он не участвует в этом
acceptance и уже раскрыт историческим прогоном.
