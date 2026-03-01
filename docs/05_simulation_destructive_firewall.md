# Simulation Exhaustive : Destruction & Red Alert 🚨

Ce document retrace le cheminement exact d'un octet lorsqu'une opération **destructrice** est déclenchée (ex: suppression de dossier ou de mot de passe).

[ ⬅️ 04: Extreme Edge ](04_simulation_extreme_edge.md) | [ 06: Shell Creation ➡️ ](06_simulation_safe_creation.md)

---

## 🏗️ Architecture du Destructive Firewall

```text
       [ AI Agent ]
              |
      (01) propose_transaction ----> [ TransactionManager ]
                                            |
      (02) DETECT "delete_*" ----> [ HITL RED ALERT ] ----> [ ZENITY UI ]
                                            |                      |
      (03) HUMAN APPROVAL <-----------------+ <---------- [ WARNING ICON ]
              |
      (04) MASTER PASSWORD ----> [ BW UNLOCK ] ----> (bw delete item)
```

## 🎭 Le Scénario de Danger
L'utilisateur `kpihx` dit à l'agent IA :
> *"IpihX, peux-tu faire le ménage et supprimer mon mot de passe Netflix (id: netflix-123) et carrément effacer le dossier 'Anciens Projets' (id: folder-old) ?"*

L'agent IA comprend qu'il doit utiliser l'outil `propose_vault_transaction` avec une intention de suppression.

## 🎬 PHASE 1 : La Forge du Payload Destructeur
L'agent IA crée ses payloads JSON selon les schémas stricts définis dans `propose_vault_transaction`.

> ⚠️ **Règle d'Isolation :** `delete_folder` est une opération **destructrice permanente** (hard-delete, pas de corbeille pour les dossiers) et doit toujours être envoyée seule dans son propre batch. L'agent IA envoie donc **deux appels distincts** :

**Batch 1 — Suppression de l'Item :**
```json
{
  "rationale": "Suppression du compte Netflix comme demandé.",
  "operations": [
    {
      "action": "delete_item",
      "target_id": "netflix-123"
    }
  ]
}
```

**Batch 2 — Suppression du Dossier (Batch isolé obligatoire) :**
```json
{
  "rationale": "Suppression du dossier Anciens Projets. NOTE: Bitwarden n'a pas de corbeille pour les dossiers. Cette action est un hard-delete permanent. Les items à l'intérieur retrouveront simplement leur chemin vers 'No Folder'.",
  "operations": [
    {
      "action": "delete_folder",
      "target_id": "folder-old"
    }
  ]
}
```

## 🎬 PHASE 2 : L'Interception & Le Red Alert (UI)

Le MCP reçoit chaque payload dans `TransactionManager.execute_batch()`.
Le payload est validé mathématiquement par Pydantic (`TransactionPayload(**payload_dict)`). Pydantic vérifie notamment :
- Qu'aucun champ illicite n'a été ajouté par l'IA.
- Que `delete_folder` est bien **seul** dans son batch (sinon : rejet immédiat avec message d'erreur explicite).

Ensuite, `execute_batch` appelle `HITLManager.review_transaction(payload)`.

1. **La Détection :** `ui.py` parcourt la liste des actions (`op.action`). Il détecte immédiatement la présence de `"delete_item"` ou `"delete_folder"`.
2. **Le Changement de Posture :** La variable `has_destructive` passe à `True`. Le dialogue Zenity standard bascule en mode Red Alert.
3. **L'Affichage à l'Humain :** Une énorme boîte de dialogue popup native s'ouvre sur l'écran de `kpihx`.
   * **Icône :** Warning ⚠️
   * **Titre :** *CRITICAL: Review Destructive Vault Transaction*
   * **Texte (en rouge vif) :** **⚠️ WARNING: DESTRUCTIVE OPERATIONS DETECTED**
   * **Contenu listé (Batch 2) :**
     `1. 💥 DELETE FOLDER (folder-old)`

## 🎬 PHASE 3 : Le Code Maître et L'Exécution

L'humain `kpihx`, alerté visuellement, prend le temps de réfléchir. L'interface affiche l'UUID du dossier. Il ne s'agit pas d'un banal déplacement.
Il valide en cliquant sur "OK" puis tape son Master Password.

Dans `transaction.py`, le subprocess wrapper récupère la session évanescente. La commande est exécutée :
1. `bw delete item netflix-123 --session <CLE>` *(Batch 1)*
2. `bw delete folder folder-old --session <CLE>` *(Batch 2)*

Aucun `bw restore folder` ne sera jamais tenté — cette commande n'existe pas. Puisque le dossier est toujours seul dans son batch, il n'y a aucune opération précédente à annuler si le delete lui-même échoue.

La session est instantanément convertie en zéros dans la RAM (bytearray wipe).
L'agent IA, qui était "gelé" (en attente du serveur) pendant tout ce processus, reçoit la chaîne `"Transaction completed successfully."` et annonce à l'humain que son coffre a été purgé de ses anciens éléments.

### PHASE 4: Atomicity, The Rollback Engine, and Auditing

The proxy intercepts this instruction. Because the user is manipulating two distinct entries, the proxy wraps the entire operation in a strict **ACID-compliant Virtual Vault Transaction**:

1. **Virtual Execution (RAM):** The proxy pulls the current records into isolated memory blocks. It virtually simulates assigning `favorite: false` to item A and `delete` to Item B.
2. **Write-Ahead Logging (Disk):** Recognizing that deleting an item is destructive, it mathematically deduces the reverse logic (`bw restore B` and `bw edit A`). It encrypts these commands using Fernet (AES-128-CBC + HMAC) with a key derived from the Master Password via PBKDF2 (480k iterations) and writes them to `~/.bw_blind_proxy/wal/pending_transaction.wal`.
3. **Execution & The Firewall:**
    *   The OS intercepts the subprocess. Zenity freezes the desktop.
    *   "**Do you wish to permit `antigravity` to un-favorite `Mail` and DELETE `Old Notes`?**"
    *   The human visually validates. They enter the password.
4. **Resiliency to `kill -9` / Power Outages:** If the PC crashes right after `bw edit A` finishes but *before* `bw delete B`, the system restarts. The proxy detects the encrypted WAL, re-prompts for the Master Password, decrypts it, and executes `bw edit A (revert)` backwards, restoring pristine vault integrity.
5. **Immutable Auditing:** All actions are finalized. A strict, **secret-scrubbed** JSON log (processed by `deep_scrub_payload`) is written to `~/.bw_blind_proxy/logs/`. The Human can later inspect this via the bundled Typer CLI:

```bash
# View the last 5 transactions in a rich table
uv run bw-proxy logs

# View the full JSON details of the most recent transaction
uv run bw-proxy log
```

**Audit Log — Batch 1 (delete_item) :**
```json
{
  "transaction_id": "c070d585-ba21-4b94-b065-4be725a0bb5b",
  "timestamp": "2026-02-28T09:28:00",
  "status": "SUCCESS",
  "rationale": "Suppression du compte Netflix comme demandé.",
  "operations_requested": [
    {"action": "delete_item", "target_id": "netflix-123"}
  ],
  "execution_trace": [
    "Deleted item netflix-123"
  ],
  "rollback_trace": []
}
```

**Audit Log — Batch 2 (delete_folder) :**
```json
{
  "transaction_id": "d181e696-cb32-5c05-c176-5cf836b1cc6c",
  "timestamp": "2026-02-28T09:28:05",
  "status": "SUCCESS",
  "rationale": "Suppression du dossier Anciens Projets.",
  "operations_requested": [
    {"action": "delete_folder", "target_id": "folder-old"}
  ],
  "execution_trace": [
    "Deleted folder folder-old"
  ],
  "rollback_trace": []
}
```

**Outcome:** The proxy has successfully operated as a flawless barrier. The Assistant confidently managed the organization tasks without **ever** touching or even "seeing" the plaintext passwords behind the items. And the user has a permanent audit trail.

---
**Sécurité Garantie :** L'agent IA n'a **aucune** capacité d'exécuter `bw delete` de lui-même. S'il tente d'envoyer 50 payloads de suppression discrètement, l'écran de `kpihx` sera inondé de pop-ups ⚠️ RED ALERT que seul le Master Password (connu exclusivement du cerveau humain) peut déverrouiller. En cas de la moindre incohérence technique en vol, le Moteur de Rollback annihilera silencieusement le reste de la transaction pour protéger les données.
