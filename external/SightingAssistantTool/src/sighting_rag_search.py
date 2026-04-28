import base64
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_MAX_DOCUMENTS = 10
DEFAULT_GNAI_URL = "https://gnai.intel.com/api"
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_SLEEP_SECONDS = 3
TRIVIAL_SKIP_QUERIES = {
    "skip",
    "none",
    "no",
    "n/a",
    "na",
    "nothing",
}


def to_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def resolve_gnai_url() -> str:
    gnai_url = os.environ.get("GNAI_URL", "").strip()
    if gnai_url:
        # Normalize to avoid double slashes when appending paths
        return gnai_url.rstrip("/")
    return DEFAULT_GNAI_URL.rstrip("/")


def build_auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def print_result(lines: list[str]) -> None:
    payload = {
        "__meta__": {"type": "tool-result", "version": "v1"},
        "output": "\n".join(lines),
    }
    print(json.dumps(payload, ensure_ascii=False))


def extract_links(text: str | None) -> list[str]:
    """Extract HTTP/HTTPS links from free text while preserving order."""
    if not text:
        return []

    matches = re.findall(r"https?://[^\s)\]>'\"}]+", text)
    seen = set()
    ordered = []
    for link in matches:
        cleaned = link.rstrip('.,;:')
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered


def post_vector_search_with_retry(url: str, headers: dict, body: dict, timeout_seconds: int) -> requests.Response:
    """Perform vector search with bounded retry for transient network/backend issues."""
    last_exc = None
    for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=body,
                timeout=timeout_seconds,
                verify=False,
            )
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < DEFAULT_MAX_RETRIES:
                sleep_seconds = DEFAULT_RETRY_SLEEP_SECONDS * attempt
                time.sleep(sleep_seconds)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Vector search retry loop ended without response or exception")


def run_single_query(query: str, base_url: str, headers: dict, profile: str, max_documents: int) -> list[str]:
    """Run one vector search and return formatted result lines."""
    params = urllib.parse.urlencode({
        "profile": profile,
        "retrieval_type": "hybrid",
        "max_documents": max_documents,
    })
    try:
        resp = post_vector_search_with_retry(
            url=f"{base_url}/rag/vector/search?{params}",
            headers=headers,
            body={"question": query, "filters": {}},
            timeout_seconds=120,
        )
    except requests.RequestException as exc:
        return [f"ERROR: vector search failed after {DEFAULT_MAX_RETRIES} attempts: {exc}"]

    if not resp.ok:
        return [f"ERROR: vector search failed: {resp.status_code} {resp.text}"]

    try:
        response_data = resp.json()
    except ValueError as exc:
        return [f"ERROR: failed to parse vector search response as JSON: {exc}"]

    results = response_data.get("items", [])
    lines = [f"Found {len(results)} documents (query: {query[:80]}{'...' if len(query) > 80 else ''})",
             f"Profile: {profile}"]
    all_seen_links: set[str] = set()
    all_retrieved_links: list[str] = []

    for issue in results:
        issue_title = issue.get('title', '')
        issue_url = (issue.get('url', '') or '').strip()
        issue_content = issue.get("page_content") or ""
        issue_links = []
        if issue_url:
            issue_links.append(issue_url)
        for content_link in extract_links(issue_content):
            if content_link not in issue_links:
                issue_links.append(content_link)
        for link in issue_links:
            if link not in all_seen_links:
                all_seen_links.add(link)
                all_retrieved_links.append(link)
        lines.append("")
        lines.append(f"### {issue_title}")
        lines.append(f"link: {issue_url}")
        if issue_links:
            lines.append("retrieved_links:")
            for link in issue_links:
                lines.append(f"- {link}")
        lines.append(issue_content)

    if all_retrieved_links:
        lines.append("")
        lines.append("### Relevant Links Retrieved")
        for link in all_retrieved_links:
            lines.append(f"- {link}")

    return lines


def main() -> int:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(stdout_reconfigure):
        stdout_reconfigure(encoding="utf-8")

    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if callable(stderr_reconfigure):
        stderr_reconfigure(encoding="utf-8")

    search_query_raw = os.environ.get("GNAI_INPUT_SEARCH_QUERY", "").strip()
    profile = os.environ.get("GNAI_INPUT_PROFILE", "").strip()
    max_documents = to_int(os.environ.get("GNAI_INPUT_MAX_DOCUMENTS"), DEFAULT_MAX_DOCUMENTS)

    if not search_query_raw:
        print_result(["ERROR: search_query is required"])
        return 1
    if not profile:
        print_result(["ERROR: profile is required"])
        return 1
    if profile != "gpu-debug":
        print_result([f"ERROR: invalid profile '{profile}'. Only 'gpu-debug' is supported."])
        return 1

    # Support JSON array of queries for parallel execution.
    # Pass search_query as '["query1", "query2"]' to run both in parallel.
    queries: list[str] = []
    if search_query_raw.startswith("["):
        try:
            parsed = json.loads(search_query_raw)
            if isinstance(parsed, list):
                queries = [str(q).strip() for q in parsed if str(q).strip()]
        except (json.JSONDecodeError, ValueError):
            pass
    if not queries:
        queries = [search_query_raw]

    # Filter trivial skip tokens
    queries = [q for q in queries if q.lower() not in TRIVIAL_SKIP_QUERIES]
    if not queries:
        print_result(["ERROR: all search queries are skip tokens"])
        return 1

    username = os.environ.get("INTEL_USERNAME", "").strip()
    password = os.environ.get("INTEL_PASSWORD", "").strip()
    if not username or not password:
        print_result(["ERROR: INTEL_USERNAME and INTEL_PASSWORD are required"])
        return 1

    base_url = resolve_gnai_url()
    headers = build_auth_header(username, password)

    if len(queries) == 1:
        # Single query — run directly
        lines = run_single_query(queries[0], base_url, headers, profile, max_documents)
        print_result(lines)
    else:
        # Multiple queries — run in parallel
        results_map: dict[str, list[str]] = {}
        with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as executor:
            future_to_query = {
                executor.submit(run_single_query, q, base_url, headers, profile, max_documents): q
                for q in queries
            }
            for future in as_completed(future_to_query):
                q = future_to_query[future]
                try:
                    results_map[q] = future.result()
                except Exception as exc:
                    results_map[q] = [f"ERROR: query failed: {exc}"]

        # Output in original query order with section headers
        all_lines: list[str] = []
        for q in queries:
            all_lines.append(f"\n{'='*60}")
            all_lines.append(f"Query: {q}")
            all_lines.append('='*60)
            all_lines.extend(results_map.get(q, []))
        print_result(all_lines)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
