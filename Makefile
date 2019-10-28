.DEFAULT_GOAL := help
export VENV := $(abspath venv)
export PATH := ${VENV}/bin:${PATH}

define BROWSER_PYSCRIPT
import os, webbrowser, sys

try:
	from urllib import pathname2url
except:
	from urllib.request import pathname2url

webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT

BROWSER := python -c "$$BROWSER_PYSCRIPT"

.PHONY: help
help: ## Shows this message.
	@echo "Asynchronous Python client for WLED."; \
	echo; \
	echo "Usage:"; \
	awk -F ':|##' '/^[^\t].+?:.*?##/ {\
		printf "\033[36m  make %-30s\033[0m %s\n", $$1, $$NF \
	}' $(MAKEFILE_LIST)

.PHONY: dev
dev: install-dev install ## Set up a development environment.

.PHONY: black
black: lint-black

.PHONY: lint
lint: lint-black lint-flake8 lint-pylint lint-mypy ## Run all linters.

.PHONY: lint-black
lint-black: ## Run linting using black & blacken-docs.
	black --safe --target-version py36 wled tests examples; \
	blacken-docs --target-version py36

.PHONY: lint-flake8
lint-flake8: ## Run linting using flake8 (pycodestyle/pydocstyle).
	flake8 wled

.PHONY: lint-pylint
lint-pylint: ## Run linting using PyLint.
	pylint wled

.PHONY: lint-mypy
lint-mypy: ## Run linting using MyPy.
	mypy -p wled

.PHONY: test
test: ## Run tests quickly with the default Python.
	pytest --cov-report html --cov-report term --cov=wled .;

.PHONY: coverage
coverage: test ## Check code coverage quickly with the default Python.
	$(BROWSER) htmlcov/index.html

.PHONY: install
install: clean ## Install the package to the active Python's site-packages.
	pip install -Ur requirements.txt; \
	pip install -e .;

.PHONY: clean clean-all
clean: clean-build clean-pyc clean-test ## Removes build, test, coverage and Python artifacts.
clean-all: clean-build clean-pyc clean-test clean-venv ## Removes all venv, build, test, coverage and Python artifacts.

.PHONY: clean-build
clean-build: ## Removes build artifacts.
	rm -fr build/; \
	rm -fr dist/; \
	rm -fr .eggs/; \
	find . -name '*.egg-info' -exec rm -fr {} +; \
	find . -name '*.egg' -exec rm -fr {} +;

.PHONY: clean-pyc
clean-pyc: ## Removes Python file artifacts.
	find . -name '*.pyc' -delete; \
	find . -name '*.pyo' -delete; \
	find . -name '*~' -delete; \
	find . -name '__pycache__' -exec rm -fr {} +;

.PHONY: clean-test
clean-test: ## Removes test and coverage artifacts.
	rm -fr .tox/; \
	rm -f .coverage; \
	rm -fr htmlcov/; \
	rm -fr .pytest_cache;

.PHONY: clean-venv
clean-venv: ## Removes Python virtual environment artifacts.
	rm -fr venv/;

.PHONY: dist
dist: clean ## Builds source and wheel package.
	python setup.py sdist; \
	python setup.py bdist_wheel; \
	ls -l dist;

.PHONY: release
release:  ## Release build on PyP
	twine upload dist/*

.PHONY: tox
tox: ## Run tests on every Python version with tox.
	tox

.PHONY: venv
venv: clean-venv ## Create Python venv environment.
	python3 -m venv venv;

.PHONY: install-dev
install-dev: clean
	pip install -Ur requirements_dev.txt; \
	pip install -Ur requirements_test.txt; \
	pre-commit install;
