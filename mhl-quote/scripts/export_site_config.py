#!/usr/bin/env python3
"""Write assets/config/quote-config.json from mhl-quote/config/quote.yaml.

The website reads JSON. The YAML file remains the shop-editable source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = REPO_ROOT / "mhl-quote" / "config" / "quote.yaml"
JSON_PATH = REPO_ROOT / "assets" / "config" / "quote-config.json"


def export_quote_config(yaml_path: Path = YAML_PATH, json_path: Path = JSON_PATH) -> Path:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{yaml_path}: expected a mapping")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return json_path


def main() -> int:
    path = export_quote_config()
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
