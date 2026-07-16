PYTHON ?= python3
NPM ?= npm
ARCHTOOL_DIR := seaf-archtool-core
SEAF_CORE_DIR := architecture/vendor/seaf-core
OUROBOROS_FULL_RUN_APPROVED ?= no

.PHONY: bootstrap verify-pins test test-seaf demo-offline ouroboros-materialize \
	ouroboros-preflight demo-e2e ouroboros-full-run-approval \
	evaluate-ouroboros-development evaluate-ouroboros-holdout \
	evaluate-ouroboros-all check-secrets project-results-check clean-generated

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

ouroboros-preflight:
	$(PYTHON) scripts/ouroboros_preflight.py

demo-e2e:
	$(PYTHON) scripts/run_ouroboros_e2e.py --case ga-05-critical-eliminate

ouroboros-full-run-approval:
ifeq ($(OUROBOROS_FULL_RUN_APPROVED),yes)
	@:
else
	@echo "OUROBOROS EVALUATION NOT AUTHORIZED: set OUROBOROS_FULL_RUN_APPROVED=yes only after explicit owner approval" >&2
	@exit 2
endif

evaluate-ouroboros-development: ouroboros-full-run-approval
	$(PYTHON) scripts/run_ouroboros_evaluation.py --split development --confirm-full-run

evaluate-ouroboros-holdout: ouroboros-full-run-approval
	$(PYTHON) scripts/run_ouroboros_evaluation.py --split holdout --confirm-full-run

evaluate-ouroboros-all: ouroboros-full-run-approval
	$(PYTHON) scripts/run_ouroboros_evaluation.py --split all --confirm-full-run

check-secrets:
	$(PYTHON) scripts/check_secrets.py

project-results-check:
	$(PYTHON) scripts/project_results_check.py

clean-generated:
	$(PYTHON) scripts/clean_generated.py
