# litellm config

Paths:

- `k8s/litellm/config.yaml` — existing multi-provider configuration used by the AWS stack.
- `k8s/litellm/vibelab-azure-config.yaml` — restricted VibeLab Azure AI Foundry catalog used by Docker Compose and AKS.

## Purpose

LiteLLM sits between OpenSail's backend and every upstream model provider (OpenAI, Anthropic, Azure, Together, etc.). The `config.yaml` defines the model list, routing rules, rate limits, and fallback chains.

## Consumed by

- AWS: Terraform `k8s/terraform/aws/litellm.tf` deploys a LiteLLM Deployment that mounts the multi-provider configuration via ConfigMap.
- Azure AKS: Terraform `k8s/terraform/azure/kubernetes.tf` deploys a private ClusterIP LiteLLM service with Azure credentials in `litellm-secrets` and mounts the VibeLab configuration.
- Docker Compose: the `litellm` service mounts the VibeLab configuration and is reachable only as `http://litellm:4000/v1` on the Compose network.

## Editing

1. For VibeLab, update deployment values (`AZURE_AI_*_DEPLOYMENT`) rather than replacing the stable public aliases: `vibelab-default`, `vibelab-fast`, and `vibelab-reasoning`.
2. Keep `AZURE_API_BASE`, `AZURE_API_KEY`, and `AZURE_API_VERSION` in the environment or Terraform secret input; never put them in a config file.
3. Apply the relevant Terraform stack. The LiteLLM service is private and does not have an ingress.

## Related

- `orchestrator/app/services/litellm_service.py` for the client side.
- `docs/orchestrator/services/model-pricing.md` for pricing metadata that flows from this config.
