# Simulation Exhaustive : La Création Sécurisée ("Shell Item") 🐚

Ce document explique comment l'IA peut structurer et proposer la création d'un tout nouvel élément, sans jamais connaître ou inscrire les données réelles de sécurité (mots de passe, CVV, numéros de sécurité sociale).

[ ⬅️ 05: Destructive Firewall ](05_simulation_destructive_firewall.md) | [ 07: Advanced Search ➡️ ](07_simulation_advanced_search.md)

---

## 🏗️ Architecture du Créateur "Air-Gapped"

```text
       [ LLM Payload ]                     [ Pydantic Models ]
              |                                     |
      (01) ACTION: CREATE ---------------+          |
              |                          |          |
      (02) 'password': 'my-hacked-pw' ---+-------> (❌ ValidationError: extra="forbid")
                                         |
                                         | (If pure shell)
                                         v
                                  [ BW SUBPROCESS ]
                                         |
      (03) Fetch empty template <--- (bw get template item.*)
                                         |
      (04) Inject public metadata 
           (username, URL, name)
                                         |
      (05) Execute safely ---------> (bw create item)
```

## 🎭 Le Scénario de Création
L'utilisateur `kpihx` dit à l'agent :
> *"IpihX, je viens de m'inscrire sur Mistral AI. Crée un nouveau Login pour Mistral dans le dossier 'AI' avec mon email habituel 'kpihx@foo.com'. Je remplirai le vrai mot de passe moi-même plus tard."*

### ⚠️ Le Piège de l'Hallucination (Action Bloquée)
Imaginons que l'IA, par excès de zèle ou hallucination, essaie de générer elle-même un mot de passe sécurisé :

```json
{
  "rationale": "Création du login Mistral AI",
  "operations": [
    {
      "action": "create_item",
      "type": 1,
      "name": "Mistral AI",
      "login": {
        "username": "kpihx@foo.com",
        "password": "Super_Strong_Random_Password_123!" 
      }
    }
  ]
}
```

Le pare-feu Pydantic `CreateLoginPayload` fonctionne en mode strict `ConfigDict(extra="forbid")`. Il n'autorise QUE `username` et `uris`. L'ajout de `"password"` fait **exploser** la validation Python :

`ValidationError: 1 validation error for TransactionPayload... Extra inputs are not permitted`

L'IA réagit à cette erreur et comprend qu'elle ne peut pas toucher aux champs secrets.

### ✅ La Bonne Méthode (La Coquille Vide)

L'IA renvoie un payload sans aucun champ interdit :

```json
{
  "rationale": "Création de la coquille vide pour Mistral AI",
  "operations": [
    {
      "action": "create_item",
      "type": 1,
      "name": "Mistral AI",
      "folder_id": "ai-folder-uuid",
      "login": {
        "username": "kpihx@foo.com",
        "uris": [{"match": null, "uri": "https://console.mistral.ai"}]
      }
    }
  ]
}
```

## 🎬 L'Exécution Polyvalente (Transaction)

Dans `transaction.py`, le proxy procède à l'assemblage :
1. Il génère via `bw` un modèle vierge en mémoire : `{"type": 1, "name": "Mistral AI", "notes": null...}`.
2. Il télécharge le modèle interne de Login : `{"username": "kpihx@foo.com", "password": null, "totp": null}`.
3. Il exécute discrètement `bw create item <JSON_ASSEMBLE>`.

**Conclusion :** L'élément "Mistral AI" est apparu dans Bitwarden. Il ne reste plus qu'à kpihx de cliquer sur "Edit" dans son application native et d'y générer son mot de passe. L'IA a fourni tout le travail fastidieux d'organisation, mais n'a eu aucun accès au coffre-fort secret en lui-même.
