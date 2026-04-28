"""archive_utils.py — Peek and on-demand extraction utilities for HSD attachment archives.

Public API
----------
peek_archive_members(abs_path, archive_format)
    List archive contents as basenames without extracting.

write_archive_manifest(manifest, workspace)
    Persist the manifest dict to archive_manifest.json in workspace.

read_archive_manifest(workspace)
    Load archive_manifest.json; returns {} if absent or unreadable.

get_extract_dir(attach_id, workspace, hsd_id='')
    Return the extraction target directory for a given attachment.

extract_archive_on_demand_with_status(attachment_name, workspace)
    Extract a single named archive, copy .log/.txt/.trace/.csv members to
    persistent_logs/, update all_log_txt_trace_csv_files.json, index any ETLs,
    and return a detailed status dict describing what happened.

extract_archive_on_demand(attachment_name, workspace)
    Compatibility wrapper returning only newly copied persistent files.
"""

import os
import json
import shutil
import logging
from collections import Counter

from utils.log_utils import get_sat_output_dir

ARCHIVE_MANIFEST_FILENAME = 'archive_manifest.json'
LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extract directory resolution
# ---------------------------------------------------------------------------

def get_extract_dir(attach_id, workspace, hsd_id=''):
    """Return the extraction target directory for a given attachment.

    Prefers SAT_<hsd_id>_Output/ (on the toolkit drive) over
    GNAI_TEMP_WORKSPACE (on C: %TEMP%) to avoid "No space left on device"
    errors for large archives (GPUView ETLs can be 500 MB–2 GB extracted).

    Parameters
    ----------
    attach_id : str
        HSD attachment ID (used in the directory name ``extracted_<id>``).
    workspace : str
        Fallback path — typically GNAI_TEMP_WORKSPACE.
    hsd_id : str, optional
        HSD article ID.  When non-empty the extract dir is placed under
        ``SAT_<hsd_id>_Output/`` instead of *workspace*.

    Returns
    -------
    str
        Absolute path to the extraction directory.
    """
    hsd_id = (hsd_id or '').strip()
    if hsd_id:
        return os.path.join(get_sat_output_dir(hsd_id), f"extracted_{attach_id}")
    return os.path.join(workspace, f"extracted_{attach_id}")


# ---------------------------------------------------------------------------
# Peek (no extraction)
# ---------------------------------------------------------------------------

def peek_archive_members(abs_path, archive_format):
    """Return a sorted list of unique member basenames without extracting.

    Parameters
    ----------
    abs_path : str
        Absolute path to the archive file.
    archive_format : str
        '7z' or 'zip'.

    Returns
    -------
    list[str]
        Sorted list of unique basenames found inside the archive.
        Empty list on any error.
    """
    import subprocess
    raw_names = []
    try:
        if archive_format == '7z':
            import py7zr
            with py7zr.SevenZipFile(abs_path, 'r') as archive:
                raw_names = archive.getnames()
        elif archive_format == 'zip':
            import zipfile
            with zipfile.ZipFile(abs_path, 'r') as archive:
                # Exclude directory entries
                raw_names = [n for n in archive.namelist() if not n.endswith('/')]
    except Exception as e:
        logging.debug(f"[archive_utils] peek via py7zr/zipfile failed for {abs_path}: {e}")

    # Fallback: 7z CLI listing.  Needed for split-archive first parts (.7z.001)
    # where py7zr may not recognise the non-.7z extension as a multi-volume archive.
    if not raw_names and archive_format == '7z':
        for seven_zip_exe in [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
            "7z",
        ]:
            try:
                result = subprocess.run(
                    [seven_zip_exe, "l", "-slt", abs_path],
                    capture_output=True,
                    timeout=60,
                    text=True,
                    errors="replace",
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("Path = "):
                            raw_names.append(line[7:])
                    logging.debug(
                        f"[archive_utils] peek via 7z CLI found {len(raw_names)} member(s) in {abs_path}"
                    )
                    break
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue

    # Return basenames; deduplicate while preserving order
    seen = set()
    basenames = []
    for name in raw_names:
        base = os.path.basename(name)
        if base and base not in seen:
            seen.add(base)
            basenames.append(base)
    return sorted(basenames)


# ---------------------------------------------------------------------------
# Manifest read/write
# ---------------------------------------------------------------------------

def write_archive_manifest(manifest, workspace):
    """Write the archive manifest dict to archive_manifest.json in workspace.

    The manifest serves two purposes:

    1. Phase 2 assistant inventory menu (via build_attachment_structure):
       Member basenames from the peek pass are injected as pending sub_attachments
       into attachment_info_file so the LLM can classify archive contents and
       include them in the selection menu — even for generically-named archives
       whose filename matches no keyword rule (e.g. "HSD_18040537448_files.7z").

    2. On-demand extraction at runtime:
       Python tools (extract_attachment.py, displaydebugger_subprocess.py) read
       this file to resolve a bare archive filename to its abs_path, format, and
       HSD attachment id needed to perform the actual extraction.

    Parameters
    ----------
    manifest : dict
        Mapping of attachment_name → {id, abs_path, format, members}.
    workspace : str
        Path to GNAI_TEMP_WORKSPACE directory.
    """
    path = os.path.join(workspace, ARCHIVE_MANIFEST_FILENAME)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        logging.debug(
            f"[archive_utils] Wrote {ARCHIVE_MANIFEST_FILENAME} "
            f"({len(manifest)} archive(s)) to {path}"
        )
    except Exception as e:
        logging.debug(f"[archive_utils] write_archive_manifest failed: {e}")


def read_archive_manifest(workspace):
    """Read archive_manifest.json from workspace.

    Returns
    -------
    dict
        Manifest dict, or {} if file is absent or unreadable.
    """
    path = os.path.join(workspace, ARCHIVE_MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.debug(f"[archive_utils] read_archive_manifest failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# On-demand extraction
# ---------------------------------------------------------------------------

def _safe_persistent_name(attach_id, base_name, used_names):
    """Return a collision-safe name for persistent_logs/<attach_id>_<base_name>."""
    candidate = f"{attach_id}_{base_name}"
    if candidate not in used_names:
        return candidate
    stem, ext = os.path.splitext(candidate)
    counter = 2
    while candidate in used_names:
        candidate = f"{stem}_{counter}{ext}"
        counter += 1
    return candidate


def _scan_extract_dir(extract_dir):
    """Return a compact summary of files currently present in an extracted tree."""
    summary = {
        'total_files': 0,
        'counts_by_ext': {},
        'sample_files': [],
    }
    if not os.path.isdir(extract_dir):
        return summary

    counts = Counter()
    sample_files = []
    for root, _, files in os.walk(extract_dir):
        for fname in files:
            if fname == '_combined.7z':
                continue
            summary['total_files'] += 1
            ext = os.path.splitext(fname)[1].lower() or '<no_ext>'
            counts[ext] += 1
            if len(sample_files) < 10:
                sample_files.append(os.path.relpath(os.path.join(root, fname), extract_dir))

    summary['counts_by_ext'] = dict(sorted(counts.items()))
    summary['sample_files'] = sample_files
    return summary


def _has_real_content(extract_dir):
    """Return True when extracted directory contains files beyond temp concat artifacts."""
    if not os.path.isdir(extract_dir):
        return False
    for root, _, files in os.walk(extract_dir):
        for fname in files:
            if fname != '_combined.7z':
                return True
    return False


def _build_archive_path_candidates(entry, workspace, attachment_name):
    """Return ordered candidate paths for a manifest-backed archive file."""
    candidates = []
    seen = set()

    def add_candidate(path):
        if not path:
            return
        normalized = os.path.abspath(path)
        if normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    stored_path = entry.get('abs_path', '')
    add_candidate(stored_path)
    add_candidate(os.path.join(workspace, attachment_name))

    source_dir = entry.get('source_dir', '')
    if source_dir:
        add_candidate(os.path.join(source_dir, attachment_name))
        if entry.get('is_split'):
            split_parts = entry.get('split_parts', [])
            if split_parts:
                add_candidate(os.path.join(source_dir, split_parts[0].get('filename', '')))

    hsd_id = (entry.get('hsd_id') or '').strip()
    if hsd_id:
        raw_attachments_dir = os.path.join(get_sat_output_dir(hsd_id), 'raw_attachments')
        add_candidate(os.path.join(raw_attachments_dir, attachment_name))
        if entry.get('is_split'):
            split_parts = entry.get('split_parts', [])
            if split_parts:
                add_candidate(os.path.join(raw_attachments_dir, split_parts[0].get('filename', '')))

    for split_part in entry.get('split_parts', []):
        part_path = split_part.get('abs_path', '')
        add_candidate(part_path)
        part_name = split_part.get('filename', '')
        if part_name:
            add_candidate(os.path.join(workspace, part_name))
            if source_dir:
                add_candidate(os.path.join(source_dir, part_name))

    return candidates


def _resolve_archive_path(entry, workspace, attachment_name):
    """Resolve the actual on-disk path for an archive or first split part."""
    candidates = _build_archive_path_candidates(entry, workspace, attachment_name)
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate, candidates
    return '', candidates


def extract_archive_on_demand_with_status(attachment_name, workspace):
    """Extract a single archive on demand and register its files in the workspace index.

    Reads archive_manifest.json to locate the archive, extracts to
    extracted_<id>/, copies .log/.txt/.trace/.csv members to persistent_logs/,
    appends new entries to all_log_txt_trace_csv_files.json, and indexes ETLs
    in all_etl_files.json.

    Parameters
    ----------
    attachment_name : str
        The attachment filename as it appears in the manifest
        (e.g. "gop_files (2).7z").
    workspace : str
        Path to GNAI_TEMP_WORKSPACE directory.

    Returns
    -------
    dict
        Detailed extraction/indexing status suitable for tool logging and JSON
        output. Includes `new_files` for compatibility with callers that need
        the copied persistent file paths.
    """
    status = {
        'success': False,
        'attachment_name': attachment_name,
        'archive_id': '',
        'archive_format': '',
        'archive_path': '',
        'extract_dir': '',
        'extraction_status': 'not_started',
        'is_split': False,
        'split_parts_expected': 0,
        'split_parts_found': 0,
        'new_files': [],
        'new_etl_entries': [],
        'extract_dir_summary': {
            'total_files': 0,
            'counts_by_ext': {},
            'sample_files': [],
        },
        'message': '',
        'error': '',
    }

    manifest = read_archive_manifest(workspace)
    if attachment_name not in manifest:
        status['extraction_status'] = 'missing_manifest_entry'
        status['message'] = f"'{attachment_name}' not found in archive_manifest.json"
        LOGGER.warning("[archive_utils] %s", status['message'])
        return status

    entry = manifest[attachment_name]
    archive_format = entry['format']
    attach_id = entry['id']
    is_split = entry.get('is_split', False)

    hsd_id = (entry.get('hsd_id') or '').strip()
    extract_dir = get_extract_dir(attach_id, workspace, hsd_id)

    status['archive_id'] = str(attach_id)
    status['archive_format'] = archive_format
    status['extract_dir'] = extract_dir
    status['is_split'] = is_split
    status['split_parts_expected'] = len(entry.get('split_parts', []))

    abs_path, attempted_paths = _resolve_archive_path(entry, workspace, attachment_name)
    if not abs_path:
        status['archive_path'] = entry.get('abs_path', '')
        status['extraction_status'] = 'missing_archive'
        status['message'] = (
            f"Archive file is missing for '{attachment_name}'"
        )
        status['error'] = 'Attempted paths: ' + '; '.join(attempted_paths[:8])
        LOGGER.error("[archive_utils] %s", status['message'])
        LOGGER.error("[archive_utils] attempted_paths=%s", attempted_paths)
        return status

    status['archive_path'] = abs_path
    LOGGER.info(
        "[archive_utils] Starting extraction for '%s' (format=%s, split=%s, path=%s)",
        attachment_name,
        archive_format,
        is_split,
        abs_path,
    )

    if not (os.path.isdir(extract_dir) and _has_real_content(extract_dir)):
        extracted_ok = False
        last_error = None

        import subprocess
        os.makedirs(extract_dir, exist_ok=True)
        if archive_format == '7z':
            if is_split:
                # HSD splits large attachments into sequential byte parts (.7z.001/.002/...).
                # The most reliable way to reconstruct: concatenate all parts in order
                # into a single .7z file, then extract that — no multi-volume handling needed.
                split_parts = sorted(
                    entry.get('split_parts', []), key=lambda p: p.get('part_num', 0)
                )
                if split_parts:
                    status['split_parts_found'] = sum(
                        1 for part in split_parts
                        if os.path.isfile(part.get('abs_path', ''))
                        or os.path.isfile(os.path.join(os.path.dirname(abs_path), part.get('filename', '')))
                    )
                    combined_path = os.path.join(extract_dir, '_combined.7z')
                    try:
                        logging.info(
                            f"[archive_utils] Concatenating {len(split_parts)} split part(s) "
                            f"for '{attachment_name}' → {combined_path}"
                        )
                        with open(combined_path, 'wb') as out_f:
                            for part in split_parts:
                                part_path = part.get('abs_path', '')
                                if not os.path.isfile(part_path):
                                    # Fallback: look in same dir as the .001 file
                                    part_path = os.path.join(
                                        os.path.dirname(abs_path), part.get('filename', '')
                                    )
                                if not os.path.isfile(part_path):
                                    raise FileNotFoundError(
                                        f"Split part not found: {part.get('filename', '?')}"
                                    )
                                logging.info(
                                    f"[archive_utils]   + part {part.get('part_num')}: {part_path}"
                                )
                                with open(part_path, 'rb') as pf:
                                    shutil.copyfileobj(pf, out_f)
                        logging.info(
                            f"[archive_utils] Concatenation complete — "
                            f"{os.path.getsize(combined_path):,} bytes"
                        )
                    except Exception as concat_err:
                        last_error = concat_err
                        logging.error(
                            f"[archive_utils] Split part concatenation failed: {concat_err}"
                        )
                        combined_path = None

                    if combined_path and os.path.isfile(combined_path):
                        # Extract the combined archive
                        try:
                            import py7zr
                            with py7zr.SevenZipFile(combined_path, 'r') as archive:
                                archive.extractall(extract_dir)
                            extracted_ok = True
                            logging.info(
                                f"[archive_utils] Extracted combined archive via py7zr to {extract_dir}"
                            )
                        except Exception as py_err:
                            last_error = py_err
                            logging.info(
                                f"[archive_utils] py7zr failed on combined archive: {py_err} — trying 7z CLI"
                            )
                            for seven_zip_exe in [
                                r"C:\Program Files\7-Zip\7z.exe",
                                r"C:\Program Files (x86)\7-Zip\7z.exe",
                                "7z",
                            ]:
                                try:
                                    result = subprocess.run(
                                        [seven_zip_exe, "x", combined_path, f"-o{extract_dir}", "-y"],
                                        capture_output=True,
                                        timeout=600,
                                    )
                                    if result.returncode == 0:
                                        extracted_ok = True
                                        logging.info(
                                            f"[archive_utils] Extracted combined archive via 7z CLI to {extract_dir}"
                                        )
                                        break
                                    else:
                                        last_error = result.stderr.decode(errors="replace")
                                        logging.error(
                                            f"[archive_utils] 7z CLI extraction failed (rc={result.returncode}): {last_error}"
                                        )
                                except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as cli_err:
                                    logging.info(f"[archive_utils] 7z CLI not available at {seven_zip_exe}: {cli_err}")
                                    continue
                        finally:
                            # Remove the temp combined file regardless of outcome
                            try:
                                os.remove(combined_path)
                            except Exception:
                                pass
                else:
                    last_error = "split_parts list is empty in manifest — cannot reconstruct archive"
                    logging.error(f"[archive_utils] {last_error}")
            else:
                # Regular single .7z archive: try py7zr first, then 7z CLI
                try:
                    import py7zr
                    with py7zr.SevenZipFile(abs_path, 'r') as archive:
                        archive.extractall(extract_dir)
                    extracted_ok = True
                    logging.info(
                        f"[archive_utils] Extracted '{attachment_name}' via py7zr to {extract_dir}"
                    )
                except Exception as e:
                    last_error = e
                    logging.info(
                        f"[archive_utils] py7zr failed for '{attachment_name}': {e} — trying 7z CLI"
                    )
                    for seven_zip_exe in [
                        r"C:\Program Files\7-Zip\7z.exe",
                        r"C:\Program Files (x86)\7-Zip\7z.exe",
                        "7z",
                    ]:
                        try:
                            result = subprocess.run(
                                [seven_zip_exe, "x", abs_path, f"-o{extract_dir}", "-y"],
                                capture_output=True,
                                timeout=300,
                            )
                            if result.returncode == 0:
                                extracted_ok = True
                                logging.info(
                                    f"[archive_utils] Extracted '{attachment_name}' via 7z CLI to {extract_dir}"
                                )
                                break
                            else:
                                last_error = result.stderr.decode(errors="replace")
                                logging.error(
                                    f"[archive_utils] 7z CLI failed (rc={result.returncode}): {last_error}"
                                )
                        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as cli_err:
                            logging.info(f"[archive_utils] 7z CLI not available at {seven_zip_exe}: {cli_err}")
                            continue
        elif archive_format == 'zip':
            try:
                import zipfile
                with zipfile.ZipFile(abs_path, 'r') as archive:
                    archive.extractall(extract_dir)
                extracted_ok = True
                logging.debug(
                    f"[archive_utils] Extracted '{attachment_name}' via zipfile to {extract_dir}"
                )
            except Exception as e:
                last_error = e
                logging.debug(
                    f"[archive_utils] zip extraction failed for '{attachment_name}': {e}"
                )

        if not extracted_ok:
            # Clean up the empty directory so that next call retries properly.
            shutil.rmtree(extract_dir, ignore_errors=True)
            status['extraction_status'] = 'failed'
            status['message'] = f"All extraction methods failed for '{attachment_name}'"
            status['error'] = str(last_error)
            LOGGER.error(
                "[archive_utils] %s: %s",
                status['message'],
                status['error'],
            )
            return status
        status['extraction_status'] = 'extracted'
    else:
        status['extraction_status'] = 'already_extracted'
        LOGGER.info(
            "[archive_utils] Reusing existing extracted content for '%s' from %s",
            attachment_name,
            extract_dir,
        )

    status['extract_dir_summary'] = _scan_extract_dir(extract_dir)
    LOGGER.info(
        "[archive_utils] Extracted tree for '%s': total_files=%s counts_by_ext=%s",
        attachment_name,
        status['extract_dir_summary']['total_files'],
        status['extract_dir_summary']['counts_by_ext'],
    )

    # Load existing JSON index
    json_path = os.path.join(workspace, 'all_log_txt_trace_csv_files.json')
    existing = []
    existing_dest_names = set()
    if os.path.isfile(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            # Track destination basenames already registered to avoid re-copying.
            existing_dest_names = {
                os.path.basename(item['file_path']) for item in existing
            }
        except Exception:
            pass

    used_names = {os.path.basename(item['file_path']) for item in existing}

    persistent_log_dir = os.path.join(workspace, 'persistent_logs')
    os.makedirs(persistent_log_dir, exist_ok=True)

    attach_info = {'id': attach_id, 'document.file_name': attachment_name}
    accepted_exts = {'.log', '.txt', '.trace', '.csv'}
    new_entries = []

    for root, _, files in os.walk(extract_dir):
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in accepted_exts:
                continue
            src = os.path.join(root, fname)
            safe_name = _safe_persistent_name(attach_id, fname, used_names)
            # Skip if a file with this safe_name is already registered in the JSON index.
            if safe_name in existing_dest_names:
                continue
            dst = os.path.join(persistent_log_dir, safe_name)
            try:
                shutil.copy2(src, dst)
                used_names.add(safe_name)
                existing_dest_names.add(safe_name)
                new_entries.append({'file_path': dst, 'attach_info': attach_info})
            except Exception as e:
                logging.debug(f"[archive_utils] Failed to copy {fname}: {e}")

    if new_entries:
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(existing + new_entries, f, indent=2)
            logging.debug(
                f"[archive_utils] Added {len(new_entries)} file(s) from "
                f"'{attachment_name}' to {json_path}"
            )
        except Exception as e:
            logging.debug(f"[archive_utils] Failed to update {json_path}: {e}")
    else:
        LOGGER.info(
            "[archive_utils] No new .log/.txt/.trace/.csv files needed registration for '%s'",
            attachment_name,
        )

    # Also index extracted .etl files into all_etl_files.json so that
    # sighting_native_etl_analyzer can discover ETLs unpacked from archives.
    # ETL files are NOT copied to persistent_logs/ — they stay in extracted_<id>/.
    etl_json_path = os.path.join(workspace, 'all_etl_files.json')
    existing_etl = []
    existing_etl_paths = set()
    if os.path.isfile(etl_json_path):
        try:
            with open(etl_json_path, 'r', encoding='utf-8') as f:
                existing_etl = json.load(f)
            existing_etl_paths = {item.get('file_path', '') for item in existing_etl}
        except Exception:
            pass

    new_etl_entries = []
    for root, _, files in os.walk(extract_dir):
        for fname in files:
            if os.path.splitext(fname)[1].lower() != '.etl':
                continue
            fp = os.path.join(root, fname)
            if fp in existing_etl_paths:
                continue
            new_etl_entries.append({
                'file_path': fp,
                'attach_info': attach_info,
                'attachment_name': attachment_name,
                'file_name': fname,
            })

    if new_etl_entries:
        try:
            with open(etl_json_path, 'w', encoding='utf-8') as f:
                json.dump(existing_etl + new_etl_entries, f, indent=2)
            logging.debug(
                f"[archive_utils] Added {len(new_etl_entries)} ETL file(s) from "
                f"'{attachment_name}' to {etl_json_path}"
            )
        except Exception as e:
            logging.debug(f"[archive_utils] Failed to update {etl_json_path}: {e}")
    else:
        LOGGER.info(
            "[archive_utils] No new ETL entries needed registration for '%s'",
            attachment_name,
        )

    status['new_files'] = [(e['file_path'], e['attach_info']) for e in new_entries]
    status['new_etl_entries'] = new_etl_entries
    status['success'] = True

    if not status['message']:
        if new_entries or new_etl_entries:
            status['message'] = (
                f"Indexed {len(new_entries)} persistent file(s) and {len(new_etl_entries)} ETL file(s)"
            )
        elif status['extract_dir_summary']['total_files']:
            status['message'] = (
                'Archive content is present, but no additional index entries were needed '
                '(already indexed or no supported analyzable files found).'
            )
        else:
            status['message'] = 'Archive extraction completed but produced no files.'

    if (
        status['extract_dir_summary']['total_files']
        and not new_entries
        and not new_etl_entries
    ):
        LOGGER.warning(
            "[archive_utils] '%s' produced no new analyzable registrations. sample_files=%s",
            attachment_name,
            status['extract_dir_summary']['sample_files'],
        )

    LOGGER.info(
        "[archive_utils] Finished '%s' with status=%s new_files=%s new_etl=%s",
        attachment_name,
        status['extraction_status'],
        len(status['new_files']),
        len(status['new_etl_entries']),
    )
    return status


def extract_archive_on_demand(attachment_name, workspace):
    """Compatibility wrapper returning only new persistent file entries."""
    status = extract_archive_on_demand_with_status(attachment_name, workspace)
    if not status.get('success'):
        return []
    return status.get('new_files', [])
