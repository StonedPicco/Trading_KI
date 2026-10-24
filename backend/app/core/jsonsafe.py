"""Convert analysis structures into strict JSON (no NaN/Inf, no numpy scalars)."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


def to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, bool | str):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, int | np.integer):
        return int(obj)
    if isinstance(obj, float | np.floating):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, pd.Timestamp | datetime | date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set | np.ndarray):
        return [to_jsonable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return to_jsonable(obj.model_dump(mode="json"))
    return str(obj)


def canonical_hash(obj: Any) -> str:
    payload = json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
