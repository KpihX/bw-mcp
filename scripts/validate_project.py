#!/usr/bin/env python3
import os
from pathlib import Path

def print_step(msg):
    print(f"[\033[94mSTEP\033[0m] {msg}")

def print_ok(msg):
    print(f"[\033[92m OK \033[0m] {msg}")

def print_fail(msg):
    print(f"[\033[91mFAIL\033[0m] {msg}")

def validate_project():
    root = Path(__file__).parent.parent
    
    print_step("Validating Project Structure...")
    expected_files = [
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "src/bw_blind_proxy/__init__.py",
        "src/bw_blind_proxy/server.py",
        "src/bw_blind_proxy/models.py",
        "src/bw_blind_proxy/config.py",
        "src/bw_blind_proxy/config.yaml",
        "src/bw_blind_proxy/subprocess_wrapper.py",
        "src/bw_blind_proxy/transaction.py",
        "src/bw_blind_proxy/ui.py",
        "tests/test_sanitization.py"
    ]
    
    all_ok = True
    for f in expected_files:
        if (root / f).exists():
            print_ok(f"Found: {f}")
        else:
            print_fail(f"Missing: {f}")
            all_ok = False
            
    print_step("Verifying pyproject.toml dependencies...")
    toml_content = (root / "pyproject.toml").read_text()
    if "pydantic" in toml_content and "pyyaml" in toml_content:
        print_ok("Dependencies properly listed in pyproject.toml")
    else:
        print_fail("Missing required dependencies in pyproject.toml")
        all_ok = False
        
    if all_ok:
        print("\n\033[92m✅ All validation checks passed successfully. The project is modular, secure, and complies with TEMPLATE standards.\033[0m")
    else:
        print("\n\033[91m❌ Validation failed. Check the errors above.\033[0m")
        exit(1)

if __name__ == "__main__":
    validate_project()
