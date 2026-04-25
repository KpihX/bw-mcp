import os
import sys
import subprocess
import html
from typing import List, Any, Dict, Optional
from .models import TransactionPayload
from .subprocess_wrapper import SecureProxyError
from .web_ui import WebHITLManager

class HITLManager:
    """
    Human-In-The-Loop GUI Manager (Agnostic).
    Uses a browser-based Web UI for all approvals and inputs.
    Falls back to TTY for non-GUI environments.
    """
    
    @staticmethod
    def ask_input(prompt: str, title: str = "BW-Proxy: User Input", password: bool = False) -> str:
        """
        Generic interactive prompt (Web GUI or TTY fallback).
        """
        # 1. Try Web UI (Agnostic GUI)
        try:
            web_data = {
                "rationale": prompt,
                "formatted_ops": [f"Input Required: {title}"],
                "has_destructive": False,
                "needs_password": password,
                "type": "input"
            }
            resp = WebHITLManager.request_approval(web_data)
            if resp and resp.get("approved"):
                if password:
                    pw = resp.get("password")
                    return pw.decode('utf-8') if pw else None
                return "Approved"
        except Exception:
            pass

        # 2. Fallback to TTY (Interactive)
        if sys.stdin.isatty():
            try:
                print(f"\n🔐 {title}")
                if password:
                    import getpass
                    return getpass.getpass(f"{prompt}: ")
                else:
                    return input(f"{prompt}: ")
            except Exception:
                 return None
        
        return None

    @staticmethod
    def ask_master_password(title: str = "BW-MCP: Unlock Vault") -> bytearray:
        """
        Triggers a secure Web popup to ask for the master password.
        Falls back to TTY input (getpass).
        Returns a mutable bytearray to allow manual memory wiping by the caller.
        """
        # 1. Try Web UI (Agnostic GUI)
        try:
            web_data = {
                "rationale": "Authentication Required",
                "formatted_ops": [f"Unlocking Vault: {title}"],
                "has_destructive": False,
                "needs_password": True,
                "type": "auth"
            }
            resp = WebHITLManager.request_approval(web_data)
            if resp and resp.get("approved"):
                return resp.get("password")
        except Exception:
            pass

        # 2. Fallback to TTY (Interactive)
        if sys.stdin.isatty():
            import getpass
            try:
                print(f"\n🔐 {title}")
                passwd = getpass.getpass("Master Password: ")
                if not passwd:
                    return None
                return bytearray(passwd.encode('utf-8'))
            except Exception:
                 return None
        
        return None

    @staticmethod
    def _format_operation(op: Any, id_to_name: Dict[str, str] = None) -> str:
        """Helper to format a specific polymorphic operation for human readability."""
        from .models import ItemAction, FolderAction, EditAction
        from .config import REDACTED_POPULATED, REDACTED_EMPTY
        
        def resolve(uuid: str, prefix: str = "") -> str:
            if not uuid: return "ROOT"
            name = (id_to_name or {}).get(uuid)
            if name: return f"'{html.escape(name)}' ({uuid})"
            return f"{prefix}({uuid})"

        def dict_to_str(d: dict) -> str:
            items = []
            for k, v in d.items():
                if v is None or v == "": continue
                if isinstance(v, str) and (REDACTED_POPULATED in v or REDACTED_EMPTY in v): continue
                val = f"'{html.escape(str(v))}'"
                items.append(f"{k}={val}")
            return " | ".join(items)

        # --- ITEM ACTIONS ---
        if op.action == ItemAction.CREATE:
            t_str = {1: "Login", 2: "SecureNote", 3: "Card", 4: "Identity"}.get(op.type, "Unknown")
            details = []
            if getattr(op, "notes", None): details.append("notes=...")
            if op.type == 1 and getattr(op, "login", None):
                f = dict_to_str(op.login.model_dump(exclude_unset=True))
                if f: details.append(f"login: ({f})")
            elif op.type == 3 and getattr(op, "card", None):
                f = dict_to_str(op.card.model_dump(exclude_unset=True))
                if f: details.append(f"card: ({f})")
            elif op.type == 4 and getattr(op, "identity", None):
                f = dict_to_str(op.identity.model_dump(exclude_unset=True))
                if f: details.append(f"identity: ({f})")
            if getattr(op, "fields", None) and op.fields:
                f_strs = [f"{f.name}={f.value}" for f in op.fields if f.type in [0, 2]]
                if f_strs: details.append(f"custom_fields: ({' | '.join(html.escape(s) for s in f_strs)})")
            d_str = f" [{', '.join(details)}]" if details else ""
            return f"🌟 CREATE ITEM ({t_str}) -> '{html.escape(op.name)}'{d_str}" + (f" in folder {resolve(op.folder_id, 'folder ')}" if op.folder_id else "")
            
        elif op.action == ItemAction.RENAME:
            return f"✏️ RENAME ITEM {resolve(op.target_id)} -> '{html.escape(op.new_name)}'"
        elif op.action == ItemAction.MOVE_TO_FOLDER:
            return f"📂 MOVE ITEM {resolve(op.target_id)} -> to folder {resolve(op.folder_id)}"
        elif op.action == ItemAction.DELETE:
            return f"💥 DELETE ITEM {resolve(op.target_id)}"
        elif op.action == ItemAction.RESTORE:
            return f"♻️ RESTORE ITEM {resolve(op.target_id)} -> From Trash"
        elif op.action == ItemAction.FAVORITE:
            state = "⭐ FAVORITE" if op.favorite else "❌ UNFAVORITE"
            return f"{state} ITEM {resolve(op.target_id)}"
        elif op.action == ItemAction.MOVE_TO_COLLECTION:
            return f"🏢 MOVE TO ORG {resolve(op.target_id)} -> Organization {resolve(op.organization_id)}"
        elif op.action == ItemAction.TOGGLE_REPROMPT:
            state = "🔒 ENABLED" if op.reprompt else "🔓 DISABLED"
            return f"🛡️ REPROMPT {resolve(op.target_id)} -> {state}"
        elif op.action == ItemAction.DELETE_ATTACHMENT:
            return f"💥 DELETE ATTACHMENT ({op.attachment_id}) -> from Item {resolve(op.target_id)}"
            
        # --- FOLDER ACTIONS ---
        elif op.action == FolderAction.CREATE:
            return f"📁 CREATE FOLDER -> '{html.escape(op.name)}'"
        elif op.action == FolderAction.RENAME:
            return f"✏️ RENAME FOLDER {resolve(op.target_id)} -> '{html.escape(op.new_name)}'"
        elif op.action == FolderAction.DELETE:
            return f"💥 DELETE FOLDER {resolve(op.target_id)}"
            
        # --- EDIT ACTIONS ---
        elif op.action == EditAction.LOGIN:
            changes = []
            if getattr(op, "username", None) is not None: changes.append(f"username='{html.escape(op.username)}'")
            if getattr(op, "uris", None) is not None: changes.append(f"uris='{html.escape(str(op.uris))}'")
            return f"🔧 EDIT LOGIN {resolve(op.target_id)} -> {', '.join(changes) if changes else 'No changes'}"
        elif op.action == EditAction.CARD:
            changes = []
            if getattr(op, "cardholderName", None) is not None: changes.append(f"cardholderName='{html.escape(op.cardholderName)}'")
            if getattr(op, "brand", None) is not None: changes.append(f"brand='{html.escape(op.brand)}'")
            return f"💳 EDIT CARD {resolve(op.target_id)} -> {', '.join(changes)}"
        elif op.action == EditAction.IDENTITY:
            changes = []
            for f in ["firstName", "lastName", "email"]:
                val = getattr(op, f, None)
                if val: changes.append(f"{f}='{html.escape(val)}'")
            return f"🪪 EDIT IDENTITY {resolve(op.target_id)} -> {', '.join(changes)}"
        elif op.action == EditAction.CUSTOM_FIELD:
            return f"🏷️ UPSERT FIELD {resolve(op.target_id)} -> '{html.escape(op.name)}' = '{html.escape(str(op.value))}'"
        elif op.action == EditAction.REFACTOR:
            dest = f" -> {resolve(op.dest_item_id)}" if op.dest_item_id else ""
            icon = {"move": "🚚 MOVE", "copy": "📋 COPY", "delete": "💥 DELETE"}.get(op.refactor_action, "⚙️ REFACTOR")
            return f"{icon} SECRET '{html.escape(op.key)}' from {resolve(op.source_item_id)}{dest}"
            
        return f"❓ UNKNOWN ACTION: {op.action}"

    @staticmethod
    def review_transaction(payload: TransactionPayload, id_to_name: dict = None) -> bool:
        """
        Displays a Web dialog with the list of operations proposed by the agent.
        """
        from .models import ItemAction, FolderAction, RefactorAction, EditAction
        
        has_destructive = any(
            op.action in [ItemAction.DELETE, ItemAction.DELETE_ATTACHMENT, FolderAction.DELETE] or 
            (op.action == EditAction.REFACTOR and op.refactor_action in ["move", "delete"])
            for op in payload.operations
        )
        
        # 1. Try Web UI (Agnostic GUI)
        try:
            web_data = {
                "type": "transaction",
                "rationale": payload.rationale,
                "formatted_ops": [HITLManager._format_operation(op, id_to_name) for op in payload.operations],
                "has_destructive": has_destructive,
                "needs_password": True
            }
            resp = WebHITLManager.request_approval(web_data)
            if resp:
                return resp.get("approved", False)
        except Exception:
            pass

        # 2. Fallback to TTY
        if sys.stdin.isatty():
            title = "⚠️ CRITICAL TRANSACTION" if has_destructive else "Transaction Review"
            print(f"\n{title}")
            print(f"Rationale: {payload.rationale}")
            for i, op in enumerate(payload.operations, 1):
                print(f"{i}. {HITLManager._format_operation(op, id_to_name)}")
            confirm = input("\nDo you approve these changes? (y/n): ")
            return confirm.lower().startswith('y')

        raise SecureProxyError("No GUI available and not in an interactive terminal.")

    @staticmethod
    def review_comparisons(payload: Any, id_to_name: dict = None) -> bool:
        """
        Displays a Web dialog for secret comparisons.
        """
        def resolve(uuid: str) -> str:
            name = (id_to_name or {}).get(uuid)
            return name if name else uuid
            
        comparisons = []
        for req in payload.comparisons:
            a_field = req.custom_name_a or req.field_a
            b_field = req.custom_name_b or req.field_b
            comparisons.append({
                "name_a": resolve(req.item_id_a),
                "name_b": resolve(req.item_id_b),
                "field": f"{a_field} ↔️ {b_field}",
                "result": "PENDING"
            })

        # 1. Try Web UI
        try:
            web_data = {
                "type": "comparison",
                "rationale": payload.rationale,
                "comparisons": comparisons,
                "match_tag": "MATCH",
                "needs_password": True
            }
            resp = WebHITLManager.request_approval(web_data)
            if resp:
                return resp.get("approved", False)
        except Exception:
            pass

        # 2. Fallback to TTY
        if sys.stdin.isatty():
            print(f"\n⚖️ Security Audit: Private Secret Comparison")
            print(f"Rationale: {payload.rationale}")
            for i, c in enumerate(comparisons, 1):
                print(f"{i}. {c['name_a']} vs {c['name_b']} [{c['field']}]")
            confirm = input("\nAuthorize these blind comparisons? (y/n): ")
            return confirm.lower().startswith('y')

        raise SecureProxyError("No GUI available and not in an interactive terminal.")

    @staticmethod
    def review_duplicate_scan(payload: Any, id_to_name: dict = None) -> bool:
        """
        Human-in-the-loop for bulk duplicate scans via Web UI.
        """
        def resolve(uuid: str) -> str:
            name = (id_to_name or {}).get(uuid)
            return name if name else uuid
            
        from .models import FindDuplicatesPayload, FindDuplicatesBatchPayload, FindAllDuplicatesPayload
        
        target_name = "Global Scan"
        field_path = "*"
        targets = []
        
        if isinstance(payload, FindDuplicatesPayload):
            target_name = resolve(payload.target_id)
            field_path = payload.field
            targets = [{"name": target_name, "id": field_path}]
        elif isinstance(payload, FindDuplicatesBatchPayload):
            target_name = "Batch Scan"
            field_path = "Multiple"
            targets = [{"name": resolve(t.target_id), "id": t.field} for t in payload.targets]
        elif isinstance(payload, FindAllDuplicatesPayload):
            target_name = "Total Vault"
            field_path = "All Secrets"
            targets = [{"name": "Vault", "id": "All"}]

        # 1. Try Web UI
        try:
            web_data = {
                "type": "duplicate_scan",
                "rationale": payload.rationale,
                "target_name": target_name,
                "field_path": field_path,
                "duplicates": targets,
                "needs_password": True
            }
            resp = WebHITLManager.request_approval(web_data)
            if resp:
                return resp.get("approved", False)
        except Exception:
            pass

        # 2. Fallback to TTY
        if sys.stdin.isatty():
            print(f"\n🔍 Bulk Audit: Secret Duplicate Finder")
            print(f"Rationale: {payload.rationale}")
            print(f"Target: {target_name} [{field_path}]")
            confirm = input("\nAuthorize this blind scan? (y/n): ")
            return confirm.lower().startswith('y')

        raise SecureProxyError("No GUI available and not in an interactive terminal.")
