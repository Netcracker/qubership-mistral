#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import jsonschema
from unittest import mock

from mistral import exceptions as exc
from mistral.lang import base as spec_base
from mistral.lang import parser as spec_parser
from mistral.tests.unit import base

WF = """
version: '2.0'
wf:
  tasks:
    task1:
      action: std.noop
      on-success:
        - task2
    task2:
      action: std.noop
"""

BAD_WF = """
version: '2.0'
wf:
  tasks:
    task1:
      action: std.noop
      retry: not-a-valid-retry-policy-object
"""

MULTI_ERROR_WF = """
version: '2.0'
wf:
  tasks:
    t1:
      action: 5
      bogus: 1
      retry: {count: x}
"""

BAD_ON_SUCCESS_WF = """
version: '2.0'
wf:
  tasks:
    t1:
      action: std.noop
      on-success: 12
"""


class SchemaValidatorCacheTest(base.BaseTest):
    def test_schema_is_checked_once_per_spec_class(self):
        spec_base._SCHEMA_VALIDATORS.clear()

        with mock.patch.object(
            jsonschema.Draft202012Validator,
            'check_schema',
            wraps=jsonschema.Draft202012Validator.check_schema
        ) as check_schema:
            for _ in range(20):
                spec_parser.get_workflow_list_spec_from_yaml(WF)

            # Without the cache check_schema ran once per spec object
            # (dozens of times for this tiny workflow).
            self.assertLess(check_schema.call_count, 15)

    def test_invalid_definition_is_still_rejected(self):
        self.assertRaises(
            exc.InvalidModelException,
            spec_parser.get_workflow_list_spec_from_yaml,
            BAD_WF
        )

    def test_error_message_matches_jsonschema_validate(self):
        def original_validate_schema(spec):
            try:
                jsonschema.validate(spec._data, spec.get_schema())
            except jsonschema.ValidationError as e:
                raise exc.InvalidModelException("Invalid DSL: %s" % e)

        for definition in (BAD_WF, MULTI_ERROR_WF, BAD_ON_SUCCESS_WF):
            patched = self.assertRaises(
                exc.InvalidModelException,
                spec_parser.get_workflow_list_spec_from_yaml,
                definition
            )

            with mock.patch.object(
                spec_base.BaseSpec,
                'validate_schema',
                original_validate_schema
            ):
                original = self.assertRaises(
                    exc.InvalidModelException,
                    spec_parser.get_workflow_list_spec_from_yaml,
                    definition
                )

            self.assertEqual(str(original), str(patched))
