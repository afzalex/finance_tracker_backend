from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from backend.app.main import create_app

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    app = create_app()
    spec = app.openapi()

    out_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Wrote OpenAPI spec to %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

