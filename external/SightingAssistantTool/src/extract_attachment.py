"""
extract_attachment.py — GNAI command tool entrypoint for on-demand archive extraction.

Reads GNAI_INPUT_ATTACHMENT_NAME from the environment, locates the archive in
archive_manifest.json, extracts it, copies analysis-relevant files (.log, .txt,
.trace, .csv) to persistent_logs/, and updates all_log_txt_trace_csv_files.json.

Environment variables consumed
-------------------------------
GNAI_INPUT_ATTACHMENT_NAME  : Archive filename key in the manifest (required)
GNAI_TEMP_WORKSPACE         : Session temp directory written by check_attachments.py
"""

import json
import logging
import os
import sys

import requests
from requests_kerberos import HTTPKerberosAuth
import urllib3

urllib3.disable_warnings()

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s', stream=sys.stdout)
LOGGER = logging.getLogger(__name__)

# Ensure src/ is on the path so utils.archive_utils is importable when the
# script is invoked via $GNAI_TOOLKIT_ENTRYPOINT from the toolkit root.
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from utils.archive_utils import (
    extract_archive_on_demand_with_status,
    read_archive_manifest,
    write_archive_manifest,
    _resolve_archive_path,
)
from utils.log_utils import get_sat_output_dir


def _redownload_missing_parts(entry, workspace):
    """Re-download missing archive (or split parts) from HSD when files are absent.

    Uses raw HTTP + Kerberos auth to avoid the HSDESAPI destructor that
    auto-deletes downloaded files on instance teardown.

    Returns True if at least the primary archive file (or the first split part)
    is now available on disk.
    """
    is_split = entry.get('is_split', False)
    hsd_id = (entry.get('hsd_id') or '').strip()

    # Determine download directory — prefer the persistent raw_attachments/ dir.
    if hsd_id:
        download_dir = os.path.join(get_sat_output_dir(hsd_id), 'raw_attachments')
    else:
        download_dir = workspace
    os.makedirs(download_dir, exist_ok=True)

    def _download_one(attach_id, filename):
        dest = os.path.join(download_dir, filename)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            return True
        url = f'https://hsdes-api.intel.com/rest/binary/{attach_id}'
        try:
            with requests.get(
                url, verify=False, auth=HTTPKerberosAuth(),
                headers={'Content-type': 'application/json'}, timeout=300,
                stream=True,
            ) as resp:
                if resp.status_code == 200:
                    bytes_written = 0
                    with open(dest, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            f.write(chunk)
                            bytes_written += len(chunk)
                    if bytes_written > 0:
                        LOGGER.info("Re-downloaded %s (%s bytes) → %s", filename, bytes_written, dest)
                        return True
                    if os.path.exists(dest):
                        os.remove(dest)
                LOGGER.error("HSD download HTTP %s for %s (id=%s)", resp.status_code, filename, attach_id)
        except Exception as exc:
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except OSError:
                    pass
            LOGGER.error("HSD download failed for %s (id=%s): %s", filename, attach_id, exc)
        return False

    if is_split:
        split_parts = entry.get('split_parts', [])
        if not split_parts:
            return False
        ok_count = 0
        for part in split_parts:
            aid = str(part.get('attach_id', ''))
            fname = part.get('filename', '')
            if not aid or not fname:
                continue
            if _download_one(aid, fname):
                # Update abs_path so extraction can find the file
                part['abs_path'] = os.path.join(download_dir, fname)
                ok_count += 1
        LOGGER.info("Re-downloaded %d/%d split parts", ok_count, len(split_parts))
        return ok_count == len(split_parts)
    else:
        attach_id = str(entry.get('id', ''))
        fname = entry.get('abs_path', '')
        if not fname:
            return False
        fname = os.path.basename(fname)
        if not attach_id or not fname:
            return False
        if _download_one(attach_id, fname):
            entry['abs_path'] = os.path.join(download_dir, fname)
            return True
        return False


def main():
    attachment_name = os.environ.get('GNAI_INPUT_ATTACHMENT_NAME', '').strip()
    workspace = os.environ.get('GNAI_TEMP_WORKSPACE', '').strip()

    if not attachment_name:
        print(json.dumps({
            'success': False,
            'error': 'GNAI_INPUT_ATTACHMENT_NAME is empty or not set.',
        }, indent=2))
        sys.exit(1)

    if not workspace or not os.path.isdir(workspace):
        print(json.dumps({
            'success': False,
            'error': f'GNAI_TEMP_WORKSPACE is not set or does not exist: {workspace!r}',
        }, indent=2))
        sys.exit(1)

    # Verify the manifest knows about this archive
    manifest = read_archive_manifest(workspace)
    if attachment_name not in manifest:
        known = sorted(manifest.keys())
        print(json.dumps({
            'success': False,
            'error': f'"{attachment_name}" not found in archive_manifest.json.',
            'known_archives': known,
        }, indent=2))
        sys.exit(1)

    entry = manifest[attachment_name]
    members_peeked = entry.get('members', [])

    LOGGER.info(
        "Resolving on-demand extraction for attachment '%s' in workspace '%s'",
        attachment_name,
        workspace,
    )

    # Check if archive files are missing and attempt re-download from HSD.
    # This recovers from the HSDESAPI destructor deleting raw_attachments/
    # files at the end of check_attachments.py, or from cross-session runs
    # where the files were cleaned up.
    resolved_path, _ = _resolve_archive_path(entry, workspace, attachment_name)
    if not resolved_path:
        LOGGER.info(
            "Archive files not found on disk for '%s' — attempting re-download from HSD",
            attachment_name,
        )
        if _redownload_missing_parts(entry, workspace):
            LOGGER.info("Re-download succeeded — updating manifest")
            manifest[attachment_name] = entry
            write_archive_manifest(manifest, workspace)
        else:
            LOGGER.warning("Re-download failed or incomplete for '%s'", attachment_name)

    extraction = extract_archive_on_demand_with_status(attachment_name, workspace)

    attach_id = entry.get('id', '')
    new_files = extraction.get('new_files', [])
    etl_files_indexed = [item['file_path'] for item in extraction.get('new_etl_entries', [])]

    # Build note based on what actually happened.
    if not extraction.get('success'):
        note = extraction.get('message') or 'Archive extraction failed.'
    elif new_files and etl_files_indexed:
        note = (
            f'Extracted {len(new_files)} log/csv/trace file(s) to persistent_logs/ '
            f'and indexed {len(etl_files_indexed)} ETL file(s) into all_etl_files.json. '
            'All analysis tools can now find them in the workspace.'
        )
    elif new_files:
        note = (
            'Files copied to persistent_logs/ and registered in '
            'all_log_txt_trace_csv_files.json. Analysis tools can now '
            'find them in the workspace.'
        )
    elif etl_files_indexed:
        note = (
            f'Archive contains ETL file(s) only — {len(etl_files_indexed)} ETL file(s) '
            'indexed into all_etl_files.json. Use sighting_native_etl_analyzer to '
            'analyze them (pass the attachment name or ETL filename as etl_target).'
        )
    else:
        if extraction.get('extraction_status') == 'already_extracted':
            note = (
                'Archive content already existed in the workspace and was re-scanned. '
                'No new index entries were needed.'
            )
        else:
            note = (
                'Extraction returned no new files. This may mean the archive '
                'contains no .log/.txt/.trace/.csv/.etl members, or extraction '
                'failed. Check that 7-Zip is installed if the archive uses '
                'a compression format py7zr cannot handle.'
            )

    LOGGER.info(
        "Extraction summary for '%s': success=%s status=%s copied=%s etl=%s",
        attachment_name,
        extraction.get('success'),
        extraction.get('extraction_status'),
        len(new_files),
        len(etl_files_indexed),
    )

    result = {
        'success': bool(extraction.get('success')),
        'attachment_name': attachment_name,
        'archive_id': attach_id,
        'archive_path': extraction.get('archive_path', ''),
        'members_peeked': len(members_peeked),
        'extraction_status': extraction.get('extraction_status'),
        'extract_dir': extraction.get('extract_dir'),
        'extract_dir_summary': extraction.get('extract_dir_summary', {}),
        'files_extracted': len(new_files),
        'etl_files_indexed': len(etl_files_indexed),
        'extracted_paths': [path for path, _ in new_files],
        'etl_paths': etl_files_indexed,
        'error': extraction.get('error', ''),
        'note': note,
    }

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
