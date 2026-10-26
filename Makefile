PY ?= python

.PHONY: test eval show clean

test:
	$(PY) -m unittest discover -s tests -v

eval:
	$(PY) evals/runner.py

# 看单条用例的审核明细：make show ID=IMP-0019
show:
	$(PY) evals/debug_case.py $(ID)

clean:
	rm -rf evals/report/result.json
	find . -name '__pycache__' -type d -exec rm -rf {} +
