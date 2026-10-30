# qubership-mistral overrides for the shared consumer Makefile in Makefile.precheck.
# Set values here, then include that file. Do not edit Makefile.precheck — refresh
# it from platform-ci-toolkit/linter/templates/Makefile when the template changes:
#   make sync-precheck-makefile PLATFORM_CI_TOOLKIT_RAW_URL=<raw-url>
#
# Unit tests still use tox/stestr (see AGENTS.md). Leave PY_BUILD empty so
# make test-python skips; wire tox into PY_BUILD/PYTHON_TEST_CMD when you want
# make test to run them inside the common linter image.

LINTER_IMAGE ?= ghcr.io/netcracker/linter
LINTER_TAG ?= common_linter_integration

DEFAULT_BRANCH ?= main

# PY_BUILD left empty: mistral unit tests use tox/stestr, not pytest via make.

include $(dir $(abspath $(lastword $(MAKEFILE_LIST))))Makefile.precheck
