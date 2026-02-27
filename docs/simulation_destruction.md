# Simulation Exhaustive : Destruction & Red Alert 🚨

Ce document retrace le cheminement exact d'un octet lorsqu'une opération **destructrice** est déclenchée (ex: suppression de dossier ou de mot de passe).

---

## 🎭 Le Scénario de Danger
L'utilisateur `kpihx` dit à l'agent IA :
> *"IpihX, peux-tu faire le ménage et supprimer mon mot de passe Netflix (id: netflix-123) et carrément effacer le dossier 'Anciens Projets' (id: folder-old) ?"*

L'agent IA comprend qu'il doit utiliser l'outil `propose_vault_transaction` avec une intention de suppression.

## 🎬 PHASE 1 : La Forge du Payload Destructeur
L'agent IA crée son payload JSON selon les schémas stricts définis dans `propose_vault_transaction`.

```json
{
  "rationale": "Suppression du compte Netflix et du dossier Anciens Projets comme demandé.",
  "operations": [
    {
      "action": "delete_item",
      "target_id": "netflix-123"
    },
    {
      "action": "delete_folder",
      "target_id": "folder-old"
    }
  ]
}
```

## 🎬 PHASE 2 : L'Interception & Le Red Alert (UI)

Le MCP reçoit le payload dans `TransactionManager.execute_batch()`.
Le payload est validé mathématiquement par Pydantic (`TransactionPayload(**payload_dict)`). Pydantic vérifie qu'aucun champ illicite n'a été ajouté par l'IA.

Ensuite, `execute_batch` appelle `HITLManager.review_transaction(payload)`.

1. **La Détection :** `ui.py` parcourt la liste des actions (`op.action`). Il détecte immédiatement la présence de `"delete_item"` et `"delete_folder"`.
2. **Le Changement de Posture :** La variable `has_destructive` passe à `True`. Le dialogue Zenity standard bascule en mode Red Alert.
3. **L'Affichage à l'Humain :** Une énorme boîte de dialogue popup native s'ouvre sur l'écran de `kpihx`.
   * **Icône :** Warning ⚠️
   * **Titre :** *CRITICAL: Review Destructive Vault Transaction*
   * **Texte (en rouge vif) :** **⚠️ WARNING: DESTRUCTIVE OPERATIONS DETECTED**
   * **Contenu listé :**
     `1. 💥 DELETE ITEM (netflix-123)`
     `2. 💥 DELETE FOLDER (folder-old)`

## 🎬 PHASE 3 : Le Code Maître et L'Exécution Irréversible

L'humain `kpihx`, alerté visuellement, prend le temps de réfléchir. L'interface affiche l'UUID du dossier et l'item. Il ne s'agit pas d'un banal déplacement.
Il valide en cliquant sur "OK" puis tape son Master Password.

Dans `transaction.py`, le subprocess wrapper récupère la session évanescente. Les commandes sont exécutées de manière ciblée :
1. `bw delete item netflix-123 --session <CLE>`
2. `bw delete folder folder-old --session <CLE>`

La session est instantanément convertie en zéros dans la RAM (bytearray wipe).
L'agent IA, qui était "gelé" (en attente du serveur) pendant tout ce processus, reçoit la chaîne `"Transaction completed successfully."` et annonce à l'humain que son coffre a été purgé de ses anciens éléments.

---
**Sécurité Garantie :** L'agent IA n'a **aucune** capacité d'exécuter `bw delete` de lui-même. S'il tente d'envoyer 50 payloads de suppression discrètement, l'écran de `kpihx` sera inondé de pop-ups ⚠️ RED ALERT que seul le Master Password (connu exclusivement du cerveau humain) peut déverrouiller.
