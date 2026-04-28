import json
import logging
import os
import sys
from collections import defaultdict

from etl_classifier import ETLAnalyzer


reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
if callable(reconfigure_stdout):
    reconfigure_stdout(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    stream=sys.stdout,
)
LOGGER = logging.getLogger(__name__)


def load_etl_index(workspace):
    etl_index_path = os.path.join(workspace, "all_etl_files.json")
    if not os.path.exists(etl_index_path):
        LOGGER.warning("ETL index file not found: %s", etl_index_path)
        return [], etl_index_path

    with open(etl_index_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list):
            LOGGER.info("Loaded %s ETL index entries from %s", len(data), etl_index_path)
            return data, etl_index_path
        LOGGER.warning("ETL index at %s is not a list; treating as empty", etl_index_path)
        return [], etl_index_path


def describe_index_targets(etl_index, limit=10):
    targets = []
    seen = set()
    for item in etl_index:
        attachment_name = (item.get("attachment_name") or "").strip()
        file_name = os.path.basename(item.get("file_name", "") or item.get("file_path", ""))
        for candidate in (attachment_name, file_name):
            if candidate and candidate.lower() not in seen:
                seen.add(candidate.lower())
                targets.append(candidate)
        if len(targets) >= limit:
            break
    return targets


def select_targets(etl_index, etl_target):
    target = (etl_target or "").strip()
    if not target:
        return [], "empty_target"

    # 1) Exact ETL file name match
    file_matches = [
        item for item in etl_index
        if os.path.basename(item.get("file_name", "")).lower() == target.lower()
    ]
    if file_matches:
        return file_matches, "exact_file_name"

    # 2) Exact attachment name match -> analyze all ETLs in that attachment
    attachment_matches = [
        item for item in etl_index
        if item.get("attachment_name", "").lower() == target.lower()
    ]
    if attachment_matches:
        return attachment_matches, "exact_attachment_name"

    # 3) Fallback substring match on ETL file name
    partial_matches = [
        item for item in etl_index
        if target.lower() in os.path.basename(item.get("file_name", "")).lower()
    ]
    if partial_matches:
        return partial_matches, "partial_file_name"

    # 4) Fallback substring match on attachment name
    partial_attachment_matches = [
        item for item in etl_index
        if target.lower() in item.get("attachment_name", "").lower()
    ]
    if partial_attachment_matches:
        return partial_attachment_matches, "partial_attachment_name"

    return [], "no_match"


def analyze_etl(path):
    analyzer = ETLAnalyzer()
    result = analyzer.analyze_etl(path)

    if "error" in result:
        return {
            "status": "error",
            "error": result.get("error", "Unknown ETL analyzer error"),
            "etl_type": "Analysis Failed",
            "driver_info": {"found": False},
            "pipe_underrun": {"detected": False},
        }

    driver_info = result.get("driver_info", {}) or {}
    return {
        "status": "ok",
        "etl_type": result.get("type", "Unknown"),
        "driver_info": {
            "found": bool(driver_info.get("found")),
            "build_type": driver_info.get("driver_build_type", "Unknown"),
            "version": driver_info.get("driver_version", "Unknown"),
            "build_date": driver_info.get("driver_build_date", "Unknown"),
            "build_string": driver_info.get("build_string", ""),
        },
        "pipe_underrun": {
            "detected": bool(result.get("pipe_underrun_detected", False))
        },
    }


def main():
    workspace = os.environ["GNAI_TEMP_WORKSPACE"]
    hsd_id = str(os.environ.get("GNAI_INPUT_ID", "")).strip()
    etl_target = os.environ.get("GNAI_INPUT_ETL_TARGET", "").strip()

    LOGGER.info("Starting native ETL analysis for HSD %s target '%s'", hsd_id or "<unknown>", etl_target)
    etl_index, etl_index_path = load_etl_index(workspace)
    selected, selection_mode = select_targets(etl_index, etl_target)
    LOGGER.info(
        "ETL target resolution for '%s': mode=%s matches=%s",
        etl_target,
        selection_mode,
        len(selected),
    )

    if not selected:
        available_targets = describe_index_targets(etl_index)
        LOGGER.warning(
            "No ETL files matched target '%s'. Available targets sample=%s",
            etl_target,
            available_targets,
        )
        output = {
            "hsd_id": hsd_id,
            "etl_target": etl_target,
            "status": "no_match",
            "message": "No ETL files matched the selected target.",
            "selection_mode": selection_mode,
            "etl_index_path": etl_index_path,
            "indexed_entry_count": len(etl_index),
            "available_targets": available_targets,
            "analyzed_files": [],
            "summary": {
                "total_analyzed": 0,
                "pipe_underrun_count": 0,
                "driver_versions": [],
            },
        }
        print(json.dumps(output, indent=2))
        return

    analyzed_files = []
    driver_versions = set()
    pipe_underrun_count = 0

    for item in selected:
        file_path = item.get("file_path", "")
        file_name = os.path.basename(item.get("file_name") or file_path)
        attachment_name = item.get("attachment_name", "")
        LOGGER.info(
            "Analyzing ETL candidate file='%s' attachment='%s' path='%s'",
            file_name,
            attachment_name,
            file_path,
        )

        if not file_path or not os.path.exists(file_path):
            LOGGER.error("ETL file path not found on disk: %s", file_path)
            analyzed_files.append({
                "attachment_name": attachment_name,
                "file_name": file_name,
                "file_path": file_path,
                "status": "error",
                "error": "ETL file path not found on disk",
            })
            continue

        result = analyze_etl(file_path)
        LOGGER.info(
            "Finished ETL analysis for '%s' with status=%s type=%s",
            file_name,
            result.get("status"),
            result.get("etl_type"),
        )

        if result.get("pipe_underrun", {}).get("detected"):
            pipe_underrun_count += 1

        driver = result.get("driver_info", {})
        if driver.get("found"):
            driver_versions.add((
                driver.get("build_type", "Unknown"),
                driver.get("version", "Unknown"),
                driver.get("build_date", "Unknown"),
            ))

        analyzed_files.append({
            "attachment_name": attachment_name,
            "file_name": file_name,
            "file_path": file_path,
            **result,
        })

    output = {
        "hsd_id": hsd_id,
        "etl_target": etl_target,
        "status": "ok",
        "etl_index_path": etl_index_path,
        "analyzed_files": analyzed_files,
        "summary": {
            "total_analyzed": len(analyzed_files),
            "pipe_underrun_count": pipe_underrun_count,
            "driver_versions": [
                {
                    "build_type": t[0],
                    "version": t[1],
                    "build_date": t[2],
                }
                for t in sorted(driver_versions)
            ],
        },
    }

    LOGGER.info(
        "Native ETL analysis complete for target '%s': analyzed=%s pipe_underrun=%s",
        etl_target,
        len(analyzed_files),
        pipe_underrun_count,
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
