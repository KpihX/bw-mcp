# Bitwarden Vault Architecture Reference 🏗️

This document is the result of an exhaustive extraction of the Bitwarden CLI (`bw get template`) schemas. It serves as the ultimate source of truth for planning how to refactor the **BW-Blind-Proxy** to cover 100% of the non-sensitive API.

---

## 1. The Global Item Wrapper
Every secret in Bitwarden is wrapped in a generic `Item` schema regardless of its type.

```json
{
  "passwordHistory": [],
  "revisionDate": null,
  "creationDate": null,
  "deletedDate": null,
  "archivedDate": null,
  "organizationId": null,
  "collectionIds": null,
  "folderId": null,
  "type": 1, // 1=Login, 2=SecureNote, 3=Card, 4=Identity
  "name": "Item name",
  "notes": "Some notes about this item.", // SENSITIVE (Could contain secrets)
  "favorite": false,
  "fields": [], // CUSTOM FIELDS ARRAY
  "login": null, // Present if type==1
  "secureNote": null, // Present if type==2
  "card": null, // Present if type==3
  "identity": null, // Present if type==4
  "sshKey": null,
  "reprompt": 0 // 0=No, 1=Ask Master Password explicitly on view
}
```

### The Custom Fields (`fields` array)
Custom fields are incredibly versatile but dangerous.
```json
{
  "name": "Field name",
  "value": "Some value",
  "type": 0 // 0=Text, 1=Hidden (SENSITIVE), 2=Boolean, 3=Linked (SENSITIVE)
}
```
**Proxy Rule:** The AI can read/write `fields` where `type == 0` or `type == 2`. The AI must NEVER see the `value` of a field where `type == 1` or `type == 3` (they must be redacted like a standard password).

---

## 2. Type 1: Login
*Already implemented safely.*
```json
{
  "uris": [],
  "username": "jdoe",
  "password": "myp@ssword123", // SENSITIVE
  "totp": "JBSWY3DPEHPK3PXP", // SENSITIVE
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
  "cardholderName": "John Doe",
  "brand": "visa",
  "number": "4242424242424242", // SENSITIVE
  "expMonth": "04",
  "expYear": "2023",
  "code": "123" // SENSITIVE (CVV)
}
```
**Proxy Rule:** To support Cards, we must explicitly redact `number` and `code`. The AI can only read/edit `cardholderName`, `brand`, `expMonth`, and `expYear`.

---

## 5. Type 4: Identity
Identities contain personal identifiable information (PII). In an ultra-secure environment, elements like SSN or Passport form must be safeguarded.
```json
{
  "title": "Mr",
  "firstName": "John",
  "middleName": "William",
  "lastName": "Doe",
  "address1": "123 Any St",
  "address2": "Apt #123",
  "address3": null,
  "city": "New York",
  "state": "NY",
  "postalCode": "10001",
  "country": "US",
  "company": "Acme Inc.",
  "email": "john@company.com",
  "phone": "5555551234",
  "ssn": "000-123-4567", // SENSITIVE
  "username": "jdoe",
  "passportNumber": "US-123456789", // SENSITIVE
  "licenseNumber": "D123-12-123-12333" // SENSITIVE
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
