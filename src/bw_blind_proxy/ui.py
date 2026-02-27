import subprocess
from typing import List, Any
from .config import load_config
from .models import TransactionPayload

class HITLManager:
    """
    Human-In-The-Loop GUI Manager.
    Uses Zenity to provide a native Ubuntu GUI for Master Password prompting 
    and transaction review. Now includes extreme warnings for deletions.
    """
    
    @staticmethod
    def ask_master_password(title: str = "BW-Blind-Proxy: Unlock Vault") -> str:
        """
        Triggers a secure Zenity popup to ask for the master password.
        """
        try:
            result = subprocess.run(
                ["zenity", "--password", f"--title={title}"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise ValueError("Password prompt cancelled by user.")
            return result.stdout.strip()
            
        except FileNotFoundError:
            raise RuntimeError("Zenity is not installed. Please install it with: sudo apt install zenity")

    @staticmethod
    def _format_operation(op: Any) -> str:
        """Helper to format a specific polymorphic operation for human readability."""
        from .models import ItemAction, FolderAction, EditAction
        
        # --- ITEM ACTIONS ---
        if op.action == ItemAction.RENAME:
            return f"✏️ RENAME ITEM ({op.target_id}) -> '{op.new_name}'"
        elif op.action == ItemAction.MOVE_TO_FOLDER:
            return f"📂 MOVE ITEM ({op.target_id}) -> to folder '{op.folder_id or 'ROOT'}'"
        elif op.action == ItemAction.DELETE:
            return f"💥 DELETE ITEM ({op.target_id})"
        elif op.action == ItemAction.RESTORE:
            return f"♻️ RESTORE ITEM ({op.target_id}) -> From Trash"
        elif op.action == ItemAction.FAVORITE:
            state = "⭐ FAVORITE" if op.favorite else "❌ UNFAVORITE"
            return f"{state} ITEM ({op.target_id})"
        elif op.action == ItemAction.MOVE_TO_COLLECTION:
            return f"🏢 MOVE TO ORG ({op.target_id}) -> Organization '{op.organization_id}'"
        elif op.action == ItemAction.TOGGLE_REPROMPT:
            state = "🔒 ENABLED" if op.reprompt else "🔓 DISABLED"
            return f"🛡️ REPROMPT ({op.target_id}) -> {state}"
        elif op.action == ItemAction.DELETE_ATTACHMENT:
            return f"💥 DELETE ATTACHMENT ({op.attachment_id}) -> from Item '{op.target_id}'"
            
        # --- FOLDER ACTIONS ---
        elif op.action == FolderAction.CREATE:
            return f"📁 CREATE FOLDER -> '{op.name}'"
        elif op.action == FolderAction.RENAME:
            return f"✏️ RENAME FOLDER ({op.target_id}) -> '{op.new_name}'"
        elif op.action == FolderAction.DELETE:
            return f"💥 DELETE FOLDER ({op.target_id})"
            
        # --- EDIT ACTIONS ---
        elif op.action == EditAction.LOGIN:
            changes = []
            if op.username: changes.append(f"Username='{op.username}'")
            if op.uris: changes.append(f"URIs={len(op.uris)} values")
            return f"🔧 EDIT LOGIN ({op.target_id}) -> {', '.join(changes)}"
        elif op.action == EditAction.CARD:
            changes = []
            if op.cardholderName: changes.append("Name")
            if op.brand: changes.append("Brand")
            if op.expMonth or op.expYear: changes.append("Expiry")
            return f"💳 EDIT CARD ({op.target_id}) -> {', '.join(changes)}"
        elif op.action == EditAction.IDENTITY:
            return f"🪪 EDIT IDENTITY ({op.target_id}) -> Updated contact fields"
        elif op.action == EditAction.CUSTOM_FIELD:
            t_str = "Text" if op.type == 0 else "Boolean"
            return f"🏷️ UPSERT FIELD ({op.target_id}) -> [{t_str}] '{op.name}' = '{op.value}'"
            
        return f"❓ UNKNOWN ACTION: {op.action}"

    @staticmethod
    def review_transaction(payload: TransactionPayload) -> bool:
        """
        Displays a Zenity dialog with the list of operations proposed by the agent.
        If any operation is destructive (delete), it uses a Warning dialog.
        """
        formatted_ops = "\n".join(
            f"{i}. {HITLManager._format_operation(op)}" 
            for i, op in enumerate(payload.operations, 1)
        )
        
        # Check for destructive operations
        has_destructive = any(op.action in ["delete_item", "delete_folder"] for op in payload.operations)
        
        if has_destructive:
            dialog_type = "--warning"
            title = "⚠️ CRITICAL: Review Destructive Vault Transaction"
            text_header = "<span color='red' size='x-large'><b>⚠️ WARNING: DESTRUCTIVE OPERATIONS DETECTED</b></span>\n\nThe AI Agent proposes these operations which include irreversible deletions:"
        else:
            dialog_type = "--question"
            title = "Review Proposed Vault Transaction"
            text_header = "The AI Agent proposes the following batch operations:"

        # We must use Pango markup to ensure colors render nicely in Zenity warning boxes.
        text = f"{text_header}\n\n<b>Operations:</b>\n{formatted_ops}\n\n<b>Rationale:</b> {payload.rationale}\n\nDo you explicitly approve these changes?"
        
        try:
            # Zenity --warning doesn't always have a Cancel button by default, 
            # but we can force question-like behavior for warnings, or just accept that OK continues. 
            # In Linux, zenity --question with an icon is better for Yes/No with markup.
            
            cmd = [
                "zenity", dialog_type,
                f"--title={title}",
                "--text", text,
                "--width=700",
                "--height=500"
            ]
            
            # If we want a warning that asks Yes/No
            if has_destructive:
                # Combining warning icon with question dialog
                cmd = [
                    "zenity", "--question",
                    "--icon-name=dialog-warning",
                    f"--title={title}",
                    "--text", text,
                    "--width=700",
                    "--height=500"
                ]
                
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
            
        except FileNotFoundError:
            raise RuntimeError("Zenity is not installed.")
