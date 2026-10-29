# qubership-mistral overrides for the shared consumer Makefile in Makefile.linter.
# Set values here, then include that file. Makefile.linter may set REPO_ROOT from
# its own path, so this file restores REPO_ROOT to this checkout afterward.
#
# Refresh Makefile.linter from platform-ci-toolkit when the template changes:
#   make sync-linter-makefile PLATFORM_CI_TOOLKIT_RAW_URL=<raw-url>
#
# Unit tests still use tox/stestr (see AGENTS.md). Leave PY_BUILD empty so
# make test-python skips; wire tox into PY_BUILD/PYTHON_TEST_CMD when you want
# make test to run them inside the common linter image.

REPO_ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

LINTER_IMAGE ?= ghcr.io/netcracker/linter
LINTER_TAG ?= common_linter_integration

DEFAULT_BRANCH ?= main

PYTHON ?= python3
# PY_BUILD left empty: mistral unit tests use tox/stestr, not pytest via make.

# Evaluate against this checkout before Makefile.linter overwrites REPO_ROOT.
GO_TEST_MODULES ?= $(shell find $(REPO_ROOT) -name go.mod -not -path '*/vendor/*' -exec dirname {} \;)
JAVA_TEST_MODULES ?= $(shell find $(REPO_ROOT) -name pom.xml -not -path '*/target/*' -exec dirname {} \;)

include $(REPO_ROOT)Makefile.linter

# Point REPO_ROOT back at this repository (firstword is this Makefile).
REPO_ROOT := $(dir $(abspath $(firstword $(MAKEFILE_LIST))))
