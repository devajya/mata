#!/usr/bin/env python3
"""
Verify that frontend/types.ts stays in sync with backend Pydantic enum types.

AGENT-CTX: This script is the enforcement boundary between the Python type
definitions (backend/backend/models.py, backend/backend/db/models.py) and the
hand-maintained TypeScript mirrors (frontend/types.ts).

It uses typing.get_args() to read the *actual* values the Pydantic models
validate against — the same values the runtime rejects if violated — and checks
that every one of those string literals appears in types.ts. A Python change
that adds or renames a Literal value will fail this script immediately without
needing a running server, a real API key, or a full test suite run.

Usage:
    # From the repo root (make target):
    make check-types

    # Directly:
    python backend/scripts/check_types_sync.py

Exit codes:
    0 — all tracked types are in sync
    1 — one or more types are out of sync (details printed to stdout)
    2 — setup error (missing file, import failure)
"""

import sys
from pathlib import Path
from typing import get_args

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow running from the repo root or from backend/.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_PKG = _REPO_ROOT / "backend"
_TYPES_TS = _REPO_ROOT / "frontend" / "types.ts"

if str(_BACKEND_PKG) not in sys.path:
    sys.path.insert(0, str(_BACKEND_PKG))

# ── Imports ───────────────────────────────────────────────────────────────────
try:
    from backend.models import ConfidenceTier, EdgeType, EffectDirection, EvidenceType
    from backend.db.models import JobStatus
except ImportError as e:
    print(f"[check-types] SETUP ERROR: Cannot import backend models: {e}")
    print("  Ensure the backend package is installed: pip install -e backend/")
    sys.exit(2)

if not _TYPES_TS.exists():
    print(f"[check-types] SETUP ERROR: {_TYPES_TS} not found")
    sys.exit(2)

# ── Type registry ─────────────────────────────────────────────────────────────
# Each entry maps a human-readable name to the tuple of expected string values.
# JobStatus is a str Enum (not a Literal), so we extract .value from each member.
TRACKED: dict[str, tuple[str, ...]] = {
    "EvidenceType":   get_args(EvidenceType),
    "EffectDirection": get_args(EffectDirection),
    "ConfidenceTier": get_args(ConfidenceTier),
    "EdgeType":       get_args(EdgeType),
    "JobStatus":      tuple(s.value for s in JobStatus),
}

# ── Check ─────────────────────────────────────────────────────────────────────
types_content = _TYPES_TS.read_text(encoding="utf-8")
errors = 0

for name, values in TRACKED.items():
    if not values:
        print(f"[check-types] WARN:  {name} — no values found in Python type (check get_args usage)")
        continue

    missing = [v for v in values if f'"{v}"' not in types_content]

    if missing:
        print(f"[check-types] FAIL:  {name}")
        print(f"             In backend but missing from frontend/types.ts:")
        for v in missing:
            print(f"               - \"{v}\"")
        errors += 1
    else:
        print(f"[check-types] OK:    {name} ({len(values)} value{'s' if len(values) != 1 else ''})")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
if errors:
    print(f"[check-types] {errors} type(s) out of sync.")
    print(f"              Update frontend/types.ts to match the backend Literal definitions.")
    sys.exit(1)
else:
    print(f"[check-types] All {len(TRACKED)} tracked types in sync ✓")
