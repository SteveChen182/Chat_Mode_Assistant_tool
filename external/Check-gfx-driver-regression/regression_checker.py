"""
GFX/GOP Driver Regression Checker
===================================
Portable module for checking QuickBuild and HSD regression data.

Usage:
  Standalone: run server.py
  As library:
    from regression_checker import qb_login, qb_search_builds, check_hsd_regression

Public API:
  QB_BASE           - QuickBuild base URL (configurable)
  QB_CREDENTIALS    - {"username": "", "password": ""} — set via qb_login()
  qb_login(u, p)    - Store credentials and verify against QB
  qb_search_builds(fail_version, pass_version, ...) -> dict
  qb_get_commits(build_id) -> dict
  check_hsd_regression(hsd_id, build_type) -> dict
"""

import re
import sys

# ── Configuration ────────────────────────────────────────────────────────────

QB_BASE = "https://ubit-gfx.intel.com"
QB_CREDENTIALS = {"username": "", "password": ""}  # in-memory only

_DEBUG_LOG = True


def _debug(message):
    if _DEBUG_LOG:
        sys.stdout.write(f"[regression-debug] {message}\n")
        sys.stdout.flush()


# ── QuickBuild API helpers ────────────────────────────────────────────────────

def qb_get_commits(build_id):
    """Fetch commit list for a QB build.
    Release builds don't have direct commits — we follow revenue-pr-XXXXX to the PR build.
    """
    import re as _re
    import requests as _req
    import urllib3 as _u3
    import xml.etree.ElementTree as _ET
    _u3.disable_warnings()

    uname = QB_CREDENTIALS.get("username", "")
    pwd = QB_CREDENTIALS.get("password", "")
    if not uname:
        return {"ok": False, "error": "not_logged_in"}

    auth = (uname, pwd)
    proxy = {"http": "", "https": ""}
    debug_tries = []

    def _get_changes(bid):
        """Return raw XML text or None for the first working /changes endpoint."""
        for ep in [f"{QB_BASE}/rest/builds/{bid}/changes"]:
            try:
                r = _req.get(ep, auth=auth, verify=False, proxies=proxy, timeout=20)
                _debug(f"  changes {ep} -> {r.status_code} len={len(r.text)}")
                debug_tries.append({"url": ep, "status": r.status_code, "snippet": r.text[:300]})
                if r.status_code == 200 and r.text.strip() and "<list/>" not in r.text:
                    return r.text
            except Exception as exc:
                debug_tries.append({"url": ep, "error": str(exc)})
        return None

    def _parse_commits(xml_text):
        try:
            root = _ET.fromstring(xml_text)
        except Exception:
            return []
        commits = []
        for cs in root:
            nested = cs.find("commits") or cs.find("changes") or cs.find("revisions")
            entries = list(nested) if nested is not None else [cs]
            for entry in entries:
                rev = entry.findtext("revision") or ""
                comment = entry.findtext("comment") or entry.findtext("message") or ""
                author = entry.findtext("author") or entry.findtext("committer") or ""
                date = entry.findtext("date") or entry.findtext("timestamp") or ""
                if rev or comment:
                    commits.append({
                        "rev": rev,
                        "author": author,
                        "date": date[:16] if date else "",
                        "comment": comment.strip().split("\n")[0][:120] if comment else "",
                    })
        seen, unique = set(), []
        for c in commits:
            k = c["rev"] or c["comment"]
            if k not in seen:
                seen.add(k)
                unique.append(c)
        return unique

    # Step 1: Get the build XML to find its version string (contains revenue-pr-XXXXX)
    build_version = ""
    build_xml_raw = ""
    try:
        rb = _req.get(f"{QB_BASE}/rest/builds/{build_id}", auth=auth, verify=False, proxies=proxy, timeout=20)
        debug_tries.append({"url": f"/rest/builds/{build_id}", "status": rb.status_code, "snippet": rb.text[:200]})
        if rb.status_code == 200:
            build_xml_raw = rb.text[:4000]
            try:
                broot = _ET.fromstring(rb.text)
                build_version = broot.findtext("version") or ""
            except Exception:
                pass
    except Exception as exc:
        debug_tries.append({"url": f"/rest/builds/{build_id}", "error": str(exc)})

    _debug(f"qb-commits build_id={build_id} version={build_version}")

    # Step 2: Try direct /changes on the given build first
    raw_text = _get_changes(build_id)
    if raw_text:
        commits = _parse_commits(raw_text)
        return {"ok": True, "build_id": build_id, "commits": commits,
                "_debug_tries": debug_tries, "_raw": raw_text[:3000]}

    # Step 3: Extract revenue-pr number from version, search for the PR build
    revenue_pr = None
    m = _re.search(r"revenue-pr-(\d+)", build_version)
    if m:
        revenue_pr = m.group(1)
        _debug(f"  looking up revenue-pr-{revenue_pr}")

    pr_build_id = None
    list_changes_url = None
    if revenue_pr:
        search_ep = f"{QB_BASE}/rest/builds?version=*revenue-pr-{revenue_pr}*&count=50"
        try:
            rs = _req.get(search_ep, auth=auth, verify=False, proxies=proxy, timeout=20)
            debug_tries.append({"url": search_ep, "status": rs.status_code, "snippet": rs.text[:600]})
            if rs.status_code == 200 and rs.text.strip() and "<list/>" not in rs.text:
                sroot = _ET.fromstring(rs.text)
                list_changes_candidates = []
                other_candidates = []
                for b in sroot:
                    bid_text = b.findtext("id") or ""
                    bver = b.findtext("version") or ""
                    if not bid_text:
                        continue
                    if bver.startswith("list-changes-"):
                        list_changes_candidates.append((int(bid_text), bver))
                    elif (not bver.startswith("prod-hini-releases")
                            and not bver.startswith("bdbasc-")
                            and not bver.startswith("ms-")):
                        other_candidates.append((int(bid_text), bver))

                if list_changes_candidates:
                    list_changes_candidates.sort(key=lambda x: x[0])
                    pr_build_id = str(list_changes_candidates[0][0])
                    list_changes_url = f"{QB_BASE}/build/{pr_build_id}"
                    _debug(f"  list-changes build id={pr_build_id} ver={list_changes_candidates[0][1]}")
                elif other_candidates:
                    other_candidates.sort(key=lambda x: x[0])
                    pr_build_id = str(other_candidates[0][0])
                    _debug(f"  fallback PR build id={pr_build_id} ver={other_candidates[0][1]}")
        except Exception as exc:
            debug_tries.append({"url": search_ep, "error": str(exc)})

    if pr_build_id:
        raw_text = _get_changes(pr_build_id)
        if raw_text:
            commits = _parse_commits(raw_text)
            return {"ok": True, "build_id": pr_build_id, "commits": commits,
                    "_note": f"commits from build {pr_build_id} (revenue-pr-{revenue_pr})",
                    "_list_changes_url": list_changes_url,
                    "_debug_tries": debug_tries, "_raw": raw_text[:3000]}

    return {
        "ok": True,
        "build_id": build_id,
        "commits": [],
        "_note": f"revenue_pr={revenue_pr} pr_build_id={pr_build_id}",
        "_list_changes_url": list_changes_url,
        "_debug_tries": debug_tries,
        "_raw": build_xml_raw,
    }


def qb_get_commits_by_version(build_version):
    """Look up a QB build by its version string, then return its commits.

    Useful for querying prod builds such as 'prod-gop-prod-releases_ww102026_ptl-65'.
    Searches QB for an exact-match build, resolves the build_id, then delegates
    to qb_get_commits().
    """
    import requests as _req
    import urllib3 as _u3
    import xml.etree.ElementTree as _ET
    _u3.disable_warnings()

    uname = QB_CREDENTIALS.get("username", "")
    pwd = QB_CREDENTIALS.get("password", "")
    if not uname:
        return {"ok": False, "error": "not_logged_in"}

    auth = (uname, pwd)
    proxy = {"http": "", "https": ""}

    _debug(f"qb-commits-by-version: searching for version='{build_version}'")
    search_url = f"{QB_BASE}/rest/builds"
    try:
        r = _req.get(
            search_url,
            params={"version": build_version, "count": "10", "status": "SUCCESSFUL"},
            auth=auth, verify=False, proxies=proxy, timeout=20,
        )
        if r.status_code != 200 or "<" not in r.text or "<list/>" in r.text:
            # Try without status filter in case the build has a different status
            r = _req.get(
                search_url,
                params={"version": build_version, "count": "10"},
                auth=auth, verify=False, proxies=proxy, timeout=20,
            )
        if r.status_code != 200 or "<list/>" in r.text or "<" not in r.text:
            return {"ok": False, "error": f"Build '{build_version}' not found in QB (HTTP {r.status_code})"}
        root = _ET.fromstring(r.text)
        build_id = None
        for b in root:
            bid = b.findtext("id") or ""
            bver = b.findtext("version") or ""
            if bver == build_version and bid:
                build_id = bid
                break
        if not build_id:
            # Fallback: take the first result
            first = root.find(".//id")
            build_id = first.text.strip() if first is not None and first.text else None
        if not build_id:
            return {"ok": False, "error": f"Build '{build_version}' not found in QB search results"}
        _debug(f"qb-commits-by-version: resolved build_id={build_id} for '{build_version}'")
    except Exception as exc:
        return {"ok": False, "error": f"QB search error: {exc}"}

    result = qb_get_commits(build_id)
    result["_resolved_from_version"] = build_version
    return result


def qb_get_build_info(build_version):
    """Return git checkout hash, GitHub compare link, and step runtimes for a QB build.

    For release-branch prod builds (e.g. prod-gop-prod-releases_ww102026_ptl-65)
    that have no direct /changes, this extracts the git revision from the
    'checkout component' step and the GitHub compare URL from the
    'create GitHub link report' artifact.

    Returns dict: ok, build_id, version, git_hash, github_link,
                  prev_build_id, prev_version, prev_git_hash, commits_url,
                  artifacts (list of {name, url})
    """
    import requests as _req
    import urllib3 as _u3
    import xml.etree.ElementTree as _ET
    import re as _re
    _u3.disable_warnings()

    uname = QB_CREDENTIALS.get("username", "")
    pwd   = QB_CREDENTIALS.get("password", "")
    if not uname:
        return {"ok": False, "error": "not_logged_in"}

    auth  = (uname, pwd)
    proxy = {"http": "", "https": ""}

    def _search_build(version):
        r = _req.get(
            f"{QB_BASE}/rest/builds",
            params={"version": version, "count": "5", "status": "SUCCESSFUL"},
            auth=auth, verify=False, proxies=proxy, timeout=20,
        )
        if r.status_code != 200 or "<list/>" in r.text or "<" not in r.text:
            return None, None
        root = _ET.fromstring(r.text)
        for b in root:
            bid = b.findtext("id") or ""
            bver = b.findtext("version") or ""
            if bver == version and bid:
                return bid, b
        first = root.find(".//id")
        if first is not None and first.text:
            return first.text.strip(), root.find(".//*[id]")
        return None, None

    def _get_full_xml(build_id):
        r = _req.get(
            f"{QB_BASE}/rest/builds/{build_id}",
            auth=auth, verify=False, proxies=proxy, timeout=20,
        )
        if r.status_code != 200:
            return None
        try:
            return _ET.fromstring(r.text)
        except Exception:
            return None

    def _extract_git_hash(xml_root):
        """Find 'Checkout revision: <hash>' in step customData."""
        for cd in xml_root.iter("customData"):
            txt = (cd.text or "")
            m = _re.search(r"[Cc]heckout revision:\s*([0-9a-f]{7,40})", txt)
            if m:
                return m.group(1)
        return ""

    def _get_github_link(build_id, xml_root):
        """Try to fetch the 'create GitHub link report' artifact."""
        # 1. Try QB report files listing
        try:
            fr = _req.get(
                f"{QB_BASE}/rest/builds/{build_id}/files",
                auth=auth, verify=False, proxies=proxy, timeout=15,
            )
            if fr.status_code == 200 and "<" in fr.text:
                froot = _ET.fromstring(fr.text)
                for entry in froot.iter():
                    name = entry.findtext("name") or entry.findtext("path") or entry.text or ""
                    if "github" in name.lower() or "link" in name.lower():
                        url = entry.findtext("url") or ""
                        _debug(f"build-info: found report entry name={name!r} url={url!r}")
                        if url:
                            cr = _req.get(url, auth=auth, verify=False, proxies=proxy, timeout=10)
                            if cr.status_code == 200:
                                return cr.text.strip()[:500]
        except Exception as exc:
            _debug(f"build-info: files listing error: {exc}")

        # 2. Look for github.com URL in any stepRuntime customData
        for cd in xml_root.iter("customData"):
            txt = (cd.text or "")
            m = _re.search(r"(https?://github[^\s<\"']+)", txt)
            if m:
                return m.group(1)

        return ""

    # --- main ---
    _debug(f"qb-build-info: searching for '{build_version}'")
    build_id, _ = _search_build(build_version)
    if not build_id:
        return {"ok": False, "error": f"Build '{build_version}' not found in QB"}

    xml_root = _get_full_xml(build_id)
    if xml_root is None:
        return {"ok": False, "error": f"Could not fetch build XML for {build_id}"}

    git_hash   = _extract_git_hash(xml_root)
    github_link = _get_github_link(build_id, xml_root)
    config_id  = xml_root.findtext("configuration") or ""

    # Find previous prod build (version suffix minus 1) for compare range
    prev_version = ""
    prev_git_hash = ""
    prev_build_id = ""
    m = _re.search(r"^(.+?)(\d+)$", build_version)
    if m:
        prev_num = int(m.group(2)) - 1
        prev_version = f"{m.group(1)}{prev_num}"
        prev_id, _ = _search_build(prev_version)
        if prev_id:
            prev_build_id = prev_id
            prev_xml = _get_full_xml(prev_id)
            if prev_xml is not None:
                prev_git_hash = _extract_git_hash(prev_xml)

    commits_url = ""
    if prev_git_hash and git_hash:
        commits_url = (
            f"git log {prev_git_hash[:12]}..{git_hash[:12]}"
            f"  (or GitHub compare: ...compare/{prev_git_hash}...{git_hash})"
        )

    _debug(
        f"qb-build-info: build_id={build_id} git={git_hash[:12]} "
        f"prev_id={prev_build_id} prev_git={prev_git_hash[:12] if prev_git_hash else ''}"
    )
    return {
        "ok": True,
        "build_id": build_id,
        "version": build_version,
        "config_id": config_id,
        "git_hash": git_hash,
        "github_link": github_link,
        "prev_build_id": prev_build_id,
        "prev_version": prev_version,
        "prev_git_hash": prev_git_hash,
        "commits_url": commits_url,
        "qb_url": f"{QB_BASE}/build/{build_id}",
    }


def _get_change_subject_from_build(build_id, auth, proxy):
    """Fetch full QB build XML and extract change_subject from secretAwareVariableValues."""
    import requests as _req
    import urllib3 as _u3
    import xml.etree.ElementTree as _ET
    _u3.disable_warnings()
    try:
        r = _req.get(f"{QB_BASE}/rest/builds/{build_id}",
                     auth=auth, verify=False, proxies=proxy, timeout=20)
        if r.status_code != 200:
            return ""
        root = _ET.fromstring(r.text)
        for entry in root.iter("entry"):
            strings = entry.findall("string")
            if not strings or (strings[0].text or "").strip() != "change_subject":
                continue
            # Value is inside <com.pmease.quickbuild.SecretAwareString><string>…
            sas = entry.find("com.pmease.quickbuild.SecretAwareString")
            if sas is not None:
                inner = (sas.findtext("string") or "").strip()
                if inner:
                    return inner
            if len(strings) >= 2:
                val = (strings[1].text or "").strip()
                if val:
                    return val
    except Exception as exc:
        _debug(f"_get_change_subject: error for build {build_id}: {exc}")
    return ""


def qb_get_all_ci_builds_in_prod(prod_version, ci_last_version="", ci_prev_last_version=""):
    """Return all CI builds incorporated into a prod build.

    Parameters
    ----------
    prod_version         e.g. "prod-gop-Xe3-47"
    ci_last_version      last CI build in this prod (e.g. "gop-ci-main-635")
    ci_prev_last_version last CI build in the PREVIOUS prod (e.g. "gop-ci-main-625")
                         When supplied the range boundary is exact; without it
                         a conservative cap of 30 is used as fallback.

    CI builds in (ci_prev_last_version, ci_last_version] are fetched in
    parallel and returned sorted oldest→newest.
    Returns [] when ci_last_version has no numeric suffix or QB is not logged in.
    """
    from concurrent.futures import ThreadPoolExecutor
    import requests as _req
    import urllib3 as _u3
    import xml.etree.ElementTree as _ET
    import re as _re
    _u3.disable_warnings()

    uname = QB_CREDENTIALS.get("username", "")
    pwd   = QB_CREDENTIALS.get("password", "")
    if not uname:
        return []

    auth  = (uname, pwd)
    proxy = {"http": "", "https": ""}

    # ── Must have ci_last_version to determine range ──────────────────────────
    m_last = _re.search(r"-(\d+)$", ci_last_version) if ci_last_version else None
    if not m_last:
        _debug(f"qb-all-ci: no ci_last_version for '{prod_version}', skip")
        return []
    ci_last_num = int(m_last.group(1))

    # ── Derive CI build prefix from prod version ──────────────────────────────
    ci_prefix = ""
    m_rel = _re.search(r"prod-gop-prod-releases_(\w+)_ptl-\d+", prod_version)
    if m_rel:
        ci_prefix = f"gop-ci-releases_{m_rel.group(1)}_ptl-"
    elif "prod-gop-Xe3p-" in prod_version:
        ci_prefix = "ci-main-"
    elif "prod-gop-Xe3-" in prod_version:
        ci_prefix = "gop-ci-main-"
    elif _re.search(r"prod-gop-prod-PTL-\d+", prod_version):
        m_num = _re.search(r"prod-gop-prod-PTL-(\d+)", prod_version)
        ci_prefix = "gop-ci-master-" if m_num and int(m_num.group(1)) <= 30 else "gop-ci-main-"
    else:
        _debug(f"qb-all-ci: unrecognised prod pattern '{prod_version}', skipping")
        return []

    # ── Determine range start ─────────────────────────────────────────────────
    m_prev = _re.search(r"-(\d+)$", ci_prev_last_version) if ci_prev_last_version else None
    if m_prev:
        ci_first_num = int(m_prev.group(1)) + 1
        _debug(f"qb-all-ci: range [{ci_first_num}..{ci_last_num}]  "
               f"prev_ci='{ci_prev_last_version}'")
    else:
        # No reliable prev boundary → conservative 30-build cap
        ci_first_num = max(1, ci_last_num - 29)
        _debug(f"qb-all-ci: no prev CI boundary, fallback range [{ci_first_num}..{ci_last_num}]")

    versions_to_check = [f"{ci_prefix}{n}" for n in range(ci_first_num, ci_last_num + 1)]

    # ── Phase 1: Parallel QB lookup of CI build IDs ───────────────────────────
    def _search_exact(version):
        try:
            r = _req.get(f"{QB_BASE}/rest/builds",
                         params={"version": version, "count": "5", "status": "SUCCESSFUL"},
                         auth=auth, verify=False, proxies=proxy, timeout=20)
            if r.status_code != 200 or "<list/>" in r.text or "<" not in r.text:
                return version, None, 0
            root = _ET.fromstring(r.text)
            for b in root:
                bid = b.findtext("id") or ""
                bver = b.findtext("version") or ""
                if bver == version and bid:
                    return version, bid, int(bid)
            first_id = root.findtext(".//id") or ""
            return (version, first_id, int(first_id)) if first_id else (version, None, 0)
        except Exception:
            return version, None, 0

    found_builds = []   # [(bid_int, bid_str, ver)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for ver, bid_str, bid_int in ex.map(_search_exact, versions_to_check):
            if bid_str:
                found_builds.append((bid_int, bid_str, ver))
    found_builds.sort()
    _debug(f"qb-all-ci: {len(found_builds)} CI builds found for '{prod_version}' "
           f"range [{ci_first_num}..{ci_last_num}]")

    if not found_builds:
        return []

    # ── Phase 2: Parallel fetch of change subjects ────────────────────────────
    def _fetch_item(item):
        bid_int, bid_str, ver = item
        cs = _get_change_subject_from_build(bid_str, auth, proxy)
        return bid_int, bid_str, ver, cs

    result_items = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for bid_int, bid_str, ver, cs in ex.map(_fetch_item, found_builds):
            result_items.append((bid_int, bid_str, ver, cs))
    result_items.sort()

    return [
        {
            "version":        ver,
            "build_id":       bid_str,
            "change_subject": cs,
            "qb_url":         f"{QB_BASE}/build/{bid_str}",
        }
        for bid_int, bid_str, ver, cs in result_items
    ]


def qb_login(username, password):
    """Verify QB credentials and store them in QB_CREDENTIALS."""
    import requests as _req
    import urllib3 as _u3
    _u3.disable_warnings()
    try:
        resp = _req.get(
            f"{QB_BASE}/rest/version",
            auth=(username, password),
            verify=False,
            proxies={"http": "", "https": ""},
            timeout=15,
        )
        if resp.status_code == 200 and resp.text.strip():
            QB_CREDENTIALS["username"] = username
            QB_CREDENTIALS["password"] = password
            _debug(f"qb-login OK: version={resp.text.strip()}")
            return {"ok": True, "version": resp.text.strip()}
        return {"ok": False, "error": f"QB returned HTTP {resp.status_code}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def qb_check_auth():
    """Return whether QB credentials are cached and still valid."""
    import requests as _req
    import urllib3 as _u3
    _u3.disable_warnings()
    uname = QB_CREDENTIALS.get("username", "")
    pwd   = QB_CREDENTIALS.get("password", "")
    if not uname or not pwd:
        return {"ok": True, "logged_in": False, "username": ""}
    try:
        resp = _req.get(
            f"{QB_BASE}/rest/version",
            auth=(uname, pwd),
            verify=False,
            proxies={"http": "", "https": ""},
            timeout=5,
        )
        if resp.status_code == 200 and resp.text.strip():
            return {"ok": True, "logged_in": True, "username": uname}
        QB_CREDENTIALS["username"] = ""
        QB_CREDENTIALS["password"] = ""
        return {"ok": True, "logged_in": False, "username": uname}
    except Exception:
        return {"ok": True, "logged_in": False, "username": uname}


def qb_search_builds(fail_version, pass_version, fix_version="", build_type="gfx",
                     found_in_version="", gop_platform=""):
    """Search QuickBuild builds matching fail/pass/fix/found_in versions.

    Args:
        build_type: 'gfx' for prod-hini-releases, 'gop' for GOP builds.
        found_in_version: additional fail version from HSD found_in_sw_version.
        gop_platform: platform short name for GOP (e.g. 'PTL') to filter builds.

    Returns:
        dict with keys: ok, config_id, fail_builds, pass_builds, fix_builds,
                        found_in_builds, quickbuild_url
    """
    import requests as _req
    import urllib3 as _u3
    import xml.etree.ElementTree as _ET
    _u3.disable_warnings()

    is_gop = build_type == "gop"
    config_name = "gop" if is_gop else "prod-hini-releases"
    qb_dashboard = "https://ubit-gfx.intel.com/dashboard/8078" if is_gop else "https://ubit-gfx.intel.com/dashboard/7931"

    uname = QB_CREDENTIALS.get("username", "")
    pwd = QB_CREDENTIALS.get("password", "")
    if not uname:
        return {"ok": False, "error": "not_logged_in"}

    auth = (uname, pwd)
    proxy = {"http": "", "https": ""}

    # Step 1: resolve config ID
    config_id = None
    if is_gop:
        config_id = "22746"
        _debug(f"qb-search: using GOP config_id={config_id}")
    else:
        for path_candidate in [
            "ubit/gfx/Releases/prod-hini-releases",
            "ubit/gfx/Build/Windows/Main/Production/prod-hini-releases",
            "ubit/gfx/Run/Production/prod-hini-releases",
        ]:
            try:
                r = _req.get(
                    f"{QB_BASE}/rest/ids",
                    params={"configuration_path": path_candidate},
                    auth=auth, verify=False, proxies=proxy, timeout=10,
                )
                if r.status_code == 200 and r.text.strip().isdigit():
                    config_id = r.text.strip()
                    _debug(f"qb-search: config_id={config_id} from path={path_candidate}")
                    break
            except Exception:
                pass

    if not config_id:
        search_name = config_name
        try:
            r = _req.get(
                f"{QB_BASE}/rest/configurations",
                params={"search": f"**/{search_name}"},
                auth=auth, verify=False, proxies=proxy, timeout=10,
            )
            if r.status_code == 200 and "<id>" in r.text:
                root = _ET.fromstring(r.text)
                for cfg in root.iter():
                    cid = cfg.findtext("id")
                    if cid and cid.isdigit():
                        config_id = cid
                        _debug(f"qb-search: config_id={config_id} from search")
                        break
        except Exception:
            pass

    if not config_id:
        try:
            r = _req.get(
                f"{QB_BASE}/rest/configurations",
                params={"parent_id": "1", "recursive": "true"},
                auth=auth, verify=False, proxies=proxy, timeout=15,
            )
            if r.status_code == 200 and "<name>" in r.text:
                root = _ET.fromstring(r.text)
                tag = "com.pmease.quickbuild.model.Configuration"
                for cfg in root.findall(tag):
                    name = cfg.findtext("name") or ""
                    if config_name in name.lower():
                        config_id = cfg.findtext("id")
                        _debug(f"qb-search: config_id={config_id} from recursive")
                        break
        except Exception:
            pass

    results = {
        "ok": True, "config_id": config_id,
        "fail_builds": [], "pass_builds": [], "fix_builds": [], "found_in_builds": []
    }

    if not config_id:
        _debug("qb-search: config_id not found, searching all builds")

    # ── Nested helper functions ──────────────────────────────────────────────

    def _version_to_nodots(v):
        """Convert '101.8724' or '32.0.101.8724' to '1018724' for QB search."""
        parts = v.replace(" ", "").split(".")
        if len(parts) == 4:
            return parts[2] + parts[3]
        elif len(parts) == 2:
            return parts[0] + parts[1]
        return v.replace(".", "")

    def _extract_ci_master(build_version):
        """Extract 'ci-master-NNNNN' from a GFX build version string."""
        m = re.search(r"(ci-master-\d+)", build_version)
        return m.group(1) if m else ""

    def _lookup_gfx_ci_build_id(ci_master_str):
        """Given 'ci-master-18303', search QB for gfx-driver-ci-master-18303 build ID."""
        if not ci_master_str:
            return ""
        m = re.search(r"ci-master-(\d+)$", ci_master_str)
        if not m:
            return ""
        ci_num = m.group(1)
        try:
            r = _req.get(f"{QB_BASE}/rest/builds",
                         params={"version": f"gfx-driver-ci-master-{ci_num}", "count": "1",
                                 "status": "SUCCESSFUL"},
                         auth=auth, verify=False, proxies=proxy, timeout=8)
            if r.status_code == 200 and "<" in r.text and "<list/>" not in r.text:
                root = _ET.fromstring(r.text)
                bld = root.find("com.pmease.quickbuild.model.Build")
                if bld is not None:
                    return bld.findtext("id") or ""
        except Exception:
            pass
        return ""

    def _extract_gop_ci_main(build_version):
        """Extract GOP/NVL CI build reference from a build version string.
        Handles: gop-ci-main-NNN, gop-ci-master-NNN, gop-ci-releases_WW_ptl-NNN, ci-main-NNN (NVL)."""
        m = re.search(r"(gop-ci-(?:main|master)-\d+|gop-ci-releases_\w+_ptl-\d+|ci-main-\d+)", build_version)
        return m.group(1) if m else ""

    def _resolve_gop_ci_from_prod(build_el, gop_platform_name, ver_num):
        """For prod-gop builds, resolve the corresponding CI build.
        Returns (ci_build_version, ci_build_id, change_subject) 3-tuple.
        """
        bid = build_el.findtext("id")
        bver = build_el.findtext("version") or ""
        if not bid:
            return "", "", ""

        ci_config_id = "22747"
        if gop_platform_name == "NVL" or "Xe3p" in bver:
            # Nova Lake: CI builds use ci-main-xxxx (no gop- prefix)
            ci_prefix = "ci-main"
        elif gop_platform_name == "PTL" and ver_num <= 30:
            ci_prefix = "gop-ci-master"
        elif "releases_" in bver and "_ptl-" in bver.lower():
            # PTL > 63: new branch naming e.g. gop-ci-releases_ww102026_ptl-N
            _ww_m = re.search(r"releases_(\w+)_ptl-", bver, re.IGNORECASE)
            ci_prefix = f"gop-ci-releases_{_ww_m.group(1)}_ptl" if _ww_m else "gop-ci-releases_ww102026_ptl"
        else:
            ci_prefix = "gop-ci-main"

        try:
            r = _req.get(f"{QB_BASE}/rest/builds/{bid}",
                         auth=auth, verify=False, proxies=proxy, timeout=15)
            if r.status_code != 200:
                return "", "", ""
            prod_xml_text = r.text
        except Exception as exc:
            _debug(f"gop ci resolve: error fetching prod build {bid}: {exc}")
            return "", "", ""

        # Direct scan for gop-ci-main/master/releases/ci-main reference
        m = re.search(r"gop-ci-(?:main|master)-\d+|gop-ci-releases_\w+_ptl-\d+|ci-main-\d+", prod_xml_text)
        if m:
            _debug(f"gop ci resolve: direct ref '{m.group()}' in {bver}")
            return m.group(), "", ""

        # Extract component_revision and change_subject
        component_revision = ""
        change_subject = ""
        try:
            detail = _ET.fromstring(prod_xml_text)
            for sav_tag in ("secretAwareVariableValues", "variables"):
                sav = detail.find(sav_tag)
                if sav is None:
                    continue
                for entry in sav.findall("entry"):
                    children = list(entry)
                    if len(children) < 2:
                        continue
                    key = (children[0].text or "").strip()
                    if key not in ("component_revision", "change_subject"):
                        continue
                    val = ""
                    for sub in children[1].iter():
                        if sub.text and sub.text.strip() and sub.tag != children[1].tag:
                            val = sub.text.strip()
                            break
                    if not val:
                        val = (children[1].text or "").strip()
                    if key == "component_revision":
                        component_revision = val
                    elif key == "change_subject":
                        change_subject = val
                if component_revision and change_subject:
                    break
        except Exception:
            pass

        if not component_revision and not change_subject:
            _debug(f"gop ci resolve: no revision/subject for {bver}, will attempt proximity match")
            # Don't return early — fall through to prefix-band search + proximity fallback
        else:
            _debug(f"gop ci resolve: hash={component_revision[:12]} subject='{change_subject}' for {bver}")

        # Get latest CI build number for prefix estimation
        n_latest_ci = 0
        try:
            r = _req.get(f"{QB_BASE}/rest/builds",
                         params={"version": f"{ci_prefix}-*", "count": "1", "status": "SUCCESSFUL",
                                 "configuration_id": ci_config_id, "recursive": "true"},
                         auth=auth, verify=False, proxies=proxy, timeout=10)
            if r.status_code == 200 and "<" in r.text:
                root = _ET.fromstring(r.text)
                bld = root.find("com.pmease.quickbuild.model.Build")
                if bld is not None:
                    lv = bld.findtext("version") or ""
                    m2 = re.search(r"-(\d+)$", lv)
                    if m2:
                        n_latest_ci = int(m2.group(1))
                        _debug(f"gop ci resolve: latest CI={lv}")
        except Exception:
            pass

        if n_latest_ci == 0:
            _debug(f"gop ci resolve: n_latest_ci=0 (config {ci_config_id} returned nothing) for {bver}; using ver_num as expected_ci fallback")
            # Don't return early — expected_ci will fall back to ver_num below

        # Get latest prod build number for ratio estimation
        n_latest_prod = 0
        if "Xe3p" in bver:
            # Nova Lake (NVL): prod-gop-Xe3p-xx
            prod_prefix_search = "prod-gop-Xe3p-*"
        elif "Xe3" in bver:
            prod_prefix_search = "prod-gop-Xe3-*"
        elif "releases_" in bver and "ptl-" in bver.lower():
            _ww_m2 = re.search(r"releases_(\w+)_ptl-", bver, re.IGNORECASE)
            _ww2 = _ww_m2.group(1) if _ww_m2 else "ww102026"
            prod_prefix_search = f"prod-gop-prod-releases_{_ww2}_ptl-*"
        else:
            prod_prefix_search = f"prod-gop-prod-{gop_platform_name}-*"
        try:
            r = _req.get(f"{QB_BASE}/rest/builds",
                         params={"version": prod_prefix_search, "count": "1", "status": "SUCCESSFUL",
                                 "configuration_id": "22746", "recursive": "true"},
                         auth=auth, verify=False, proxies=proxy, timeout=10)
            if r.status_code == 200 and "<" in r.text:
                root = _ET.fromstring(r.text)
                bld = root.find("com.pmease.quickbuild.model.Build")
                if bld is not None:
                    lv = bld.findtext("version") or ""
                    m2 = re.search(r"-(\d+)$", lv)
                    if m2:
                        n_latest_prod = int(m2.group(1))
        except Exception:
            pass

        if n_latest_ci > 0 and n_latest_prod > 0:
            expected_ci = max(1, round(ver_num * n_latest_ci / n_latest_prod))
        else:
            expected_ci = ver_num
        _debug(f"gop ci resolve: n_latest_ci={n_latest_ci} n_latest_prod={n_latest_prod} expected_ci={expected_ci}")

        # Prefix-batch search — fetch CI builds in 3 adjacent bands.
        # QB ignores `offset` with wildcard queries and always returns newest-first.
        # Band granularity depends on CI number magnitude:
        #   >= 100 → hundreds band (e.g. "gop-ci-main-5*" covers 500-599)
        #   >= 10  → tens band (e.g. "gop-ci-main-5*" covers 50-59)
        #   < 10   → ones band (e.g. "gop-ci-releases_ww...-6*" covers 6, 60, 61...)
        target_bid_int = int(bid)
        page_builds = {}  # ci_bid_str -> ci_ver_str

        is_releases_naming = ci_prefix.startswith("gop-ci-releases_")

        if is_releases_naming:
            # New branch: small number of CI builds (single-digit range).
            # Do a full-prefix search to avoid wildcard "6*" missing exact "6".
            for use_cfg_filter in (True, False):
                if page_builds:
                    break
                if not use_cfg_filter:
                    _debug(f"gop ci resolve: releases full-prefix: no results with config filter, retrying without")
                extra = {"configuration_id": ci_config_id, "recursive": "true"} if use_cfg_filter else {}
                try:
                    r = _req.get(f"{QB_BASE}/rest/builds",
                                 params={"version": f"{ci_prefix}-*", "count": "50",
                                         "status": "SUCCESSFUL", **extra},
                                 auth=auth, verify=False, proxies=proxy, timeout=20)
                    if r.status_code == 200 and "<" in r.text and "<list/>" not in r.text:
                        root = _ET.fromstring(r.text)
                        for bld_el in root.findall("com.pmease.quickbuild.model.Build"):
                            ci_bid_s = bld_el.findtext("id") or ""
                            ci_ver_s = bld_el.findtext("version") or ""
                            if ci_bid_s and ci_ver_s and ci_prefix in ci_ver_s:
                                page_builds[ci_bid_s] = ci_ver_s
                except Exception as exc:
                    _debug(f"gop ci resolve: releases full-prefix fetch error: {exc}")
            _debug(f"gop ci resolve: releases full-prefix found {len(page_builds)} CI builds")
        else:
            # Existing band search for gop-ci-main / gop-ci-master
            if expected_ci >= 100:
                leading_digit = expected_ci // 100
            elif expected_ci >= 10:
                leading_digit = expected_ci // 10
            else:
                leading_digit = expected_ci
            for use_cfg_filter in (True, False):
                if use_cfg_filter:
                    extra = {"configuration_id": ci_config_id, "recursive": "true"}
                else:
                    if page_builds:
                        break
                    _debug(f"gop ci resolve: no builds with config_id={ci_config_id}, retrying without filter")
                    extra = {}
                for d in [leading_digit - 1, leading_digit, leading_digit + 1]:
                    if d < 0:
                        continue
                    search_ver = f"{ci_prefix}-{d}*"
                    try:
                        r = _req.get(f"{QB_BASE}/rest/builds",
                                     params={"version": search_ver, "count": "200",
                                             "status": "SUCCESSFUL", **extra},
                                     auth=auth, verify=False, proxies=proxy, timeout=20)
                        if r.status_code == 200 and "<" in r.text and "<list/>" not in r.text:
                            root = _ET.fromstring(r.text)
                            for bld_el in root.findall("com.pmease.quickbuild.model.Build"):
                                ci_bid_s = bld_el.findtext("id") or ""
                                ci_ver_s = bld_el.findtext("version") or ""
                                if ci_bid_s and ci_ver_s and ci_prefix in ci_ver_s:
                                    page_builds[ci_bid_s] = ci_ver_s
                    except Exception as exc:
                        _debug(f"gop ci resolve: prefix fetch error ({search_ver}): {exc}")
            _debug(f"gop ci resolve: {len(page_builds)} CI builds from band search")

        if page_builds:
            # Sort: CI builds with bid just below prod_bid ran just before prod → best candidates
            sorted_builds = sorted(
                ((int(ci_bid_s), ci_bid_s, ci_ver_s) for ci_bid_s, ci_ver_s in page_builds.items()),
                key=lambda x: (0 if x[0] < target_bid_int else 1, abs(x[0] - target_bid_int))
            )
            for ci_bid_int, ci_bid, ci_ver_s in sorted_builds[:8]:
                try:
                    r2 = _req.get(f"{QB_BASE}/rest/builds/{ci_bid}",
                                  auth=auth, verify=False, proxies=proxy, timeout=10)
                    if r2.status_code == 200:
                        ci_xml = r2.text
                        if (component_revision and component_revision in ci_xml) or \
                           (change_subject and change_subject in ci_xml):
                            _debug(f"gop ci resolve: matched {ci_ver_s} (bid_diff={target_bid_int - ci_bid_int})")
                            return ci_ver_s, ci_bid, change_subject
                except Exception:
                    pass
            # Proximity fallback: no hash/subject data available → return closest CI by build ID
            if not component_revision and not change_subject:
                _ci_bid_int, _ci_bid, _ci_ver_s = sorted_builds[0]
                _debug(f"gop ci resolve: proximity fallback → {_ci_ver_s} (no hash data)")
                return _ci_ver_s, _ci_bid, ""

        _debug(f"gop ci resolve: no match found for {bver}")
        return "", "", change_subject

    def _resolve_cherry_pick_ci_master(build_version):
        """For cherry-pick builds like 'prod-hini-releases_26ww06-prod-101.8509-revenue-pr-1018517',
        extract the prod version and find the original ci-master build.
        Returns (ci_master_str, source_version) or ("", "").
        """
        mp = re.search(r"prod-(\d+\.\d+)", build_version)
        if not mp:
            return "", ""
        prod_ver = mp.group(1)
        prod_nodots = prod_ver.replace(".", "")
        _debug(f"cherry-pick resolve: prod_ver={prod_ver} from {build_version}")

        search_patterns = [
            f"*revenue-pr-{prod_nodots}",
            f"*revenue-pr-{prod_nodots}*",
            f"prod-*{prod_nodots}*",
        ]
        for pat in search_patterns:
            params = {"version": pat, "count": "20", "status": "SUCCESSFUL"}
            if config_id:
                params["configuration_id"] = config_id
            try:
                r = _req.get(
                    f"{QB_BASE}/rest/builds",
                    params=params,
                    auth=auth, verify=False, proxies=proxy, timeout=15,
                )
                if r.status_code == 200 and "<" in r.text and "<list/>" not in r.text:
                    root = _ET.fromstring(r.text)
                    tag = "com.pmease.quickbuild.model.Build"
                    for build in root.findall(tag):
                        bver = build.findtext("version") or ""
                        if not bver.startswith("prod-hini-releases"):
                            continue
                        if "-ms-attestation-sign-" in bver or "-ms-preprod-sign-" in bver:
                            continue
                        cm = re.search(r"(ci-master-\d+)", bver)
                        if cm:
                            _debug(f"cherry-pick resolved: {prod_ver} -> {cm.group(1)} from {bver}")
                            return cm.group(1), prod_ver
            except Exception as exc:
                _debug(f"cherry-pick resolve error: {exc}")
        _debug(f"cherry-pick resolve: no ci-master found for {prod_ver}")
        return f"prod-{prod_ver}", prod_ver

    def _resolve_bugcheck_ci_master(build_el):
        """For bugcheck / hini-master builds, read variables to find the ci-master version.
        Falls back to full XML text scan for ci-master pattern.
        Returns ci_master string or "".
        """
        _VAR_KEYS = ("binary_reuse_base", "component_branch", "parent_build_version", "ci_branch", "branch")

        def _scan_sav(sav_el, bver_label):
            if sav_el is None:
                return ""
            for entry in sav_el.findall("entry"):
                children = list(entry)
                if len(children) < 2:
                    continue
                key = (children[0].text or "").strip()
                if key not in _VAR_KEYS:
                    continue
                val = ""
                for sub in children[1].iter():
                    if sub.text and sub.text.strip() and sub.tag != children[1].tag:
                        val = sub.text.strip()
                        break
                if not val:
                    val = (children[1].text or "").strip()
                if val:
                    cm = re.search(r"(ci-master-\d+)", val)
                    if cm:
                        _debug(f"resolved via {key}: {bver_label} -> {cm.group(1)} (val={val})")
                        return cm.group(1)
            return ""

        bver = build_el.findtext("version") or ""
        result = _scan_sav(build_el.find("secretAwareVariableValues"), bver)
        if result:
            return result

        bid = build_el.findtext("id")
        if bid:
            try:
                r = _req.get(
                    f"{QB_BASE}/rest/builds/{bid}",
                    auth=auth, verify=False, proxies=proxy, timeout=15,
                )
                if r.status_code == 200:
                    cm = re.search(r"(ci-master-\d+)", r.text)
                    if cm:
                        _debug(f"resolved via raw XML scan: {bver} -> {cm.group(1)}")
                        return cm.group(1)
                    detail = _ET.fromstring(r.text)
                    result = _scan_sav(detail.find("secretAwareVariableValues"), bver)
                    if result:
                        return result
                    result = _scan_sav(detail.find("variables"), bver)
                    if result:
                        return result
            except Exception as exc:
                _debug(f"hini-master detail fetch error: {exc}")

        _debug(f"ci-master resolve: no result found for {bver}")
        return ""

    # ── Main search loop ─────────────────────────────────────────────────────

    for label, version in [("fail", fail_version), ("pass", pass_version),
                            ("fix", fix_version), ("found_in", found_in_version)]:
        if not version:
            continue

        if is_gop:
            _m_ver = re.search(r'(\d+)$', version.strip())
            _ver_num = int(_m_ver.group(1)) if _m_ver else 0
            _ver_short = str(_ver_num) if _ver_num else version

            if gop_platform == "NVL":
                # Nova Lake: prod-gop-Xe3p-xx
                search_patterns = [f"prod-gop-Xe3p-{_ver_short}*"]
            elif gop_platform == "PTL" and _ver_num > 0 and _ver_num <= 30:
                search_patterns = [f"prod-gop-prod-PTL-{_ver_short}*"]
            elif gop_platform == "PTL" and _ver_num > 30 and _ver_num <= 63:
                search_patterns = [f"prod-gop-Xe3-{_ver_short}*"]
            elif gop_platform == "PTL" and _ver_num > 63:
                # New branch naming: prod-gop-prod-releases_WWNNNN_ptl-N
                search_patterns = [
                    f"prod-gop-prod-releases_*ptl-{_ver_short}",
                    f"prod-gop-*ptl-{_ver_short}*",
                ]
            else:
                search_patterns = [
                    f"prod-gop-*{gop_platform}-{_ver_short}*" if gop_platform else f"prod-gop-*{_ver_short}*",
                ]
        else:
            nodots = _version_to_nodots(version)
            search_patterns = [f"prod-*{nodots}*", f"*{nodots}*"]
            parts = version.split(".")
            if len(parts) == 4:
                search_patterns.append(f"*{parts[2]}.{parts[3]}*")
            elif len(parts) == 2:
                search_patterns.append(f"*{version}*")

        found = False
        _gop_build_count = 0  # cap: avoid unbounded CI-resolution for broad searches
        _GOP_BUILDS_CAP = 3
        for pattern in search_patterns:
            if is_gop and config_id:
                cfg_options = [config_id, None]
            else:
                cfg_options = [None]
                if config_id:
                    cfg_options.append(config_id)
            for cfg_filter in cfg_options:
                params = {"version": pattern, "count": "20", "status": "SUCCESSFUL"}
                if cfg_filter:
                    params["configuration_id"] = cfg_filter
                    if is_gop:
                        params["recursive"] = "true"
                try:
                    r = _req.get(
                        f"{QB_BASE}/rest/builds",
                        params=params,
                        auth=auth, verify=False, proxies=proxy, timeout=15,
                    )
                    if r.status_code == 200 and "<" in r.text and "<list/>" not in r.text:
                        root = _ET.fromstring(r.text)
                        tag = "com.pmease.quickbuild.model.Build"
                        for build in root.findall(tag):
                            if is_gop and _gop_build_count >= _GOP_BUILDS_CAP:
                                _debug(f"qb-search: GOP build cap ({_GOP_BUILDS_CAP}) reached for label={label}")
                                break
                            bid = build.findtext("id") or ""
                            bver = build.findtext("version") or ""
                            bstatus = build.findtext("status") or ""
                            bcfg = build.findtext("configuration") or ""
                            if is_gop:
                                if not (bver.startswith("gop-ci-") or bver.startswith("prod-gop-")):
                                    continue
                                if bver.startswith("coverity-") or bver.startswith("gop-verify-"):
                                    continue
                                if gop_platform and bver.startswith("prod-gop-"):
                                    _bnum_m = re.search(r'-(\d+)$', bver)
                                    _bnum = int(_bnum_m.group(1)) if _bnum_m else 0
                                    _GOP_PLATFORM_PROD_FILTER = {
                                        "PTL": lambda v, n: (
                                            v.startswith("prod-gop-prod-PTL-") if n <= 30 else
                                            (v.startswith("prod-gop-Xe3-") if n <= 63 else
                                             ("releases_" in v and "ptl-" in v.lower()))
                                        ),
                                        "NVL": lambda v, n: v.startswith("prod-gop-Xe3p-"),
                                    }
                                    filter_fn = _GOP_PLATFORM_PROD_FILTER.get(gop_platform)
                                    if filter_fn and not filter_fn(bver, _bnum):
                                        continue
                            else:
                                if not bver.startswith("prod-hini-releases") and \
                                   not bver.startswith("prod-bugcheck-") and \
                                   not bver.startswith("prod-hini-master-"):
                                    continue
                            if "-ms-attestation-sign-" in bver:
                                continue
                            if "-ms-preprod-sign-" in bver:
                                continue
                            is_bugcheck = bver.startswith("prod-bugcheck-")
                            is_hini_master = bver.startswith("prod-hini-master-")
                            if is_gop:
                                if bver.startswith("prod-gop-"):
                                    ci_master, ci_build_id, _change_subj = _resolve_gop_ci_from_prod(
                                        build, gop_platform, _ver_num)
                                    # ── Resolve previous prod's CI master so the range boundary is exact ──
                                    _prev_ci_master = ""
                                    _m_bv = re.search(r'^(.+?)(\d+)$', bver)
                                    if _m_bv and ci_master:
                                        _prev_prod_ver = f"{_m_bv.group(1)}{int(_m_bv.group(2)) - 1}"
                                        try:
                                            _rp = _req.get(
                                                f"{QB_BASE}/rest/builds",
                                                params={"version": _prev_prod_ver, "count": "3",
                                                        "status": "SUCCESSFUL"},
                                                auth=auth, verify=False, proxies=proxy, timeout=10)
                                            if _rp.status_code == 200 and "<" in _rp.text \
                                                    and "<list/>" not in _rp.text:
                                                _prev_root = _ET.fromstring(_rp.text)
                                                _ptag = "com.pmease.quickbuild.model.Build"
                                                for _pb in _prev_root.findall(_ptag):
                                                    if (_pb.findtext("version") or "") == _prev_prod_ver:
                                                        _m_pn = re.search(r'-(\d+)$', _prev_prod_ver)
                                                        _pv_num = int(_m_pn.group(1)) if _m_pn else 0
                                                        _prev_ci_master, _, _ = _resolve_gop_ci_from_prod(
                                                            _pb, gop_platform, _pv_num)
                                                        break
                                        except Exception as _pce:
                                            _debug(f"qb-all-ci: prev prod CI lookup error: {_pce}")
                                    _all_ci = qb_get_all_ci_builds_in_prod(
                                        bver, ci_last_version=ci_master,
                                        ci_prev_last_version=_prev_ci_master)
                                else:
                                    ci_master = _extract_gop_ci_main(bver)
                                    ci_build_id = bid
                                    _all_ci = []
                                src_ver = ""
                            elif is_bugcheck:
                                ci_master = _resolve_bugcheck_ci_master(build)
                                src_ver = ""
                            elif is_hini_master:
                                ci_master = _resolve_bugcheck_ci_master(build)
                                src_ver = ""
                            elif re.search(r"prod-\d+\.\d+", bver):
                                ci_master = _resolve_bugcheck_ci_master(build)
                                if ci_master:
                                    mp = re.search(r"prod-(\d+\.\d+)", bver)
                                    src_ver = mp.group(1) if mp else ""
                                else:
                                    ci_master, src_ver = _resolve_cherry_pick_ci_master(bver)
                            else:
                                ci_master = _extract_ci_master(bver)
                                src_ver = ""
                            build_entry = {
                                "build_id": bid,
                                "version": bver,
                                "status": bstatus,
                                "configuration_id": bcfg,
                                "ci_master": ci_master,
                            }
                            if is_gop and ci_build_id:
                                build_entry["ci_build_id"] = ci_build_id
                            if is_gop and _all_ci:
                                build_entry["ci_builds"] = _all_ci
                            elif not is_gop and ci_master:
                                gfx_ci_bid = _lookup_gfx_ci_build_id(ci_master)
                                if gfx_ci_bid:
                                    build_entry["ci_build_id"] = gfx_ci_bid
                            if src_ver:
                                build_entry["cherry_pick_from"] = src_ver
                            if is_bugcheck:
                                build_entry["is_bugcheck"] = True
                            results[f"{label}_builds"].append(build_entry)
                            if is_gop:
                                _gop_build_count += 1
                    if results[f"{label}_builds"]:
                        found = True
                        _debug(f"qb-search {label} (pattern={pattern}, cfg={cfg_filter}): "
                               f"{len(results[f'{label}_builds'])} builds")
                        break
                except Exception as exc:
                    _debug(f"qb-search {label} error: {exc}")
            if found:
                break

        if not found:
            _debug(f"qb-search {label}: no builds found for {version}")

    results["quickbuild_url"] = qb_dashboard
    return results


# ── HSD Regression Check ──────────────────────────────────────────────────────

REGRESSION_FIELDS = (
    "id,title,status,family,component,component_affected,"
    "client_platf.bug.regression,"
    "client_platf.bug.last_passing_bkc,"
    "client_platf.bug.fixed_in_version,"
    "client_platf.bug.ss_gfx_driver_version,"
    "client_platf.bug.version_found_in,"
    "client_platf.bug.found_in_sw_version,"
    "regression,is_regression,regression_build_label,from_release,"
    "description"
)


def check_hsd_regression(hsd_id, build_type="gfx"):
    """Query HSD API directly for regression-related fields using Kerberos auth.

    Returns dict with keys:
      ok, hsd_id, title, status, component, driver_version_fail,
      driver_version_fail_source, found_in_version, is_regression,
      last_passing_bkc, fixed_in_version, quickbuild_url
      (+ gop_platform if build_type == "gop")
    """
    url = (
        f"https://hsdes-api.intel.com/rest/article/{hsd_id}"
        f"?fields={REGRESSION_FIELDS}"
    )
    _debug(f"regression-check fetch url={url}")

    try:
        import requests as _req
        from requests_kerberos import HTTPKerberosAuth as _KerberosAuth
        from requests_kerberos import OPTIONAL as _OPTIONAL
        import urllib3 as _u3
    except ImportError:
        _debug("auto-installing missing packages: requests, requests_kerberos, urllib3")
        import subprocess
        _pkgs = ["requests", "requests_kerberos", "urllib3"]
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + _pkgs)
        import requests as _req
        from requests_kerberos import HTTPKerberosAuth as _KerberosAuth
        from requests_kerberos import OPTIONAL as _OPTIONAL
        import urllib3 as _u3
    try:
        _u3.disable_warnings()
        resp = _req.get(
            url,
            auth=_KerberosAuth(mutual_authentication=_OPTIONAL),
            verify=False,
            headers={"Content-type": "application/json"},
            proxies={"http": "", "https": ""},
            timeout=30,
        )
        if resp.status_code != 200:
            return {"ok": False, "error": f"HSD API HTTP {resp.status_code}"}
        data = resp.json().get("data", [])
    except Exception as exc:
        return {"ok": False, "error": f"HSD API error: {exc}"}

    if not data:
        return {"ok": False, "error": f"HSD {hsd_id} not found or no data returned"}

    row = data[0] if isinstance(data, list) else data

    def _normalize_version(v):
        """Normalize driver version strings: '32.0.101.8793' -> '101.8793'"""
        v = v.strip()
        if not v:
            return v
        v = v.split(",")[0].strip()
        parts = v.split(".")
        if len(parts) == 4:
            v = parts[2] + "." + parts[3]
        if re.fullmatch(r"\d+\.\d+", v):
            return v
        m = re.search(r"\b(10[0-9]\.\d{4,})\b", v)
        if m:
            return m.group(1)
        m = re.search(r"\b(\d{2,}\.\d{4,})\b", v)
        if m:
            return m.group(1)
        return v

    def _extract_gop_version(v):
        """Extract GOP version number: 'GOP v47' -> '47', '26.0.47' -> '47', 'ww47' -> '47'"""
        v = v.strip()
        if not v:
            return ""
        # Guard: GFX driver versions have 4+ digit build suffixes (e.g. "101.8793",
        # "32.0.101.8793"). GOP versions are small integers — skip these entirely.
        if re.search(r'\.\d{4,}', v):
            return ""
        m = re.search(r'\b\d+\.\d+\.(\d+)\b', v)
        if m:
            return m.group(1)
        cleaned = re.sub(r'(?i)\bgop\b', '', v).strip()
        m = re.search(r'\bv?(\d+)\b', cleaned)
        if m:
            return m.group(1)
        # Handle "wwNN" / "wNN" work-week suffix (e.g. "ww47" -> "47")
        m = re.search(r'(\d+)\s*$', cleaned)
        if m:
            return m.group(1)
        return v

    def _parse_gop_platform(family="", component="", title=""):
        """Extract platform short name from HSD family, component, and/or title field."""
        _PLATFORM_MAP = {
            "nova lake": "NVL",
            "panther lake": "PTL",
            "wildcat lake": "PTL",
            "lunar lake": "LNL",
            "arrow lake": "ARL",
            "meteor lake": "MTL",
            "battlemage": "BMG",
            "raptor lake": "RPL",
            "alder lake": "ADL",
            "tiger lake": "TGL",
            "dg2": "DG2",
            "xe3p": "NVL",   # architecture alias for Nova Lake
            "cls": "CLS",
        }
        # Short abbreviations matched as [ABBREV] in the HSD title
        _KNOWN_ABBREVS = ["NVL", "PTL", "LNL", "ARL", "MTL", "BMG", "ADL", "TGL", "DG2"]
        # Board / project codenames → platform
        _BOARD_MAP = {"janus": "PTL"}

        # 1. family field (highest priority) — e.g. "Panther Lake Platforms"
        if family:
            family_lower = family.lower()
            for name, short in _PLATFORM_MAP.items():
                if name in family_lower:
                    return short

        # 2. component field (priority: firmware/GOP sub-components first)
        if component:
            comp_lower = component.lower()
            for part in component.split(","):
                part = part.strip().lower()
                if "gop" in part or "firmware" in part:
                    for name, short in _PLATFORM_MAP.items():
                        if name in part:
                            return short
            for name, short in _PLATFORM_MAP.items():
                if name in comp_lower:
                    return short

        # 3. Fallback: scan the HSD title for [ABBREV] markers, full names, and codenames
        if title:
            title_upper = title.upper()
            title_lower = title.lower()
            for abbrev in _KNOWN_ABBREVS:
                if f"[{abbrev}]" in title_upper or f"[{abbrev} " in title_upper:
                    return abbrev
            for name, short in _PLATFORM_MAP.items():
                if name in title_lower:
                    return short
            for board, short in _BOARD_MAP.items():
                if board in title_lower:
                    return short

        return ""

    regression_val = (
        str(row.get("client_platf.bug.regression") or "").strip()
        or str(row.get("is_regression") or row.get("regression") or "").strip()
        or "Unknown"
    )

    title = str(row.get("title") or "").strip()
    description = str(row.get("description") or "").strip()
    _fail_candidates = [
        ("ss_gfx_driver_version",  str(row.get("client_platf.bug.ss_gfx_driver_version") or "").strip()),
        ("found_in_sw_version",    str(row.get("client_platf.bug.found_in_sw_version") or "").strip()),
        ("version_found_in",       str(row.get("client_platf.bug.version_found_in") or "").strip()),
        ("from_release",           str(row.get("from_release") or "").strip()),
    ]
    driver_fail = ""
    driver_fail_source = ""
    for _src, _val in _fail_candidates:
        if _val:
            driver_fail = _val
            driver_fail_source = _src
            break
    if not driver_fail and title:
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", title)
        if m:
            driver_fail = m.group(1)
            driver_fail_source = "title"
    if not driver_fail and description:
        m = re.search(r"(\d+\.\d+\.\d+\.\d+|\b10[0-9]\.\d{4,}\b)", description)
        if m:
            driver_fail = m.group(1)
            driver_fail_source = "description"
    driver_fail = _normalize_version(driver_fail)
    _debug(f"driver_fail={driver_fail!r} source={driver_fail_source!r}")

    last_passing = (
        str(row.get("client_platf.bug.last_passing_bkc") or "").strip()
        or str(row.get("regression_build_label") or "").strip()
    )
    last_passing = _normalize_version(last_passing)

    fixed_in = str(row.get("client_platf.bug.fixed_in_version") or "").strip()
    fixed_in = _normalize_version(fixed_in)

    found_in_sw = str(row.get("client_platf.bug.found_in_sw_version") or "").strip()
    found_in_sw = _normalize_version(found_in_sw)
    if found_in_sw and found_in_sw == driver_fail:
        found_in_sw = ""

    status = str(row.get("status") or "").strip()
    component = str(row.get("component") or row.get("component_affected") or "").strip()

    gop_platform = ""
    if build_type == "gop":
        family = str(row.get("family") or "").strip()
        gop_platform = _parse_gop_platform(family=family, component=component, title=title)
        _debug(f"gop_platform={gop_platform!r} family={family!r} component={component!r} title={title[:60]!r}")

        raw_found_in = str(row.get("client_platf.bug.found_in_sw_version") or "").strip()
        raw_version_found_in = str(row.get("client_platf.bug.version_found_in") or "").strip()
        gop_fail_raw = raw_found_in or raw_version_found_in
        if gop_fail_raw:
            gop_fail = _extract_gop_version(gop_fail_raw)
            if gop_fail:
                driver_fail = gop_fail
                driver_fail_source = "found_in_sw_version (GOP)"
                _debug(f"gop override driver_fail={driver_fail!r} from raw={gop_fail_raw!r}")

        raw_passing = str(row.get("client_platf.bug.last_passing_bkc") or "").strip()
        if raw_passing:
            gop_pass = _extract_gop_version(raw_passing)
            if gop_pass:
                last_passing = gop_pass
                _debug(f"gop override last_passing={last_passing!r} from raw={raw_passing!r}")

        raw_fixed = str(row.get("client_platf.bug.fixed_in_version") or "").strip()
        if raw_fixed:
            gop_fixed = _extract_gop_version(raw_fixed)
            if gop_fixed:
                fixed_in = gop_fixed
                _debug(f"gop override fixed_in={fixed_in!r} from raw={raw_fixed!r}")

        if found_in_sw:
            found_in_sw = _extract_gop_version(found_in_sw) or found_in_sw
        if found_in_sw == driver_fail:
            found_in_sw = ""

        # Normalize last_passing to bare GOP number if it came from a non-GOP field
        # (e.g. regression_build_label="ww47" → "47")
        if last_passing and not last_passing.isdigit():
            _gp_norm = _extract_gop_version(last_passing)
            if _gp_norm:
                last_passing = _gp_norm
                _debug(f"gop normalized last_passing={last_passing!r}")

        # ── Fallback: scan description HTML for GOP version info when fields are empty ──
        if not driver_fail or not last_passing:
            _debug(f"gop version fields incomplete (fail={driver_fail!r} pass={last_passing!r}), scanning description")
            if description:
                import html as _html_mod
                _desc = re.sub(r'<[^>]+>', ' ', _html_mod.unescape(description))
                _desc = re.sub(r'\s+', ' ', _desc)

                # Strategy 1: explicit "Pass/Fail on GOP vN" text in description
                _PASS_RE = re.compile(
                    r'pass(?:ing)?(?:\s+on)?\s+GOP\s+(?:version\s+)?v?(\d+)'
                    r'|GOP\s+(?:version\s+)?v?(\d+)\s+(?:is\s+)?pass',
                    re.IGNORECASE)
                _FAIL_RE = re.compile(
                    r'fail(?:s|ed)?(?:\s+on)?\s+GOP\s+(?:version\s+)?v?(\d+)'
                    r'|GOP\s+(?:version\s+)?v?(\d+)\s+(?:is\s+)?fail',
                    re.IGNORECASE)
                if not last_passing:
                    _mp = _PASS_RE.search(_desc)
                    if _mp:
                        last_passing = _mp.group(1) or _mp.group(2) or ""
                        _debug(f"desc explicit pass={last_passing!r}")
                if not driver_fail:
                    _mf = _FAIL_RE.search(_desc)
                    if _mf:
                        driver_fail = _mf.group(1) or _mf.group(2) or ""
                        driver_fail_source = "description_explicit (GOP)"
                        _debug(f"desc explicit fail={driver_fail!r}")

                # Strategy 2: "GOP Driver [XX.X.NN]" paired with "DB:Start: NNNNN" timing
                # Sort by timing: smallest=pass, largest=fail
                if not driver_fail or not last_passing:
                    _timing_pairs = []
                    for _tm in re.finditer(
                        r'GOP\s+Driver\s+\[\d+\.\d+\.(\d+)\].*?DB:Start:\s*(\d+)',
                        _desc, re.IGNORECASE
                    ):
                        _ver_n, _t = int(_tm.group(1)), int(_tm.group(2))
                        if _ver_n <= 999:   # skip large build-number versions from other platforms
                            _timing_pairs.append((_ver_n, _t))
                    _debug(f"timing_pairs={_timing_pairs!r}")
                    if len(_timing_pairs) >= 2:
                        _timing_pairs.sort(key=lambda x: x[1])
                        if not last_passing:
                            last_passing = str(_timing_pairs[0][0])
                            _debug(f"desc timing pass={last_passing!r}")
                        if not driver_fail:
                            driver_fail = str(_timing_pairs[-1][0])
                            driver_fail_source = "description_timing (GOP)"
                            _debug(f"desc timing fail={driver_fail!r}")

                # Strategy 3: collect all "GOP vN" / "26.0.N" mentions (first=pass, last=fail)
                if not driver_fail or not last_passing:
                    _gop_vers = list(dict.fromkeys(
                        re.findall(r'GOP\s+(?:Driver\s+\[\d+\.\d+\.)?v?(\d+)', _desc, re.IGNORECASE)
                    ))
                    _debug(f"gop_ver_scan={_gop_vers!r}")
                    if not last_passing and _gop_vers:
                        last_passing = _gop_vers[0]
                    if not driver_fail and len(_gop_vers) >= 2:
                        driver_fail = _gop_vers[-1]
                        driver_fail_source = "description_scan (GOP)"
                        _debug(f"desc scan final: fail={driver_fail!r} pass={last_passing!r}")

    result = {
        "ok": True,
        "hsd_id": str(hsd_id),
        "title": title,
        "status": status,
        "component": component,
        "driver_version_fail": driver_fail,
        "driver_version_fail_source": driver_fail_source,
        "found_in_version": found_in_sw,
        "is_regression": regression_val,
        "last_passing_bkc": last_passing,
        "fixed_in_version": fixed_in,
        "quickbuild_url": "https://ubit-gfx.intel.com/dashboard/8078" if build_type == "gop" else "https://ubit-gfx.intel.com/dashboard/7931",
    }
    if build_type == "gop" and gop_platform:
        result["gop_platform"] = gop_platform
    _debug(f"regression-check result: {result}")
    return result
