# Local development helpers for Qubership Mistral.
#
#   make build                  Create .venv, install runtime deps, editable Mistral
#   make test                   Run Mistral + operator unit tests
#   make test-mistral           Mistral unit tests via tox -e py3
#   make test-mistral MODULE=api
#   make test-operator          Operator unit tests via tox -e operator
#   make build-<svc>            Docker image; <svc>: api engine executor notifier (see `make help`)
#   make test-<svc>             Unit tests; <svc>: api engine executor notifier
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
DOCKER      ?= docker
IMAGE_TAG   ?= latest
MISTRAL_IMAGE   ?= qubership-mistral
OPERATOR_IMAGE  ?= qubership-mistral-operator
MISTRAL_SERVICES := api engine executor notifier
TEST_FILTER = $(if $(MODULE),mistral.tests.unit.$(MODULE),)

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
.PHONY: build-image build-operator build-services test-services
.PHONY: $(addprefix build-,$(MISTRAL_SERVICES))
.PHONY: test-api test-engine test-executor test-notifier

help:
	@echo "Targets:"
	@echo "  build           Create $(VENV), install requirements.txt + nc_requirements.txt,"
	@echo "                  then pip install -e . (editable Mistral)"
	@echo "  test            Run Mistral and operator unit tests"
	@echo "  test-mistral    Mistral unit tests via tox -e $(TOXENV)  (MODULE=api ARGS='...')"
	@echo "  test-operator   Operator unit tests via tox -e operator"
	@echo "  build-image     Docker image $(MISTRAL_IMAGE):$(IMAGE_TAG) (shared by all Mistral services)"
	@echo "  build-<svc>     Alias of build-image, <svc> in: $(MISTRAL_SERVICES)"
	@echo "  test-<svc>      Unit tests, <svc> in: api engine executor notifier"
	@echo "  build-operator  Operator Docker image $(OPERATOR_IMAGE):$(IMAGE_TAG)"
	@echo "  build-services, test-services           Everything above"
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

# Per-service targets
# api, engine, executor, notifier all run from the
# same image (Dockerfile, SERVER=<name>), so each build-<service> builds it.

build-image:
	$(DOCKER) build -t $(MISTRAL_IMAGE):$(IMAGE_TAG) -f Dockerfile .

$(addprefix build-,$(MISTRAL_SERVICES)): build-image

build-operator:
	$(DOCKER) build -t $(OPERATOR_IMAGE):$(IMAGE_TAG) -f operator/Dockerfile operator

build-services: build-image build-operator

test-api:
	$(MAKE) test-mistral MODULE=api
test-engine:
	$(MAKE) test-mistral MODULE=engine
test-executor:
	$(MAKE) test-mistral MODULE=executors
test-notifier:
	$(MAKE) test-mistral MODULE=notifiers
test-services: test-api test-engine test-executor test-notifier test-operator

# Common linter integration
# common.mk is not included directly because it defines targets
# (test, test-go, test-python, test-java, verify) that would conflict with
# this Makefile's existing test targets. The lint-related targets are
# exposed here and delegated to common.mk.


# LINTER_IMAGE ?= ghcr.io/netcracker/linter
# LINTER_TAG ?= common_linter_integration

# DEFAULT_BRANCH ?= main
# export DEFAULT_BRANCH

# .PHONY: lint lint-super-linter skill-validate lint-fix verify
# lint lint-super-linter skill-validate lint-fix:
# 	$(MAKE) -f common.mk $@

# # verify must run the consumer's test target, not common.mk's
# # test-go/test-python/test-java targets.
# verify: lint test

# common.mk lint integration is disabled until common.mk is added to the
# repository, so verify only runs the local test suite for now.
.PHONY: verify
verify: test
