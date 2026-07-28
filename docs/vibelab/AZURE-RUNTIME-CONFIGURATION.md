# Azure runtime configuration

VibeLab uses one server-managed route for AI requests:

`VibeLab → LiteLLM → Azure AI Foundry`

The browser never receives an Azure key, a LiteLLM key, or a provider endpoint.

## Required Azure values

Set these only in ignored `.env` files for local development, or inject them
through the Azure deployment secret workflow. Do not commit real values.

| Variable | Purpose |
| --- | --- |
| `AZURE_API_BASE` | Azure AI Foundry/Azure OpenAI endpoint. |
| `AZURE_API_KEY` | Azure provider credential. |
| `AZURE_API_VERSION` | Azure API version supported by the deployment. |
| `AZURE_AI_DEFAULT_DEPLOYMENT` | Azure deployment behind `vibelab-default`. |
| `AZURE_AI_FAST_DEPLOYMENT` | Azure deployment behind `vibelab-fast`. |
| `AZURE_AI_REASONING_DEPLOYMENT` | Azure deployment behind `vibelab-reasoning`. |

`LITELLM_API_BASE` is `http://litellm:4000/v1` in Docker Compose and the
private `litellm-service` address in Azure. `LITELLM_DEFAULT_MODELS` defaults
to `vibelab-default,vibelab-fast,vibelab-reasoning`; only these aliases are
application-facing.

## Local runtime

Prepare the local environment once (or safely re-run after pulling changes):

```sh
python3 scripts/setup-local-env.py
docker compose up -d --build
```

The setup script creates or completes the ignored `.env` atomically. It
generates `SECRET_KEY`, `INTERNAL_API_SECRET`, both local PostgreSQL passwords,
`LITELLM_MASTER_KEY`, and the Marketplace Hub token; it preserves existing
non-placeholder values and never prints their values. The only values an
operator must supply are:

```text
AZURE_API_BASE
AZURE_API_KEY
AZURE_API_VERSION
AZURE_AI_DEFAULT_DEPLOYMENT
AZURE_AI_FAST_DEPLOYMENT
AZURE_AI_REASONING_DEPLOYMENT
```

After supplying them, run the normal command again:

```sh
docker compose up -d --build
```

The official LiteLLM image is private to `tesslate-network`; it has no host
port. Check health with `docker compose ps litellm` and, after credentials are
configured, run a model-list and minimal completion from an internal service.

Before starting, an operator can validate names without printing any secret:

```sh
python3 scripts/setup-local-env.py --validate-azure --env-file .env
```

When one or more Azure variables are absent, Compose still starts the
non-AI services. LiteLLM stays running in an explicitly disabled, unhealthy
state and logs only the missing variable names. Add the variables to `.env`
and recreate the LiteLLM service. The application returns the generic AI
availability message rather than exposing provider setup to normal users.

## Azure runtime

The Azure Terraform configuration creates a private ClusterIP LiteLLM
deployment and its ConfigMap. Azure provider credentials are injected only
into `litellm-secrets`; backend, worker, and gateway receive only the proxy
URL, master key, and model aliases through the existing app secret. Supply the
required values through the ignored Azure tfvars/secret process (or the
platform's existing secret injection), then run the standard Azure Terraform
and deployment workflow.

The namespace NetworkPolicies allow only backend, worker, and gateway pods to
reach LiteLLM on TCP 4000. The LiteLLM pod can reach PostgreSQL and external
HTTPS for Azure AI Foundry, while the proxy remains inaccessible to the
browser and ingress.

## Team governance

See [Platform Team and Workspace Governance](PLATFORM-TEAM-WORKSPACE-GOVERNANCE.md)
for the platform Team policies, per-user creation overrides, invitation flow,
and private-by-default Workspace access. Team Settings → **Feature access**
continues to control Marketplace and Automations for non-admin members. Both
are off by default. Team admins always have access; editors and viewers gain
access only when the matching option is enabled. Library remains available.
API keys, provider configuration, Marketplace Sources, and Cloud settings
remain team-admin-only.

Chat defaults to **Allow all edits** when no user choice is stored. The Assist
to Build TO-BE approval gate still rejects all write tools until it is approved.

## Health validation

1. Verify LiteLLM is ready (`/health/readiness`) and private.
2. Verify backend, worker, and gateway contain `LITELLM_API_BASE`,
   `LITELLM_MASTER_KEY`, and `LITELLM_DEFAULT_MODELS`—not Azure credentials.
3. From an internal service, authenticate to LiteLLM, list models, and make a
   minimal completion using `vibelab-default`.
4. Confirm a standard user sees only central aliases and no provider settings.

Without real Azure values, configuration and unit validation can run, but a
live health check or completion must be reported as unverified.
