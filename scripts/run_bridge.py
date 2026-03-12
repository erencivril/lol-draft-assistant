from __future__ import annotations

from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))
sys.path.append(str(repo_root / "backend"))

from bridge.bridge_client import main


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
