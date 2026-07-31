# VibeLab rebranding inventory

## Applied

- Product name, application metadata, manifest, and SVG favicon use VibeLab.
- Authentication surfaces use the text identity `VibeLab by Legrand`.
- Core accent tokens use Legrand blue while preserving the existing theme
  system and its light/dark support.
- The system agent is presented as `VibeLab Default`.
- The federated system source keeps its upstream-safe UUID and handle but is
  displayed as `Legrand Official`; by default it is a local empty catalog.
- Commercial prompts now direct users to request quota from an administrator.
- The allocation settings surface retains quota and usage visibility without
  displaying prices, purchases, upgrades, or Stripe workflows.
- User-facing documentation links now route to internal feedback rather than
  upstream Tesslate domains.

## Approved assets still needed

No approved Legrand asset was present in `app/public`. Replace the temporary
text mark and `favicon.svg` only with approved assets supplied by Legrand.

## Deliberately retained references

Technical identifiers such as `tesslate-official`, `TesslateAgent`, package
and schema names, migration history, upstream URLs in developer documentation,
and required copyright/licence material remain unchanged for compatibility and
traceability. They are not user-facing product identity.
