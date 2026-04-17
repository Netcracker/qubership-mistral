# M2M Authentication Using Kubernetes Token Review API

Added a new authentication mechanism that allows services running inside kubernetes to be authenticated using their Service Account Tokens.


## Configuration
A new authentication type "k8s-sa" is introduced.

``` yaml
mistralCommonParams:
    auth:
        enable: true
        type: k8s-sa
```

Added a new [handler](https://github.com/Netcracker/qubership-mistral/blob/fix/reduce_resources/mistral/auth/k8s_sa.py) at mistral/auth/k8s_sa.py and hooked it in [setup.cfg](https://github.com/Netcracker/qubership-mistral/blob/fix/reduce_resources/setup.cfg#L117). This is now responsible for

- Extact the token from incoming request
- Call Kubernetes TokenReview API for token validation
- building the Mistral auth context

## Kubernetes Client setup

Inside the K8sSAAuthHandler

config.load_incluster_config()

This loads:

- the Service Account token of the Mistral API pod
- cluster API endpoint

This enables Mistral to securely communicate with the Kubernetes API Server

## Token validation using Kubernetes

Instead of validating JWTs itself, Mistral relies on Kubernetes:

self.api.create_token_review(review)

This calls the TokenReview API on the Kubernetes API Server.

API Used: POST /apis/authentication.k8s.io/v1/tokenreviews

Mistral sends the incoming token, and Kubernetes tells us:

- whether it is valid
- which service account it belongs to

## RBAC Setup
To allow this, created:

- a Service Account for Mistral API (mistral-api-sa)
- a ClusterRole with permission:
tokenreviews.create
- a ClusterRoleBinding to attach it

This is required because Mistral itself needs permission to ask Kubernetes to validate tokens.

- This Service Account is attached to Mistral-Api pod, as it handles authentication.
