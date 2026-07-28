#!/bin/sh
# Validate without exposing values.  Placeholder handling lives in the same
# implementation that prepares .env so Compose and local setup cannot drift.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python "$script_dir/setup-local-env.py" --validate-azure
