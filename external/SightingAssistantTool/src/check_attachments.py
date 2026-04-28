import os
import sys
import shutil
import re
from hsdes import HSDESAPI
import py7zr
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import json
logging.basicConfig(level = logging.INFO, format = '%(asctime)s - %(levelname)s - %(message)s', stream = sys.stdout)
from utils.archive_utils import peek_archive_members, write_archive_manifest
from utils.log_utils import get_sat_output_dir

# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

attachment_info_file = "attachment_info_file"


def dedupe_attachments_by_filename(attachments):
    """Return one attachment record per unique filename, preserving first-seen order."""
    unique = []
    seen = set()
    duplicate_names = []
    for attach in attachments:
        file_name = attach['document.file_name']
        if file_name in seen:
            duplicate_names.append(file_name)
            continue
        seen.add(file_name)
        unique.append(attach)
    return unique, duplicate_names

def download_attachment(hsd, attach, workspace, download_dir=None):
    """Download a single attachment.

    Parameters
    ----------
    download_dir : str, optional
        Directory to place the downloaded file.  Defaults to ``workspace``.
    """
    target_dir = download_dir if download_dir else workspace
    combined_path = os.path.join(target_dir, attach['document.file_name'])
    abs_filename = os.path.abspath(combined_path)
    
    if os.path.isfile(abs_filename) and os.path.getsize(abs_filename) > 0:
        logging.info(f"Reusing existing attachment download: {attach['document.file_name']}")
        return abs_filename, attach, True

    # Remove stale zero-byte or partial files before retrying the download.
    if os.path.exists(abs_filename):
        try:
            os.remove(abs_filename)
        except OSError:
            pass
    
    last_error = None
    for attempt in range(1, 3):
        try:
            hsd.download_attachment(abs_filename, attach['id'])
            if os.path.isfile(abs_filename) and os.path.getsize(abs_filename) > 0:
                logging.info(
                    "Downloaded attachment '%s' to %s on attempt %s",
                    attach['document.file_name'],
                    abs_filename,
                    attempt,
                )
                return abs_filename, attach, False
            last_error = "download completed but file is missing or empty"
        except Exception as e:
            last_error = str(e)
        if os.path.exists(abs_filename):
            try:
                os.remove(abs_filename)
            except OSError:
                pass
        logging.warning(
            "Failed to download attachment '%s' on attempt %s: %s",
            attach['document.file_name'],
            attempt,
            last_error,
        )
    return None, attach, False


def extract_and_find_file_types(abs_filename, attach, workspace):
    """Extract archive and find ETL, .log, .txt, .trace, and .csv files"""
    if not os.path.exists(abs_filename):
        return [], [], [], [], []
    
    _, ext = os.path.splitext(abs_filename)
    attachment_extraction_path = os.path.join(workspace, f"extracted_{attach['id']}")
    etl_files = []
    dot_log_files = []
    dot_txt_files = []
    dot_trace_files = []
    dot_csv_files = []

    # Check for direct file attachments (not archives)
    if ext.lower() == ".etl":
        logging.debug(f"Direct ETL file detected: {abs_filename}")
        etl_files.append((abs_filename, attach))
        return etl_files, dot_log_files, dot_txt_files, dot_trace_files, dot_csv_files
    elif ext.lower() == ".log":
        logging.debug(f"Direct .log file detected: {abs_filename}")
        dot_log_files.append((abs_filename, attach))
        return etl_files, dot_log_files, dot_txt_files, dot_trace_files, dot_csv_files
    elif ext.lower() == ".txt":
        logging.debug(f"Direct .txt file detected: {abs_filename}")
        dot_txt_files.append((abs_filename, attach))
        return etl_files, dot_log_files, dot_txt_files, dot_trace_files, dot_csv_files
    elif ext.lower() == ".trace":
        logging.debug(f"Direct .trace file detected: {abs_filename}")
        dot_trace_files.append((abs_filename, attach))
        return etl_files, dot_log_files, dot_txt_files, dot_trace_files, dot_csv_files
    elif ext.lower() == ".csv":
        logging.debug(f"Direct .csv file detected: {abs_filename}")
        dot_csv_files.append((abs_filename, attach))
        return etl_files, dot_log_files, dot_txt_files, dot_trace_files, dot_csv_files

    # Extract archives
    extraction_needed = False
    if ext.lower() == ".7z":
        try:
            os.makedirs(attachment_extraction_path, exist_ok=True)
            with py7zr.SevenZipFile(abs_filename, 'r') as archive:
                archive.extractall(attachment_extraction_path)
            logging.debug(f"[SUCCESS]: 7z extraction completed at {attachment_extraction_path}")
            extraction_needed = True
        except Exception as e:
            logging.debug(f"[ERROR]: Failed to extract 7z file: {e}")
            return [], [], [], [], []
            
    elif ext.lower() == ".zip":
        try:
            os.makedirs(attachment_extraction_path, exist_ok=True)
            with zipfile.ZipFile(abs_filename, 'r') as zip_ref:
                zip_ref.extractall(attachment_extraction_path)
            logging.debug(f"[SUCCESS]: Zip extraction completed at {attachment_extraction_path}")
            extraction_needed = True
        except Exception as e:
            logging.debug(f"[ERROR]: Failed to extract zip file: {e}")
            return [], [], [], [], []
    else:
        logging.debug(f"Unsupported file extension: {ext}")
        return [], [], [], [], []
    
    # Search for all file types in extracted archives
    if extraction_needed:
        for root, dirs, files in os.walk(attachment_extraction_path):
            for file in files:
                file_path = os.path.join(root, file)
                if file.lower().endswith(".etl"):
                    etl_files.append((file_path, attach))
                elif file.lower().endswith(".log"):
                    dot_log_files.append((file_path, attach))
                elif file.lower().endswith(".txt"):
                    dot_txt_files.append((file_path, attach))
                elif file.lower().endswith(".trace"):
                    dot_trace_files.append((file_path, attach))
                elif file.lower().endswith(".csv"):
                    dot_csv_files.append((file_path, attach))

    return etl_files, dot_log_files, dot_txt_files, dot_trace_files, dot_csv_files


# HSD splits attachments >80 MB into sequential parts: <base>.7z.001, .002, ...
_SPLIT_PART_RE = re.compile(r'^(.+\.7z)\.(\d{3,})$', re.IGNORECASE)


def detect_split_groups(attachments):
    """Identify HSD split archive parts and group them by their combined base name.

    HSD enforces an 80 MB per-attachment limit.  When a submitted file exceeds this
    it is split into sequential parts: <base>.7z.001, <base>.7z.002, etc.

    Parameters
    ----------
    attachments : list[dict]
        Raw HSD attachment records from get_attachments_list.

    Returns
    -------
    split_groups : dict
        base_name -> [(part_num: int, attach: dict), ...] sorted ascending by part_num.
    split_part_filenames : set
        All individual part filenames — used to exclude them from other processing loops.
    """
    groups = {}
    for attach in attachments:
        m = _SPLIT_PART_RE.match(attach['document.file_name'])
        if m:
            base_name, part_num = m.group(1), int(m.group(2))
            groups.setdefault(base_name, []).append((part_num, attach))
    split_groups = {b: sorted(p, key=lambda x: x[0]) for b, p in groups.items()}
    split_part_filenames = {
        a['document.file_name']
        for parts in split_groups.values()
        for _, a in parts
    }
    return split_groups, split_part_filenames


def build_attachment_structure(attachments, all_etl_files, all_log_txt_trace_files, all_csv_files=None, archive_manifest=None):
    """Build attachment structure that leaves space for other log results to be merged later"""
    
    attachment_info = {}

    # Identify split archive part filenames from the manifest.
    # Individual parts are skipped here and replaced with a single combined entry below.
    split_part_filenames = set()
    if archive_manifest:
        for entry in archive_manifest.values():
            if entry.get('is_split'):
                for sp in entry.get('split_parts', []):
                    split_part_filenames.add(sp.get('filename', ''))

    # Initialize all attachments first
    for attach in attachments:
        attachment_name = attach['document.file_name']
        if attachment_name in split_part_filenames:
            continue  # represented as one combined entry — skip individual parts

        if attachment_name.lower().endswith(('.zip', '.7z')):
            attachment_info[attachment_name] = {
                "attachment_type": "archive",
                "archive_format": "zip" if attachment_name.lower().endswith('.zip') else "7z",
                "sub_attachments": {}
            }
        else:
            attachment_info[attachment_name] = {
                "attachment_type": "direct_file",
                "archive_format": None
            }
    
    # Add ETL files
    for etl_path, attach_info in all_etl_files:
        attachment_name = attach_info['document.file_name']
        file_name = os.path.basename(etl_path)
        
        # Native ETL analysis is now user-driven in the interactive loop.
        # Keep ETL entries discoverable with pending status until selected.
        etl_info = {
            "etl_type": "pending_analysis",
            "driver_info": {
                "found": False,
                "status": "pending_analysis"
            },
            "pipe_underrun": {
                "detected": False,
                "status": "pending_analysis"
            }
        }
        
        if attachment_info[attachment_name]['attachment_type'] == 'archive':
            attachment_info[attachment_name]['sub_attachments'][file_name] = {"etl_info": etl_info}
        else:
            attachment_info[attachment_name]['etl_info'] = etl_info
    
    # Add log/txt/trace files with placeholders for analysis
    for log_path, attach_info in all_log_txt_trace_files:
        attachment_name = attach_info['document.file_name']
        original_file_name = os.path.basename(log_path)
        
        # These paths come from persistent_logs where files are named
        # <attachment_id>_<original_filename>. Strip only that leading attachment ID.
        if '_' in original_file_name and original_file_name.startswith(str(attach_info['id'])):
            file_name = '_'.join(original_file_name.split('_')[1:])
        else:
            file_name = original_file_name
        
        # Create placeholder structure that analysis will fill
        if file_name.lower().endswith('.log'):
            log_info = {
                "log_type": "pending_analysis",
                "log_analysis_results": {
                    "status": "pending"
                }
            }
            
            if attachment_info[attachment_name]['attachment_type'] == 'archive':
                attachment_info[attachment_name]['sub_attachments'][file_name] = {"log_info": log_info}
            else:
                attachment_info[attachment_name]['log_info'] = log_info
                
        elif file_name.lower().endswith('.txt'):
            txt_info = {
                "txt_type": "pending_analysis",
                "txt_analysis_results": {
                    "status": "pending"
                }
            }
            
            if attachment_info[attachment_name]['attachment_type'] == 'archive':
                attachment_info[attachment_name]['sub_attachments'][file_name] = {"txt_info": txt_info}
            else:
                attachment_info[attachment_name]['txt_info'] = txt_info
                
        elif file_name.lower().endswith('.trace'):
            trace_info = {
                "trace_type": "pending_analysis",
                "trace_analysis_results": {
                    "status": "pending"
                }
            }
            
            if attachment_info[attachment_name]['attachment_type'] == 'archive':
                attachment_info[attachment_name]['sub_attachments'][file_name] = {"trace_info": trace_info}
            else:
                attachment_info[attachment_name]['trace_info'] = trace_info

    # Add CSV files (PTAT / GfxPnp logs) with placeholder for analysis
    for csv_path, attach_info in (all_csv_files or []):
        attachment_name = attach_info['document.file_name']
        original_file_name = os.path.basename(csv_path)

        # These paths come from persistent_logs where files are named
        # <attachment_id>_<original_filename>. Strip only that leading attachment ID.
        if '_' in original_file_name and original_file_name.startswith(str(attach_info['id'])):
            file_name = '_'.join(original_file_name.split('_')[1:])
        else:
            file_name = original_file_name

        if attachment_name not in attachment_info:
            continue

        csv_info = {
            "csv_type": "pending_analysis",
            "csv_analysis_results": {
                "status": "pending"
            }
        }

        if attachment_info[attachment_name]['attachment_type'] == 'archive':
            attachment_info[attachment_name]['sub_attachments'][file_name] = {"csv_info": csv_info}
        else:
            attachment_info[attachment_name]['csv_info'] = csv_info

    # Add a single virtual combined entry for each HSD split archive group.
    # Individual part entries were excluded from the init loop above.
    # The manifest stub injection below will populate sub_attachments automatically.
    if archive_manifest:
        for base_name, entry in archive_manifest.items():
            if not entry.get('is_split'):
                continue
            parts = entry.get('split_parts', [])
            part_suffixes = '+'.join(
                p['filename'].rsplit('.', 1)[-1] for p in parts if 'filename' in p
            )
            attachment_info[base_name] = {
                'attachment_type': 'split_archive',
                'archive_format': '7z',
                'is_split': True,
                'split_parts': [p['filename'] for p in parts if 'filename' in p],
                'split_note': (
                    f"HSD split archive — {len(parts)} parts ({part_suffixes}). "
                    "All parts will be combined automatically when selected for analysis."
                ),
                'sub_attachments': {},
            }

    # Populate sub_attachments for archive members recorded in the peek manifest.
    #
    # WHY this is needed for the Phase 2 assistant inventory menu:
    # The normal sub_attachments population loops above (ETL, log, txt, trace, csv)
    # only add entries for files that were *physically extracted* to persistent_logs/.
    # In the interactive flow, display/GOP archives are intentionally NOT pre-extracted —
    # they are only peeked in Phase 2a.  This means their sub_attachments would remain
    # empty {}, and the LLM would see no contents inside the archive during Phase 2.
    #
    # The manifest already holds the member basenames from the peek pass, so we inject
    # pending stubs here so the LLM can classify each member (e.g. "intelgop_boot.log"
    # → GOP log) and include it in the numbered selection menu shown to the user.
    # Without this injection, generically-named archives (e.g. "HSD_18040537448_files.7z")
    # whose name matches no keyword rule would appear as opaque blobs with no contents,
    # and their files would never reach the Phase 3 interactive loop.
    if archive_manifest:
        for attach_name, manifest_entry in archive_manifest.items():
            if attach_name not in attachment_info:
                continue
            for member_basename in manifest_entry.get('members', []):
                # Don't overwrite entries already populated by the direct-file loops above
                if member_basename in attachment_info[attach_name].get('sub_attachments', {}):
                    continue
                # Use "pending_extraction" (not "pending_analysis") to distinguish
                # these stubs from files that ARE on disk but not yet analyzed.
                # These members have never been extracted — the archive has only been
                # peeked.  Extraction happens on demand when the user selects the item.
                ext = os.path.splitext(member_basename)[1].lower()
                if ext == '.log':
                    sub_entry = {"log_info": {"log_type": "pending_extraction", "log_analysis_results": {"status": "pending_extraction"}}}
                elif ext == '.txt':
                    sub_entry = {"txt_info": {"txt_type": "pending_extraction", "txt_analysis_results": {"status": "pending_extraction"}}}
                elif ext == '.trace':
                    sub_entry = {"trace_info": {"trace_type": "pending_extraction", "trace_analysis_results": {"status": "pending_extraction"}}}
                elif ext == '.etl':
                    sub_entry = {"etl_info": {"etl_type": "pending_extraction", "driver_info": {"found": False}, "pipe_underrun": {"detected": False}}}
                elif ext == '.csv':
                    sub_entry = {"csv_info": {"csv_type": "pending_extraction", "csv_analysis_results": {"status": "pending_extraction"}}}
                else:
                    continue
                attachment_info[attach_name].setdefault('sub_attachments', {})[member_basename] = sub_entry

    return attachment_info




if __name__ == "__main__":
    hsd = HSDESAPI()
    attachments = hsd.get_attachments_list(int(os.environ['GNAI_INPUT_ID']))
    unique_attachments, duplicate_attachment_names = dedupe_attachments_by_filename(attachments)
    workspace = os.environ['GNAI_TEMP_WORKSPACE']
    hsd_id = str(os.environ.get('GNAI_INPUT_ID', '')).strip()

    # Create the persistent output directory first so raw attachments are
    # downloaded directly there — no intermediate copy to GNAI_TEMP_WORKSPACE.
    # Extraction working dirs (extracted_<id>/, persistent_logs/) still live
    # in workspace because they are transient per-session working state.
    sat_output_dir = get_sat_output_dir(hsd_id)
    raw_attachments_dir = os.path.join(sat_output_dir, 'raw_attachments')
    os.makedirs(raw_attachments_dir, exist_ok=True)

    print("=" * 30)
    print("= Attachment list ")
    print("=" * 30)
    
    for i, attach in enumerate(unique_attachments):
        print(f"Attachment no.{i+1} : {attach['document.file_name']}")

    if duplicate_attachment_names:
        duplicate_summary = ', '.join(sorted(set(duplicate_attachment_names)))
        print(f"[INFO] Collapsed duplicate attachment rows by filename: {duplicate_summary}")

    logging.debug("\n" + "=" * 50)
    logging.debug("PHASE 1: DOWNLOADING ALL ATTACHMENTS")
    logging.debug("=" * 50)

    # Phase 1: Download all attachments directly into raw_attachments/.
    # No copy step needed — the file lives permanently in the output dir.
    downloaded_attachments = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        download_futures = {
            executor.submit(download_attachment, hsd, attach, workspace, raw_attachments_dir): attach
            for attach in unique_attachments
        }
        for future in as_completed(download_futures):
            result = future.result()
            attach = download_futures[future]
            if result[0] is not None:
                downloaded_attachments.append(result)
    
    logging.debug(f"\nDownloaded/Found {len(downloaded_attachments)} attachments")

    # Prevent HSDESAPI destructor from deleting persistent downloads.
    # HSDESAPI.__del__ auto-removes every path in self.attachments, but these
    # files live in raw_attachments/ and must survive for on-demand extraction
    # later in the session (sighting_extract_attachment).
    hsd.attachments.clear()

    # Detect HSD split archive parts (e.g. file.7z.001, .002, .003).
    # HSD enforces an 80 MB per-attachment limit and splits larger files sequentially.
    split_groups, split_part_filenames = detect_split_groups(unique_attachments)
    if split_groups:
        print("\n[INFO] Split archive(s) detected (HSD 80 MB attachment limit):")
        for base_name, parts in split_groups.items():
            part_labels = '+'.join(
                p_attach['document.file_name'].rsplit('.', 1)[-1]
                for _, p_attach in parts
            )
            print(f"  {base_name}  ({len(parts)} parts: {part_labels})")
        print("  Parts will be combined automatically when selected for analysis.\n")
    
    # Phase 2a: Peek all archives to build the interactive menu manifest.
    # This is a separate pass so the archive file handles are fully closed
    # before the extraction pass below opens them again.
    logging.debug("PHASE 2a: PEEKING ARCHIVES FOR MANIFEST")

    archive_manifest = {}  # attachment_name -> {id, abs_path, format, members}
    peek_items = [
        (abs_filename, attach)
        for abs_filename, attach, was_skipped in downloaded_attachments
        if os.path.splitext(abs_filename)[1].lower() in ('.7z', '.zip')
    ]
    with ThreadPoolExecutor(max_workers=4) as executor:
        peek_futures = {
            executor.submit(
                peek_archive_members,
                abs_filename,
                '7z' if os.path.splitext(abs_filename)[1].lower() == '.7z' else 'zip',
            ): (abs_filename, attach)
            for abs_filename, attach in peek_items
        }
        for future in as_completed(peek_futures):
            abs_filename, attach = peek_futures[future]
            fmt = '7z' if os.path.splitext(abs_filename)[1].lower() == '.7z' else 'zip'
            members = future.result()
            archive_manifest[attach['document.file_name']] = {
                'id': str(attach['id']),
                'abs_path': abs_filename,
                'source_dir': raw_attachments_dir,
                'hsd_id': hsd_id,
                'format': fmt,
                'members': members,
            }
            logging.debug(
                f"Peeked {attach['document.file_name']}: {len(members)} member(s)"
            )

    # Add split archive groups to the manifest.
    # Split parts (.7z.001 etc.) do not match the ext check above so need a separate
    # pass.  We open the .001 part with py7zr which handles multi-volume archives
    # automatically when all sibling parts are in the same directory (workspace).
    if split_groups:
        dl_path_map = {
            a['document.file_name']: abs_f
            for abs_f, a, _ in downloaded_attachments
            if abs_f
        }
        for base_name, parts in split_groups.items():
            first_filename = parts[0][1]['document.file_name']
            first_abs = dl_path_map.get(first_filename)
            if not first_abs:
                logging.warning(f"[split] .001 part not downloaded for {base_name} — skipping")
                continue
            members = peek_archive_members(first_abs, '7z')
            split_parts_list = [
                {
                    'part_num': pnum,
                    'abs_path': dl_path_map.get(p_attach['document.file_name'], ''),
                    'attach_id': str(p_attach['id']),
                    'filename': p_attach['document.file_name'],
                }
                for pnum, p_attach in parts
            ]
            archive_manifest[base_name] = {
                'id': str(parts[0][1]['id']),
                'abs_path': first_abs,
                'source_dir': raw_attachments_dir,
                'hsd_id': hsd_id,
                'format': '7z',
                'members': members,
                'is_split': True,
                'split_parts': split_parts_list,
            }
            logging.debug(
                f"Split archive '{base_name}': {len(parts)} part(s), {len(members)} member(s)"
            )

    # Phase 2b: Catalogue DIRECT (non-archive) attachments only.
    # Archives (.zip / .7z) are intentionally skipped here — they were already
    # downloaded in Phase 1 and peeked in Phase 2a.  Their members are injected
    # as pending_extraction stubs via build_attachment_structure + archive_manifest
    # so the LLM can show them in the selection menu.  Actual extraction happens
    # on demand when the user selects an item (sighting_extract_attachment tool).
    logging.debug("PHASE 2b: CATALOGUING DIRECT (NON-ARCHIVE) FILES")

    all_etl_files = []
    all_log_files = []
    all_txt_files = []
    all_trace_files = []
    all_csv_files = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        extract_futures = {
            executor.submit(extract_and_find_file_types, abs_filename, attach, workspace): attach
            for abs_filename, attach, was_skipped in downloaded_attachments
            if os.path.splitext(abs_filename)[1].lower() not in ('.7z', '.zip')
            and attach['document.file_name'] not in split_part_filenames
        }
        for future in as_completed(extract_futures):
            attach = extract_futures[future]
            etl_f, log_f, txt_f, trace_f, csv_f = future.result()
            all_etl_files.extend(etl_f)
            all_log_files.extend(log_f)
            all_txt_files.extend(txt_f)
            all_trace_files.extend(trace_f)
            all_csv_files.extend(csv_f)
            if etl_f or log_f or txt_f or trace_f or csv_f:
                logging.debug(
                    f"Found {len(etl_f)} ETL, {len(log_f)} .log, {len(txt_f)} .txt, "
                    f"{len(trace_f)} .trace, {len(csv_f)} .csv in {attach['document.file_name']}"
                )

    logging.debug(
        f"\nTotal direct files: {len(all_etl_files)} ETL, {len(all_log_files)} .log, "
        f"{len(all_txt_files)} .txt, {len(all_trace_files)} .trace, "
        f"{len(all_csv_files)} .csv  |  Archives pending on-demand extraction: {len(archive_manifest)}"
    )
    
    # Phase 4: Copy all extracted files (log/txt/trace/csv) to persistent_logs/ and save combined index
    all_log_txt_trace_files = all_log_files + all_txt_files + all_trace_files

    persistent_log_dir = os.path.join(workspace, 'persistent_logs')
    os.makedirs(persistent_log_dir, exist_ok=True)

    # Step 1: Compute destination names sequentially (fast, handles collisions).
    copy_plan = []  # [(source_path, persistent_path, attach_info), ...]
    used_persistent_names = set()
    for file_path, attach_info in all_log_txt_trace_files + all_csv_files:
        if not os.path.exists(file_path):
            continue
        base_name = os.path.basename(file_path)
        safe_name = f"{attach_info['id']}_{base_name}"

        extracted_prefix = os.path.join(workspace, f"extracted_{attach_info['id']}")
        try:
            common_root = os.path.commonpath([os.path.abspath(file_path), os.path.abspath(extracted_prefix)])
        except ValueError:
            common_root = ""

        if common_root == os.path.abspath(extracted_prefix):
            rel_from_extracted = os.path.relpath(file_path, extracted_prefix)
            rel_dir = os.path.dirname(rel_from_extracted)
            if rel_dir and rel_dir != '.':
                rel_token = rel_dir.replace('\\', '__').replace('/', '__')
                rel_token = re.sub(r'[^A-Za-z0-9._-]+', '-', rel_token).strip('-_')
                if rel_token:
                    safe_name = f"{attach_info['id']}_{rel_token}_{base_name}"

        if safe_name in used_persistent_names:
            stem, ext = os.path.splitext(safe_name)
            counter = 2
            while safe_name in used_persistent_names:
                safe_name = f"{stem}_{counter}{ext}"
                counter += 1

        persistent_path = os.path.join(persistent_log_dir, safe_name)
        used_persistent_names.add(safe_name)
        copy_plan.append((file_path, persistent_path, attach_info))

    # Step 2: Copy files in parallel (I/O-bound).
    def _copy_one(item):
        src, dst, ai = item
        try:
            shutil.copy2(src, dst)
            return dst, ai, None
        except Exception as e:
            return src, ai, e

    all_log_txt_trace_csv_persistent = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        for dst_or_src, ai, err in executor.map(_copy_one, copy_plan):
            if err is None:
                all_log_txt_trace_csv_persistent.append((dst_or_src, ai))
            else:
                logging.warning(
                    "Failed to copy file to persistent_logs: %s", err,
                )
                all_log_txt_trace_csv_persistent.append((dst_or_src, ai))

    # Save combined index — log_file_analyzer.py reads this via log_utils
    json_path = os.path.join(workspace, 'all_log_txt_trace_csv_files.json')
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(
                [{'file_path': fp, 'attach_info': ai} for fp, ai in all_log_txt_trace_csv_persistent],
                f, indent=2
            )
    except Exception as e:
        logging.error(f"Failed to save {json_path}: {e}")

    # Save ETL index for interactive native ETL analysis tool.
    etl_json_path = os.path.join(workspace, 'all_etl_files.json')
    try:
        with open(etl_json_path, 'w', encoding='utf-8') as f:
            json.dump(
                [
                    {
                        'file_path': fp,
                        'attach_info': ai,
                        'attachment_name': ai.get('document.file_name', ''),
                        'file_name': os.path.basename(fp),
                    }
                    for fp, ai in all_etl_files
                ],
                f,
                indent=2,
            )
    except Exception as e:
        logging.error(f"Failed to save {etl_json_path}: {e}")

    # Split for downstream consumers
    all_log_txt_trace_files_persistent = [
        (p, a) for p, a in all_log_txt_trace_csv_persistent if not p.lower().endswith('.csv')
    ]
    all_csv_files_persistent = [
        (p, a) for p, a in all_log_txt_trace_csv_persistent if p.lower().endswith('.csv')
    ]

    # Write archive manifest so analysis tools can extract on demand
    write_archive_manifest(archive_manifest, workspace)

    logging.debug("PHASE 4: CALLING log_file_analyzer FOR .LOG, .TXT, AND .TRACE FILES")

    # Print out attachment and their info
    print(f"\nAttachment Analysis:")
    print("-" * 80)
        

    print(f"\n1. ETL Analysis:")
    print("-" * 80)
    print("Native ETL analysis deferred to interactive selection.")
    print("Use sighting_native_etl_analyzer on selected ETL items.")
    print("-" * 80)

    logging.debug("PROCESSING COMPLETE")

    print("\nPipe Underrun Analysis: Pending interactive ETL analysis")
    print("\nGraphics Driver Information: Pending interactive ETL analysis")


    # Build new attachment structure
    attachment_info_structure = build_attachment_structure(
        unique_attachments, all_etl_files, all_log_txt_trace_files_persistent,
        all_csv_files=all_csv_files_persistent,
        archive_manifest=archive_manifest
    )


    # Combined output with new structure
    combined_output = {
        "attachment_info": attachment_info_structure,
        "summary": {
            "total_attachments": len(unique_attachments),
            "duplicate_attachment_rows_collapsed": len(duplicate_attachment_names),
            "file_type_counts": {
                "etl_files": len(all_etl_files),
                "log_files": len(all_log_files),
                "txt_files": len(all_txt_files),
                "trace_files": len(all_trace_files),
                "csv_files": len(all_csv_files_persistent),
                "archives_pending_extraction": len(archive_manifest)
            }
        }
    }

    output = json.dumps(combined_output, indent=2)

    file_output = os.path.join(os.environ['GNAI_TEMP_WORKSPACE'], f'{attachment_info_file}')

    try:
        with open(file_output, 'w', encoding='utf-8') as f:
            f.write(output)
            attachment_info_file = file_output
        print(f"Attachment info written to: {file_output}")
    except FileNotFoundError:
        print(f'[ERROR] Directory path does not exist: {os.path.dirname(file_output)}')
    except PermissionError:
        print(f'[ERROR] Permission denied when writing to file: {file_output}')
    except OSError as e:
        print(f'[ERROR] OS error occurred while writing file {file_output}: {e}')
    except UnicodeEncodeError as e:
        print(f'[ERROR] Unicode encoding error while writing to {file_output}: {e}')
    except Exception as e:
        print(f'[ERROR] Unexpected error occurred while writing to {file_output}: {e}')
