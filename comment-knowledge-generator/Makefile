# Community knowledge generator: common tasks.  Run `make help` to list them.
PY ?= python3

.PHONY: help install test test-fast test-group demo serve fixtures clean

help:          ## list the tasks
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-11s %s\n", $$1, $$2}'

install:       ## install pipeline + test dependencies
	$(PY) -m pip install -r requirements-dev.txt

test:          ## run every automated test case and write a report to reports/
	$(PY) scripts/run_tests.py

test-fast:     ## same, without the headless-Chrome page checks (group G)
	$(PY) scripts/run_tests.py --no-browser

test-group:    ## one group, e.g. make test-group G=E
	$(PY) scripts/run_tests.py --group $(G)

demo:          ## build public/index.html from the synthetic fixtures (no API calls)
	$(PY) scripts/build_demo.py

serve:         ## serve public/ and open the browser test runner
	$(PY) scripts/serve.py

fixtures:      ## regenerate tests/fixtures from tests/fixtures/make_fixtures.py
	$(PY) tests/fixtures/make_fixtures.py

clean:         ## remove generated reports and caches
	rm -rf reports/*.md reports/*.csv reports/*.xml .pytest_cache tests/__pycache__
