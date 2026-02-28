import json
import copy
from typing import List, Dict, Any, Callable, Tuple, Optional
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
        rollback_stack: List[Callable] = []
        
        try:
            for op in payload.operations:
                msg, rollback_func = TransactionManager._execute_single_action(op, session_key)
                results.append(msg)
                if rollback_func:
                    rollback_stack.insert(0, rollback_func) # Prepend for LIFO execution
            return "Transaction completed successfully.\n" + "\n".join(results)
        except Exception as main_err:
            # Operation failed mid-flight. Rollback!
            try:
                for rb_func in rollback_stack:
                    rb_func()
                return f"CRITICAL: Transaction failed at an operation ({str(main_err)}). A full rollback was successfully performed. Vault is pristine."
            except Exception as fatal_err:
                return f"FATAL ERROR: Transaction failed, AND the rollback mechanism also failed. Vault is in an inconsistent state! Reason: {str(fatal_err)}"
        finally:
            sk_bytes = bytearray(session_key, 'utf-8')
            for i in range(len(sk_bytes)):
                sk_bytes[i] = 0
            del sk_bytes
            del session_key

    @staticmethod
    def _execute_single_action(op: VaultTransactionAction, session_key: str) -> Tuple[str, Optional[Callable]]:
        
        # Helper to encapsulate the common get -> edit cycle safely
        def safe_edit_item(target_id: str, field_updater: Callable) -> Tuple[str, Callable]:
            original_item_data = SecureSubprocessWrapper.execute_json(["get", "item", target_id], session_key)
            item_data = copy.deepcopy(original_item_data)
            
            field_updater(item_data)
            encoded_json = json.dumps(item_data)
            SecureSubprocessWrapper.execute(["edit", "item", target_id, encoded_json], session_key)
            
            def rollback():
                orig_json = json.dumps(original_item_data)
                SecureSubprocessWrapper.execute(["edit", "item", target_id, orig_json], session_key)
                
            return target_id, rollback

        # --- ITEM ACTIONS ---
        if op.action == ItemAction.CREATE:
            item_tpl = SecureSubprocessWrapper.execute_json(["get", "template", "item"], session_key)
            item_tpl["type"] = op.type
            item_tpl["name"] = op.name
            item_tpl["folderId"] = op.folder_id
            item_tpl["organizationId"] = op.organization_id
            item_tpl["favorite"] = op.favorite
            # Crucially empty the notes template to avoid accidental secrets
            item_tpl["notes"] = None
            
            if op.type == 1 and op.login:
                login_tpl = SecureSubprocessWrapper.execute_json(["get", "template", "item.login"], session_key)
                if op.login.username is not None: login_tpl["username"] = op.login.username
                if op.login.uris is not None: login_tpl["uris"] = op.login.uris
                item_tpl["login"] = login_tpl
            elif op.type == 3 and op.card:
                card_tpl = SecureSubprocessWrapper.execute_json(["get", "template", "item.card"], session_key)
                if op.card.cardholderName is not None: card_tpl["cardholderName"] = op.card.cardholderName
                if op.card.brand is not None: card_tpl["brand"] = op.card.brand
                if op.card.expMonth is not None: card_tpl["expMonth"] = op.card.expMonth
                if op.card.expYear is not None: card_tpl["expYear"] = op.card.expYear
                item_tpl["card"] = card_tpl
            elif op.type == 4 and op.identity:
                id_tpl = SecureSubprocessWrapper.execute_json(["get", "template", "item.identity"], session_key)
                # Apply non-None fields
                for k, v in op.identity.model_dump(exclude_none=True).items():
                    if k in id_tpl:
                        id_tpl[k] = v
                item_tpl["identity"] = id_tpl
                
            encoded_json = json.dumps(item_tpl)
            res_str = SecureSubprocessWrapper.execute(["create", "item", encoded_json], session_key)
            # Try parsing the returned string. Sometimes bw outputs JSON on create.
            try:
                new_id = json.loads(res_str).get("id")
            except Exception:
                # Fallback if bw doesn't return JSON by default without --response
                # Actually --response or capturing stdout might work, but if we don't have it, we might be blind to the ID.
                # It's better to force --response if possible? `bw create` usually prints raw JSON to stdout.
                new_id = None
            
            # If we don't have the ID, we cannot rollback safely. Let's assume it returns JSON.
            def rollback():
                if new_id:
                    SecureSubprocessWrapper.execute(["delete", "item", new_id], session_key)
                    SecureSubprocessWrapper.execute(["delete", "item", new_id, "--permanent"], session_key) # Ensure complete removal of hallucinated items
            
            return f"-> Created new {op.type} item '{op.name}'", rollback
            
        elif op.action == ItemAction.RENAME:
            def u(data): data["name"] = op.new_name
            _, rollback = safe_edit_item(op.target_id, u)
            return f"-> Renamed item {op.target_id} to '{op.new_name}'", rollback
            
        elif op.action == ItemAction.MOVE_TO_FOLDER:
            def u(data): data["folderId"] = op.folder_id
            _, rollback = safe_edit_item(op.target_id, u)
            return f"-> Moved item {op.target_id} to folder '{op.folder_id}'", rollback
            
        elif op.action == ItemAction.DELETE:
            SecureSubprocessWrapper.execute(["delete", "item", op.target_id], session_key)
            def rollback():
                SecureSubprocessWrapper.execute(["restore", "item", op.target_id], session_key)
            return f"-> Deleted item {op.target_id}", rollback

        elif op.action == ItemAction.RESTORE:
            SecureSubprocessWrapper.execute(["restore", "item", op.target_id], session_key)
            def rollback():
                SecureSubprocessWrapper.execute(["delete", "item", op.target_id], session_key)
            return f"-> Restored item {op.target_id} from trash", rollback
            
        elif op.action == ItemAction.FAVORITE:
            def u(data): data["favorite"] = op.favorite
            _, rollback = safe_edit_item(op.target_id, u)
            state = "Favorited" if op.favorite else "Unfavorited"
            return f"-> {state} item {op.target_id}", rollback

        elif op.action == ItemAction.MOVE_TO_COLLECTION:
            # Move from personal vault to an organization vault
            original_item_data = SecureSubprocessWrapper.execute_json(["get", "item", op.target_id], session_key)
            SecureSubprocessWrapper.execute(["move", op.target_id, op.organization_id], session_key)
            def rollback():
                # Moving an item transfers ownership. Restoring it might require a new clone.
                # For safety, we try a simple re-edit if possible:
                orig_json = json.dumps(original_item_data)
                SecureSubprocessWrapper.execute(["edit", "item", op.target_id, orig_json], session_key)
            return f"-> Moved item {op.target_id} to Organization {op.organization_id}", rollback

        elif op.action == ItemAction.TOGGLE_REPROMPT:
            def u(data): data["reprompt"] = 1 if op.reprompt else 0
            _, rollback = safe_edit_item(op.target_id, u)
            state = "Enabled" if op.reprompt else "Disabled"
            return f"-> {state} master password reprompt for item {op.target_id}", rollback

        elif op.action == ItemAction.DELETE_ATTACHMENT:
            # 'bw delete attachment' normally needs the itemid too
            SecureSubprocessWrapper.execute(["delete", "attachment", op.attachment_id, "--itemid", op.target_id], session_key)
            def rollback():
                pass # Unrecoverable unless we downloaded it first.
            return f"-> Deleted attachment {op.attachment_id} from item {op.target_id} (Unrecoverable)", rollback

        # --- FOLDER ACTIONS ---
        elif op.action == FolderAction.CREATE:
            folder_tpl = SecureSubprocessWrapper.execute_json(["get", "template", "folder"], session_key)
            folder_tpl["name"] = op.name
            encoded_json = json.dumps(folder_tpl)
            res_str = SecureSubprocessWrapper.execute(["create", "folder", encoded_json], session_key)
            
            try:
                new_id = json.loads(res_str).get("id")
            except Exception:
                new_id = None
                
            def rollback():
                if new_id:
                    SecureSubprocessWrapper.execute(["delete", "folder", new_id], session_key)
                    
            return f"-> Created new folder '{op.name}'", rollback
            
        elif op.action == FolderAction.RENAME:
            original_folder = SecureSubprocessWrapper.execute_json(["get", "folder", op.target_id], session_key)
            folder_data = copy.deepcopy(original_folder)
            folder_data["name"] = op.new_name
            encoded_json = json.dumps(folder_data)
            SecureSubprocessWrapper.execute(["edit", "folder", op.target_id, encoded_json], session_key)
            
            def rollback():
                orig_json = json.dumps(original_folder)
                SecureSubprocessWrapper.execute(["edit", "folder", op.target_id, orig_json], session_key)
                
            return f"-> Renamed folder {op.target_id} to '{op.new_name}'", rollback
            
        elif op.action == FolderAction.DELETE:
            SecureSubprocessWrapper.execute(["delete", "folder", op.target_id], session_key)
            def rollback():
                SecureSubprocessWrapper.execute(["restore", "folder", op.target_id], session_key)
            return f"-> Deleted folder {op.target_id}", rollback

        elif op.action == FolderAction.RESTORE:
            SecureSubprocessWrapper.execute(["restore", "folder", op.target_id], session_key)
            def rollback():
                SecureSubprocessWrapper.execute(["delete", "folder", op.target_id], session_key)
            return f"-> Restored folder {op.target_id} from trash", rollback
            
        # --- EDIT ACTIONS ---
        elif op.action == EditAction.LOGIN: # Renamed to EDIT_ITEM_LOGIN in the provided snippet, but keeping original for now
            def u(data):
                if "login" not in data or not isinstance(data["login"], dict):
                    data["login"] = {}
                if op.username is not None: data["login"]["username"] = op.username
                if op.uris is not None: data["login"]["uris"] = op.uris
            _, rollback = safe_edit_item(op.target_id, u)
            return f"-> Edited login details for item {op.target_id}", rollback
            
        elif op.action == EditAction.CARD: # Renamed to EDIT_ITEM_CARD in the provided snippet, but keeping original for now
            def u(data):
                if "card" not in data or not isinstance(data["card"], dict):
                    data["card"] = {}
                if op.cardholderName is not None: data["card"]["cardholderName"] = op.cardholderName
                if op.brand is not None: data["card"]["brand"] = op.brand
                if op.expMonth is not None: data["card"]["expMonth"] = op.expMonth
                if op.expYear is not None: data["card"]["expYear"] = op.expYear
            _, rollback = safe_edit_item(op.target_id, u)
            return f"-> Edited card details for item {op.target_id}", rollback

        elif op.action == EditAction.IDENTITY: # Renamed to EDIT_ITEM_IDENTITY in the provided snippet, but keeping original for now
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
            _, rollback = safe_edit_item(op.target_id, u)
            return f"-> Edited identity details for item {op.target_id}", rollback

        elif op.action == EditAction.CUSTOM_FIELD: # Renamed to UPSERT_CUSTOM_FIELD in the provided snippet, but keeping original for now
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
            
            _, rollback = safe_edit_item(op.target_id, u)
            return f"-> Upserted custom field '{op.name}' for item {op.target_id}", rollback
            
        else:
            raise ValueError(f"CRITICAL: Unhandled polymorphic action type: {op.action}")
