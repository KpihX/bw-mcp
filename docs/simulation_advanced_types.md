# Simulation Exhaustive : Types Avancés & Défense PII 🛡️

Ce document présente comment le BW-Blind-Proxy gère l'édition des types sensibles (Identity, Card) et des champs personnalisés tout en bloquant toute fuite de secret.

---

## 🎭 Le Scénario d'Édition Avancée
L'utilisateur `kpihx` dit à l'agent IA :
> *"IpihX, peux-tu mettre à jour l'Identité 'Profil Pro' (id: id-prof) pour changer mon adresse email en 'kpihx@lokad.com' ? Ensuite, ajoute un champ personnalisé 'Projet' avec la valeur 'BW-Proxy' sur cet item."*

## 🎬 PHASE 1 : L'Interprétation LLM & Le Payload

L'agent IA utilise les schémas complexes définis dans le proxy. Il sait qu'il ne doit pas renvoyer tout le JSON, juste les champs qu'il veut modifier.

```json
{
  "rationale": "Mise à jour de l'email professionnel et ajout du tag de projet selon vos instructions.",
  "operations": [
    {
      "action": "edit_item_identity",
      "target_id": "id-prof",
      "email": "kpihx@lokad.com"
    },
    {
      "action": "upsert_custom_field",
      "target_id": "id-prof",
      "name": "Projet",
      "value": "BW-Proxy",
      "type": 0
    }
  ]
}
```

## 🎬 PHASE 2 : L'Échec de l'Attaque PII (Anti-Fuite)
Imaginons qu'un prompt malicieux demande à l'IA d'intervertir le numéro de sécurité sociale dans l'identité. Si l'IA tente d'ajouter `"ssn": "123-modified"` dans le payload :

1. Pydantic intercepte l'appel via `EditItemIdentityAction`.
2. Le champ `ssn` n'est **pas** défini dans le modèle Pydantic, et `extra="forbid"` est actif.
3. Le payload est jeté aux oubliettes avec une erreur `Extra inputs are not permitted`. La modification PII est impossible.

## 🎬 PHASE 3 : L'Exécution (Le Merge Intelligent)
L'humain valide via la Zenity UI. Le mot de passe est saisi.

Dans `transaction.py`, la boucle d'exécution utilise un "Merge Intelligent" :

### 1. `edit_item_identity`
Le wrapper récupère en local (avec la session temporaire) l'OJBET COMPLET :
```json
{
  "id": "id-prof",
  "name": "Profil Pro",
  "identity": {
    "firstName": "Ivann",
    "email": "old@email.com",
    "ssn": "999-SECRET-999" // Gardé intact en RAM
  }
}
```
Le code python prend le champ du LLM (`email: kpihx@lokad.com`) et l'écrase dans le dictionnaire en RAM. **Le SSN n'est jamais touché**. Le JSON reconstitué est renvoyé à BW via `bw edit item`.

### 2. `upsert_custom_field`
Même logique. Le proxy Python vérifie si un champ "Projet" existe. S'il n'existe pas, il l'ajoute à la liste des `fields`. 
**Défense critique :** Si le LLM avait demandé d'altérer un champ caché (Type 1), le proxy Pydantic aurait refusé la requête, ou si le proxy détectait que le champ existant est de type secret, il aurait craché une erreur `CRITICAL: Cannot edit custom field... it is of secret Type 1`.

---
**Verdict :** Une IA peut réorganiser complètement une collection d'identités, annoter des cartes avec des dates d'expiration mises à jour, sans **jamais** pouvoir lire le SSN ni le CVV, et sans pouvoir les écraser par erreur.
