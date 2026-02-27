from enum import StrEnum
from typing import List, Optional, Any, Dict, Literal, Union, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

# -----------------
# ACTION ENUMERATIONS (CENTRALIZATION)
# -----------------

class ItemAction(StrEnum):
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

class EditAction(StrEnum):
    LOGIN = "edit_item_login"
    CARD = "edit_item_card"
    IDENTITY = "edit_item_identity"
    CUSTOM_FIELD = "upsert_custom_field"


# -----------------
# DATA FETCH MODELS (Sanitized Views)
# -----------------

class BlindLogin(BaseModel):
    """Login schema that strictly ignores passwords and TOTP secrets."""
    model_config = ConfigDict(extra="ignore")  
    
    username: Optional[str] = None
    uris: Optional[List[Dict[str, Any]]] = None
    
    password: Optional[str] = Field(default="[REDACTED_BY_PROXY]", exclude=True)
    totp: Optional[str] = Field(default="[REDACTED_BY_PROXY]", exclude=True)

    @model_validator(mode='before')
    @classmethod
    def force_redact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'password' in data: data['password'] = "[REDACTED_BY_PROXY]"
            if 'totp' in data: data['totp'] = "[REDACTED_BY_PROXY]"
        return data

class BlindCard(BaseModel):
    """Card schema that protects credit card numbers and CVV codes."""
    model_config = ConfigDict(extra="ignore")
    
    cardholderName: Optional[str] = None
    brand: Optional[str] = None
    expMonth: Optional[str] = None
    expYear: Optional[str] = None
    
    number: Optional[str] = Field(default="[REDACTED_BY_PROXY]", exclude=True)
    code: Optional[str] = Field(default="[REDACTED_BY_PROXY]", exclude=True)
    
    @model_validator(mode='before')
    @classmethod
    def force_redact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'number' in data: data['number'] = "[REDACTED_BY_PROXY]"
            if 'code' in data: data['code'] = "[REDACTED_BY_PROXY]"
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
    
    ssn: Optional[str] = Field(default="[REDACTED_BY_PROXY]", exclude=True)
    passportNumber: Optional[str] = Field(default="[REDACTED_BY_PROXY]", exclude=True)
    licenseNumber: Optional[str] = Field(default="[REDACTED_BY_PROXY]", exclude=True)
    
    @model_validator(mode='before')
    @classmethod
    def force_redact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'ssn' in data: data['ssn'] = "[REDACTED_BY_PROXY]"
            if 'passportNumber' in data: data['passportNumber'] = "[REDACTED_BY_PROXY]"
            if 'licenseNumber' in data: data['licenseNumber'] = "[REDACTED_BY_PROXY]"
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
                data["value"] = "[REDACTED_BY_PROXY]"
        return data

class BlindItem(BaseModel):
    """
    Strict representation of a Bitwarden Item for the LLM context.
    Covers all 4 types (Login, SecureNote, Card, Identity) and Custom Fields.
    SecureNotes are automatically handled by the fact that we redact the 'notes' field.
    """
    model_config = ConfigDict(extra="ignore")
    
    id: str
    organizationId: Optional[str] = None
    folderId: Optional[str] = None
    type: int
    name: str
    favorite: bool = False
    reprompt: int = 0
    notes: Optional[str] = Field(default="[REDACTED_BY_PROXY]", exclude=True)
    
    fields: Optional[List[BlindField]] = None
    login: Optional[BlindLogin] = None
    card: Optional[BlindCard] = None
    identity: Optional[BlindIdentity] = None
    secureNote: Optional[Dict[str, Any]] = None # Always empty in pure BW API anyway

class BlindFolder(BaseModel):
    """Strict representation of a Bitwarden Folder."""
    model_config = ConfigDict(extra="ignore")
    
    id: str
    name: str


# -----------------
# TRANSACTION MODELS (POLYMORPHIC ACTIONS)
# -----------------

class BaseAction(BaseModel):
    """Base for all atomic actions. Rejects any undocumented field."""
    model_config = ConfigDict(extra="forbid") 
    action: str

# --- ITEM ACTIONS ---
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
