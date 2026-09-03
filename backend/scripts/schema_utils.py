# -*- coding: utf-8 -*-
"""Schema preparation helpers for scripts and tests."""

import subprocess
from pathlib import Path

from backend.config import DATABASE_URL


def ensure_schema_ready() -> None:
    """Ensure the PostgreSQL schema is ready for script/test use."""
    if not DATABASE_URL.lower().startswith(("postgresql://", "postgresql+")):
        raise RuntimeError("Only PostgreSQL DATABASE_URL values are supported.")

    backend_dir = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(backend_dir),
        check=True,
    )
