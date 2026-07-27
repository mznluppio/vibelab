# Assist to Build — plan MVP

## Audit et décision

Le chat projet dispose déjà d'un transport de pause/reprise :
`PendingUserInputManager`, le tool `request_review`, l'événement SSE
`approval_required`, l'endpoint générique `POST /api/chat/agent/approval` et
la carte `BuilderReviewCard`. Les réponses arrivent au même worker via Redis,
ce qui permet de reprendre le run sans nouvelle API, table ou système
d'approbation.

Le `ToolRegistry` applique déjà ses contrôles avant chaque exécution. Son mode
`plan` laisse cependant `bash_exec` disponible : il ne protège donc pas ce
workflow à lui seul. La garde Assist to Build sera placée avant ce contrôle et
refusera tous les outils mutatifs jusqu'à l'approbation TO-BE, y compris si le
client demande `edit_mode=allow`.

Les messages et leurs métadonnées JSON portent déjà les états de tâche et les
étapes de l'agent. Le workflow y conservera son étape, ses checkpoints et les
approbations ; aucune migration n'est requise.

## Plan d'implémentation

1. Ajouter l'agent officiel `assist-to-build` aux seeds du hub local avec un
   prompt de Discovery, AS-IS, TO-BE et Build qui appelle le checkpoint déjà
   existant.
2. Étendre le tool de revue existant d'un `kind=assist_to_build_review` et
   d'un `stage` (`as_is`/`to_be`), persister son payload dans les métadonnées
   du message, puis appliquer la garde de tools dans le registre.
3. Généraliser `BuilderReviewCard` pour afficher le résumé Markdown, Mermaid
   (avec fallback texte), hypothèses, risques et exigences, en conservant le
   même endpoint de réponse.
4. Ajouter des tests backend/frontend couvrant les deux gates, le refus des
   tools mutatifs et le rendu/fallback Mermaid, puis valider le parcours avec
   les mécanismes de chat existants.

## Limite du prototype

Le parcours est volontairement fixe à deux revues. Il n'ajoute ni moteur de
workflow configurable, ni approbation générique supplémentaire, ni éditeur de
diagrammes.
