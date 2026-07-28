# Azure runtime configuration

VibeLab uses one server-managed route for AI requests:

`VibeLab → LiteLLM → Azure AI Foundry`

The browser never receives an Azure key, a LiteLLM key, or a provider endpoint.

## Required secrets

Set these only in ignored `.env` files for local development, or inject them
through the Azure deployment secret workflow. Do not commit real values.

| Variable | Purpose |
| --- | --- |
| `LITELLM_MASTER_KEY` | Authenticates VibeLab services to the central LiteLLM gateway. |
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

Copy `.env.example` to ignored `.env`, replace the placeholders above, then
start the normal stack with `docker compose up --build -d`. The official
LiteLLM image is private to `tesslate-network`; it has no host port. Check
health with `docker compose ps litellm` and, after credentials are configured,
run a model-list and minimal completion from an internal service.

## Azure runtime

The Azure Terraform configuration creates a private ClusterIP LiteLLM
deployment and its ConfigMap. Azure provider credentials are injected only
into `litellm-secrets`; backend, worker, and gateway receive only the proxy
URL, master key, and model aliases through the existing app secret. Supply the
required values through the ignored Azure tfvars/secret process (or the
platform's existing secret injection), then run the standard Azure Terraform
and deployment workflow.

## Team governance

Team Settings → **Feature access** controls Marketplace and Automations for
non-admin members. Both are off by default. Team admins always have access;
editors and viewers gain access only when the matching option is enabled.
Library remains available. API keys, provider configuration, Marketplace
Sources, and Cloud settings remain team-admin-only.

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
