codespell:
	codespell -w $(shell git ls-files)

codespell-check:
	codespell $(shell git ls-files)

coverage.xml: testcov
	coverage xml

coverage-report: testcov
	coverage report

flake8:
	flake8 jupyter_workflow tests

format:
	isort jupyter_workflow tests
	black jupyter_workflow tests

format-check:
	isort --check-only jupyter_workflow tests
	black --diff --check jupyter_workflow tests

pyupgrade:
	pyupgrade --py3-only --py310-plus $(shell git ls-files | grep .py)

test:
	python -m pytest -rs ${PYTEST_EXTRA}

testcov:
	python -m pytest -rs --cov --junitxml=junit.xml -o junit_family=legacy --cov-report= ${PYTEST_EXTRA}
