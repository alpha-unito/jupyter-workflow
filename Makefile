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
	black jupyter_workflow tests

format-check:
	black --diff --check jupyter_workflow tests

pyupgrade:
	pyupgrade --py3-only --py38-plus $(shell git ls-files | grep .py)

test:
	python -m pytest -rs ${PYTEST_EXTRA}

testcov:
	coverage run -m pytest -rs ${PYTEST_EXTRA}
	coverage combine --quiet --append
