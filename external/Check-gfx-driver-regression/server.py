"""
Standalone HTTP server for GFX/GOP Driver Regression Checker.

Endpoints:
  POST /v1/qb-login          - Store QB credentials
  POST /v1/qb-builds         - Search QuickBuild for builds
  POST /v1/qb-commits        - Get commits for a QB build
  POST /v1/regression-check  - Check HSD regression data
  GET  /v1/health            - Health check

Usage:
  python server.py
  python server.py --port 8776

Environment variables:
  REGRESSION_PORT   (default: 8776)
  REGRESSION_HOST   (default: 127.0.0.1)
  REGRESSION_DEBUG  (default: 1)
"""

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Import the regression checker module from the same directory
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import regression_checker as _rc
import regression_cache as _cache

HOST = os.environ.get("REGRESSION_HOST", "127.0.0.1")
PORT = int(os.environ.get("REGRESSION_PORT", "8776"))
DEBUG_LOG = os.environ.get("REGRESSION_DEBUG", "1").strip().lower() in {"1", "true", "yes", "on"}


def _debug(message):
    if DEBUG_LOG:
        sys.stdout.write(f"[regression-server] {message}\n")
        sys.stdout.flush()


# Share the debug function with the checker module
_rc._debug = _debug

# ── Cache instances (files stored next to server.py) ─────────────────────────
_driver_history      = _cache._DriverHistoryStore()
_build_version_cache = _cache._BuildVersionCache()


def _json_response(handler, status_code, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


class RegressionHandler(BaseHTTPRequestHandler):
    server_version = "RegressionServer/1.0"
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self):
        _json_response(self, 200, {"ok": True})

    def do_GET(self):
        if self.path in ("/health", "/v1/health"):
            _json_response(self, 200, {"ok": True, "service": "regression-checker"})
        elif self.path.startswith("/driver-history"):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            hsd_id     = (qs.get("hsd_id")     or [""])[0].strip()
            build_type = (qs.get("build_type") or ["gfx"])[0].strip()
            if hsd_id:
                record = _driver_history.lookup(hsd_id, build_type)
                if record:
                    _json_response(self, 200, {"ok": True, "cached": True, "record": record})
                else:
                    _json_response(self, 200, {"ok": True, "cached": False})
            else:
                records = _driver_history.list_all(build_type)
                _json_response(self, 200, {"ok": True, "records": records})
        else:
            _json_response(self, 404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            _json_response(self, 400, {"ok": False, "error": "Invalid JSON payload"})
            return

        if self.path in ("/v1/qb-login", "/qb-login"):
            username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or "")
            if not username or not password:
                _json_response(self, 400, {"ok": False, "error": "Username and password required"})
                return
            _debug(f"qb-login user={username}")
            result = _rc.qb_login(username, password)
            _json_response(self, 200 if result.get("ok") else 401, result)

        elif self.path in ("/v1/qb-builds", "/qb-builds"):
            fail_v = str(payload.get("fail_version") or "").strip()
            pass_v = str(payload.get("pass_version") or "").strip()
            fix_v = str(payload.get("fix_version") or "").strip()
            found_in_v = str(payload.get("found_in_version") or "").strip()
            b_type = str(payload.get("build_type") or "gfx").strip()
            gop_plat = str(payload.get("gop_platform") or "").strip()
            _debug(f"qb-builds fail={fail_v} pass={pass_v} type={b_type} platform={gop_plat}")
            result = _rc.qb_search_builds(fail_v, pass_v, fix_v, b_type, found_in_v, gop_platform=gop_plat)
            _json_response(self, 200 if result.get("ok") else 401, result)

        elif self.path in ("/v1/qb-commits", "/qb-commits"):
            build_id = str(payload.get("build_id") or "").strip()
            if not build_id:
                _json_response(self, 400, {"ok": False, "error": "build_id required"})
                return
            _debug(f"qb-commits build_id={build_id}")
            result = _rc.qb_get_commits(build_id)
            _json_response(self, 200 if result.get("ok") else 502, result)

        elif self.path in ("/v1/regression-check", "/regression-check"):
            hsd_id = str(payload.get("hsd_id") or "").strip()
            if not re.fullmatch(r"\d{8,}", hsd_id):
                _json_response(self, 400, {"ok": False, "error": "Invalid HSD ID"})
                return
            build_type = str(payload.get("build_type") or "gfx").strip()
            _debug(f"regression-check hsd_id={hsd_id} build_type={build_type}")
            result = _rc.check_hsd_regression(hsd_id, build_type=build_type)
            _json_response(self, 200 if result.get("ok") else 502, result)

        elif self.path in ("/driver-history",):
            hsd_id     = str(payload.get("hsd_id")     or "").strip()
            build_type = str(payload.get("build_type") or "gfx").strip()
            if not hsd_id:
                _json_response(self, 400, {"ok": False, "error": "hsd_id required"})
                return
            record_id = _driver_history.save(hsd_id, build_type,
                                             payload.get("hsd_data") or {},
                                             payload.get("qb_data"))
            _debug(f"driver-history saved hsd_id={hsd_id} record_id={record_id}")
            _json_response(self, 200, {"ok": True, "record_id": record_id})

        elif self.path in ("/driver-history/delete",):
            record_id  = str(payload.get("record_id")  or "").strip()
            build_type = str(payload.get("build_type") or "gfx").strip()
            if not record_id:
                _json_response(self, 400, {"ok": False, "error": "record_id required"})
                return
            removed = _driver_history.delete(record_id, build_type)
            _debug(f"driver-history delete record_id={record_id} removed={removed}")
            _json_response(self, 200, {"ok": True, "removed": removed})

        elif self.path in ("/build-cache/lookup",):
            versions   = [str(v) for v in (payload.get("versions") or []) if v]
            build_type = str(payload.get("build_type") or "gfx").strip()
            found   = _build_version_cache.lookup_multi(versions, build_type)
            missing = [v for v in versions if v not in found]
            _debug(f"build-cache lookup type={build_type} found={list(found.keys())}")
            _json_response(self, 200, {"ok": True, "found": found, "missing": missing})

        elif self.path in ("/build-cache/save",):
            build_type = str(payload.get("build_type") or "gfx").strip()
            entries    = payload.get("entries") or []
            _build_version_cache.save_multi(entries, build_type)
            _debug(f"build-cache saved {len(entries)} entries type={build_type}")
            _json_response(self, 200, {"ok": True, "saved": len(entries)})

        else:
            _json_response(self, 404, {"ok": False, "error": "Not found"})

    def log_message(self, fmt, *args):
        sys.stdout.write(f"[regression-server] {self.address_string()} - {fmt % args}\n")
        sys.stdout.flush()


def main():
    print(f"Starting Regression Server on http://{HOST}:{PORT}")
    print(f"Debug log: {'enabled' if DEBUG_LOG else 'disabled'}")
    print("Endpoints: /v1/qb-login  /v1/qb-builds  /v1/qb-commits  /v1/regression-check")
    print("           /driver-history  /driver-history/delete  /build-cache/lookup  /build-cache/save")
    server = ThreadingHTTPServer((HOST, PORT), RegressionHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Regression server stopped.")


if __name__ == "__main__":
    main()
