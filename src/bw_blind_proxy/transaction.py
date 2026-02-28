import json
import copy
import uuid
from typing import List, Dict, Any, Callable, Tuple, Optional
from .models import (
    TransactionPayload, VaultTransactionAction, ItemAction, 
    FolderAction, EditAction, TransactionStatus
)
from .subprocess_wrapper import SecureSubprocessWrapper, SecureBWError
from .ui import HITLManager
from .wal import WALManager
from .logger import TransactionLogger

class TransactionManager:
    """
    Manages the Human-in-The-Loop batch execution of vault modifications.
    Supports completely exhaustive API elements via rigorous Enum categorization.
    """
    
    @staticmethod
    def _perform_rollback(
        tx_id: str,
        rollback_stack: List[Dict[str, Any]],
        session_key: str
    ) -> Dict[str, Any]:
        """
        Core LIFO rollback engine, shared by execute_batch and check_recovery.
        Returns a structured result dict:
          {
            "success": bool,
            "executed": List[str],         # commands that ran successfully
            "failed_cmd": str | None,       # the single cmd that crashed (if any)
            "error": str | None             # the exception message (if any)
          }
        This function DOES NOT touch the WAL. Callers decide whether to clear or
        preserve it based on the result, enabling safe non-destructive recovery.
        """
        # Materialise once to allow O(1)-index access if a crash occurs mid-loop
        rollback_lifo_list = list(reversed(rollback_stack))
        executed: List[str] = []
        
        try:
            for rb_cmd in rollback_lifo_list:
                args = rb_cmd.get("cmd", [])
                if args and args[0] == "bw":
                    # Strip "bw" — SecureSubprocessWrapper.execute prepends it automatically
                    SecureSubprocessWrapper.execute(args[1:], session_key)
                    executed.append(" ".join(args))
                    
                    # 💡 Consume the executed command from WAL incrementally
                    WALManager.pop_rollback_command(tx_id)
                    
            return {"success": True, "executed": executed, "failed_cmd": None, "error": None}
        except Exception as e:
            # Identify the single command that failed via O(1) index
            rb_idx = len(executed)
            failed_cmd = None
            if rb_idx < len(rollback_lifo_list):
                args = rollback_lifo_list[rb_idx].get("cmd", [])
                failed_cmd = " ".join(args)
            return {"success": False, "executed": executed, "failed_cmd": failed_cmd, "error": str(e)}

    @staticmethod
    def check_recovery(session_key: str) -> Optional[str]:
        """
        Checks the WAL for orphaned transactions resulting from a hard crash.
        If found, calls _perform_rollback to restore vault integrity.

        - On success: clears the WAL, logs CRASH_RECOVERED_ON_BOOT, returns a warning for the LLM.
        - On failure: PRESERVES the WAL (so manual recovery is still possible),
          logs ROLLBACK_FAILED, and returns a rich diagnostic message so the LLM can
          decide whether to retry or escalate to the user.
        """
        if not WALManager.has_pending_transaction():
            return None
            
        wal_data = WALManager.read_wal()
        tx_id = wal_data.get("transaction_id", "UNKNOWN")
        rollback_stack = wal_data.get("rollback_commands", [])
        
        result = TransactionManager._perform_rollback(tx_id, rollback_stack, session_key)
        
        # Synthetic Pydantic payload used to produce a log entry for this recovery event
        mock_payload = TransactionPayload(
            rationale="Hard-crash detected upon startup. System auto-recovered via WAL.",
            operations=[]
        )
        
        if result["success"]:
            # Vault is clean — destroy the WAL so we never re-apply the same rollback
            WALManager.clear_wal()
            TransactionLogger.log_transaction(
                transaction_id=tx_id,
                payload=mock_payload,
                status=TransactionStatus.CRASH_RECOVERED_ON_BOOT,
                executed_rolled_back_cmds=result["executed"]
            )
            return (
                f"WARNING: A previous critical crash was detected (TX: {tx_id}). "
                f"The proxy executed a full WAL rollback ({len(result['executed'])} command(s)) "
                f"and restored vault integrity. The previous transaction was aborted. "
                f"You may now proceed safely."
            )
        else:
            # WAL is intentionally NOT cleared — the vault is still dirty
            TransactionLogger.log_transaction(
                transaction_id=tx_id,
                payload=mock_payload,
                status=TransactionStatus.ROLLBACK_FAILED,
                error_message=f"RecoveryError: {result['error']}",
                executed_rolled_back_cmds=result["executed"],
                failed_rollback_cmd=result["failed_cmd"]
            )
            msg = (
                f"CRITICAL: A previous crash (TX: {tx_id}) was detected and the WAL rollback FAILED.\n"
                f"Recovery Error: {result['error']}\n"
                f"Successfully reversed commands: {result['executed']}\n"
                f"Command that failed to revert: {result['failed_cmd']}\n\n"
                f"The WAL file has been preserved. "
                f"Diagnosis: If this is a transient network error, retry calling ANY tool to re-attempt recovery. "
                f"If the error mentions 'Item not found', manual intervention is required: "
                f"run the failed command directly via the Bitwarden CLI. "
                f"IMPORTANT: Do NOT attempt new vault operations until this is resolved."
            )
            return msg


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
        executed_ops: List[str] = []
        failed_op = None
        executed_rolled_back_cmds = []
        failed_rollback_cmd = None   # Only ONE cmd can fail per LIFO sequential pass
        
        rollback_stack: List[Dict[str, Any]] = []
        tx_id = str(uuid.uuid4())
        logger_status = TransactionStatus.SUCCESS
        logger_err = None
        
        # Initialize WAL
        WALManager.write_wal(tx_id, rollback_stack)
        
        try:
            for op in payload.operations:
                msg, rollback_cmds = TransactionManager._execute_single_action(op, session_key)
                results.append(msg)
                
                # Operation succeeded, record its human-readable message trace
                executed_ops.append(msg)
                
                if rollback_cmds:
                    # Append commands in reverse to maintain LIFO execution during rollback
                    rollback_stack.extend(reversed(rollback_cmds))
                    WALManager.write_wal(tx_id, rollback_stack)
                    
            WALManager.clear_wal()
            return "Transaction completed successfully.\n" + "\n".join(results)
        except Exception as main_err:
            logger_err = str(main_err)
            
            # Since the current op caused the exception, it's not in executed_ops
            # We can deduce the failed operation by looking at the len of executed_ops
            idx = len(executed_ops)
            if idx < len(payload.operations):
                failed_op = payload.operations[idx].model_dump(exclude_none=True)
                
            logger_status = TransactionStatus.ROLLBACK_TRIGGERED
            # Delegate to the shared engine — no WAL mutation inside (except popping)
            rb_result = TransactionManager._perform_rollback(tx_id, rollback_stack, session_key)
            
            executed_rolled_back_cmds = rb_result["executed"]
            failed_rollback_cmd = rb_result["failed_cmd"]
            
            if rb_result["success"]:
                WALManager.clear_wal()
                logger_status = TransactionStatus.ROLLBACK_SUCCESS
                
                err_msg = f"CRITICAL: Transaction failed during the following operation:\n{json.dumps(failed_op, indent=2)}\n\nError: {str(main_err)}\n\n"
                err_msg += f"A full rollback was successfully performed. The {len(executed_rolled_back_cmds)} commands executed to revert your previous {len(executed_ops)} operations have reversed the vault back to its pristine state."
                return err_msg
            else:
                logger_status = TransactionStatus.ROLLBACK_FAILED
                # Enrich logger_err with the full dual error chain for total log transparency
                logger_err = f"ExecutionError: {str(main_err)} | RollbackError: {rb_result['error']}"
                
                fatal_msg = f"FATAL ERROR: Transaction failed, AND the rollback mechanism also failed. Vault is in an inconsistent state!\n"
                fatal_msg += f"Execution Error: {str(main_err)}\n"
                fatal_msg += f"Rollback Error: {rb_result['error']}\n\n"
                fatal_msg += f"The following rollback commands successfully executed before crash: {json.dumps(executed_rolled_back_cmds)}\n"
                fatal_msg += f"The command that failed to rollback: {failed_rollback_cmd}\n"
                
                return fatal_msg
        finally:
            # Pass all tracing info directly to the logic logger using kwargs
            TransactionLogger.log_transaction(
                transaction_id=tx_id, 
                payload=payload, 
                status=logger_status, 
                error_message=logger_err,
                executed_ops=executed_ops,
                failed_op=failed_op,
                executed_rolled_back_cmds=executed_rolled_back_cmds,
                failed_rollback_cmd=failed_rollback_cmd
            )
            sk_bytes = bytearray(session_key, 'utf-8')
            for i in range(len(sk_bytes)):
                sk_bytes[i] = 0
            del sk_bytes
            del session_key

    @staticmethod
    def _execute_single_action(op: VaultTransactionAction, session_key: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        
        # Helper to encapsulate the common get -> edit cycle safely
        def safe_edit_item(target_id: str, field_updater: Callable) -> Tuple[str, List[Dict[str, Any]]]:
            original_item_data = SecureSubprocessWrapper.execute_json(["get", "item", target_id], session_key)
            item_data = copy.deepcopy(original_item_data)
            
            field_updater(item_data)
            encoded_json = json.dumps(item_data)
            SecureSubprocessWrapper.execute(["edit", "item", target_id, encoded_json], session_key)
            
            orig_json = json.dumps(original_item_data)
            rollback_cmds = [{"cmd": ["bw", "edit", "item", target_id, orig_json]}]
                
            return target_id, rollback_cmds

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
            
            try:
                new_id = json.loads(res_str).get("id")
            except Exception:
                new_id = None
            
            rollback_cmds = []
            if new_id:
                rollback_cmds = [
                    {"cmd": ["bw", "delete", "item", new_id]},
                    {"cmd": ["bw", "delete", "item", new_id, "--permanent"]}
                ]
            
            return f"-> Created new {op.type} item '{op.name}'", rollback_cmds
            
        elif op.action == ItemAction.RENAME:
            def u(data): data["name"] = op.new_name
            _, rollback_cmds = safe_edit_item(op.target_id, u)
            return f"-> Renamed item {op.target_id} to '{op.new_name}'", rollback_cmds
            
        elif op.action == ItemAction.MOVE_TO_FOLDER:
            def u(data): data["folderId"] = op.folder_id
            _, rollback_cmds = safe_edit_item(op.target_id, u)
            return f"-> Moved item {op.target_id} to folder '{op.folder_id}'", rollback_cmds
            
        elif op.action == ItemAction.DELETE:
            SecureSubprocessWrapper.execute(["delete", "item", op.target_id], session_key)
            rollback_cmds = [{"cmd": ["bw", "restore", "item", op.target_id]}]
            return f"-> Deleted item {op.target_id}", rollback_cmds

        elif op.action == ItemAction.RESTORE:
            SecureSubprocessWrapper.execute(["restore", "item", op.target_id], session_key)
            rollback_cmds = [{"cmd": ["bw", "delete", "item", op.target_id]}]
            return f"-> Restored item {op.target_id} from trash", rollback_cmds
            
        elif op.action == ItemAction.FAVORITE:
            def u(data): data["favorite"] = op.favorite
            _, rollback_cmds = safe_edit_item(op.target_id, u)
            state = "Favorited" if op.favorite else "Unfavorited"
            return f"-> {state} item {op.target_id}", rollback_cmds

        elif op.action == ItemAction.MOVE_TO_COLLECTION:
            original_item_data = SecureSubprocessWrapper.execute_json(["get", "item", op.target_id], session_key)
            SecureSubprocessWrapper.execute(["move", op.target_id, op.organization_id], session_key)
            orig_json = json.dumps(original_item_data)
            rollback_cmds = [{"cmd": ["bw", "edit", "item", op.target_id, orig_json]}]
            return f"-> Moved item {op.target_id} to Organization {op.organization_id}", rollback_cmds

        elif op.action == ItemAction.TOGGLE_REPROMPT:
            def u(data): data["reprompt"] = 1 if op.reprompt else 0
            _, rollback_cmds = safe_edit_item(op.target_id, u)
            state = "Enabled" if op.reprompt else "Disabled"
            return f"-> {state} master password reprompt for item {op.target_id}", rollback_cmds

        elif op.action == ItemAction.DELETE_ATTACHMENT:
            SecureSubprocessWrapper.execute(["delete", "attachment", op.attachment_id, "--itemid", op.target_id], session_key)
            return f"-> Deleted attachment {op.attachment_id} from item {op.target_id} (Unrecoverable)", None

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
                
            rollback_cmds = []
            if new_id:
                rollback_cmds = [{"cmd": ["bw", "delete", "folder", new_id]}]
                    
            return f"-> Created new folder '{op.name}'", rollback_cmds
            
        elif op.action == FolderAction.RENAME:
            original_folder = SecureSubprocessWrapper.execute_json(["get", "folder", op.target_id], session_key)
            folder_data = copy.deepcopy(original_folder)
            folder_data["name"] = op.new_name
            encoded_json = json.dumps(folder_data)
            SecureSubprocessWrapper.execute(["edit", "folder", op.target_id, encoded_json], session_key)
            
            orig_json = json.dumps(original_folder)
            rollback_cmds = [{"cmd": ["bw", "edit", "folder", op.target_id, orig_json]}]
                
            return f"-> Renamed folder {op.target_id} to '{op.new_name}'", rollback_cmds
            
        elif op.action == FolderAction.DELETE:
            SecureSubprocessWrapper.execute(["delete", "folder", op.target_id], session_key)
            rollback_cmds = [{"cmd": ["bw", "restore", "folder", op.target_id]}]
            return f"-> Deleted folder {op.target_id}", rollback_cmds

        elif op.action == FolderAction.RESTORE:
            SecureSubprocessWrapper.execute(["restore", "folder", op.target_id], session_key)
            rollback_cmds = [{"cmd": ["bw", "delete", "folder", op.target_id]}]
            return f"-> Restored folder {op.target_id} from trash", rollback_cmds
            
        # --- EDIT ACTIONS ---
        elif op.action == EditAction.LOGIN: 
            def u(data):
                if "login" not in data or not isinstance(data["login"], dict):
                    data["login"] = {}
                if op.username is not None: data["login"]["username"] = op.username
                if op.uris is not None: data["login"]["uris"] = op.uris
            _, rollback_cmds = safe_edit_item(op.target_id, u)
            return f"-> Edited login details for item {op.target_id}", rollback_cmds
            
        elif op.action == EditAction.CARD: 
            def u(data):
                if "card" not in data or not isinstance(data["card"], dict):
                    data["card"] = {}
                if op.cardholderName is not None: data["card"]["cardholderName"] = op.cardholderName
                if op.brand is not None: data["card"]["brand"] = op.brand
                if op.expMonth is not None: data["card"]["expMonth"] = op.expMonth
                if op.expYear is not None: data["card"]["expYear"] = op.expYear
            _, rollback_cmds = safe_edit_item(op.target_id, u)
            return f"-> Edited card details for item {op.target_id}", rollback_cmds

        elif op.action == EditAction.IDENTITY: 
            def u(data):
                if "identity" not in data or not isinstance(data["identity"], dict):
                    data["identity"] = {}
                
                # Use model_dump or Pydantic v2 compliant iteration
                for field in op.model_fields.keys():
                    if field in ["action", "target_id", "rationale"]: continue
                    val = getattr(op, field)
                    if val is not None:
                        data["identity"][field] = val
            _, rollback_cmds = safe_edit_item(op.target_id, u)
            return f"-> Edited identity details for item {op.target_id}", rollback_cmds

        elif op.action == EditAction.CUSTOM_FIELD: 
            def u(data):
                fields = data.get("fields", [])
                found = False
                for f in fields:
                    if f.get("name") == op.name:
                        # Defensive overwrite block against secrets
                        if f.get("type") in [1, 3]:
                            raise ValueError(f"CRITICAL ERROR: Cannot edit custom field '{op.name}' because it is of secret Type 1 or 3.")
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
            
            _, rollback_cmds = safe_edit_item(op.target_id, u)
            return f"-> Upserted custom field '{op.name}' for item {op.target_id}", rollback_cmds
            
        else:
            raise ValueError(f"CRITICAL: Unhandled polymorphic action type: {op.action}")
