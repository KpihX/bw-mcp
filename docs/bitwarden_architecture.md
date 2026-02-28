# Bitwarden Vault Architecture Reference 🏗️

This document is the result of an exhaustive extraction of the Bitwarden CLI (`bw get template`) schemas. It serves as the ultimate source of truth for planning how to refactor the **BW-Blind-Proxy** to cover 100% of the non-sensitive API.

---

## 1. The Global Item Wrapper
Every secret in Bitwarden is wrapped in a generic `Item` schema regardless of its type.

```json
{
  "passwordHistory": [],      // List of previous passwords (REDACTED)
  "revisionDate": null,       // Last update timestamp
  "creationDate": null,       // Date of creation (e.g., "2024-01-01T12:00:00Z")
  "deletedDate": null,        // Present if in Trash (e.g., "2024-02-28T10:15:00Z")
  "archivedDate": null,       // Present if archived
  "organizationId": null,     // UUID of the organization if shared
  "collectionIds": null,      // List of collection UUIDs
  "folderId": "folder-123",   // UUID of parent folder (e.g., "b87...f92")
  "type": 1,                  // 1=Login, 2=SecureNote, 3=Card, 4=Identity
  "name": "GitHub Account",   // Visible item label
  "notes": "My recovery key", // SENSITIVE (Could contain secrets) -> [REDACTED]
  "favorite": true,           // Starred status
  "fields": [],               // Array of CustomField objects
  "login": { ... },           // Login details (if type 1)
  "secureNote": { ... },      // Note details (if type 2)
  "card": { ... },            // Credit Card details (if type 3)
  "identity": { ... },        // Identity details (if type 4)
  "sshKey": null,             // SSH primary key data
  "reprompt": 0               // 0=Standard, 1=Ask Master Pw before viewing
}
```

### The Custom Fields (`fields` array)
Custom fields are incredibly versatile but dangerous.
```json
{
  "name": "Security Question", // Label of the custom field
  "value": "My Pet's Name",    // The actual stored data
  "type": 0                    // 0=Text (Shown), 1=Hidden (REDACTED), 2=Boolean, 3=Linked
}
```
**Proxy Rule:** The AI can read/write `fields` where `type == 0` or `type == 2`. The AI must NEVER see the `value` of a field where `type == 1` or `type == 3` (they must be redacted like a standard password).

---

## 2. Type 1: Login
*Already implemented safely.*
```json
{
  "uris": [
    { "uri": "https://github.com/login", "match": null } 
  ],
  "username": "kpihx-x24",     // Visible to AI
  "password": "secret_pw_123", // SENSITIVE -> [REDACTED]
  "totp": "6-digit-seed-base32",// SENSITIVE -> [REDACTED]
  "fido2Credentials": []
}
```

---

## 3. Type 2: Secure Note
```json
{
  "type": 0 // Generic Note Type identifier
}
```
**Proxy Rule:** A `SecureNote` item has its entire value stored in the global `notes` field of the Item wrapper. Since we redact `notes` globally by default, an AI sees a SecureNote merely as a title (e.g., "WiFi Codes"). We CANNOT let the AI edit notes.

---

## 4. Type 3: Card (Credit/Debit)
```json
{
  "cardholderName": "I. Harold K. P.", // Holder name
  "brand": "visa",            // Brand (e.g., "mastercard", "amex")
  "number": "4000123456789010",// SENSITIVE -> [REDACTED]
  "expMonth": "12",           // Expiry Month (Visible to AI)
  "expYear": "2028",          // Expiry Year (Visible to AI)
  "code": "555"               // SENSITIVE (CVV) -> [REDACTED]
}
```
**Proxy Rule:** To support Cards, we must explicitly redact `number` and `code`. The AI can only read/edit `cardholderName`, `brand`, `expMonth`, and `expYear`.

---

## 5. Type 4: Identity
Identities contain personal identifiable information (PII). In an ultra-secure environment, elements like SSN or Passport form must be safeguarded.
```json
{
  "title": "Mr",
  "firstName": "Ivann",
  "middleName": "Harold",
  "lastName": "Kamdem",
  "address1": "Rue de l'Ecole Polytechnique",
  "address2": "Bâtiment X24",
  "address3": null,
  "city": "Palaiseau",
  "state": "IDF",
  "postalCode": "91120",
  "country": "FR",
  "company": "Lokad",
  "email": "kpihx@lokad.com",
  "phone": "+33612345678",
  "ssn": "1234567890123",      // SENSITIVE -> [REDACTED]
  "username": "kpihx",
  "passportNumber": "FRA-555", // SENSITIVE -> [REDACTED]
  "licenseNumber": "LIC-999"   // SENSITIVE -> [REDACTED]
}
```
**Proxy Rule:** The proxy will redact `ssn`, `passportNumber`, and `licenseNumber`. The AI can read and edit the standard address and contact info.

---

## 6. Advanced Edge Features (Trash, Collections, Attachments, Send)

Through exhaustive CLI validation (`bw --help`, web research), here is the absolute boundary of the Bitwarden architecture:

1. **The Trash (`bw list items --trash`, `bw restore`)** : Items deleted are sent to the Trash for 30 days. We CAN restore them.
2. **Organizations and Collections (`bw list collections`, `bw move <id> <orgId>`)** : For enterprise/family accounts, items belong to Collections. The AI currently only manages personal `folders`. 
3. **Attachments (`bw create attachment`, `bw delete attachment`)** : Physical files attached to secrets.
4. **Bitwarden Sends (`bw send`)** : Ephemeral text/files sharing.
5. **Master Password Reprompt (`reprompt`: 0/1)** : Forces the app to ask for the master password when accessing an item.

---

## 7. Project Adjustment (The Final API Coverage)
To make **BW-Blind-Proxy** exhaustively complete, we must implement these adjustments:

1. **Schema Refactoring (`models.py`)**:
   - Create `BlindCard` (redacts number, code).
   - Create `BlindIdentity` (redacts ssn, passport, license).
   - Create `BlindField` (redacts `value` if target is hidden/linked).
   - Update `BlindItem` to include `card`, `identity`, `secureNote` and `fields`.

2. **Transaction Refactoring (`models.py` & `transaction.py`)**:
   - Add action `toggle_favorite` (target_id, boolean).
   - Add action `edit_item_card` (allows changing expiry date, name).
   - Add action `edit_item_identity` (allows changing address/email).
   - Add action `upsert_custom_field` (allows adding/modifying Text/Boolean fields safely without erasing existing hidden fields). 

3. **Phase 4 "The Extreme Edge" (FULLY IMPLEMENTED)**:
   - Added `ItemAction.RESTORE` (Trash recovery).
   - Added `ItemAction.DELETE_ATTACHMENT` (Attachment purging).
   - Added `ItemAction.MOVE_TO_COLLECTION` (Enterprise sharing).
   - Added `ItemAction.TOGGLE_REPROMPT` (Master Password reprompt flag).

This design guarantees that *every single non-sensitive lever* in Bitwarden is directly, explicitly, and securely accessible by the LLM via Pydantic Enums, while not a single cryptographic or PII secret can ever leak.
