PY ?= python
CASE ?= IMP-0025

.PHONY: test eval show audit list clean

test:
	$(PY) -m unittest discover -s tests -v

eval:
	$(PY) evals/runner.py

# 跑一票单证全流程：make audit CASE=IMP-0025
audit:
	$(PY) -m src.app.cli audit $(CASE) --auto --offline

list:
	$(PY) -m src.app.cli list

# 看单条用例的审核明细：make show ID=IMP-0019
show:
	$(PY) evals/debug_case.py $(ID)

clean:
	rm -rf evals/report/result.json
	find . -name '__pycache__' -type d -exec rm -rf {} +
