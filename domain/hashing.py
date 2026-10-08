"""Hash canonico: mismo contenido, mismo hash, sin importar el orden."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_hash(obj: Any) -> str:
    """Hash SHA-256 del JSON canonico: el mismo contenido da el mismo hash."""
    canonical = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
