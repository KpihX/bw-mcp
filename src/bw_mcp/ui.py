import subprocess
import html
from typing import List, Any, Dict
from .models import TransactionPayload

class HITLManager:
    """
    Human-In-The-Loop GUI Manager.
    Uses Zenity to provide a native Ubuntu GUI for Master Password prompting 
    and transaction review. Now includes extreme warnings for deletions.
    """
    
    @staticmethod
    def ask_master_password(title: str = "BW-MCP: Unlock Vault") -> bytearray:
        """
        Triggers a secure Zenity popup to ask for the master password.
        Returns a mutable bytearray to allow manual memory wiping by the caller.
        """
        try:
            # text=False prevents Python from caching an immutable string in RAM
            result = subprocess.run(
                ["zenity", "--password", f"--title={title}"],
                capture_output=True,
                text=False
            )
            if result.returncode != 0:
                raise ValueError("Password prompt cancelled by user.")
                
            # Convert raw bytes directly to mutable bytearray and strip trailing newlines
            pw_bytes = bytearray(result.stdout)
            while pw_bytes and pw_bytes[-1] in (b'\n'[0], b'\r'[0]):
                pw_bytes.pop()
                
            return pw_bytes
            
        except FileNotFoundError:
            raise RuntimeError("Zenity is not installed. Please install it with: sudo apt install zenity")

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
                # Do not show proxy redacted tags in the UI
                if isinstance(v, str) and (REDACTED_POPULATED in v or REDACTED_EMPTY in v): continue
                
                if isinstance(v, list):
                    if not v: continue
                    val = f"'{html.escape(str(v))}'"
                else:
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
            if getattr(op, "username", None) is not None: 
                changes.append(f"username='{html.escape(op.username)}'")
            if getattr(op, "uris", None) is not None:
                changes.append(f"uris='{html.escape(str(op.uris))}'")
            return f"🔧 EDIT LOGIN {resolve(op.target_id)} -> {', '.join(changes) if changes else 'No changes'}"
            
        elif op.action == EditAction.CARD:
            changes = []
            if getattr(op, "cardholderName", None) is not None: changes.append(f"cardholderName='{html.escape(op.cardholderName)}'")
            if getattr(op, "brand", None) is not None: changes.append(f"brand='{html.escape(op.brand)}'")
            if getattr(op, "expMonth", None) is not None: changes.append(f"expMonth='{html.escape(op.expMonth)}'")
            if getattr(op, "expYear", None) is not None: changes.append(f"expYear='{html.escape(op.expYear)}'")
            return f"💳 EDIT CARD {resolve(op.target_id)} -> {', '.join(changes) if changes else 'No changes'}"
            
        elif op.action == EditAction.IDENTITY:
            fields = ["title", "firstName", "middleName", "lastName", "address1", "address2", "address3", "city", "state", "postalCode", "country", "company", "email", "phone", "username"]
            changes = []
            for f in fields:
                val = getattr(op, f, None)
                if val is not None:
                    changes.append(f"{f}='{html.escape(val)}'")
            return f"🪪 EDIT IDENTITY {resolve(op.target_id)} -> {', '.join(changes) if changes else 'No changes'}"
            
        elif op.action == EditAction.CUSTOM_FIELD:
            t_str = "Text" if getattr(op, "type", 0) == 0 else "Boolean"
            # Values are coerced to string for Custom Fields, but handle None just in case
            val_str = html.escape(str(op.value)) if op.value is not None else ""
            return f"🏷️ UPSERT FIELD {resolve(op.target_id)} -> [{t_str}] '{html.escape(op.name)}' = '{val_str}'"
            
        return f"❓ UNKNOWN ACTION: {op.action}"

    @staticmethod
    def review_transaction(payload: TransactionPayload, id_to_name: dict = None) -> bool:
        """
        Displays a Zenity dialog with the list of operations proposed by the agent.
        If any operation is destructive (delete), it uses a Warning dialog.
        """
        formatted_ops = "\n".join(
            f"{i}. {HITLManager._format_operation(op, id_to_name)}" 
            for i, op in enumerate(payload.operations, 1)
        )
        
        from .models import ItemAction, FolderAction
        # Check for destructive operations using Enums instead of hardcoded strings
        has_destructive = any(op.action in [ItemAction.DELETE, ItemAction.DELETE_ATTACHMENT, FolderAction.DELETE] for op in payload.operations)
        
        if has_destructive:
            # dialog_type is always --question for Yes/No semantics.
            # Destructive ops add --icon-name=dialog-warning to show a red icon.
            # 1. Use GTK4-compatible 'foreground' attribute (deprecated 'color' silently breaks Pango in GTK4,
            #    causing the entire text area to render blank).
            # 2. Keep a plain-text emoji prefix OUTSIDE the span so that even if Pango skips the span,
            #    the user still sees the ⚠️ RED ALERT heading.
            title = "⚠️ CRITICAL: Review Destructive Vault Transaction"
            text_header = "⚠️ RED ALERT: DESTRUCTIVE OPERATIONS DETECTED\n<span foreground='red' size='large'><b>This action is IRREVERSIBLE. Read carefully before approving.</b></span>\n\nThe AI Agent proposes these operations which include irreversible deletions:"
        else:
            title = "Review Proposed Vault Transaction"
            text_header = "The AI Agent proposes the following batch operations:"

        # We must use Pango markup to ensure colors render nicely in Zenity warning boxes.
        text = f"{text_header}\n\n<b>Operations:</b>\n{formatted_ops}\n\n<b>Rationale:</b> {html.escape(payload.rationale)}\n\nDo you explicitly approve these changes?"
        
        try:
            # Always use --question for Yes/No semantics.
            # Destructive operations add --icon-name=dialog-warning for a red icon.
            # Non-destructive operations use the default info icon.
            if has_destructive:
                cmd = [
                    "zenity", "--question",
                    "--icon-name=dialog-warning",
                    f"--title={title}",
                    "--text", text,
                    "--width=700",
                    "--height=500"
                ]
            else:
                cmd = [
                    "zenity", "--question",
                    f"--title={title}",
                    "--text", text,
                    "--width=700",
                    "--height=500"
                ]
                
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
            
        except FileNotFoundError:
            raise RuntimeError("Zenity is not installed.")

    @staticmethod
    def review_comparisons(payload: Any, id_to_name: dict = None) -> bool:
        """
        Displays a Zenity dialog with the list of blind comparisons proposed by the agent.
        Now shows dynamic field paths clearly.
        """
        def format_req(req, idx):
            def resolve(uuid: str) -> str:
                name = (id_to_name or {}).get(uuid)
                return f"'{html.escape(name)}'" if name else f"({uuid})"
            
            a_field = f"'{html.escape(req.custom_name_a)}'" if req.custom_name_a else req.field_a
            b_field = f"'{html.escape(req.custom_name_b)}'" if req.custom_name_b else req.field_b
            
            return f"{idx}. ⚖️ <b>{resolve(req.item_id_a)}</b> [{a_field}] ↔️ <b>{resolve(req.item_id_b)}</b> [{b_field}]"

        formatted_ops = "\n".join(
            format_req(req, i) for i, req in enumerate(payload.comparisons, 1)
        )
        
        title = "🔒 Security Audit: Private Secret Comparison"
        text_header = "The AI Agent requests <b>Blind Comparisons</b> between secrets.\n"
        text_header += "<span foreground='blue'>The AI will only see 'MATCH' or 'MISMATCH'. It will NOT see the content.</span>"
        
        text = f"{text_header}\n\n<b>Comparisons (Read-Only):</b>\n{formatted_ops}\n\n<b>Rationale:</b> {html.escape(payload.rationale)}\n\nDo you grant permission to perform this blind audit?"
        
        try:
            cmd = [
                "zenity", "--question",
                f"--title={title}",
                "--text", text,
                "--width=750",
                "--height=550"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            raise RuntimeError("Zenity is not installed.")

    @staticmethod
    def review_duplicate_scan(payload: Any, id_to_name: dict = None) -> bool:
        """
        Human-in-the-loop for bulk duplicate scans (Single or Batch).
        """
        def resolve(uuid: str) -> str:
            name = (id_to_name or {}).get(uuid)
            return f"'{html.escape(name)}'" if name else f"({uuid})"
            
        title = "🔍 Bulk Audit: Secret Duplicate Finder"
        text_header = f"The AI Agent requests a <b>Blind Secret Scan</b> of your vault.\n"
        text_header += "<span foreground='blue'>Results will only list IDs that match your target secrets. The actual text remains hidden.</span>"

        # Handle Single vs Batch payloads
        from .models import FindDuplicatesPayload, FindDuplicatesBatchPayload, FindAllDuplicatesPayload
        
        details = []
        if isinstance(payload, FindDuplicatesPayload):
            target = resolve(payload.target_id)
            field = html.escape(payload.field)
            cand_field = html.escape(payload.candidate_field or field)
            details.append(f"• <b>Target:</b> {target} [field: {field}]")
            details.append(f"• <b>Searching in:</b> candidates [field: {cand_field}]")
        elif isinstance(payload, FindDuplicatesBatchPayload):
            details.append("<b>Batch Targets:</b>")
            for t in payload.targets:
                target = resolve(t.target_id)
                field = html.escape(t.field)
                details.append(f"  - {target} [field: {field}]")
        elif isinstance(payload, FindAllDuplicatesPayload):
            details.append("🌐 <b>Mode: Total Vault Collision Scan</b>")
            details.append("This will scan <b>ALL secrets</b> across <b>ALL items</b> to find reuse.")
        
        count = len(getattr(payload, 'candidate_ids', []) or [])
        cand_str = f"{count} items" if count > 0 else "ALL (restricted by type)"
        
        text = (
            f"{text_header}\n\n"
            f"{chr(10).join(details)}\n"
            f"• <b>Candidate Pool:</b> {cand_str}\n\n"
            f"<b>Rationale:</b> {html.escape(payload.rationale)}\n\n"
            f"Do you grant permission to perform this scan?"
        )
        
        try:
            cmd = [
                "zenity", "--question",
                f"--title={title}",
                "--text", text,
                "--width=700",
                "--height=500"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            raise RuntimeError("Zenity is not installed.")
 
