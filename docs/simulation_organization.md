# Simulation Exhaustive : Organisation Complexe & Création 📂

Ce document détaille comment le proxy gère une réorganisation massive du coffre en utilisant la polyvalence de l'outil `propose_vault_transaction`.

---

## 🎭 Le Scénario d'Organisation
L'utilisateur `kpihx` dit à l'agent IA :
> *"IpihX, crée un dossier 'Cloud Providers'. Ensuite, renomme le compte 'Amazon Web Serv' en 'AWS Root', change son URL en 'console.aws.amazon.com' mais ne touche surtout pas au mot de passe.*

## 🎬 PHASE 1 : La Construction du Payload Polymorphe
L'agent IA comprend qu'il a besoin de plusieurs atomes d'action différents : `create_folder`, `rename_item`, `edit_item_login`.

```json
{
  "rationale": "Création du dossier Cloud Providers, renommage du compte AWS et mise à jour de son URI.",
  "operations": [
    {
      "action": "create_folder",
      "name": "Cloud Providers"
    },
    {
      "action": "rename_item",
      "target_id": "aws-item-123",
      "new_name": "AWS Root"
    },
    {
      "action": "edit_item_login",
      "target_id": "aws-item-123",
      "uris": [{"match": null, "uri": "https://console.aws.amazon.com"}]
    }
  ]
}
```

## 🎬 PHASE 2 : L'Échec de l'Attaque (Anti-Sabotage)
Imaginons que l'AI hallucine ou soit malicieuse, et tente d'ajouter un champ "password" dans le bloc `edit_item_login` pour verrouiller kpihx hors de son compte `AWS Root`.

1. **La Frappe de Pydantic :** La liste `operations` est scannée par `models.TransactionPayload`.
2. Le validateur de la classe `EditItemLoginAction` utilise `ConfigDict(extra="forbid")`.
3. Pydantic lève une exception ultra-critique `ValidationError: Extra inputs are not permitted`.
4. Le bloc est immédiatement rejeté, aucune UI n'apparaît, l'agent IA reçoit l'Erreur de Validation Proxy et la transaction est annulée.

## 🎬 PHASE 3 : L'Exécution Légitime de la Séquence (Transaction Sécurisée)
Si le payload est parfaitement propre (comme dans l'exemple initial), la Zenity UI se lève, affiche les 3 opérations. kpihx valide et tape le mot de passe maître.

Dans `transaction.py`, la boucle d'exécution commence :

### 1. `create_folder`
* Le Python Wrapper exécute `bw get template folder` pour obtenir la signature JSON exacte d'un dossier Bitwarden vierge.
* Il injecte `"name": "Cloud Providers"` dans le JSON.
* Il injecte le tout : `bw create folder '{"name":"Cloud Providers"}'`.

### 2. `rename_item`
* Le Wrapper exécute `bw get item aws-item-123`.
* Récupère le JSON **complet** (avec le mot de passe secret).
* Modifie uniquement le `"name": "AWS Root"`.
* Exécute `bw edit item aws-item-123 <JSON_COMPLET>`. La donnée secrète est protégée car elle fait un simple aller-retour dans l'OS sans jamais sortir côté Agent.

### 3. `edit_item_login`
* Le Wrapper récupère à nouveau le JSON complet d'`aws-item-123` fraîchement renommé.
* S'assure de l'existence de la clé `login`.
* Met à jour la liste des `"uris"`.
* Laisse *"password"* et *"totp"* absolument intacts.
* Pousse vers `bw edit item aws-item-123 <JSON_COMPLET>`.

Là encore, tout est fini. Tous les mots de passe intermédiaires, les `session_key` et les UUID ont été manipulés puis essuyés de la RAM. L'Agent IA reçoit la confirmation. Le coffre The Bitwarden est immaculé.
