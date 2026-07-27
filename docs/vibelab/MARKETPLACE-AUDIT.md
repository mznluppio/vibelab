# Audit marketplace VibeLab

Date : 2026-07-27. État observé uniquement : cette mission ne modifie ni les
sources, ni les seeds, ni les migrations, ni les workflows de marketplace.

## Synthèse

La marketplace mélange aujourd'hui catalogue fédéré, contenu local historique
et pipeline Apps distinct. Bases, Agents et Themes peuvent devenir publics
immédiatement : il n'existe pas de revue communautaire commune. Les Apps ont
un pipeline de validation, incomplet pour une source locale. Skills,
connecteurs et cibles de déploiement n'ont pas de parcours complet de
création/publication communautaire.

## `Legrand Official` et `Sync error`

Le handle `tesslate-official` et son UUID réservé restent des identifiants de
compatibilité. Le seed courant (`orchestrator/app/seeds/marketplace_sources.py`)
affiche `Legrand Official` et utilise par défaut `local://legrand-official`,
sauf surcharge `LEGRAND_OFFICIAL_BASE_URL`; il ne vide pas un `last_sync_error`
historique.

Une base issue uniquement de la migration historique
`orchestrator/alembic/versions/0088_marketplace_sources.py` peut encore avoir
`https://marketplace.tesslate.com`. Le worker HTTP essaie alors l'ancien hub et
persiste son erreur. Une surcharge d'environnement vers cette URL a le même
effet. Pour qualifier l'incident, relever `base_url`, `last_sync_error` et
`LEGRAND_OFFICIAL_BASE_URL` sur l'instance. Cette passe ne masque ni n'efface
l'erreur.

Avec `local://legrand-official`,
`orchestrator/app/services/marketplace_local.py` lit les manifests sous
`$OPENSAIL_HOME` sans joindre Tesslate. Cette voie est incomplète : elle génère
des événements virtuels et met à jour les métadonnées, mais ne les applique pas
au cache catalogue. La source officielle locale ne peut donc pas alimenter un
catalogue officiel utilisable.

Décision future : faire de `Legrand Official` soit un vrai hub interne fédéré,
soit une source système locale dont les manifests sont réellement ingérés. Le
mode hybride actuel ne fournit pas une marketplace interne propre.

## Templates / Bases

Les templates officiels ne sont plus seedés dans l'orchestrateur. Les JSON sont
dans `packages/tesslate-marketplace/app/seeds/{agents,opensource_agents,bases,community_bases}.json`
et sont chargés par `packages/tesslate-marketplace/app/services/seed_loader.py`.
L'orchestrateur consomme ensuite les changements avec
`orchestrator/app/services/marketplace_sync.py`. Les anciens scripts
`scripts/seed/seed_marketplace_bases.py` et apparentés importent des modules
supprimés : ils sont obsolètes.

Un utilisateur soumet une Base via Marketplace > Browse > Bases et
`app/src/components/modals/SubmitBaseModal.tsx`; la route est
`POST /api/marketplace/bases/submit`. Il peut modifier, changer la visibilité
et supprimer depuis `app/src/pages/library/BasesPage.tsx`.

Il n'y a pas de `pending_review` pour les Bases. `private` est limité au
créateur (pas un vrai scope Team) et `public` est visible directement. Une Base
officielle provient du hub fédéré ou du CRUD administrateur, avec source
officielle et sans créateur utilisateur. Un template seedé est du contenu
d'amorçage du hub, pas un statut produit.

`app/src/components/admin/BaseManagement.tsx` et `/api/admin/bases` fournissent
CRUD, retrait/restauration et mise en avant : c'est le seul parcours UI actuel
pour ajouter localement une Base officielle sans code, mais il reste distinct
du hub fédéré qui devrait devenir source d'autorité.

## Agents

Library > Agents (`app/src/pages/library/AgentsPage.tsx`) crée, édite et retire
des Agents avec `POST /api/marketplace/agents/create` et PATCH/DELETE. Library
appelle aussi `/{id}/publish` et `/{id}/unpublish`. Publier est immédiat
(`is_published=True`, type open, source locale) : aucun modèle ou statut
`pending_review` n'existe dans le code. Les mentions documentaires sont
historiques. Il n'y a pas de point d'approbation/rejet communautaire.

Les administrateurs ont un CRUD dans l'Admin Dashboard et `/api/admin/agents`;
la création affecte la source officielle. C'est une publication directe, non
un workflow de revue.

## Skills et autres contenus

Un Skill est un `MarketplaceAgent` de type `skill`. Le frontend permet de
consulter, installer et associer (`app/src/pages/library/SkillsPage.tsx`), mais
il n'existe aucun endpoint ou écran de création, édition, partage, publication
ou dépublication utilisateur. Un administrateur ne peut pas publier un Skill
`Legrand Official` via l'UI : il faut le publier dans un hub interne/fédéré puis
le synchroniser. Il manque studio auteur, soumission, revue et publisher
officiel.

| Type | Création utilisateur | Partage/publication | Modération | Publication officielle | UI / endpoints |
| --- | --- | --- | --- | --- | --- |
| Bases | Oui | Oui, immédiate | Retrait admin seulement | CRUD admin ou hub | Oui / oui |
| Agents | Oui | Oui, immédiate | Non | CRUD admin ou hub | Oui / oui |
| Skills | Non | Non | Non | Hub seulement | Browse-install / browse-install |
| Themes | Oui | Oui, immédiate | Non | Hub / historique | Oui / oui |
| Apps | Oui | Soumission versionnée | Oui, par étapes | Pas de publisher opérateur dédié | Oui / oui |
| MCP / Connectors | Configuration personnelle | Pas de catalogue partagé | Non | Hub / historique | Oui / utilisateur-projet |
| Deployment targets | Non, comme contenu catalogue | Permissions projet | Non | Seed/code | Canvas / CRUD projet |

Themes ont création, édition, suppression, fork, publication et dépublication,
mais sans revue ni UI admin. Les connecteurs personnalisés créent un
`UserMcpConfig`, pas une entrée partageable. Les deployment targets sont des
ressources projet (`/api/projects/{slug}/deployment-targets`), non des objets
marketplace publiables.

Les Apps créent un `AppVersion` en `pending_stage1` et un `AppSubmission`, puis
passent par un workbench administrateur. Les mutations de gouvernance utilisent
un client fédéré; pour `LOCAL_SOURCE_ID` / `local://`, il n'existe pas de
branche in-process. Un hub interne ou une implémentation locale est nécessaire
avant de considérer la modération des Apps locales utilisable.

## Recommandation pour une phase ultérieure

1. **Legrand Official** : contenu administrateur dans un hub interne de
   référence, directement approuvé et audité.
2. **Community** : `draft` → `pending_review` → `approved` / `rejected`, plus
   `withdrawn` et `yanked`, avec une file de revue commune.
3. **Private / Team** : contenu non indexé avec scopes utilisateur et Team
   réels.

Stabiliser le hub officiel et son ingestion avant d'étendre le pipeline Apps
aux Bases, Agents, Themes et Skills. Décider d'abord la source d'autorité, les
droits admin/Team, les règles de promotion, la migration du contenu actuel et
le retrait/rollback. Rien de cette architecture n'est implémenté ici.
