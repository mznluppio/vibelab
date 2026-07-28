#!/bin/sh
# Validate the runtime inputs for VibeLab's private Azure AI Foundry proxy.
#
# This script intentionally prints variable *names* only. It is safe to run in
# local shells, Docker Compose, and Kubernetes startup paths.

set -eu

missing=""
for name in \
  LITELLM_MASTER_KEY \
  AZURE_API_BASE \
  AZURE_API_KEY \
  AZURE_API_VERSION
do
  eval "value=\${$name-}"
  if [ -z "$value" ]; then
    missing="${missing}${missing:+ }${name}"
  fi
done

# Callers normally provide deployment names. Compose and Terraform turn those
# into provider-prefixed AZURE_AI_*_MODEL values before the proxy starts, so
# accept either representation without ever printing its value.
for alias in DEFAULT FAST REASONING
do
  eval "deployment=\${AZURE_AI_${alias}_DEPLOYMENT-}"
  eval "model=\${AZURE_AI_${alias}_MODEL-}"
  if [ -z "$deployment" ] && { [ -z "$model" ] || [ "$model" = "azure/" ]; }; then
    missing="${missing}${missing:+ }AZURE_AI_${alias}_DEPLOYMENT"
  fi
done

if [ -n "$missing" ]; then
  echo "LiteLLM Azure runtime configuration is incomplete. Missing: $missing" >&2
  exit 1
fi

echo "LiteLLM Azure runtime configuration is present."
