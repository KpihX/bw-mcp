import json
import copy
import uuid
import base64
from typing import List, Dict, Any, Callable, Tuple, Optional
from .models import (
    TransactionPayload, VaultTransactionAction, ItemAction, 
    FolderAction, EditAction, TransactionStatus, SecretFieldTarget,
    RefactorAction, RefactorScope
)
from .subprocess_wrapper import SecureSubprocessWrapper, SecureBWError, _sanitize_args_for_log, _safe_error_message
from .ui import HITLManager
from .wal import WALManager
from .logger import TransactionLogger
from .scrubber import deep_scrub_payload
from .vault_runtime import VaultExecutionContext, ensure_fresh_sync, finalize_execution_context, open_vault_session

class TransactionManager:
    """
    Manages the Human-in-The-Loop batch execution of vault modifications.
    Supports completely exhaustive API elements via rigorous Enum categorization.
    """
    
    @staticmethod
    def _perform_rollback(
        tx_id: str,
        rollback_stack: List[Dict[str, Any]],
        master_password_or_session_key: bytearray,
        session_key: Optional[bytearray] = None,
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
        active_session_key = session_key or master_password_or_session_key
        # Materialise once to allow O(1)-index access if a crash occurs mid-loop
        rollback_lifo_list = list(reversed(rollback_stack))
        executed: List[str] = []
        
        try:
            for rb_cmd in rollback_lifo_list:
                args = rb_cmd.get("cmd", [])
                if args and args[0] == "bw":
                    # Strip "bw" — SecureSubprocessWrapper.execute prepends it automatically
                    SecureSubprocessWrapper.execute(args[1:], active_session_key)
                    # Sanitize before storing — never log base64 payloads
                    executed.append(_sanitize_args_for_log(args))
                    
                    # 💡 Consume the executed command from WAL incrementally
                    WALManager.pop_rollback_command(tx_id, master_password_or_session_key)
                    
            return {"success": True, "executed": executed, "failed_cmd": None, "error": None}
        except Exception as e:
            # Identify the single command that failed via O(1) index
            rb_idx = len(executed)
            failed_cmd = None
            if rb_idx < len(rollback_lifo_list):
                args = rollback_lifo_list[rb_idx].get("cmd", [])
                # Sanitize before storing — never log base64 payloads
                failed_cmd = _sanitize_args_for_log(args)
            return {"success": False, "executed": executed, "failed_cmd": failed_cmd, "error": _safe_error_message(e)}

    @staticmethod
    def check_recovery(
        master_password_or_session_key: bytearray,
        session_key: Optional[bytearray] = None,
    ) -> Optional[str]:
        """
        Checks the WAL for orphaned transactions resulting from a hard crash.
        If found, calls _perform_rollback to restore vault integrity.

        - On success: clears the WAL, logs CRASH_RECOVERED_ON_BOOT, returns a warning for the LLM.
        - On failure: PRESERVES the WAL (so manual recovery is still possible),
          logs ROLLBACK_FAILED, and returns a rich diagnostic message so the LLM can
          decide whether to retry or escalate to the user.
        """
        wal_key = master_password_or_session_key
        active_session_key = session_key or master_password_or_session_key

        if not WALManager.has_pending_transaction():
            return None
            
        wal_data = WALManager.read_wal(wal_key)
        tx_id = wal_data.get("transaction_id", "UNKNOWN")
        rollback_stack = wal_data.get("rollback_commands", [])
        
        result = TransactionManager._perform_rollback(tx_id, rollback_stack, wal_key, active_session_key)
        
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
    def execute_batch(
        payload_dict: Dict[str, Any],
        *,
        execution_context: Optional[VaultExecutionContext] = None,
    ) -> str:
        try:
            payload = TransactionPayload(**payload_dict)
        except Exception as e:
            # Pydantic's ValidationError includes rejected field VALUES in str(e),
            # which could leak secrets the LLM tried to smuggle through.
            # We only expose the structural error type, not the content.
            return f"Error: Invalid transaction payload. {_safe_error_message(e)}"
            
        if not payload.operations:
            return "Error: No operations provided in the transaction payload."
            
        owned_context = execution_context is None
        context = execution_context or VaultExecutionContext(
            title="Unlock Vault for Transaction Review",
            raw_status={},
            auth_state="locked",
            unlock_deferred=True,
        )
        
        try:
            # 1. Resolve target names for display (requires session if available)
            id_to_name = {}
            if context.session_key:
                try:
                    id_to_name = TransactionManager._resolve_action_names(payload.operations, context.session_key)
                except Exception:
                    pass # Fallback to UUIDs if name resolution fails initially
            
            # 2. Combined Review + Password Prompt
            approval = HITLManager.authorize_transaction(
                payload, 
                id_to_name=id_to_name, 
                needs_password=context.session_key is None
            )
            
            if not approval.get("approved"):
                return "Transaction aborted by the user."

            # 3. Open session if needed
            if context.session_key is None:
                try:
                    open_vault_session(
                        context,
                        title="Unlock Vault for Transaction Review",
                        master_password=approval.get("password"),
                    )
                except Exception as e:
                    return f"Transaction failed during unlock: {_safe_error_message(e)}"

            # 4. Resolve names AGAIN if they weren't resolved before (now we have a session)
            if not id_to_name:
                 try:
                    id_to_name = TransactionManager._resolve_action_names(payload.operations, context.session_key)
                 except SecureBWError as e:
                    return f"Transaction failed during target resolution: {str(e)}"

            # 5. Ensure fresh sync
            try:
                ensure_fresh_sync(context)
            except SecureBWError as e:
                return f"Transaction failed during sync: {str(e)}"

            session_key = context.session_key
            if session_key is None:
                return "Transaction failed: no active Bitwarden session is available."

            recovery_msg = TransactionManager.check_recovery(session_key)
            if recovery_msg:
                return recovery_msg
                
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
            WALManager.write_wal(tx_id, rollback_stack, session_key)
            
            try:
                for op in payload.operations:
                    msg, rollback_cmds = TransactionManager._execute_single_action(op, session_key)
                    results.append(msg)
                    
                    # Operation succeeded, record its human-readable message trace
                    executed_ops.append(msg)
                    
                    if rollback_cmds:
                        # Append commands in reverse to maintain LIFO execution during rollback
                        rollback_stack.extend(reversed(rollback_cmds))
                        WALManager.write_wal(tx_id, rollback_stack, session_key)
                        
                WALManager.clear_wal()
                return "Transaction completed successfully.\n" + "\n".join(results)
            except Exception as main_err:
                logger_err = _safe_error_message(main_err)
                
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
                    
                    safe_err = _safe_error_message(main_err)
                    # Scrub failed_op before returning to LLM to prevent leaking secret field values
                    scrubbed_failed_op = deep_scrub_payload(failed_op) if failed_op else None
                    err_msg = f"CRITICAL: Transaction failed during the following operation:\n{json.dumps(scrubbed_failed_op, indent=2)}\n\nError: {safe_err}\n\n"
                    err_msg += f"A full rollback was successfully performed. The {len(executed_rolled_back_cmds)} commands executed to revert your previous {len(executed_ops)} operations have reversed the vault back to its pristine state."
                    return err_msg
                else:
                    logger_status = TransactionStatus.ROLLBACK_FAILED
                    safe_err = _safe_error_message(main_err)
                    # Enrich logger_err with the full dual error chain for total log transparency
                    logger_err = f"ExecutionError: {safe_err} | RollbackError: {rb_result['error']}"
                    
                    fatal_msg = f"FATAL ERROR: Transaction failed, AND the rollback mechanism also failed. Vault is in an inconsistent state!\n"
                    fatal_msg += f"Execution Error: {safe_err}\n"
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
        finally:
            if owned_context:
                finalize_execution_context(context)

    @staticmethod
    def _resolve_action_names(operations: List[VaultTransactionAction], session_key: bytearray) -> Dict[str, str]:
        """
        Connects to Bitwarden to resolve UUIDs into human-readable names for UI display,
        and proactively VALIDATES that the UUID points to the correct entity type before any
        operations execute or WALs are created.
        """
        id_to_name = {}
        
        def resolve_and_validate(uid: str, expected_type: str):
            if not uid or uid in id_to_name:
                return
            try:
                # expected_type must be "item", "folder", or "organization"
                entity = SecureSubprocessWrapper.execute_json(["get", expected_type, uid], session_key)
                id_to_name[uid] = entity.get("name", uid)
            except Exception as e:
                # Intercept the hallucination securely, so the error bubbles up cleanly to the LLM
                raise SecureBWError(f"Validation Error: Target '{uid}' is not a valid '{expected_type}' or does not exist. "
                                    f"Ensure you are using the correct action for this entity type. "
                                    f"Original error from CLI: {_safe_error_message(e)}")

        for op in operations:
            # Proper Enum member checking
            is_item_action = isinstance(op.action, (ItemAction, EditAction))
            is_folder_action = isinstance(op.action, FolderAction)
            
            # 1. Validate target_id (the main entity being manipulated)
            if getattr(op, "target_id", None):
                if is_item_action:
                    resolve_and_validate(op.target_id, "item")
                elif is_folder_action:
                    if op.action != FolderAction.CREATE:  # Special case: create folder has no target_id yet
                        resolve_and_validate(op.target_id, "folder")
            
            # 2. Validate folder_id (where items are moved or created)
            if getattr(op, "folder_id", None):
                resolve_and_validate(op.folder_id, "folder")
                
            # 3. Validate organization_id (for collections and org creations)
            if getattr(op, "organization_id", None):
                resolve_and_validate(op.organization_id, "organization")

        return id_to_name

    @staticmethod
    def _execute_refactor_action(op: Any, session_key: bytearray) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        """
        Executes a secure, blind refactoring operation.
        Internal data manipulation is hidden from the MCP tool level.
        """
        # 1. Fetch Source
        source_item = SecureSubprocessWrapper.get_item_raw(op.source_item_id, session_key)
        source_orig = copy.deepcopy(source_item)
        
        # 2. Extract Value
        secret_value = None
        
        if op.scope == RefactorScope.FIELD:
            fields = source_item.get("fields", [])
            found_idx = -1
            for i, f in enumerate(fields):
                if f.get("name") == op.key:
                    secret_value = f.get("value")
                    found_idx = i
                    break
            
            if found_idx != -1 and op.refactor_action in [RefactorAction.MOVE, RefactorAction.DELETE]:
                fields.pop(found_idx)
                source_item["fields"] = fields
        
        elif op.scope == RefactorScope.LOGIN_USER:
            secret_value = source_item.get("login", {}).get("username")
            if op.refactor_action in [RefactorAction.MOVE, RefactorAction.DELETE]:
                if "login" in source_item:
                    source_item["login"]["username"] = None
        
        elif op.scope == RefactorScope.LOGIN_PASS:
            secret_value = source_item.get("login", {}).get("password")
            if op.refactor_action in [RefactorAction.MOVE, RefactorAction.DELETE]:
                if "login" in source_item:
                    source_item["login"]["password"] = None
        
        elif op.scope == RefactorScope.LOGIN_TOTP:
            secret_value = source_item.get("login", {}).get("totp")
            if op.refactor_action in [RefactorAction.MOVE, RefactorAction.DELETE]:
                if "login" in source_item:
                    source_item["login"]["totp"] = None
        
        elif op.scope == RefactorScope.NOTE:
            secret_value = source_item.get("notes")
            if op.refactor_action in [RefactorAction.MOVE, RefactorAction.DELETE]:
                source_item["notes"] = None

        if secret_value is None and op.refactor_action != RefactorAction.DELETE:
            raise SecureBWError(f"Refactor Error: Source field '{op.scope}.{op.key}' not found or empty in item {op.source_item_id}.")

        # 3. Handle COPY/MOVE injection
        dest_orig = None
        dest_item = None
        if op.refactor_action in [RefactorAction.MOVE, RefactorAction.COPY]:
            if not op.dest_item_id:
                raise SecureBWError("Refactor Error: dest_item_id is required for MOVE/COPY operations.")
            
            dest_key = op.dest_key or op.key
            
            if op.dest_item_id == op.source_item_id:
                dest_item = source_item # Pointer to same dict (modified in-place)
                dest_item_id = op.source_item_id
            else:
                dest_item = SecureSubprocessWrapper.get_item_raw(op.dest_item_id, session_key)
                dest_orig = copy.deepcopy(dest_item)
                dest_item_id = op.dest_item_id
            
            # Injection Logic
            if op.scope == RefactorScope.FIELD:
                d_fields = dest_item.setdefault("fields", [])
                found = False
                for f in d_fields:
                    if f.get("name") == dest_key:
                        f["value"] = secret_value
                        found = True
                        break
                if not found:
                    d_fields.append({"name": dest_key, "value": secret_value, "type": 0})
            
            elif op.scope == RefactorScope.LOGIN_USER:
                dest_item.setdefault("login", {})["username"] = secret_value
            
            elif op.scope == RefactorScope.LOGIN_PASS:
                dest_item.setdefault("login", {})["password"] = secret_value
            
            elif op.scope == RefactorScope.LOGIN_TOTP:
                dest_item.setdefault("login", {})["totp"] = secret_value
            
            elif op.scope == RefactorScope.NOTE:
                dest_item["notes"] = secret_value

        # 4. Commit & Rollback Preparation
        rollback_cmds = []
        
        # A. Edit Source (Source is always edited for MOVE/DELETE, or even COPY if we updated source_item object)
        src_payload = base64.b64encode(json.dumps(source_item).encode()).decode()
        SecureSubprocessWrapper.execute(["edit", "item", op.source_item_id, src_payload], session_key)
        
        src_orig_b64 = base64.b64encode(json.dumps(source_orig).encode()).decode()
        rollback_cmds.append({"cmd": ["bw", "edit", "item", op.source_item_id, src_orig_b64]})
        
        # B. Edit Destination (Only if different from source)
        if dest_item and op.dest_item_id != op.source_item_id:
            dst_payload = base64.b64encode(json.dumps(dest_item).encode()).decode()
            SecureSubprocessWrapper.execute(["edit", "item", op.dest_item_id, dst_payload], session_key)
            
            dst_orig_b64 = base64.b64encode(json.dumps(dest_orig).encode()).decode()
            rollback_cmds.append({"cmd": ["bw", "edit", "item", op.dest_item_id, dst_orig_b64]})
            
        msg = f"-> Refactored ({op.refactor_action}) {op.scope}.{op.key} from {op.source_item_id}"
        if op.dest_item_id:
            msg += f" to {op.dest_item_id} (key: {op.dest_key or op.key})"
            
        return msg, rollback_cmds

    @staticmethod
    def _execute_single_action(op: VaultTransactionAction, session_key: bytearray) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        
        # Helper to encapsulate the common get -> edit cycle safely
        def safe_edit_item(target_id: str, field_updater: Callable) -> Tuple[str, List[Dict[str, Any]]]:
            original_item_data = SecureSubprocessWrapper.execute_json(["get", "item", target_id], session_key)
            item_data = copy.deepcopy(original_item_data)
            
            field_updater(item_data)
            # bw edit requires base64-encoded JSON
            encoded_b64 = base64.b64encode(json.dumps(item_data).encode()).decode()
            SecureSubprocessWrapper.execute(["edit", "item", target_id, encoded_b64], session_key)
            
            orig_b64 = base64.b64encode(json.dumps(original_item_data).encode()).decode()
            rollback_cmds = [{"cmd": ["bw", "edit", "item", target_id, orig_b64]}]
                
            return target_id, rollback_cmds

        # --- ITEM ACTIONS ---
        if op.action == ItemAction.CREATE:
            item_tpl = SecureSubprocessWrapper.execute_json(["get", "template", "item"], session_key)
            item_tpl["type"] = op.type
            item_tpl["name"] = op.name
            item_tpl["folderId"] = op.folder_id
            item_tpl["organizationId"] = op.organization_id
            item_tpl["favorite"] = op.favorite
            # Use provided notes or ensure it's empty
            item_tpl["notes"] = op.notes if op.notes else None
            
            if op.type == 1:
                item_tpl["login"] = SecureSubprocessWrapper.execute_json(["get", "template", "item.login"], session_key)
                if op.login:
                    if op.login.username is not None: item_tpl["login"]["username"] = op.login.username
                    if op.login.uris is not None: item_tpl["login"]["uris"] = op.login.uris
            elif op.type == 2:
                # Secure Note
                item_tpl["secureNote"] = SecureSubprocessWrapper.execute_json(["get", "template", "item.secureNote"], session_key)
            elif op.type == 3:
                item_tpl["card"] = SecureSubprocessWrapper.execute_json(["get", "template", "item.card"], session_key)
                if op.card:
                    if op.card.cardholderName is not None: item_tpl["card"]["cardholderName"] = op.card.cardholderName
                    if op.card.brand is not None: item_tpl["card"]["brand"] = op.card.brand
                    if op.card.expMonth is not None: item_tpl["card"]["expMonth"] = op.card.expMonth
                    if op.card.expYear is not None: item_tpl["card"]["expYear"] = op.card.expYear
            elif op.type == 4:
                item_tpl["identity"] = SecureSubprocessWrapper.execute_json(["get", "template", "item.identity"], session_key)
                if op.identity:
                    for k, v in op.identity.model_dump(exclude_none=True).items():
                        if k in item_tpl["identity"]:
                            item_tpl["identity"][k] = v
                
            # bw create requires base64-encoded JSON
            encoded_b64 = base64.b64encode(json.dumps(item_tpl).encode()).decode()
            res_str = SecureSubprocessWrapper.execute(["create", "item", encoded_b64], session_key)

            try:
                new_id = json.loads(res_str).get("id")
            except (json.JSONDecodeError, AttributeError):
                new_id = None

            if not new_id:
                # The item was physically created in Bitwarden (CLI exited 0) but the
                # response is unparseable. We cannot register a rollback command without
                # the UUID. Raising here is safer than returning empty rollback_cmds and
                # silently proceeding — the batch fails loudly, prior ops are reversed,
                # and the user is informed that this specific item may be an orphan.
                raise SecureBWError(
                    f"create_item for '{op.name}' succeeded in Bitwarden but returned no "
                    f"parseable item ID. The item may exist as an orphan in your vault. "
                    f"Rollback of this creation is impossible — please delete it manually via "
                    f"the Bitwarden web vault or CLI. Prior operations in this batch have been rolled back."
                )

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
            
            # Encoded JSON for collection IDs
            encoded_cols = ""
            if op.collection_ids:
                encoded_cols = base64.b64encode(json.dumps(op.collection_ids).encode()).decode()
            
            SecureSubprocessWrapper.execute(["move", op.target_id, op.organization_id, encoded_cols], session_key)
            
            orig_b64 = base64.b64encode(json.dumps(original_item_data).encode()).decode()
            rollback_cmds = [{"cmd": ["bw", "edit", "item", op.target_id, orig_b64]}]
            return f"-> Moved item {op.target_id} to Organization {op.organization_id} (Collections: {op.collection_ids or 'None'})", rollback_cmds

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
            # bw create requires base64-encoded JSON
            encoded_b64 = base64.b64encode(json.dumps(folder_tpl).encode()).decode()
            res_str = SecureSubprocessWrapper.execute(["create", "folder", encoded_b64], session_key)
            
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
            # bw edit requires base64-encoded JSON
            encoded_b64 = base64.b64encode(json.dumps(folder_data).encode()).decode()
            SecureSubprocessWrapper.execute(["edit", "folder", op.target_id, encoded_b64], session_key)
            
            orig_b64 = base64.b64encode(json.dumps(original_folder).encode()).decode()
            rollback_cmds = [{"cmd": ["bw", "edit", "folder", op.target_id, orig_b64]}]
                
            return f"-> Renamed folder {op.target_id} to '{op.new_name}'", rollback_cmds
            
        elif op.action == FolderAction.DELETE:
            SecureSubprocessWrapper.execute(["delete", "folder", op.target_id], session_key)
            # delete_folder is enforced to be a standalone batch (size 1).
            # If it succeeds, there is nothing else in the batch to roll back.
            # If it fails, nothing was executed. Either way, rollback_cmds is empty.
            rollback_cmds = []
            return f"-> Deleted folder {op.target_id}", rollback_cmds

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
            
        elif op.action == EditAction.REFACTOR:
            return TransactionManager._execute_refactor_action(op, session_key)

        else:
            raise ValueError(f"CRITICAL: Unhandled polymorphic action type: {op.action}")
