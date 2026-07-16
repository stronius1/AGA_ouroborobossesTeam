.PHONY: review baseline evolve test demo

review: ## blocker-review: exit 1 is the expected HITL outcome
	@set +e; python3 scripts/run_review.py --pr golden/prs/pr-12; rc=$$?; set -e; \
	if [ $$rc -ne 1 ]; then echo "ERROR: expected review exit 1, got $$rc" >&2; if [ $$rc -eq 0 ]; then exit 2; else exit $$rc; fi; fi; \
	echo "Expected escalation confirmed (review exit 1)."

baseline: ## metrics on the protected golden snapshot
	python3 evolver/fitness.py --out build/metrics-baseline.json

evolve: ## candidate-only offline evolution
	python3 scripts/run_evolution.py --demo

test: ## complete offline suite
	python3 -m compileall -q tools evolver scripts tests
	python3 -m pytest -q

demo: ## end-to-end blocker review -> evolution -> verified artifacts
	@set +e; python3 scripts/run_review.py --pr golden/prs/pr-12; rc=$$?; set -e; \
	if [ $$rc -ne 1 ]; then echo "ERROR: expected blocker escalation exit 1, got $$rc" >&2; if [ $$rc -eq 0 ]; then exit 2; else exit $$rc; fi; fi; \
	echo "Expected blocker/escalation confirmed."
	python3 scripts/run_evolution.py --demo
	@test -s build/evolution-pr.md
	@test -s build/rules.diff
	@test -s build/metrics-baseline.json
	@test -s build/metrics-candidate.json
	@test -s build/candidate-manifest.json
	@! grep -R -n '{{[^}]*}}' build/evolution-pr.md build/rules.diff
	@echo "Demo artifacts verified; Merge — только человеком."
