"""Import archived V1 tree as ``zeus_client`` for historical oracles only."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_PARENT = ROOT / "src_v1_legacy"
if str(ARCHIVE_PARENT) not in sys.path:
    sys.path.insert(0, str(ARCHIVE_PARENT))
# Drop installed V2 if present so archive wins
for key in list(sys.modules):
    if key == "zeus_client" or key.startswith("zeus_client."):
        del sys.modules[key]
