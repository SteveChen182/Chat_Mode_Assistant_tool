"""
regression_bridge.py — HTTP-agnostic dispatch for regression / QB endpoints.

This module extracts all request-handling logic so that any bridge server can
delegate to it without duplicating code.

Usage in a bridge server
------------------------
    import regression_bridge as _rb

    # After importing regression_checker (to register the debug function):
    _rc._debug = _debug
    _rb._rc = _rc          # share the same already-imported module object

    # In do_POST / request handler – after parsing the JSON body:
    status, result = _rb.dispatch(self.path, payload_dict, debug_fn=_debug)
    # → send HTTP response with status and result

Alternatively, just call dispatch() without pre-setting _rc; the module will
try to import regression_checker itself (works as long as sys.path includes
the Check-gfx-driver-regression directory).
"""
import re as _re

# Will be populated by the bridge server right after it imports regression_checker,
# OR lazily on first dispatch() call.
_rc = None  # type: ignore

# All path patterns handled by this module (both with and without /v1 prefix).
PATHS = frozenset({
    "/regression-check", "/v1/regression-check",
    "/qb-login",         "/v1/qb-login",
    "/qb-check-auth",    "/v1/qb-check-auth",
    "/qb-builds",        "/v1/qb-builds",
    "/qb-commits",       "/v1/qb-commits",
    "/qb-build-info",    "/v1/qb-build-info",
})


def _ensure_rc():
    """Lazy-import regression_checker if not already injected by the bridge."""
    global _rc
    if _rc is not None:
        return True
    try:
        import regression_checker as _mod  # noqa: F401
        _rc = _mod
        return True
    except ImportError:
        return False


def dispatch(path: str, payload: dict, debug_fn=None) -> tuple:
    """Process a regression/QB API call.

    Parameters
    ----------
    path      : raw request path (e.g. '/v1/regression-check')
    payload   : already-parsed JSON body dict
    debug_fn  : optional callable(str) for debug logging

    Returns
    -------
    (http_status_code: int, result_dict: dict)
    """
    dbg = debug_fn or (lambda _: None)

    if not _ensure_rc():
        return 503, {"ok": False, "error": "regression_checker module not available"}

    # Forward the bridge's debug function so regression_checker can use it.
    if debug_fn:
        try:
            _rc._debug = debug_fn  # type: ignore[union-attr]
        except Exception:
            pass

    # Normalise path: strip optional /v1 prefix, then dispatch.
    norm = path
    if norm.startswith("/v1/"):
        norm = norm[3:]  # /v1/foo → /foo

    if norm == "/regression-check":
        return _regression_check(payload, dbg)
    if norm == "/qb-login":
        return _qb_login(payload, dbg)
    if norm == "/qb-check-auth":
        return _qb_check_auth(payload, dbg)
    if norm == "/qb-builds":
        return _qb_builds(payload, dbg)
    if norm == "/qb-commits":
        return _qb_commits(payload, dbg)
    if norm == "/qb-build-info":
        return _qb_build_info(payload, dbg)

    return 404, {"ok": False, "error": f"Unknown regression endpoint: {path}"}


# ── Individual handlers ────────────────────────────────────────────────────

def _regression_check(payload: dict, dbg) -> tuple:
    hsd_id = str(payload.get("hsd_id") or "").strip()
    if not _re.fullmatch(r"\d{8,}", hsd_id):
        return 400, {"ok": False, "error": "Invalid HSD ID"}
    build_type = str(payload.get("build_type") or "gfx").strip()
    dbg(f"regression-check hsd_id={hsd_id} build_type={build_type}")
    result = _rc.check_hsd_regression(hsd_id, build_type=build_type)  # type: ignore[union-attr]
    return (200 if result.get("ok") else 502), result


def _qb_login(payload: dict, dbg) -> tuple:
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        return 400, {"ok": False, "error": "Username and password required"}
    dbg(f"qb-login user={username}")
    result = _rc.qb_login(username, password)  # type: ignore[union-attr]
    return (200 if result.get("ok") else 401), result


def _qb_check_auth(payload: dict, dbg) -> tuple:
    dbg("qb-check-auth")
    result = _rc.qb_check_auth()  # type: ignore[union-attr]
    return 200, result


def _qb_builds(payload: dict, dbg) -> tuple:
    fail_v    = str(payload.get("fail_version")    or "").strip()
    pass_v    = str(payload.get("pass_version")    or "").strip()
    fix_v     = str(payload.get("fix_version")     or "").strip()
    found_in_v = str(payload.get("found_in_version") or "").strip()
    b_type    = str(payload.get("build_type")      or "gfx").strip()
    gop_plat  = str(payload.get("gop_platform")    or "").strip()
    dbg(f"qb-builds fail={fail_v} pass={pass_v} fix={fix_v} found_in={found_in_v} type={b_type} platform={gop_plat}")
    result = _rc.qb_search_builds(fail_v, pass_v, fix_v, b_type, found_in_v, gop_platform=gop_plat)  # type: ignore[union-attr]
    return (200 if result.get("ok") else 502), result


def _qb_commits(payload: dict, dbg) -> tuple:
    build_id      = str(payload.get("build_id")      or "").strip()
    build_version = str(payload.get("build_version") or "").strip()
    if not build_id and not build_version:
        return 400, {"ok": False, "error": "build_id or build_version required"}
    if build_version and not build_id:
        dbg(f"qb-commits by version='{build_version}'")
        result = _rc.qb_get_commits_by_version(build_version)  # type: ignore[union-attr]
    else:
        dbg(f"qb-commits build_id={build_id}")
        result = _rc.qb_get_commits(build_id)  # type: ignore[union-attr]
    return (200 if result.get("ok") else 502), result


def _qb_build_info(payload: dict, dbg) -> tuple:
    build_version = str(payload.get("build_version") or "").strip()
    if not build_version:
        return 400, {"ok": False, "error": "build_version required"}
    dbg(f"qb-build-info version='{build_version}'")
    result = _rc.qb_get_build_info(build_version)  # type: ignore[union-attr]
    return (200 if result.get("ok") else 502), result
