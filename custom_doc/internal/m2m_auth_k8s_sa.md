# M2M Authentication Using Kubernetes Token Review API

Added a new authentication mechanism that allows services running inside Kubernetes to be authenticated using their Service Account Tokens.


## Configuration

A new authentication type `k8s-sa` is introduced. Optionally, `projectRules` can be configured to map token claims to a Mistral `project_id`.

```yaml
mistralCommonParams:
  auth:
    enable: true
    type: k8s-sa
    projectRules:
      - type: extract
        field: "iss"
        pattern: "*/realms/{value}"
```

Added a new [handler](https://github.com/Netcracker/qubership-mistral/blob/feat/m2m_auth/mistral/auth/k8s_sa.py) at `mistral/auth/k8s_sa.py` and hooked it in [setup.cfg](https://github.com/Netcracker/qubership-mistral/blob/feat/m2m_auth/setup.cfg#L117). This is responsible for:

- Extracting the token from the incoming request
- Calling the Kubernetes TokenReview API for token validation
- Building the Mistral auth context



## Kubernetes Client Setup

Inside `K8sSAAuthHandler`:

```python
config.load_incluster_config()
```

This loads the Service Account token of the Mistral API pod and the cluster API endpoint into the client config, enabling Mistral to securely communicate with the Kubernetes API Server.


## Token Validation Using Kubernetes

Instead of validating JWTs itself, Mistral delegates validation to Kubernetes:

```python
self.api.create_token_review(review)
```

API used: `POST /apis/authentication.k8s.io/v1/tokenreviews`

Mistral sends the incoming token and Kubernetes returns:
- Whether the token is valid
- Which service account it belongs to (`system:serviceaccount:<namespace>:<name>`)
- Group memberships


## Project ID Resolution

Mistral provides a configurable rule-based mapping via `projectRules`.project_id is determined by evaluating a configurable rule list against the decoded token claims.

### How it works

Rules are evaluated in order. The first matching rule wins. If no rule matches, `<default-project>` is used.

#### Rule Types
*extract*:
Applies a glob pattern to the field value and returns the text captured by {value} directly as project_id.

Required fields: type, field, pattern

```yaml
projectRules:
  - type: extract
    field: "iss"
    pattern: "*/{value}"
```
Given "iss": "https://auth.example.com/realms/my-tenant", this yields project_id = "my-tenant"

*map*:
Compares a field value (or the part captured by an optional pattern) to a configured value. On match, returns the configured project string as project_id.

Required fields: type, field, value, project

Optional field: pattern

Without pattern — the raw field value is compared:

```yaml
projectRules:
  - type: map
    field: "aud"
    value: "account"
    project: "project-alpha"
```
Given "aud" : "account", yields project_id = "project-alpha"

With pattern — {value} is extracted first, then compared:

```yaml
projectRules:
  - type: map
    field: "iss"
    pattern: "*/{value}"
    value: "tenant-a"
    project: "project-alpha"
```
 Given "iss": "https://auth.example.com/realms/tenant-a", yields project_id = "project-alpha"

### Configuration reference

`projectRules` is configured under `mistralCommonParams.auth` in Helm values. It is stored as a JSON string in the `mistral-common-params` ConfigMap under the key `auth-project-rules`, injected into the pod as the env var `AUTH_PROJECT_RULES`, and read by oslo.config from the `[auth]` section as `project_rules`.


## RBAC Setup

The following resources are created by the Helm chart:

- A **ServiceAccount** `mistral-api-sa` for the Mistral API pod
- A **ClusterRole** `mistral-token-reviewer` with permission `tokenreviews:create` on `authentication.k8s.io`
- A **ClusterRoleBinding** `mistral-token-reviewer-binding` attaching the ClusterRole to `mistral-api-sa`

The `mistral-api-sa` ServiceAccount is attached to the Mistral API pod (only when `auth.type: k8s-sa`) because the API pod is the one handling authentication and needs permission to call the TokenReview API.
