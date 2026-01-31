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
	npm run lint

format-check:
	isort --check-only jupyter_workflow tests
	black --diff --check jupyter_workflow tests
	npm run lint:check

pyupgrade:
	pyupgrade --py3-only --py310-plus $(shell git ls-files | grep .py)

test:
	python -m pytest -rs ${PYTEST_EXTRA}
	npm run test

testcov:
	coverage run -m pytest -rs ${PYTEST_EXTRA}
	npm run coverage
	coverage combine --quiet --append
