#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path

# Add src to path to import the local package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bw_proxy import cli_bridge, main

def generate_markdown():
    # Trigger registration to fill the registry
    # We pass dummy functions since we only care about metadata
    cli_bridge.register_all(main.do_app, lambda *a, **k: None, lambda: None)
    
    registry = cli_bridge._COMMAND_REGISTRY
    
    lines = [
        "| Command | Description | Typed JSON Schema |",
        "| :--- | :--- | :--- |"
    ]
    
    for name in sorted(registry.keys()):
        data = registry[name]
        summary = data["parsed_doc"]["summary"].replace("\n", " ")
        schema_json = json.dumps(data["schema"], indent=2)
        schema_md = f"<pre>{schema_json}</pre>"
        lines.append(f"| `do {name}` | {summary} | {schema_md} |")
    
    return "\n".join(lines)

def sync_readme(content: str):
    readme_path = Path(__file__).parent.parent / "README.md"
    text = readme_path.read_text(encoding="utf-8")
    
    start_marker = "<!-- API_START -->"
    end_marker = "<!-- API_END -->"
    
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    
    if start_idx == -1 or end_idx == -1:
        print("Error: Markers not found in README.md")
        return
    
    new_text = (
        text[:start_idx + len(start_marker)] + 
        "\n\n" + content + "\n\n" + 
        text[end_idx:]
    )
    
    readme_path.write_text(new_text, encoding="utf-8")
    print(f"✅ README.md synced with {len(registry)} commands.")

if __name__ == "__main__":
    registry = cli_bridge._COMMAND_REGISTRY
    md_content = generate_markdown()
    sync_readme(md_content)
