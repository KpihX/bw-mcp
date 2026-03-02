from enum import StrEnum
from typing import List, Optional, Any, Dict, Literal, Union, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator
from bw_mcp.config import REDACTED_POPULATED, REDACTED_EMPTY, MAX_BATCH_SIZE

# -----------------
# ACTION ENUMERATIONS (CENTRALIZATION)
# -----------------

class ItemAction(StrEnum):
    CREATE = "create_item"
    RENAME = "rename_item"
    MOVE_TO_FOLDER = "move_item"
    DELETE = "delete_item"
    RESTORE = "restore_item"            # Phase 4 Edge
    FAVORITE = "favorite_item"
    MOVE_TO_COLLECTION = "move_to_collection" # Phase 4 Edge
    TOGGLE_REPROMPT = "toggle_reprompt"      # Phase 4 Edge
    DELETE_ATTACHMENT = "delete_attachment"  # Phase 4 Edge

class FolderAction(StrEnum):
    CREATE = "create_folder"
    RENAME = "rename_folder"
    DELETE = "delete_folder"
    # NOTE: restore_folder does NOT exist in the Bitwarden CLI.
    # Folders are hard-deleted (no trash). Removing a folder also clears
    # the folderId of all items inside, making rollback architecturally
    # unsolvable without pre-deletion snapshots. delete_folder is therefore
    # enforced to run as a standalone transaction (like delete_attachment).

class EditAction(StrEnum):
    LOGIN = "edit_item_login"
    CARD = "edit_item_card"
    IDENTITY = "edit_item_identity"
    CUSTOM_FIELD = "upsert_custom_field"

class TransactionStatus(StrEnum):
    SUCCESS = "SUCCESS"                            # Batch finished perfectly
    ROLLBACK_TRIGGERED = "ROLLBACK_TRIGGERED"      # Error caught, starting reversal
    ROLLBACK_SUCCESS = "ROLLBACK_SUCCESS"          # Error caught and vault restored to pristine state
    ROLLBACK_FAILED = "ROLLBACK_FAILED"            # CRITICAL: Both execution and recovery failed
    CRASH_RECOVERED_ON_BOOT = "CRASH_RECOVERED_ON_BOOT"  # Found and cleared an orphan WAL file
    ABORTED = "ABORTED"                            # Human cancelled the Zenity prompt


# -----------------
# DATA FETCH MODELS (Sanitized Views)
# -----------------

class BlindLogin(BaseModel):
    """Login schema that strictly ignores passwords and TOTP secrets."""
    model_config = ConfigDict(extra="ignore")  
    
    username: Optional[str] = None
    uris: Optional[List[Dict[str, Any]]] = None
    
    password: Optional[str] = Field(default=REDACTED_EMPTY)
    totp: Optional[str] = Field(default=REDACTED_EMPTY)

    @model_validator(mode='before')
    @classmethod
    def force_redact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'password' in data: 
                data['password'] = REDACTED_POPULATED if data['password'] else REDACTED_EMPTY
            if 'totp' in data: 
                data['totp'] = REDACTED_POPULATED if data['totp'] else REDACTED_EMPTY
        return data

class BlindCard(BaseModel):
    """Card schema that protects credit card numbers and CVV codes."""
    model_config = ConfigDict(extra="ignore")
    
    cardholderName: Optional[str] = None
    brand: Optional[str] = None
    expMonth: Optional[str] = None
    expYear: Optional[str] = None
    
    number: Optional[str] = Field(default=REDACTED_EMPTY)
    code: Optional[str] = Field(default=REDACTED_EMPTY)
    
    @model_validator(mode='before')
    @classmethod
    def force_redact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'number' in data: 
                data['number'] = REDACTED_POPULATED if data['number'] else REDACTED_EMPTY
            if 'code' in data: 
                data['code'] = REDACTED_POPULATED if data['code'] else REDACTED_EMPTY
        return data

class BlindIdentity(BaseModel):
    """Identity schema that protects critical PII (SSN, Passport, License)."""
    model_config = ConfigDict(extra="ignore")
    
    title: Optional[str] = None
    firstName: Optional[str] = None
    middleName: Optional[str] = None
    lastName: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None
    address3: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postalCode: Optional[str] = None
    country: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    username: Optional[str] = None
    
    ssn: Optional[str] = Field(default=REDACTED_EMPTY)
    passportNumber: Optional[str] = Field(default=REDACTED_EMPTY)
    licenseNumber: Optional[str] = Field(default=REDACTED_EMPTY)
    
    @model_validator(mode='before')
    @classmethod
    def force_redact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'ssn' in data: 
                data['ssn'] = REDACTED_POPULATED if data['ssn'] else REDACTED_EMPTY
            if 'passportNumber' in data: 
                data['passportNumber'] = REDACTED_POPULATED if data['passportNumber'] else REDACTED_EMPTY
            if 'licenseNumber' in data: 
                data['licenseNumber'] = REDACTED_POPULATED if data['licenseNumber'] else REDACTED_EMPTY
        return data

class BlindField(BaseModel):
    """Custom Field schema. Redacts value if it is Hidden (1) or Linked (3)."""
    model_config = ConfigDict(extra="ignore")
    
    name: str
    type: int
    value: Optional[str] = None
    
    @model_validator(mode='before')
    @classmethod
    def safe_value(cls, data: Any) -> Any:
        if isinstance(data, dict):
            f_type = data.get("type", 0)
            if f_type in [1, 3]:  # Hidden or Linked are secrets.
                data["value"] = REDACTED_POPULATED if data.get("value") else REDACTED_EMPTY
        return data

class BlindItem(BaseModel):
    """
    Strict representation of a Bitwarden Item for the LLM context.
    Covers all 4 types (Login, SecureNote, Card, Identity) and Custom Fields.
    SecureNotes are automatically handled by the fact that we redact the 'notes' field.
    """
    model_config = ConfigDict(extra="ignore")
    
    id: Optional[str] = None
    organizationId: Optional[str] = None
    folderId: Optional[str] = None
    type: int
    name: str
    favorite: bool = False
    reprompt: int = 0
    notes: Optional[str] = Field(default=REDACTED_EMPTY)
    
    @model_validator(mode='before')
    @classmethod
    def force_redact_notes(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'notes' in data:
                data['notes'] = REDACTED_POPULATED if data['notes'] else REDACTED_EMPTY
        return data
    
    fields: Optional[List[BlindField]] = None
    login: Optional[BlindLogin] = None
    card: Optional[BlindCard] = None
    identity: Optional[BlindIdentity] = None
    secureNote: Optional[Dict[str, Any]] = None # Always empty in pure BW API anyway

class BlindFolder(BaseModel):
    """Strict representation of a Bitwarden Folder."""
    model_config = ConfigDict(extra="ignore")
    
    id: Optional[str] = None
    name: str

class BlindOrganization(BaseModel):
    """Strict representation of a Bitwarden Organization."""
    model_config = ConfigDict(extra="ignore")
    
    id: Optional[str] = None
    name: str

class BlindOrganizationCollection(BaseModel):
    """Strict representation of an Organization Collection."""
    model_config = ConfigDict(extra="ignore")
    
    id: str
    organizationId: str
    name: str
    externalId: Optional[str] = None


# -----------------
# TRANSACTION MODELS (POLYMORPHIC ACTIONS)
# -----------------

class BaseAction(BaseModel):
    """Base for all atomic actions. Rejects any undocumented field."""
    model_config = ConfigDict(extra="forbid") 
    action: str

# --- ITEM ACTIONS ---
class CreateLoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Optional[str] = None
    uris: Optional[List[Dict[str, str]]] = None

class CreateCardPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cardholderName: Optional[str] = None
    brand: Optional[str] = None
    expMonth: Optional[str] = None
    expYear: Optional[str] = None

class CreateIdentityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    firstName: Optional[str] = None
    middleName: Optional[str] = None
    lastName: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None
    address3: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postalCode: Optional[str] = None
    country: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    username: Optional[str] = None

class CreateItemAction(BaseAction):
    """
    Creates a new empty shell item. 
    Any attempt to pass 'password', 'totp', 'ssn', 'number', 'code' etc. 
    will trigger a Pydantic ValidationError because of extra="forbid".
    """
    action: Literal[ItemAction.CREATE] = ItemAction.CREATE
    type: Literal[1, 2, 3, 4] = Field(description="1: Login, 2: SecureNote, 3: Card, 4: Identity")
    name: str
    folder_id: Optional[str] = None
    organization_id: Optional[str] = None
    favorite: bool = False
    
    login: Optional[CreateLoginPayload] = None
    card: Optional[CreateCardPayload] = None
    identity: Optional[CreateIdentityPayload] = None

class RenameItemAction(BaseAction):
    action: Literal[ItemAction.RENAME] = ItemAction.RENAME
    target_id: str
    new_name: str

class MoveItemAction(BaseAction):
    action: Literal[ItemAction.MOVE_TO_FOLDER] = ItemAction.MOVE_TO_FOLDER
    target_id: str
    folder_id: Optional[str] = Field(description="UUID of the destination folder, or None to move to root.")

class DeleteItemAction(BaseAction):
    action: Literal[ItemAction.DELETE] = ItemAction.DELETE
    target_id: str

class RestoreItemAction(BaseAction):
    action: Literal[ItemAction.RESTORE] = ItemAction.RESTORE
    target_id: str

class FavoriteItemAction(BaseAction):
    action: Literal[ItemAction.FAVORITE] = ItemAction.FAVORITE
    target_id: str
    favorite: bool

class MoveToCollectionAction(BaseAction):
    action: Literal[ItemAction.MOVE_TO_COLLECTION] = ItemAction.MOVE_TO_COLLECTION
    target_id: str
    organization_id: str

class ToggleRepromptAction(BaseAction):
    action: Literal[ItemAction.TOGGLE_REPROMPT] = ItemAction.TOGGLE_REPROMPT
    target_id: str
    reprompt: bool

class DeleteAttachmentAction(BaseAction):
    action: Literal[ItemAction.DELETE_ATTACHMENT] = ItemAction.DELETE_ATTACHMENT
    target_id: str
    attachment_id: str

# --- FOLDER ACTIONS ---
class CreateFolderAction(BaseAction):
    action: Literal[FolderAction.CREATE] = FolderAction.CREATE
    name: str

class RenameFolderAction(BaseAction):
    action: Literal[FolderAction.RENAME] = FolderAction.RENAME
    target_id: str
    new_name: str

class DeleteFolderAction(BaseAction):
    action: Literal[FolderAction.DELETE] = FolderAction.DELETE
    target_id: str

# --- EDIT ACTIONS ---
class EditItemLoginAction(BaseAction):
    action: Literal[EditAction.LOGIN] = EditAction.LOGIN
    target_id: str
    username: Optional[str] = None
    uris: Optional[List[Dict[str, str]]] = None
    
class EditItemCardAction(BaseAction):
    action: Literal[EditAction.CARD] = EditAction.CARD
    target_id: str
    cardholderName: Optional[str] = None
    brand: Optional[str] = None
    expMonth: Optional[str] = None
    expYear: Optional[str] = None

class EditItemIdentityAction(BaseAction):
    action: Literal[EditAction.IDENTITY] = EditAction.IDENTITY
    target_id: str
    title: Optional[str] = None
    firstName: Optional[str] = None
    middleName: Optional[str] = None
    lastName: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None
    address3: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postalCode: Optional[str] = None
    country: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    username: Optional[str] = None

class UpsertCustomFieldAction(BaseAction):
    """
    Adds or updates a Custom Field. 
    Can only write fields of type 0 (Text) or 2 (Boolean).
    Forbids the AI from maliciously setting a field as Type 1 (Hidden) to bury secrets.
    """
    action: Literal[EditAction.CUSTOM_FIELD] = EditAction.CUSTOM_FIELD
    target_id: str
    name: str
    value: str
    type: Literal[0, 2] = Field(default=0, description="0 for Text, 2 for Boolean. Hidden/Linked are forbidden.")


VaultTransactionAction = Annotated[
    Union[
        CreateItemAction,
        RenameItemAction, 
        MoveItemAction, 
        DeleteItemAction, 
        RestoreItemAction,
        FavoriteItemAction,
        MoveToCollectionAction,
        ToggleRepromptAction,
        DeleteAttachmentAction,
        CreateFolderAction, 
        RenameFolderAction, 
        DeleteFolderAction,
        EditItemLoginAction,
        EditItemCardAction,
        EditItemIdentityAction,
        UpsertCustomFieldAction
    ],
    Field(discriminator="action")
]

class TransactionPayload(BaseModel):
    """A batch of explicitly typed operations proposed by the agent."""
    model_config = ConfigDict(extra="forbid")
    
    operations: List[VaultTransactionAction]
    rationale: str = Field(..., description="Explain to the host human why you are proposing these exact changes.")

    @model_validator(mode='after')
    def isolate_disruptive_actions(self) -> 'TransactionPayload':
        """
        Enforce that certain high-risk actions must be executed as standalone
        transactions to minimize collateral risk:

        - 'delete_attachment': UNRECOVERABLE (bypasses Bitwarden Trash entirely).
        - 'delete_folder': DISRUPTIVE (hard delete — folders have no trash).
          All items in the folder lose their folderId. Cannot be rolled back
          if bundled with other operations because folderId info is destroyed
          on execution and cannot be reconstructed post-hoc.
        """
        has_attachment_deletion = any(
            op.action == ItemAction.DELETE_ATTACHMENT for op in self.operations
        )
        has_folder_deletion = any(
            op.action == FolderAction.DELETE for op in self.operations
        )
        
        if has_attachment_deletion and len(self.operations) > 1:
            raise ValueError(
                "CRITICAL SECURITY RULE: The 'delete_attachment' action is UNRECOVERABLE (bypasses Bitwarden Trash). "
                "Because it cannot be rolled back safely if another operation in the batch fails, "
                "you MUST send this action completely isolated in its own batch of size 1. "
                "Do not bundle it with other operations."
            )

        if has_folder_deletion and len(self.operations) > 1:
            raise ValueError(
                "CRITICAL SECURITY RULE: The 'delete_folder' action is DISRUPTIVE and cannot be bundled. "
                "Bitwarden folders are hard-deleted (no trash). All items inside lose their folder reference. "
                "Rolling back a folder deletion in a mixed transaction is architecturally unsolvable. "
                "You MUST send 'delete_folder' completely isolated in its own batch of size 1."
            )
            
        return self

    @model_validator(mode='after')
    def enforce_max_batch_size(self) -> 'TransactionPayload':
        """
        Enforce a configurable upper bound on the number of operations per batch.
        Larger batches extend the race-condition window with external Bitwarden clients,
        increasing the probability of a FATAL rollback failure if an external edit
        modifies an item targeted by this transaction in flight.
        Limit is read from config.yaml → proxy.max_batch_size.
        """
        if len(self.operations) > MAX_BATCH_SIZE:
            raise ValueError(
                f"BATCH TOO LARGE: You submitted {len(self.operations)} operations, "
                f"but the proxy enforces a maximum of {MAX_BATCH_SIZE} operations per batch "
                f"(configured via proxy.max_batch_size in config.yaml). "
                f"Split your request into smaller batches of at most {MAX_BATCH_SIZE} operations each."
            )
        return self
