# Copyright 2018 - Extreme Networks, Inc.
# Modified in 2025 by NetCracker Technology Corp.
#
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

from http import HTTPStatus
import json
from oslo_config import cfg
from oslo_log import log as logging
import requests
from requests.exceptions import ChunkedEncodingError

from mistral.notifiers import base
from mistral.services import secure_request


LOG = logging.getLogger(__name__)


class WebhookPublisher(base.NotificationPublisher):

    def publish(self, ctx, ex_id, data, event, timestamp, **kwargs):
        url = kwargs.get('url')
        headers = kwargs.get('headers', {})

        if 'headers' in data:
            headers.update(data['headers'])
            del data['headers']

        if cfg.CONF.oauth2.security_profile == 'prod':
            headers = secure_request.set_auth_token(headers)

        # Use stream=True to prevent automatic reading of response body
        # This avoids ChunkedEncodingError in urllib3 2.x when chunked
        # transfer encoding is incomplete
        resp = requests.post(
            url,
            data=json.dumps(data),
            headers=headers,
            stream=True
        )

        LOG.info("Webook request url=%s code=%s", url, resp.status_code)

        if resp.status_code not in [HTTPStatus.OK, HTTPStatus.CREATED]:
            # Only read response body when needed (error case)
            try:
                error_text = resp.text
            except ChunkedEncodingError:
                # If chunked encoding is incomplete, use content instead
                error_text = resp.content.decode('utf-8', errors='replace')
            raise Exception(error_text)
        else:
            # For successful responses, consume the response to avoid
            # connection pool issues, but ignore any chunked encoding errors
            try:
                resp.content
            except ChunkedEncodingError:
                # Ignore chunked encoding errors for successful responses
                # The request was successful, we just couldn't read the full body
                pass
