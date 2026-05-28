"""
GFX/GOP Driver Regression — Cache layer
========================================
Provides two JSON-backed cache stores:

  _DriverHistoryStore  — HSD-level cache (full result per HSD ID)
  _BuildVersionCache   — Per-version build data cache (individual QB builds)

Both classes accept an optional ``data_dir`` constructor argument that
controls where the JSON files are written.  When omitted the files are
placed in the same directory as this module.

Usage (standalone server):
    from regression_cache import _DriverHistoryStore, _BuildVersionCache
    driver_history     = _DriverHistoryStore()
    build_version_cache = _BuildVersionCache()

Usage (bridge server — files stored in bridge/):
    import os
    from regression_cache import _DriverHistoryStore, _BuildVersionCache
    _BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
    driver_history     = _DriverHistoryStore(data_dir=_BRIDGE_DIR)
    build_version_cache = _BuildVersionCache(data_dir=_BRIDGE_DIR)
"""

import json
import os
import threading
import time


class _DriverHistoryStore:
    """Per-build-type JSON cache for regression check results.

    Files: <data_dir>/driver_history_gfx.json  and  driver_history_gop.json

    Storage format: {record_id: {record_id, hsd_id, build_type, timestamp,
                                  hsd_data, qb_data}}
    record_id = f"{hsd_id}_{unix_ms}" — unique per search, never overwritten.

    Backward compat: old records keyed by plain hsd_id are still readable;
    record_id is synthesised as the key when the field is absent.
    """

    def __init__(self, data_dir=None):
        self._lock = threading.Lock()
        self._dir  = data_dir or os.path.dirname(os.path.abspath(__file__))

    def _path(self, build_type: str) -> str:
        bt = "gop" if "gop" in build_type.lower() else "gfx"
        return os.path.join(self._dir, f"driver_history_{bt}.json")

    def _load(self, build_type: str) -> dict:
        p = self._path(build_type)
        if not os.path.exists(p):
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _flush(self, build_type: str, store: dict):
        with open(self._path(build_type), "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)

    def _enrich(self, key: str, record: dict) -> dict:
        """Ensure record has record_id (synthesise from key for old records)."""
        if "record_id" not in record:
            record = dict(record)
            record["record_id"] = key
        return record

    def save(self, hsd_id: str, build_type: str, hsd_data: dict, qb_data) -> str:
        """Append a new record and return its unique record_id."""
        record_id = f"{hsd_id}_{int(time.time() * 1000)}"
        with self._lock:
            store = self._load(build_type)
            store[record_id] = {
                "record_id": record_id,
                "hsd_id":    str(hsd_id),
                "build_type": build_type,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "hsd_data":  hsd_data or {},
                "qb_data":   qb_data,
            }
            self._flush(build_type, store)
        return record_id

    def lookup(self, hsd_id: str, build_type: str):
        """Return the most recent record for hsd_id, or None."""
        with self._lock:
            store = self._load(build_type)
        matches = [
            self._enrich(k, v) for k, v in store.items()
            if v.get("hsd_id") == str(hsd_id)
        ]
        if not matches:
            return None
        return max(matches, key=lambda r: r.get("timestamp", ""))

    def list_for_hsd(self, hsd_id: str, build_type: str) -> list:
        """Return all records for a specific hsd_id, newest first."""
        with self._lock:
            store = self._load(build_type)
        records = [
            self._enrich(k, v) for k, v in store.items()
            if v.get("hsd_id") == str(hsd_id)
        ]
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return records

    def list_all(self, build_type: str) -> list:
        with self._lock:
            store = self._load(build_type)
        records = [self._enrich(k, v) for k, v in store.items()]
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return records

    def delete(self, record_id: str, build_type: str) -> bool:
        """Delete a specific record by its record_id."""
        with self._lock:
            store = self._load(build_type)
            if record_id in store:
                del store[record_id]
                self._flush(build_type, store)
                return True
        return False


class _BuildVersionCache:
    """Per-version QB build result cache, keyed by driver version number.

    Files: <data_dir>/build_cache_gfx.json  and  build_cache_gop.json
    Each file:
        {"36": {"version": "36", "build_type": "gop",
                "timestamp": "...", "build_data": {...}}, ...}

    Lets future HSD searches skip QuickBuild entirely when all required
    build versions have already been resolved before.
    """

    def __init__(self, data_dir=None):
        self._lock = threading.Lock()
        self._dir  = data_dir or os.path.dirname(os.path.abspath(__file__))

    def _path(self, build_type: str) -> str:
        bt = "gop" if "gop" in build_type.lower() else "gfx"
        return os.path.join(self._dir, f"build_cache_{bt}.json")

    def _load(self, build_type: str) -> dict:
        p = self._path(build_type)
        if not os.path.exists(p):
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _flush(self, build_type: str, store: dict):
        with open(self._path(build_type), "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)

    def lookup_multi(self, versions: list, build_type: str) -> dict:
        """Return {version: build_data} for every version found in cache."""
        with self._lock:
            store = self._load(build_type)
        found = {}
        for v in versions:
            v = str(v).strip()
            if v and v in store:
                found[v] = store[v].get("build_data", {})
        return found

    def save_multi(self, entries: list, build_type: str):
        """Save a list of {version, build_data} entries atomically."""
        with self._lock:
            store = self._load(build_type)
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            for e in entries:
                v  = str(e.get("version") or "").strip()
                bd = e.get("build_data") or {}
                if v:
                    store[v] = {
                        "version":    v,
                        "build_type": build_type,
                        "timestamp":  ts,
                        "build_data": bd,
                    }
            self._flush(build_type, store)
