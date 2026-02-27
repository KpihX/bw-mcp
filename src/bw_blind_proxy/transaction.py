import json
from typing import List, Dict, Any
from .models import TransactionPayload, VaultTransactionAction, ItemAction, FolderAction, EditAction
from .subprocess_wrapper import SecureSubprocessWrapper, SecureBWError
from .ui import HITLManager

class TransactionManager:
    """
    Manages the Human-in-The-Loop batch execution of vault modifications.
    Supports completely exhaustive API elements via rigorous Enum categorization.
    """
    
    @staticmethod
    def execute_batch(payload_dict: Dict[str, Any]) -> str:
        try:
            payload = TransactionPayload(**payload_dict)
        except Exception as e:
            return f"Error: Invalid transaction payload. {str(e)}"
            
        if not payload.operations:
            return "Error: No operations provided in the transaction payload."
            
        approved = HITLManager.review_transaction(payload)
        if not approved:
            return "Transaction aborted by the user."
            
        try:
            master_password = HITLManager.ask_master_password(title="Approve Transaction - Enter Master Password")
        except Exception as e:
            return f"Transaction aborted: {str(e)}"
            
        try:
            session_key = SecureSubprocessWrapper.unlock_vault(master_password)
        except SecureBWError as e:
            return f"Transaction failed during unlock: {str(e)}"
            
        results = []
        try:
            for op in payload.operations:
                result = TransactionManager._execute_single_action(op, session_key)
                results.append(result)
            return "Transaction completed successfully.\n" + "\n".join(results)
        except Exception as e:
            return f"Transaction failed mid-execution: {str(e)}. Some operations may have completed."
        finally:
            sk_bytes = bytearray(session_key, 'utf-8')
            for i in range(len(sk_bytes)):
                sk_bytes[i] = 0
            del sk_bytes
            del session_key

    @staticmethod
    def _execute_single_action(op: VaultTransactionAction, session_key: str) -> str:
        
        # Helper to encapsulate the common get -> edit cycle safely
        def safe_edit_item(target_id: str, field_updater: callable) -> str:
            item_data = SecureSubprocessWrapper.execute_json(["get", "item", target_id], session_key)
            field_updater(item_data)
            encoded_json = json.dumps(item_data)
            SecureSubprocessWrapper.execute(["edit", "item", target_id, encoded_json], session_key)
            return target_id

        # --- ITEM ACTIONS ---
        if op.action == ItemAction.RENAME:
            def u(data): data["name"] = op.new_name
            safe_edit_item(op.target_id, u)
            return f"-> Renamed item {op.target_id} to '{op.new_name}'"
            
        elif op.action == ItemAction.MOVE_TO_FOLDER:
            def u(data): data["folderId"] = op.folder_id
            safe_edit_item(op.target_id, u)
            return f"-> Moved item {op.target_id} to folder '{op.folder_id}'"
            
        elif op.action == ItemAction.DELETE:
            SecureSubprocessWrapper.execute(["delete", "item", op.target_id], session_key)
            return f"-> Deleted item {op.target_id}"

        elif op.action == ItemAction.RESTORE:
            SecureSubprocessWrapper.execute(["restore", "item", op.target_id], session_key)
            return f"-> Restored item {op.target_id} from trash"
            
        elif op.action == ItemAction.FAVORITE:
            def u(data): data["favorite"] = op.favorite
            safe_edit_item(op.target_id, u)
            state = "Favorited" if op.favorite else "Unfavorited"
            return f"-> {state} item {op.target_id}"

        elif op.action == ItemAction.MOVE_TO_COLLECTION:
            # Move from personal vault to an organization vault
            SecureSubprocessWrapper.execute(["move", op.target_id, op.organization_id], session_key)
            return f"-> Moved item {op.target_id} to Organization {op.organization_id}"

        elif op.action == ItemAction.TOGGLE_REPROMPT:
            def u(data): data["reprompt"] = 1 if op.reprompt else 0
            safe_edit_item(op.target_id, u)
            state = "Enabled" if op.reprompt else "Disabled"
            return f"-> {state} master password reprompt for item {op.target_id}"

        elif op.action == ItemAction.DELETE_ATTACHMENT:
            # Ensure the attachment belongs to this item. 'bw delete attachment' normally needs the itemid too, 
            # though the CLI docs say `bw delete attachment <id>`. Safest approach is providing target_id as context
            # Actually you specify attachment id or name. 
            SecureSubprocessWrapper.execute(["delete", "attachment", op.attachment_id, "--itemid", op.target_id], session_key)
            return f"-> Deleted attachment {op.attachment_id} from item {op.target_id}"

        # --- FOLDER ACTIONS ---
        elif op.action == FolderAction.CREATE:
            folder_tpl = SecureSubprocessWrapper.execute_json(["get", "template", "folder"], session_key)
            folder_tpl["name"] = op.name
            encoded_json = json.dumps(folder_tpl)
            SecureSubprocessWrapper.execute(["create", "folder", encoded_json], session_key)
            return f"-> Created folder '{op.name}'"
            
        elif op.action == FolderAction.RENAME:
            folder_data = SecureSubprocessWrapper.execute_json(["get", "folder", op.target_id], session_key)
            folder_data["name"] = op.new_name
            encoded_json = json.dumps(folder_data)
            SecureSubprocessWrapper.execute(["edit", "folder", op.target_id, encoded_json], session_key)
            return f"-> Renamed folder {op.target_id} to '{op.new_name}'"
            
        elif op.action == FolderAction.DELETE:
            SecureSubprocessWrapper.execute(["delete", "folder", op.target_id], session_key)
            return f"-> Deleted folder {op.target_id}"
            
        # --- EDIT ACTIONS ---
        elif op.action == EditAction.LOGIN:
            def u(data):
                if "login" not in data or not isinstance(data["login"], dict):
                    data["login"] = {}
                if op.username is not None: data["login"]["username"] = op.username
                if op.uris is not None: data["login"]["uris"] = op.uris
            safe_edit_item(op.target_id, u)
            return f"-> Edited login details for item {op.target_id}"
            
        elif op.action == EditAction.CARD:
            def u(data):
                if "card" not in data or not isinstance(data["card"], dict):
                    data["card"] = {}
                if op.cardholderName is not None: data["card"]["cardholderName"] = op.cardholderName
                if op.brand is not None: data["card"]["brand"] = op.brand
                if op.expMonth is not None: data["card"]["expMonth"] = op.expMonth
                if op.expYear is not None: data["card"]["expYear"] = op.expYear
            safe_edit_item(op.target_id, u)
            return f"-> Edited card details for item {op.target_id}"

        elif op.action == EditAction.IDENTITY:
            def u(data):
                if "identity" not in data or not isinstance(data["identity"], dict):
                    data["identity"] = {}
                for field in [
                    "title", "firstName", "middleName", "lastName", "address1", "address2", 
                    "address3", "city", "state", "postalCode", "country", "company", "email", 
                    "phone", "username"
                ]:
                    val = getattr(op, field)
                    if val is not None:
                        data["identity"][field] = val
            safe_edit_item(op.target_id, u)
            return f"-> Edited identity details for item {op.target_id}"

        elif op.action == EditAction.CUSTOM_FIELD:
            def u(data):
                fields = data.get("fields", [])
                found = False
                for f in fields:
                    if f.get("name") == op.name:
                        if f.get("type", 0) in [1, 3]:
                            raise ValueError(f"CRITICAL: Cannot edit custom field '{op.name}'; it is of secret Type {f.get('type')}.")
                        f["value"] = op.value
                        f["type"] = op.type
                        found = True
                        break
                
                if not found:
                    fields.append({
                        "name": op.name,
                        "value": op.value,
                        "type": op.type
                    })
                data["fields"] = fields
            
            safe_edit_item(op.target_id, u)
            return f"-> Upserted custom field '{op.name}' for item {op.target_id}"
            
        else:
            raise ValueError(f"CRITICAL: Unhandled polymorphic action type: {op.action}")
