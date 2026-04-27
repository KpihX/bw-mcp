import getpass
import html
import json
import sys
from typing import Any, Dict, Optional

from .config import HITL_VALIDATION_MODE
from .models import TransactionPayload
from .scrubber import deep_scrub_payload
from .subprocess_wrapper import SecureProxyError
from .web_ui import WebHITLManager


class HITLManager:
    """
    Human-in-the-loop manager.

    Validation content is built once, then rendered either through the browser
    or through the terminal fallback. This prevents browser/TTY drift.
    """

    @staticmethod
    def _prefers_browser() -> bool:
        return HITL_VALIDATION_MODE == "browser"

    @staticmethod
    def _safe_title(data: Dict[str, Any]) -> str:
        return data.get("review_title") or data.get("prompt_title") or "BW-Proxy Validation"

    @staticmethod
    def _render_terminal_review(data: Dict[str, Any]) -> None:
        title = HITLManager._safe_title(data)
        print(f"\n=== {title} ===")

        rationale = data.get("rationale")
        if rationale:
            print(f"Rationale: {rationale}")

        notice = data.get("review_notice")
        if notice:
            print(f"Notice: {notice}")

        if data.get("has_destructive"):
            print("Warning: destructive or irreversible operations detected.")

        if data.get("operations_details"):
            print("\nDetailed Operations:")
            for idx, op in enumerate(data["operations_details"], 1):
                print(f"{idx}. {op.get('summary', '')}")
                for ref in op.get("resolved_refs", []):
                    ref_name = ref.get("name")
                    suffix = f" ({ref_name})" if ref_name else ""
                    print(f"   - {ref.get('field')}: {ref.get('id')}{suffix}")
                raw_json = op.get("raw_json")
                if raw_json:
                    print("   Payload:")
                    for line in raw_json.splitlines():
                        print(f"     {line}")
        elif data.get("comparisons"):
            print("\nComparisons:")
            for idx, comparison in enumerate(data["comparisons"], 1):
                print(
                    f"{idx}. {comparison.get('name_a')} vs {comparison.get('name_b')} "
                    f"[{comparison.get('field')}]"
                )
        elif data.get("duplicates"):
            print("\nScan Targets:")
            for idx, target in enumerate(data["duplicates"], 1):
                print(f"{idx}. {target.get('name')} [{target.get('id')}]")
        elif data.get("formatted_ops"):
            print("\nSummary:")
            for idx, op in enumerate(data["formatted_ops"], 1):
                print(f"{idx}. {op}")

    @staticmethod
    def _terminal_prompt(data: Dict[str, Any]) -> Dict[str, Any]:
        flow = data.get("flow", "prompt")
        prompt_title = data.get("prompt_title") or HITLManager._safe_title(data)
        input_kind = data.get("input_kind", "text")
        prompt_label = data.get("input_label") or "Input"
        placeholder = data.get("input_placeholder") or ""
        primary_action = data.get("primary_action") or "Continue"
        response: Dict[str, Any] = {"approved": False}

        captured_text: Optional[str] = None
        captured_password: Optional[bytearray] = None

        if flow in {"prompt", "prompt_review"}:
            print(f"\n=== {prompt_title} ===")
            if data.get("rationale"):
                print(data["rationale"])
            if placeholder:
                print(f"Hint: {placeholder}")

            if input_kind == "password":
                raw_password = getpass.getpass(f"{prompt_label}: ")
                if not raw_password:
                    return response
                captured_password = bytearray(raw_password.encode("utf-8"))
            else:
                captured_text = input(f"{prompt_label}: ").strip()
                if not captured_text:
                    return response

            if flow == "prompt":
                response["approved"] = True
                if captured_password is not None:
                    response["password"] = captured_password
                if captured_text is not None:
                    response["input_text"] = captured_text
                return response

        HITLManager._render_terminal_review(data)
        confirm = input(f"\n{primary_action}? (y/n): ").strip().lower()
        if not confirm.startswith("y"):
            return response

        response["approved"] = True
        if captured_password is not None:
            response["password"] = captured_password
        if captured_text is not None:
            response["input_text"] = captured_text
        return response

    @staticmethod
    def _request_validation(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        browser_first = HITLManager._prefers_browser()

        if browser_first:
            try:
                resp = WebHITLManager.request_approval(data)
                if resp is not None:
                    return resp
            except Exception:
                pass

            if sys.stdin.isatty():
                return HITLManager._terminal_prompt(data)
            raise SecureProxyError("Browser validation failed and no interactive terminal fallback is available.")

        if sys.stdin.isatty():
            return HITLManager._terminal_prompt(data)

        try:
            resp = WebHITLManager.request_approval(data)
            if resp is not None:
                return resp
        except Exception:
            pass
        raise SecureProxyError("Terminal validation was requested but no interactive terminal is available.")

    @staticmethod
    def ask_input(prompt: str, title: str = "BW-Proxy: User Input", password: bool = False) -> Optional[str]:
        data = {
            "type": "input",
            "flow": "prompt",
            "rationale": prompt,
            "prompt_title": title,
            "input_kind": "password" if password else "text",
            "input_label": "Master Password" if password else "Value",
            "input_placeholder": prompt,
            "primary_action": "Submit",
        }
        resp = HITLManager._request_validation(data)
        if not resp or not resp.get("approved"):
            return None
        if password:
            pw = resp.get("password")
            return pw.decode("utf-8") if pw else None
        return resp.get("input_text")

    @staticmethod
    def ask_master_password(title: str = "BW-Proxy: Unlock Vault") -> Optional[bytearray]:
        data = {
            "type": "auth",
            "flow": "prompt",
            "rationale": "Authentication Required",
            "prompt_title": title,
            "input_kind": "password",
            "input_label": "Master Password",
            "input_placeholder": "Enter your master password",
            "primary_action": "Unlock",
        }
        resp = HITLManager._request_validation(data)
        if resp and resp.get("approved"):
            return resp.get("password")
        return None

    @staticmethod
    def _authorize_review(data: Dict[str, Any], *, needs_password: bool = False) -> Dict[str, Any]:
        payload = dict(data)
        if needs_password:
            payload["flow"] = "prompt_review"
            payload.setdefault("prompt_title", "Unlock Vault")
            payload.setdefault("input_kind", "password")
            payload.setdefault("input_label", "Master Password")
            payload.setdefault("input_placeholder", "Enter your master password")
        else:
            payload["flow"] = "review"
        return HITLManager._request_validation(payload) or {"approved": False}

    @staticmethod
    def _format_operation(op: Any, id_to_name: Dict[str, str] | None = None) -> str:
        """Render one polymorphic operation as a stable human-readable summary."""
        from .config import REDACTED_EMPTY, REDACTED_POPULATED
        from .models import EditAction, FolderAction, ItemAction

        def resolve(uuid: str, prefix: str = "") -> str:
            if not uuid:
                return "ROOT"
            name = (id_to_name or {}).get(uuid)
            if name:
                return f"'{html.escape(name)}' ({uuid})"
            return f"{prefix}({uuid})"

        def dict_to_str(values: dict) -> str:
            items = []
            for key, value in values.items():
                if value is None or value == "":
                    continue
                if isinstance(value, str) and (REDACTED_POPULATED in value or REDACTED_EMPTY in value):
                    continue
                items.append(f"{key}='{html.escape(str(value))}'")
            return " | ".join(items)

        if op.action == ItemAction.CREATE:
            type_name = {1: "Login", 2: "SecureNote", 3: "Card", 4: "Identity"}.get(op.type, "Unknown")
            details = []
            if getattr(op, "notes", None):
                details.append("notes=...")
            if op.type == 1 and getattr(op, "login", None):
                fields = dict_to_str(op.login.model_dump(exclude_unset=True))
                if fields:
                    details.append(f"login: ({fields})")
            elif op.type == 3 and getattr(op, "card", None):
                fields = dict_to_str(op.card.model_dump(exclude_unset=True))
                if fields:
                    details.append(f"card: ({fields})")
            elif op.type == 4 and getattr(op, "identity", None):
                fields = dict_to_str(op.identity.model_dump(exclude_unset=True))
                if fields:
                    details.append(f"identity: ({fields})")
            if getattr(op, "fields", None):
                field_pairs = [f"{field.name}={field.value}" for field in op.fields if field.type in [0, 2]]
                if field_pairs:
                    details.append(f"custom_fields: ({' | '.join(html.escape(item) for item in field_pairs)})")
            detail_suffix = f" [{', '.join(details)}]" if details else ""
            folder_suffix = f" in folder {resolve(op.folder_id, 'folder ')}" if op.folder_id else ""
            return f"🌟 CREATE ITEM ({type_name}) -> '{html.escape(op.name)}'{detail_suffix}{folder_suffix}"

        if op.action == ItemAction.RENAME:
            return f"✏️ RENAME ITEM {resolve(op.target_id)} -> '{html.escape(op.new_name)}'"
        if op.action == ItemAction.MOVE_TO_FOLDER:
            return f"📂 MOVE ITEM {resolve(op.target_id)} -> to folder {resolve(op.folder_id)}"
        if op.action == ItemAction.DELETE:
            return f"💥 DELETE ITEM {resolve(op.target_id)}"
        if op.action == ItemAction.RESTORE:
            return f"♻️ RESTORE ITEM {resolve(op.target_id)} -> From Trash"
        if op.action == ItemAction.FAVORITE:
            state = "⭐ FAVORITE" if op.favorite else "❌ UNFAVORITE"
            return f"{state} ITEM {resolve(op.target_id)}"
        if op.action == ItemAction.MOVE_TO_COLLECTION:
            return f"🏢 MOVE TO ORG {resolve(op.target_id)} -> Organization {resolve(op.organization_id)}"
        if op.action == ItemAction.TOGGLE_REPROMPT:
            state = "🔒 ENABLED" if op.reprompt else "🔓 DISABLED"
            return f"🛡️ REPROMPT {resolve(op.target_id)} -> {state}"
        if op.action == ItemAction.DELETE_ATTACHMENT:
            return f"💥 DELETE ATTACHMENT ({op.attachment_id}) -> from Item {resolve(op.target_id)}"
        if op.action == FolderAction.CREATE:
            return f"📁 CREATE FOLDER -> '{html.escape(op.name)}'"
        if op.action == FolderAction.RENAME:
            return f"✏️ RENAME FOLDER {resolve(op.target_id)} -> '{html.escape(op.new_name)}'"
        if op.action == FolderAction.DELETE:
            return f"💥 DELETE FOLDER {resolve(op.target_id)}"
        if op.action == EditAction.LOGIN:
            changes = []
            if getattr(op, "username", None) is not None:
                changes.append(f"username='{html.escape(op.username)}'")
            if getattr(op, "uris", None) is not None:
                changes.append(f"uris='{html.escape(str(op.uris))}'")
            return f"🔧 EDIT LOGIN {resolve(op.target_id)} -> {', '.join(changes) if changes else 'No changes'}"
        if op.action == EditAction.CARD:
            changes = []
            if getattr(op, "cardholderName", None) is not None:
                changes.append(f"cardholderName='{html.escape(op.cardholderName)}'")
            if getattr(op, "brand", None) is not None:
                changes.append(f"brand='{html.escape(op.brand)}'")
            return f"💳 EDIT CARD {resolve(op.target_id)} -> {', '.join(changes)}"
        if op.action == EditAction.IDENTITY:
            changes = []
            for field_name in ("firstName", "lastName", "email"):
                value = getattr(op, field_name, None)
                if value:
                    changes.append(f"{field_name}='{html.escape(value)}'")
            return f"🪪 EDIT IDENTITY {resolve(op.target_id)} -> {', '.join(changes)}"
        if op.action == EditAction.CUSTOM_FIELD:
            return f"🏷️ UPSERT FIELD {resolve(op.target_id)} -> '{html.escape(op.name)}' = '{html.escape(str(op.value))}'"
        if op.action == EditAction.REFACTOR:
            dest = f" -> {resolve(op.dest_item_id)}" if op.dest_item_id else ""
            icon = {"move": "🚚 MOVE", "copy": "📋 COPY", "delete": "💥 DELETE"}.get(op.refactor_action, "⚙️ REFACTOR")
            return f"{icon} SECRET '{html.escape(op.key)}' from {resolve(op.source_item_id)}{dest}"
        return f"❓ UNKNOWN ACTION: {op.action}"

    @staticmethod
    def _serialize_operation_details(op: Any, id_to_name: Dict[str, str] | None = None) -> Dict[str, Any]:
        scrubbed = deep_scrub_payload(op.model_dump(exclude_none=True))
        resolved_refs = []
        for field_name in ("target_id", "folder_id", "organization_id", "source_item_id", "dest_item_id"):
            raw_value = scrubbed.get(field_name)
            if not raw_value:
                continue
            resolved_refs.append(
                {
                    "field": field_name,
                    "id": raw_value,
                    "name": (id_to_name or {}).get(raw_value),
                }
            )

        return {
            "action": str(op.action),
            "summary": HITLManager._format_operation(op, id_to_name),
            "raw_json": json.dumps(scrubbed, indent=2, ensure_ascii=False),
            "resolved_refs": resolved_refs,
        }

    @staticmethod
    def _build_transaction_request(payload: TransactionPayload, id_to_name: Dict[str, str] | None = None, *, needs_password: bool = False) -> Dict[str, Any]:
        from .models import EditAction, FolderAction, ItemAction

        has_destructive = any(
            op.action in [ItemAction.DELETE, ItemAction.DELETE_ATTACHMENT, FolderAction.DELETE]
            or (op.action == EditAction.REFACTOR and op.refactor_action in ["move", "delete"])
            for op in payload.operations
        )

        return {
            "type": "transaction",
            "flow": "prompt_review" if needs_password else "review",
            "rationale": payload.rationale,
            "review_title": "Transparent Transaction Review",
            "review_notice": (
                "Nothing is executed while you inspect this page. "
                "Execution starts only after you authorize the transaction."
            ),
            "prompt_title": "Unlock Vault for Transaction Review",
            "input_kind": "password",
            "input_label": "Master Password",
            "input_placeholder": "Enter your master password",
            "primary_action": "Authorize Transaction",
            "formatted_ops": [HITLManager._format_operation(op, id_to_name) for op in payload.operations],
            "operations_details": [HITLManager._serialize_operation_details(op, id_to_name) for op in payload.operations],
            "has_destructive": has_destructive,
        }

    @staticmethod
    def _build_comparison_request(payload: Any, id_to_name: Dict[str, str] | None = None) -> Dict[str, Any]:
        def resolve(uuid: str) -> str:
            return (id_to_name or {}).get(uuid) or uuid

        comparisons = []
        for request in payload.comparisons:
            field_a = request.custom_name_a or request.field_a
            field_b = request.custom_name_b or request.field_b
            comparisons.append(
                {
                    "name_a": resolve(request.item_id_a),
                    "name_b": resolve(request.item_id_b),
                    "field": f"{field_a} ↔ {field_b}",
                    "result": "PENDING",
                }
            )

        return {
            "type": "comparison",
            "flow": "review",
            "rationale": payload.rationale,
            "review_title": "Transparent Comparison Review",
            "review_notice": (
                "Nothing runs while you inspect this page. "
                "Blind comparisons start only after authorization."
            ),
            "comparisons": comparisons,
            "match_tag": "MATCH",
            "primary_action": "Authorize Comparison",
            "has_destructive": False,
        }

    @staticmethod
    def _build_duplicate_scan_request(payload: Any, id_to_name: Dict[str, str] | None = None) -> Dict[str, Any]:
        from .models import FindAllDuplicatesPayload, FindDuplicatesBatchPayload, FindDuplicatesPayload

        def resolve(uuid: str) -> str:
            return (id_to_name or {}).get(uuid) or uuid

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
            targets = [{"name": resolve(target.target_id), "id": target.field} for target in payload.targets]
        elif isinstance(payload, FindAllDuplicatesPayload):
            target_name = "Total Vault"
            field_path = "All Secrets"
            targets = [{"name": "Vault", "id": "All"}]

        return {
            "type": "duplicate_scan",
            "flow": "review",
            "rationale": payload.rationale,
            "review_title": "Transparent Duplicate Scan Review",
            "review_notice": (
                "Nothing runs while you inspect this page. "
                "The scan starts only after authorization."
            ),
            "target_name": target_name,
            "field_path": field_path,
            "duplicates": targets,
            "primary_action": "Authorize Scan",
            "has_destructive": False,
        }

    @staticmethod
    def authorize_transaction(payload: TransactionPayload, id_to_name: Dict[str, str] | None = None, needs_password: bool = False) -> Dict[str, Any]:
        data = HITLManager._build_transaction_request(payload, id_to_name, needs_password=needs_password)
        return HITLManager._authorize_review(data, needs_password=needs_password)

    @staticmethod
    def authorize_comparisons(payload: Any, id_to_name: Dict[str, str] | None = None, needs_password: bool = False) -> Dict[str, Any]:
        return HITLManager._authorize_review(
            HITLManager._build_comparison_request(payload, id_to_name),
            needs_password=needs_password,
        )

    @staticmethod
    def authorize_duplicate_scan(payload: Any, id_to_name: Dict[str, str] | None = None, needs_password: bool = False) -> Dict[str, Any]:
        return HITLManager._authorize_review(
            HITLManager._build_duplicate_scan_request(payload, id_to_name),
            needs_password=needs_password,
        )

    @staticmethod
    def review_transaction(payload: TransactionPayload, id_to_name: Dict[str, str] | None = None, needs_password: bool = False) -> bool:
        resp = HITLManager.authorize_transaction(payload, id_to_name, needs_password=needs_password)
        return bool(resp and resp.get("approved"))

    @staticmethod
    def review_comparisons(payload: Any, id_to_name: Dict[str, str] | None = None) -> bool:
        resp = HITLManager.authorize_comparisons(payload, id_to_name)
        return bool(resp and resp.get("approved"))

    @staticmethod
    def review_duplicate_scan(payload: Any, id_to_name: Dict[str, str] | None = None) -> bool:
        resp = HITLManager.authorize_duplicate_scan(payload, id_to_name)
        return bool(resp and resp.get("approved"))
