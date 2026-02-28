# BW-Blind-Proxy: Simulation Exhaustive du Pipeline 🔬

Ce document retrace le cheminement exact d'un octet de donnée, depuis la requête en langage naturel de l'utilisateur jusqu'à la destruction finale en mémoire vive (RAM) de la clé de session cryptographique.
**Rien n'est omis. Chaque classe, chaque fonction, chaque module est détaillé dans son ordre canonique d'exécution.**

---

## 🎭 Le Scénario Initial
L'utilisateur `kpihx` ouvre son terminal et tape :
> *"IpihX, peux-tu regarder mon Bitwarden, trouver mon compte 'GitHub', le renommer en 'GitHub_Pro' et le déplacer dans mon dossier 'Dev' ?"*

L'agent IA (Claude/Gemini) lit cette phrase. Il réalise qu'il a besoin d'informations sur l'état du coffre Bitwarden. Il décide d'appeler l'outil `get_vault_map`.

---

## 🎬 PHASE 1 : Fetching Sécurisé & Sanitization

```text
 +---------+      (1) Ask       +--------------+
 | server  | -----------------> |  ui (Zenity) |
 |  (MCP)  | <----------------- |              |
 +----+----+      "Password"    +--------------+
      |
      | (2) unlock_vault("Password")
      v
 +----+----+      (3) Convert to bytearray      +-----------+
 | wrapper | ---------------------------------> |    RAM    |
 | (Python)| <--------------------------------- | [P][a][s] |
 +----+----+                                    +-----+-----+
      |                                               ^
      | (4) subprocess.run(env={"BW_PASSWORD"})       |
      v                                               |
 +----+----+                                          |
 | bw CLI  |       (6) WIPE bytearray to 0x00         |
 | (Local) | -----------------------------------------+
 +---------+
```

### 1. Entrée dans `server.py`
L'outil `@mcp.tool() get_vault_map()` est déclenché par le client MCP.
* L'outil tente de récupérer la structure du coffre. Mais le coffre est verrouillé.

### 2. L'Alerte GUI dans `ui.py`
Le code appelle `HITLManager.ask_master_password(title="Proxy Request: Read Vault Map")`.
* **Fonction exécutée :** `subprocess.run(["zenity", "--password", ...])`
* **Objectif :** Bloquer l'exécution Python et afficher une fenêtre système native à `kpihx`. L'agent IA est en attente réseau. Il ne peut rien faire.
* `kpihx` tape son mot de passe : `SuperSecret123`.
* Zenity renvoie le mot de passe via `stdout`, capturé par `result.stdout.strip()`.

### 3. Le Déverrouillage Isolant dans `subprocess_wrapper.py`
Le mot de passe retourne dans `server.py`, qui l'envoie immédiatement à `SecureSubprocessWrapper.unlock_vault("SuperSecret123")`.
* **Problème de l'OS :** Passer "SuperSecret123" en argument de commande Bash expose la chaîne à `ps aux`.
* **L'Astuce :** 
  1. On copie l'environnement Linux actuel : `env = os.environ.copy()`.
  2. On convertit le mot de passe en tableau d'octets mutables : `pw_bytes = bytearray("SuperSecret123", 'utf-8')`.
  3. On injecte ce mot de passe dans l'environnement Python cloné sous le nom `"BW_PASSWORD"`.
  4. On lance `subprocess.run(["bw", "unlock", "--passwordenv", "BW_PASSWORD", "--raw"], env=env)`. La CLI Bitwarden se sert dans l'environnement virtuel du processus Python enfant.
* **Le Résultat :** La CLI crache la clé de session éphémère (ex: `12345SESSIONKEY67890`) via `stdout`.
* **Le Nettoyage (The Scrubbing) :** Le bloc `finally` s'exécute. `env["BW_PASSWORD"]` est écrasé par `"DEADBEEF...DEADBEEF"`. La boucle Python écrase manuellement chaque case du `pw_bytes` avec des `0`. Le Garbage Collector Python n'a plus rien de compromettant à nettoyer. La mémoire est saine.

### 4. L'Interrogation de la CLI
Nous avons la session. Mais on ne donne pas tout de suite le JSON à l'IA. `server.py` appelle `SecureSubprocessWrapper.execute_json(["list", "folders"], session_key)`.
* **Entrée dans `execute()` :** On refait le coup du `bytearray` muté, mais cette fois pour injecter `"BW_SESSION"`.
* On lance `bw list folders` et `bw list items`.
* **Le Retour `execute_json()` :** On récupère des JSON bruts massifs contenant les mots de passe de `kpihx`, ses codes TOTP (2FA), ses notes de cartes bancaires.
* *Note sur le STDERR :* Si la commande foire, `execute()` intercepte `result.returncode != 0` et lève une exception générique `SecureBWError`. Le message d'erreur d'origine n'est pas transmis pour éviter qu'une erreur de la CLI n'imprime accidentellement le contenu d'une note secrète dans les logs de l'IA.

### 5. La Guillotine de Données dans `models.py`
Le JSON brut atterrit dans `server.py`. On boucle dessus avec Pydantic : `[BlindItem(**i) for i in raw_items]`.
* Prenons l'item "GitHub". Pydantic lit les données.
* Il voit la clé `password`. Mais le modèle `BlindItem` a une sous-classe `BlindLogin` qui contient un `@model_validator(mode='before')`.
* **Exécution du validateur `force_redact` :** Avant même d'initialiser l'objet, Pydantic écrase brutalement `data['password'] = "[REDACTED_BY_PROXY]"`.
* Il voit la clé mystère ajoutée hier par les développeurs de Bitwarden : `recovery_codes_v2`. Mais le modèle a la directive `model_config = ConfigDict(extra="ignore")`. La clé `recovery_codes_v2` est foudroyée en vol et n'entre pas dans l'objet.
* `BlindItem.model_dump(exclude_unset=True)` génère un dictionnaire propre. Le mot de passe (pourtant caviardé) est totalement supprimé du dictionnaire final grâce au flag `exclude=True` défini dans le Field.

### 6. Le Retour à l'IA
Le JSON purgé retourne à l'agent IA. 
Il sait maintenant que "GitHub" a l'UUID `item-001` et "Dev" a l'UUID `folder-777`. **C'est tout ce qu'il sait.**

---

## 🎬 PHASE 2 : La Logique d'Intelligence et Le Proxy Aveugle

L'agent IA analyse le prompt initial de `kpihx` et le JSON.
Il prépare un appel à l'outil `propose_vault_transaction(payload)` dans `server.py`.
* **Le Payload de l'IA :**
```json
{
  "rationale": "I will rename your GitHub account to 'GitHub_Pro' and move it to the 'Dev' folder as you requested.",
  "operations": [
    {"action": "rename", "target_id": "item-001", "new_value": "GitHub_Pro"},
    {"action": "move", "target_id": "item-001", "new_value": "folder-777"}
  ]
}
```

---

## 🎬 PHASE 3 : L'Exécution en Tranchées (Write Pipeline)

### 1. La Porte d'Entrée (`server.py` vers `transaction.py`)
`server.py` route le payload vers `TransactionManager.execute_batch()`.
* **Vérification d'intégrité :** `payload = TransactionPayload(**payload_dict)`. Pydantic vérifie que l'IA n'essaie pas d'injecter une commande bash cachée ou un champ inconnu.

### 2. La Demande de Consentement (`ui.py`)
`transaction.py` formate une longue chaîne de caractères explicative et appelle `HITLManager.review_transaction(rationale, formatted_ops)`.
* Une popup Zenity immense apparaît sur l'écran de `kpihx`.
* `kpihx` lit exactement ce que l'IA compte faire : 
  `1. RENAME on ID: item-001 (New Value: GitHub_Pro)`
  `2. MOVE on ID: item-001 (New Value: folder-777)`
* `kpihx` clique sur `OK`. Le processus Python (bloqué en fond) se débloque.
* On redemande le Master Password via `HITLManager.ask_master_password()` (pour des raisons de sécurité, le mot de passe de la phase 1 a déjà été détruit de la RAM, il faut redéverrouiller le coffre pour écrire).

### 3. La Mise à Jour Unitaire
La fonction `execute_batch` obtient une clé de session `session_key` temporaire.
Elle boucle sur les opérations : `_execute_single_action(op, session_key)`.

#### A. Le Renommage (L'astuce de l'Edit Complet)
* Bitwarden CLI ne permet pas de dire juste "Renomme ça". Il faut lui donner le JSON entier modifié.
* `_execute_single_action` appelle d'abord `SecureSubprocessWrapper.execute_json(["get", "item", "item-001"], session_key)`.
* Le Python Proxy récupère le JSON **COMPLET ET NON CENSURÉ** de GitHub (avec le vrai mot de passe en clair).
* **Attention :** Ce JSON n'est *jamais* retourné à l'IA. Il reste dans l'espace mémoire privé de `transaction.py`.
* Le script Python fait la chirurgie : `item_data["name"] = "GitHub_Pro"`.
* Le script ré-encode le JSON en string (`json.dumps`) et lance `execute(["edit", "item", "item-001", encoded_json])`. La CLI met à jour le vault chiffré.

#### B. Le Déplacement
* Même procédé. Le proxy récupère le tout dernier JSON (celui qui s'appelle maintenant "GitHub_Pro"), écrase la clé `item_data["folderId"] = "folder-777"`, et renvoie tout à la CLI via `bw edit`.

### 4. Le Grand Écrasement (Destruction de Preuves)
Les opérations s'achèvent. Le bloc `finally` dans `execute_batch` du `transaction.py` s'abat pour conclure le processus.
```python
sk_bytes = bytearray(session_key, 'utf-8')
for i in range(len(sk_bytes)):
    sk_bytes[i] = 0
del sk_bytes
del session_key
```
Encore une fois, la RAM de l'ordinateur de `kpihx` est assainie manuellement. Le bloc de mémoire où s'était logée la `BW_SESSION` ne contient désormais qu'une suite de `0x00` (des zéros binaires), rendant la rétro-ingénierie par dump mémoire post-mortem totalement inutile.

### 5. La Fin du Scénario
`transaction.py` retourne à `server.py` la phrase : *"Transaction completed successfully."*
`server.py` remonte cette phrase via le protocole MCP à l'Agent IA.

L'Agent IA te répond textuellement dans ton terminal :
> *"KpihX, j'ai terminé l'opération. J'ai renommé votre compte en 'GitHub_Pro' et je l'ai basculé dans 'Dev'."*

---
*(Fin de la Simulation. Tout s'est déroulé de façon chirurgicale, sans que l'IA ne puisse voir un seul secret, ni qu'un hacker en veille sur le port système ne puisse subtiliser la clé de session).*
