# qubership-mistral overrides for the shared consumer Makefile in Makefile.common.
# Set values here, then include that file. Do not edit Makefile.common — refresh
# it from platform-ci-toolkit/linter/templates/Makefile.common.mk when the template changes:
#   make sync-precheck-makefile PLATFORM_CI_TOOLKIT_RAW_URL=<raw-url>
#
# Unit tests still use tox/stestr (see AGENTS.md). Leave PY_BUILD empty so
# make test-python skips; wire tox into PY_BUILD/PYTHON_TEST_CMD when you want
# make test-python to run them inside the python test image.

LINTER_IMAGE ?= ghcr.io/netcracker/linter
LINTER_TAG ?= common_linter_integration

DEFAULT_BRANCH ?= main

# PY_BUILD left empty: mistral unit tests use tox/stestr, not pytest via make.

include Makefile.common
