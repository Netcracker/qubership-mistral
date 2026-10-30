# Local development helpers for Qubership Mistral.
#
#   make build                  Create .venv, install runtime deps, editable Mistral
#   make test                   Run Mistral + operator unit tests
#   make test-mistral           Mistral unit tests via tox -e py3
#   make test-mistral MODULE=api
#   make test-operator          Operator unit tests via tox -e operator
#
# Activate the local venv afterwards:
#   source .venv/bin/activate
#
# Requires Python >= 3.10.
#
# Native libraries (install these if pip fails to build confluent-kafka / psycopg2):
#   macOS:  brew install librdkafka libpq
#   Debian: sudo apt install -y gcc libpq-dev librdkafka-dev python3-dev libffi-dev

PYTHON      ?= python3
VENV        ?= .venv
PIP         := $(VENV)/bin/pip
VENV_PYTHON := $(VENV)/bin/python
TOX         := $(VENV)/bin/tox
TOXENV      ?= py3
TOXOPTS     ?=
MODULE      ?=
ARGS        ?=
TEST_FILTER := $(if $(MODULE),mistral.tests.unit.$(MODULE),)

UNAME_S := $(shell uname -s)

ifeq ($(UNAME_S),Darwin)
  BREW_LIBRDKAFKA := $(shell brew --prefix librdkafka 2>/dev/null)
  BREW_LIBPQ      := $(shell brew --prefix libpq 2>/dev/null)
  ifneq ($(BREW_LIBRDKAFKA),)
    export CFLAGS          += -I$(BREW_LIBRDKAFKA)/include
    export LDFLAGS         += -L$(BREW_LIBRDKAFKA)/lib
    export PKG_CONFIG_PATH := $(BREW_LIBRDKAFKA)/lib/pkgconfig:$(PKG_CONFIG_PATH)
  endif
  ifneq ($(BREW_LIBPQ),)
    export CFLAGS  += -I$(BREW_LIBPQ)/include
    export LDFLAGS += -L$(BREW_LIBPQ)/lib
    export PATH    := $(BREW_LIBPQ)/bin:$(PATH)
  endif
endif

.DEFAULT_GOAL := help

.PHONY: help venv build test test-mistral test-operator

help:
	@echo "Targets:"
	@echo "  build           Create $(VENV), install requirements.txt + nc_requirements.txt,"
	@echo "                  then pip install -e . (editable Mistral)"
	@echo "  test            Run Mistral and operator unit tests"
	@echo "  test-mistral    Mistral unit tests via tox -e $(TOXENV)  (MODULE=api ARGS='...')"
	@echo "  test-operator   Operator unit tests via tox -e operator"
	@echo ""
	@echo "Examples:"
	@echo "  make test"
	@echo "  make test-mistral MODULE=api"
	@echo "  make test-mistral MODULE=engine ARGS='--concurrency=1'"
	@echo "  make test-mistral TOXOPTS=-r"
	@echo "  make test-operator"
	@echo "  make test-operator ARGS='-k dbaas'"
	@echo ""
	@echo "After build:  source $(VENV)/bin/activate"

$(VENV)/bin/pip:
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || \
		(echo "Python >= 3.10 is required (found $$($(PYTHON) --version))" && exit 1)
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip wheel
	$(PIP) install "setuptools==81.0.0"

venv: $(VENV)/bin/pip

build: venv
	$(PIP) install --upgrade -r requirements.txt
	$(PIP) install --upgrade -r nc_requirements.txt
	$(PIP) install --no-dependencies --no-build-isolation -e . --config-settings editable_mode=compat
	@echo ""
	@echo "Mistral installed into $(VENV)."
	@echo "Activate with: source $(VENV)/bin/activate"

$(VENV)/bin/tox: $(VENV)/bin/pip
	$(PIP) install tox

test: test-mistral test-operator

test-mistral: $(VENV)/bin/tox
	$(TOX) $(TOXOPTS) -e $(TOXENV) -- $(TEST_FILTER) $(ARGS)

test-operator: $(VENV)/bin/tox
	$(TOX) $(TOXOPTS) -e operator -- $(ARGS)
