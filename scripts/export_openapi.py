#!/usr/bin/env python
"""Export the OpenAPI spec deterministically — no server needed.

The frontend type pipeline (npm run types:openapi) consumes this file:
one definition site (the Pydantic models), one spec, generated TS types.

Usage: python scripts/export_openapi.py [output.json]
"""

import json
import sys
from pathlib import Path


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    from api.app import app

    spec = app.openapi()
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    ops = sum(
        len([m for m in methods if m in ("get", "post", "put", "delete")])
        for methods in spec.get("paths", {}).values()
    )
    schemas = len(spec.get("components", {}).get("schemas", {}))
    print("exported %s: %d paths, %d operations, %d schemas" % (
        out, len(spec.get("paths", {})), ops, schemas))


if __name__ == "__main__":
    main()
