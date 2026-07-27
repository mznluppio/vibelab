# OpenSail baseline

- Upstream: `TesslateAI/OpenSail`
- Baseline SHA: `bc6cf79fda5b13c937dbae92bdf2d912a987eeb0`
- Local tag: `upstream-baseline-2026-07-27`
- Date: 2026-07-27

## Commands

```bash
git submodule update --init --recursive
docker compose up --build -d
docker compose ps
curl http://localhost:8000/health
```

## Result

The upstream Docker stack starts successfully with Traefik, PostgreSQL, Redis,
the orchestrator, ARQ worker, gateway, Vite frontend, migrations, and system
seeding. Registration, password login, authenticated API access, project
creation, and persistence across the project API were verified.

The initial clone needs `git submodule update --init --recursive`; the agent
runner is a required upstream submodule and a build without it fails before
startup. This is an upstream setup requirement, not a VibeLab change.

## Limits of this local baseline

No LiteLLM endpoint or key is available locally, so agent chat generation and
its resulting workspace edits cannot be exercised. The runtime remains healthy
without it, but model discovery reports no configured models.

The upstream marketplace source initially has no synchronised bases in this
environment. An empty workspace was therefore used to verify project creation
and persistence; base selection and workspace preview require an approved
catalog source and a configured model provider.
