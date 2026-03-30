from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.app.main import create_app


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    app = create_app()
    spec = app.openapi()

    out_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote OpenAPI spec to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

