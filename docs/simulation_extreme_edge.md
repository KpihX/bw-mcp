# Simulation Exhaustive : L’Extrême Frontière (Phase 4) 🌌

Ce document illustre comment le BW-Blind-Proxy gère les opérations les plus spécialisées et rares de Bitwarden : la gestion de la Corbeille, le transfert vers les Organisations (Entreprise), la suppression de pièces jointes, et l'exigence de Reprompt du Master Password.

---

## 🎭 Le Scénario de Sécurité Maximale
L'utilisateur `kpihx` dit à l'agent IA :
> *"IpihX, j'ai fait une erreur, restaure le compte 'Projet Alpha' de la corbeille. Ensuite, déplace ce compte vers l'Organisation Lokad (id: org-lokad), active la demande de Master Password à chaque consultation, et supprime la pièce jointe 'vieux-logo.png' (id: att-55) qui ne sert plus à rien."*

## 🎬 PHASE 1 : La Forge du Payload (Enums)

L'agent IA utilise les 15 actions strictes dérivées de `ItemAction` pour forger son JSON.

```json
{
  "rationale": "Restauration, transfert vers Lokad, sécurisation par Reprompt et nettoyage de la pièce jointe.",
  "operations": [
    {
      "action": "restore_item",
      "target_id": "projet-alpha-id"
    },
    {
      "action": "move_to_collection",
      "target_id": "projet-alpha-id",
      "organization_id": "org-lokad"
    },
    {
      "action": "toggle_reprompt",
      "target_id": "projet-alpha-id",
      "reprompt": true
    },
    {
      "action": "delete_attachment",
      "target_id": "projet-alpha-id",
      "attachment_id": "att-55"
    }
  ]
}
```

## 🎬 PHASE 2 : L'Alerte Destructrice Partielle

Lorsque le payload passe dans `ui.py`, le système repère l'action `"delete_attachment"`.
Bien qu'il ne s'agisse pas de supprimer un item entier, supprimer un fichier est **irréversible**.

1. La Zenity UI s'affiche en mode **⚠️ RED ALERT**.
2. Le texte indique :
   `1. ♻️ RESTORE ITEM (projet-alpha-id) -> From Trash`
   `2. 🏢 MOVE TO ORG (projet-alpha-id) -> Organization 'org-lokad'`
   `3. 🛡️ REPROMPT (projet-alpha-id) -> 🔒 ENABLED`
   `4. 💥 DELETE ATTACHMENT (att-55) -> from Item 'projet-alpha-id'`

L'utilisateur voit clairement la destruction du fichier. Il valide et insère son Master Password.

## 🎬 PHASE 3 : L'Exécution Polyvalente (Transaction)

Dans `transaction.py`, la session éphémère est activée. La boucle `_execute_single_action` se met en marche et route chaque Enum vers sa fonction Bash correspondante :

### 1. `ItemAction.RESTORE`
* Commande Bash : `bw restore item projet-alpha-id`
* L'item sort instantanément de la corbeille.

### 2. `ItemAction.MOVE_TO_COLLECTION`
* Commande Bash : `bw move projet-alpha-id org-lokad`
* L'item quitte le coffre personnel de `kpihx` pour rejoindre le coffre partagé de l'organisation Entreprise.

### 3. `ItemAction.TOGGLE_REPROMPT`
* Le proxy fait un `bw get item projet-alpha-id`.
* Il télécharge la structure JSON non-censurée en mémoire RAM locale.
* Il cible spécifiquement la clé `"reprompt"` et la passe de `0` à `1`.
* Il renvoie le JSON avec `bw edit item projet-alpha-id <JSON>`.
* **Résultat :** Désormais, même si kpihx est connecté à l'extension navigateur Bitwarden, cliquer sur cet item lui demandera de retaper son mot de passe. C'est le plus haut niveau de paranoïa disponible dans BW.

### 4. `ItemAction.DELETE_ATTACHMENT`
* Commande Bash : `bw delete attachment att-55 --itemid projet-alpha-id`
* Le fichier `vieux-logo.png` est définitivement pulvérisé des serveurs Bitwarden.

---
**Conclusion :** L'agent IA a piloté les couches les plus profondes et sécurisées de la plateforme Bitwarden (Corbeille, Enterprise, Master Reprompt) sans **jamais** connaître le mot de passe de "Projet Alpha". La flexibilité est totale. La sécurité est inviolable.
