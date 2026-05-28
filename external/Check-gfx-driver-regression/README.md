# Check GFX/GOP Driver Regression

Portable toolkit for checking QuickBuild CI build associations and HSD regression data
for Intel GFX and GOP drivers.

Integrated into the Chat Mode Assistant Chrome Extension as the core regression engine.

## Files

| File | Purpose |
|---|---|
| `regression_checker.py` | Core Python module — all QB + HSD fetch logic |
| `regression_cache.py` | Cache layer — `_DriverHistoryStore` + `_BuildVersionCache` |
| `server.py` | Standalone HTTP server (runs without the full GNAI bridge) |
| `regression_ui.js` | Frontend JavaScript — UI components for regression display |
| `requirements.txt` | Python dependencies (`requests`, `requests_kerberos`, `urllib3`) |

## Architecture

```
 Chrome Extension (regression_ui.js)
        │
        │ HTTP (port 8776)
        ▼
 bridge_server.py
        │
        ├── regression_checker.py   ← HSD fetch + QB search
        └── regression_cache.py     ← History + Build version cache
```

### Cache Layer (`regression_cache.py`)

Two JSON-backed stores, keyed separately for GFX and GOP:

**`_DriverHistoryStore`** — full regression result per HSD search
- Each search creates a new record with `record_id = "{hsd_id}_{unix_ms}"` (never overwrites)
- Multiple records per HSD allowed (e.g. after Re-enter with different versions)
- Files: `driver_history_gfx.json`, `driver_history_gop.json`

**`_BuildVersionCache`** — per-version QB build data
- Individual build objects cached by version number (e.g. `"34"`, `"101.6651"`)
- Lets future searches skip QuickBuild entirely for already-resolved versions
- Files: `build_cache_gfx.json`, `build_cache_gop.json`

### Query Priority (Frontend)

```
① Same-HSD History lookup (by hsd_id)          ← fastest
② Cross-HSD History lookup (by fail/pass ver)  ← reuses data from other HSDs
③ Per-version Build Cache (assemble from parts)← skips QB login
④ QuickBuild full search                        ← last resort
```

## Standalone Usage

```bash
pip install -r requirements.txt
python server.py              # default port 8776
REGRESSION_PORT=9000 python server.py
```

### Endpoints

| Method | Path | Body / Query |
|--------|------|--------------|
| POST | `/regression-check` | `{"hsd_id":"14025751818", "build_type":"gop"}` |
| POST | `/qb-login` | `{"username":"...", "password":"..."}` |
| POST | `/qb-builds` | `{"fail_version":"34", "pass_version":"30", "fix_version":"47", "build_type":"gop", "platform":"PTL"}` |
| POST | `/qb-commits` | `{"build_id":"21215327"}` |
| GET  | `/driver-history` | `?build_type=gop` list all; `?hsd_id=X&build_type=gop` lookup latest; `?hsd_id=X&build_type=gop&list=1` list all for HSD |
| POST | `/driver-history` | `{"hsd_id":"...", "build_type":"gop", "hsd_data":{...}, "qb_data":{...}}` → `{ok, record_id}` |
| POST | `/driver-history/delete` | `{"record_id":"14025751818_1779963196123", "build_type":"gop"}` |
| POST | `/build-cache/lookup` | `{"versions":["34","30"], "build_type":"gop"}` → `{ok, found:{}, missing:[]}` |
| POST | `/build-cache/save` | `{"build_type":"gop", "entries":[{"version":"34", "build_data":{...}}]}` |
| GET  | `/health` | — |

### build_type values

- `"gfx"` — Intel GFX driver (`prod-hini-releases-*`)
- `"gop"` — GOP firmware driver (`prod-gop-*`)

## Integration with bridge_server.py

`bridge_server.py` automatically imports from this folder:

```python
from regression_checker import ...
from regression_cache import _DriverHistoryStore, _BuildVersionCache

_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
_driver_history      = _DriverHistoryStore(data_dir=_BRIDGE_DIR)
_build_version_cache = _BuildVersionCache(data_dir=_BRIDGE_DIR)
```

Cache files are written to `bridge/` (not inside `external/`) so they persist across git operations.

## Integration with a Chrome Extension

1. Copy `regression_ui.js` to your extension folder
2. Add to your `sidepanel.html` **before** your main script:
   ```html
   <script src="regression_ui.js"></script>
   ```
3. Ensure the following globals exist in your main script:
   - `BRIDGE_BASE_URL` — HTTP base URL (e.g. `"http://127.0.0.1:8776"`)
   - `activeHsdId` — current HSD ID string
   - `isSending` — boolean lock (shared with other async operations)
   - `t(key)` / `tFormat(key, vars)` — i18n helpers
   - `setStatus(mode, text)` — status bar update
   - `addSystemMessage(text)` — add plain text to chat
   - `addHtmlMessage(html)` — add HTML to chat (returns element)
4. Call the exported functions from your buttons:
   ```javascript
   checkGfxRegression()  // GFX Driver regression check
   checkGopRegression()  // GOP Firmware regression check
   showDriverHistoryPanel()  // Open history panel
   ```

## QB API Notes

- **QuickBuild base URL**: `https://ubit-gfx.intel.com`
- **Config IDs**: GOP root=22746, GOP CI=22747, GFX=23083
- **PTL GOP naming**:
  - Version ≤ 30: CI = `gop-ci-master-{N}`, Prod = `prod-gop-prod-PTL-{N}`
  - Version > 30: CI = `gop-ci-main-{N}`, Prod = `prod-gop-Xe3-{N}`
- **CI resolution** uses prefix-batch search (~10 QB requests total, ~17s)
- **QB API quirk**: `offset` parameter is ignored for wildcard `version=` queries
