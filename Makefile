PYTHON ?= python3
NPM ?= npm
ARCHTOOL_DIR := seaf-archtool-core
SEAF_CORE_DIR := architecture/vendor/seaf-core
OUROBOROS_FULL_RUN_APPROVED ?= no
DEVELOPMENT_V2_PAID_APPROVED ?= no
DEVELOPMENT_V2_REPEAT_ORDINAL ?=
DEVELOPMENT_V2_CAPTURE_ID ?=
DEVELOPMENT_V2_ATTESTATION_KEY_FILE ?=
DEVELOPMENT_V2_SERIES_INPUTS ?=
DEVELOPMENT_V2_MAX_P95_MS ?=
DEVELOPMENT_V2_MAX_COST_USD ?=
STABILITY_INPUTS ?=
STABILITY_MAX_P95_MS ?=
STABILITY_MAX_COST_USD ?=
AGA_OUROBOROS_PROFILE_HOME ?= $(HOME)/.local/share/aga-ouroboros-v6.64.1/home
AGA_OUROBOROS_VENV_DIR ?= $(abspath $(AGA_OUROBOROS_PROFILE_HOME)/../venv)
AGA_OUROBOROS_SOURCE_DIR ?= $(abspath $(AGA_OUROBOROS_PROFILE_HOME)/../source)
OUROBOROS_PROFILE_MANAGER = \
	AGA_OUROBOROS_PROFILE_HOME="$(AGA_OUROBOROS_PROFILE_HOME)" \
	AGA_OUROBOROS_VENV_DIR="$(AGA_OUROBOROS_VENV_DIR)" \
	AGA_OUROBOROS_SOURCE_DIR="$(AGA_OUROBOROS_SOURCE_DIR)" \
	$(PYTHON) scripts/ouroboros_profile.py

.PHONY: bootstrap verify-pins test test-seaf demo-offline ouroboros-materialize \
	ouroboros-profile-init ouroboros-profile-sync ouroboros-configure-key \
	ouroboros-start ouroboros-stop ouroboros-status ouroboros-preflight \
	demo-e2e ouroboros-full-run-approval \
	evaluate-ouroboros-development evaluate-ouroboros-holdout \
	evaluate-ouroboros-all evaluate-ouroboros-development-v2 \
	development-v2-paid-approval validate-development-v2 verify-development-v2 \
	verify-development-v2-series \
	check-secrets project-results-check clean-generated \
	self-evolution architecture-self-evolution loop-a-local-candidate \
	self-evolution-ui self-evolution-ui-fixture clean-caches demo-verify \
	submission-consistency-check semantic-stability-report

bootstrap:
	git submodule update --init --recursive
	$(MAKE) verify-pins
	$(PYTHON) -m pip install -r aga-skill/requirements-dev.txt
	cd $(ARCHTOOL_DIR) && $(NPM) ci

verify-pins:
	$(PYTHON) scripts/verify_pins.py

test:
	cd aga-skill && $(PYTHON) -m pytest -q -p no:cacheprovider
	cd aga-skill && $(PYTHON) -m unittest discover -s tests

test-seaf: verify-pins
	cd aga-skill && $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_seaf_native.py tests/test_repository_snapshot.py tests/test_mcp.py
	$(PYTHON) scripts/validate_architecture.py architecture/dochub.yaml
	cd $(ARCHTOOL_DIR) && $(NPM) test -- --runInBand
	cd $(ARCHTOOL_DIR) && $(NPM) run backend-build

demo-offline:
	cd aga-skill && $(PYTHON) scripts/run_seaf_review.py --case demo-critical-dependency --mode offline

ouroboros-materialize:
	$(PYTHON) scripts/materialize_ouroboros_cases.py --case ga-05-critical-eliminate

ouroboros-profile-init:
	$(OUROBOROS_PROFILE_MANAGER) init

ouroboros-profile-sync:
	$(OUROBOROS_PROFILE_MANAGER) sync

ouroboros-configure-key:
	$(OUROBOROS_PROFILE_MANAGER) configure-key

ouroboros-start:
	$(OUROBOROS_PROFILE_MANAGER) start

ouroboros-stop:
	$(OUROBOROS_PROFILE_MANAGER) stop

ouroboros-status:
	$(OUROBOROS_PROFILE_MANAGER) status

ouroboros-preflight:
	$(OUROBOROS_PROFILE_MANAGER) preflight

demo-e2e:
	$(OUROBOROS_PROFILE_MANAGER) exec -- $(PYTHON) scripts/run_ouroboros_e2e.py --case ga-05-critical-eliminate

architecture-self-evolution:
	$(OUROBOROS_PROFILE_MANAGER) exec -- $(PYTHON) scripts/run_architecture_evolution.py --demo

loop-a-local-candidate:
	cd aga-skill && $(PYTHON) scripts/run_evolution.py --demo
	cd aga-skill && $(PYTHON) scripts/publish_candidate.py --build build --repository .. --actor "AGA local human-review connector"

self-evolution: architecture-self-evolution loop-a-local-candidate

self-evolution-ui-fixture:
	cd aga-skill && $(PYTHON) scripts/run_evolution.py --demo
	$(PYTHON) scripts/generate_self_evolution_ui_fixture.py

self-evolution-ui: self-evolution-ui-fixture
	$(PYTHON) scripts/self_evolution_ui.py

ouroboros-full-run-approval:
ifeq ($(OUROBOROS_FULL_RUN_APPROVED),yes)
	@:
else
	@echo "OUROBOROS EVALUATION NOT AUTHORIZED: set OUROBOROS_FULL_RUN_APPROVED=yes only after explicit owner approval" >&2
	@exit 2
endif

evaluate-ouroboros-development: ouroboros-full-run-approval
	$(OUROBOROS_PROFILE_MANAGER) exec -- $(PYTHON) scripts/run_ouroboros_evaluation.py --split development --confirm-full-run

evaluate-ouroboros-holdout: ouroboros-full-run-approval
	$(OUROBOROS_PROFILE_MANAGER) exec -- $(PYTHON) scripts/run_ouroboros_evaluation.py --split holdout --confirm-full-run

evaluate-ouroboros-all: ouroboros-full-run-approval
	$(OUROBOROS_PROFILE_MANAGER) exec -- $(PYTHON) scripts/run_ouroboros_evaluation.py --split all --confirm-full-run

validate-development-v2:
	$(PYTHON) evaluation/development-v2/corpus_tool.py validate

verify-development-v2: validate-development-v2
	$(PYTHON) -m pytest -q -p no:cacheprovider evaluation/development-v2/tests

development-v2-paid-approval:
ifeq ($(DEVELOPMENT_V2_PAID_APPROVED),yes)
	@:
else
	@echo "DEVELOPMENT-V2 PAID EVALUATION NOT AUTHORIZED: set DEVELOPMENT_V2_PAID_APPROVED=yes only after explicit owner approval" >&2
	@exit 2
endif
	@case "$(DEVELOPMENT_V2_REPEAT_ORDINAL)" in 1|2|3|4|5) : ;; *) echo "DEVELOPMENT_V2_REPEAT_ORDINAL must be one of 1 2 3 4 5" >&2; exit 2 ;; esac
	@case "$(DEVELOPMENT_V2_CAPTURE_ID)" in ''|*[!a-z0-9_.-]*) echo "DEVELOPMENT_V2_CAPTURE_ID must use lowercase letters, digits, dot, underscore, or hyphen" >&2; exit 2 ;; *) : ;; esac
	@test -n "$(strip $(DEVELOPMENT_V2_ATTESTATION_KEY_FILE))" || { echo "DEVELOPMENT_V2_ATTESTATION_KEY_FILE is required for frozen-series capture signing" >&2; exit 2; }

evaluate-ouroboros-development-v2: development-v2-paid-approval
	$(PYTHON) evaluation/development-v2/corpus_tool.py validate --require-measurement-ready
	$(OUROBOROS_PROFILE_MANAGER) exec -- $(PYTHON) evaluation/development-v2/run_paid_evaluation.py --selection development --repeat-ordinal "$(DEVELOPMENT_V2_REPEAT_ORDINAL)" --capture-id "$(DEVELOPMENT_V2_CAPTURE_ID)" --attestation-key-file "$(DEVELOPMENT_V2_ATTESTATION_KEY_FILE)" --confirm-paid-run

verify-development-v2-series:
	@test -n "$(strip $(DEVELOPMENT_V2_SERIES_INPUTS))" || { echo "DEVELOPMENT_V2_SERIES_INPUTS must name exactly five trusted capture files" >&2; exit 2; }
	@test -n "$(strip $(DEVELOPMENT_V2_MAX_P95_MS))" || { echo "DEVELOPMENT_V2_MAX_P95_MS is required" >&2; exit 2; }
	@test -n "$(strip $(DEVELOPMENT_V2_MAX_COST_USD))" || { echo "DEVELOPMENT_V2_MAX_COST_USD is required" >&2; exit 2; }
	@test -n "$(strip $(DEVELOPMENT_V2_ATTESTATION_KEY_FILE))" || { echo "DEVELOPMENT_V2_ATTESTATION_KEY_FILE is required to authenticate capture files" >&2; exit 2; }
	$(PYTHON) evaluation/development-v2/runner.py --verify-series $(DEVELOPMENT_V2_SERIES_INPUTS) --max-p95-ms "$(DEVELOPMENT_V2_MAX_P95_MS)" --max-cost-usd "$(DEVELOPMENT_V2_MAX_COST_USD)" --attestation-key-file "$(DEVELOPMENT_V2_ATTESTATION_KEY_FILE)"

semantic-stability-report:
	@test -n "$(strip $(STABILITY_INPUTS))" || { echo "STABILITY_INPUTS is required (at least five distinct trusted development captures)" >&2; exit 2; }
	@test -n "$(strip $(STABILITY_MAX_P95_MS))" || { echo "STABILITY_MAX_P95_MS is required" >&2; exit 2; }
	@test -n "$(strip $(STABILITY_MAX_COST_USD))" || { echo "STABILITY_MAX_COST_USD is required" >&2; exit 2; }
	$(PYTHON) scripts/semantic_stability_report.py $(STABILITY_INPUTS) --max-p95-ms "$(STABILITY_MAX_P95_MS)" --max-cost-usd "$(STABILITY_MAX_COST_USD)"

check-secrets:
	$(PYTHON) scripts/check_secrets.py

project-results-check:
	$(PYTHON) scripts/project_results_check.py

submission-consistency-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/submission_consistency_check.py

clean-generated:
	$(PYTHON) scripts/clean_generated.py

clean-caches:
	$(PYTHON) scripts/clean_generated.py --caches-only

demo-verify: export PYTHONDONTWRITEBYTECODE=1
demo-verify: clean-caches
	cd aga-skill && $(PYTHON) scripts/run_evolution.py --demo
	cd aga-skill && $(PYTHON) -m pytest -q -p no:cacheprovider \
		tests/test_self_evolution_ui.py \
		tests/test_self_evolution_scenario.py \
		tests/test_self_evolution_ui_fixture.py \
		tests/test_architecture_evolution.py \
		tests/test_remediation.py \
		tests/test_submission_consistency.py
	$(MAKE) verify-development-v2
	$(MAKE) clean-caches
	$(MAKE) project-results-check
