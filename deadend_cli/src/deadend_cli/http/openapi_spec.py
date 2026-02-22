# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Generate OpenAPI spec for the HTTP API (without running the server)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def get_openapi_schema() -> dict:
    """Build the FastAPI app with minimal state and return its OpenAPI schema."""
    from .app import create_app

    # Schema generation does not run route handlers; state can be None/empty.
    app = create_app(
        component_manager=None,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        deadend_agent_refs={},
    )
    return app.openapi()


def main() -> None:
    """Write OpenAPI spec to docs/openapi.json and docs/openapi.yaml."""
    output_dir = os.environ.get("OPENAPI_OUTPUT_DIR", "docs")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    schema = get_openapi_schema()

    json_path = out_path / "openapi.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"Wrote {json_path}", file=sys.stderr)

    try:
        import yaml
    except ImportError:
        print("PyYAML not installed; skipping openapi.yaml", file=sys.stderr)
        return

    yaml_path = out_path / "openapi.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"Wrote {yaml_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
