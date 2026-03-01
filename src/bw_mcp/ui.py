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
        
        def resolve(uuid: str, prefix: str = "") -> str:
            if not uuid: return "ROOT"
            name = (id_to_name or {}).get(uuid)
            if name: return f"'{html.escape(name)}'"
            return f"{prefix}({uuid})"

        # --- ITEM ACTIONS ---
        if op.action == ItemAction.CREATE:
            t_str = {1: "Login", 2: "SecureNote", 3: "Card", 4: "Identity"}.get(op.type, "Unknown")
            # If creating a new item, op.name is available directly
            return f"🌟 CREATE ITEM ({t_str}) -> '{html.escape(op.name)}'" + (f" in folder {resolve(op.folder_id, 'folder ')}" if op.folder_id else "")
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
            if op.username: changes.append(f"Username='{html.escape(op.username)}'")
            if op.uris: changes.append(f"URIs={len(op.uris)} values")
            return f"🔧 EDIT LOGIN {resolve(op.target_id)} -> {', '.join(changes)}"
        elif op.action == EditAction.CARD:
            changes = []
            if op.cardholderName: changes.append("Name")
            if op.brand: changes.append("Brand")
            if op.expMonth or op.expYear: changes.append("Expiry")
            return f"💳 EDIT CARD {resolve(op.target_id)} -> {', '.join(changes)}"
        elif op.action == EditAction.IDENTITY:
            return f"🪪 EDIT IDENTITY {resolve(op.target_id)} -> Updated contact fields"
        elif op.action == EditAction.CUSTOM_FIELD:
            t_str = "Text" if op.type == 0 else "Boolean"
            return f"🏷️ UPSERT FIELD {resolve(op.target_id)} -> [{t_str}] '{html.escape(op.name)}' = '{html.escape(op.value)}'"
            
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
        
        # Check for destructive operations
        has_destructive = any(op.action in ["delete_item", "delete_folder"] for op in payload.operations)
        
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
