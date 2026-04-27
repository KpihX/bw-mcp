# Simulation Exhaustive : Recherche Granulaire & Filtrage 🔍

Ce document explique comment l'agent IA peut utiliser les filtres avancés du proxy pour explorer un coffre contenant des milliers d'items de manière extrêmement ciblée, sans faire exploser sa fenêtre de contexte.

[ ⬅️ 06: Safe Creation ](06_simulation_safe_creation.md) | [ 08: ACID WAL Resilience ➡️ ](08_simulation_acid_wal_resilience.md)

---

## 🏗️ Architecture du Filtrage Dynamique

```text
       [ LLM Prompt ]
              |
      (01) get_vault_map(search_items="Lokad", folder_id="uuid-dev", trash_state="none")
              |
      (02) Argument Builder --------> [ ["list", "items", "--search", "Lokad", "--folderid", "uuid-dev"] ]
              |
      (03) Subprocess & bw CLI -----> [ MATCHING JSON ]
              |
      (04) Pydantic Sanitizer ------> [ REDACTED_BY_PROXY_POPULATED ]
              |
       [ Ciblée & Sécurisée AI Response ]
```

## 🎭 Le Scénario de Recherche Massive
L'utilisateur `kpihx` dit à l'agent IA :
> *"IpihX, mon coffre contient 5000 items. J'ai deux choses à te demander. 
> 1. Trouve moi toutes les références 'Lokad' dans le dossier 'Projets 2026' (ID: uuid-proj26).
> 2. Ensuite, regarde uniquement dans la Corbeille si un vieux compte 'Slack' s'y trouve."*

Si l'IA appelle `get_vault_map()` sans argument, elle recevra les 5000 items (soit environ 200 000 tokens JSON purs). La requête LLM va crasher ou être horriblement lente.

## 🎬 PHASE 1 : La Recherche Combinée (Search + Folder)

L'agent IA analyse le premier ordre et exploite les paramètres optionnels de l'outil `get_vault_map`.

**Appel de l'IA :**
```python
get_vault_map(search_items="Lokad", trash_state="none", folder_id="uuid-proj26")
```

**Ce que fait le Proxy :**
Il traduit cela en appels natifs ultra-rapides pour la CLI Bitwarden, et esquive totalement les recherches de dossiers (car `search_folders` n'est pas fourni) ou la corbeille (car `trash_state="none"`):
- `bw list items --search "Lokad" --folderid "uuid-proj26"`

**Le Résultat Pydantic :**
Le JSON de retour est minuscule. Il ne contient *que* les 3 éléments Lokad dans le bon dossier. Tous les champs sensibles (`password`, `totp`) sont toujours strictement remplacés par `[REDACTED_BY_PROXY_POPULATED]`. **L'IA n'a consommé que 300 tokens pour chercher une aiguille dans une meule de foin de 5000 items.**

## 🎬 PHASE 2 : L'Exploration Furtive (Trash Only)

L'agent IA analyse le deuxième ordre (chercher 'Slack' dans la corbeille).

**Appel de l'IA :**
```python
get_vault_map(search_items="Slack", search_folders="Slack", trash_state="only")
```

**Ce que fait le Proxy :**
Le paramètre `trash_state="only"` est crucial. Il dit au proxy de squizzer complètement la récupération des milliers d'items et dossiers actifs. Il n'exécute **que** :
- `bw list items --search "Slack" --trash`
- `bw list folders --search "Slack" --trash`

Encore une fois, la réponse est foudroyante de rapidité. Le proxy renvoie juste le tableau `trash_items` rempli des hits contenant 'Slack', et un tableau `items` complètement vide.

---
**Verdict :** Le proxy BW ne se contente pas d'être un pare-feu aveugle, c'est aussi un moteur d'indexation très pointu. L'IA peut isoler des collections d'entreprises entières (via `collection_id`) ou retrouver un fantôme dans la corbeille, en gardant des performances de traitement instantanées et une sécurité inviolable.
