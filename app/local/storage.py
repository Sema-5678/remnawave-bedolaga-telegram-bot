from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


class PaymentsStore:
    """
    JSON store:
      key = uid
      value = payment record dict

    Thread-safe within a single process (asyncio.Lock).
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def load(self) -> Dict[str, Dict[str, Any]]:
        async with self._lock:
            if not self.path.exists():
                return {}
            raw = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
            if not raw.strip():
                return {}
            return json.loads(raw)

    async def save(self, payments: Dict[str, Dict[str, Any]]) -> None:
        async with self._lock:
            await asyncio.to_thread(_atomic_write_json, self.path, payments)

    async def get(self, uid: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            if not self.path.exists():
                return None
            raw = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            return data.get(uid)

    async def upsert(self, uid: str, record: Dict[str, Any]) -> None:
        async with self._lock:
            raw = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
            data = json.loads(raw) if raw.strip() else {}
            data[uid] = record
            await asyncio.to_thread(_atomic_write_json, self.path, data)

    async def patch(self, uid: str, **fields: Any) -> Optional[Dict[str, Any]]:
        async with self._lock:
            raw = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
            data = json.loads(raw) if raw.strip() else {}
            rec = data.get(uid)
            if rec is None:
                return None
            rec.update(fields)
            data[uid] = rec
            await asyncio.to_thread(_atomic_write_json, self.path, data)
            return rec

    async def iter_pending(self) -> Dict[str, Dict[str, Any]]:
        data = await self.load()
        return {k: v for k, v in data.items() if v.get("status") in {"pending", "polling"}}
