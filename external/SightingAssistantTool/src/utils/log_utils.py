"""
1.Base classes for log processors

This module provides the abstract base class for all log processors.
Designed to be extensible for different log types (GOP, system logs, performance logs, etc.).

2.Utility functions for merging log analysis results

This module provides utilities to merge various types of log analysis results
into the attachment_info_file for state maintenance across different log processors.

Supported log types:
- GOP (Graphics Output Protocol) logs
- Burnin Test logs
- PTAT logs
- Future log types can be easily added
"""

from abc import ABC, abstractmethod
from typing import Dict, Tuple, List, Optional
import json
import tempfile
import os
import logging
import re

class LogProcessor(ABC):
    """Abstract base class for log processors."""
    
    @abstractmethod
    def detect_log_type(self, file_path: str) -> Tuple[bool, str]:
        """
        Detect if the file is of this log type.
        
        Args:
            file_path (str): Path to the log file (.txt, .log, or .trace)
            
        Returns:
            Tuple[bool, str]: (is_this_log_type, reason/detection_info)
        """
        pass
    
    @abstractmethod
    def process_log(self, file_path: str) -> Dict:
        """
        Process the log file and return results.
        
        Args:
            file_path (str): Path to the log file (.txt, .log, or .trace)
            
        Returns:
            Dict: Dictionary containing parsed results and analysis
        """
        pass

    def _handle_generic_processing_result(
        self,
        attach_name: str,
        data: Dict,
        attachment_results: Dict,
        analysis_results: List,
        result_key: str,
        log_display: str,
    ) -> None:
        """
        Generic handler for successful or failed processing results.

        This centralizes common logic used by different log processors and can be
        reused by other processors (e.g. GOP, Burnin) by passing the appropriate
        result_key and log_display values.
        """
        import os
        if data and result_key in data and 'error' not in data:
            analysis_results.append(data)
            file_name = os.path.basename(data.get('file_path', 'Unknown'))
            if result_key == 'pattern_matches':
                # GOP-specific message
                attachment_results[attach_name].append(
                    f"{file_name} : {log_display} processed successfully"
                )
            else:
                # Generic message with event count
                event_count = len(data.get(result_key, {}).get('events', []))
                attachment_results[attach_name].append(
                    f"{file_name} : {log_display} processed successfully ({event_count} events)"
                )
        elif data and 'error' in data:
            error_msg = data.get('error', 'Unknown error')
            file_name = os.path.basename(data.get('file_path', 'Unknown'))
            attachment_results[attach_name].append(
                f"{file_name} : {log_display} Processing Failed - {error_msg}"
            )

    def _handle_common_processing_error(
        self,
        log_prefix: str,
        file_path: str,
        attach_info: Dict,
        error: Exception,
        attachment_results: Dict,
    ) -> None:
        """
        Generic handler for processing exceptions.

        This centralizes exception handling so other processors can reuse it by
        providing their own log_prefix (e.g. "GOP", "BURNIN").
        """
        file_name = os.path.basename(file_path)
        attach_name = attach_info.get('document.file_name', 'Unknown')
        attachment_results[attach_name].append(
            f"{file_name} : Processing exception - {str(error)}"
        )
        logging.error(f"[{log_prefix}] Exception processing {file_name}: {str(error)}")


def build_hsd_prefixed_output_name(
    file_name_or_path: str,
    hsd_id: Optional[str] = None,
) -> str:
    """Return <hsd_id>_<normalized_filename> for user-facing output files.

    - Accepts either a filename or full path.
    - If input is prefixed like <attachment_id>_<name>, removes the numeric prefix.
    - Always preserves the source extension.
    - If HSD ID is not available (arg and env missing), returns the original basename.
    - HSD ID lookup order: explicit arg -> env (`GNAI_INPUT_HSD_ID`, `GNAI_INPUT_ID`).
    - PTAT/GfxPnp call this helper only after `check_attachments.py` copies files into
      `persistent_logs/` using `<attachment_id>_<original_filename>` naming.
    - Because of that guaranteed format, stripping the leading numeric prefix is
      intentional and safe for the current PTAT/GfxPnp pipeline.
    - If this helper is reused outside `persistent_logs/`, re-check whether leading
      numeric prefixes are meaningful parts of the real filename.

    Examples:
    - build_hsd_prefixed_output_name(
            "C:/temp/persistent_logs/16029447857_PTATMonitor.csv",
            hsd_id="18040537448",
        )
        -> "18040537448_PTATMonitor.csv"

    - build_hsd_prefixed_output_name(
            "16029476866_GTMetrics.csv",
            hsd_id="18040537448",
        )
        -> "18040537448_GTMetrics.csv"

    - build_hsd_prefixed_output_name("raw_metrics.csv", hsd_id="18040537448")
        -> "18040537448_raw_metrics.csv"

    - build_hsd_prefixed_output_name("raw_metrics.csv", hsd_id=None)  # no env HSD ID
        -> "raw_metrics.csv"
    """
    base_name = os.path.basename(file_name_or_path)
    name_only, extension = os.path.splitext(base_name)

    normalized_name = re.sub(r'^\d+_', '', name_only)

    resolved_hsd = (
        hsd_id
        or os.environ.get('GNAI_INPUT_HSD_ID')
        or os.environ.get('GNAI_INPUT_ID')
        or ''
    ).strip()
    if not resolved_hsd:
        return base_name

    safe_hsd_id = re.sub(r'[^0-9A-Za-z_-]+', '_', resolved_hsd)
    return f"{safe_hsd_id}_{normalized_name}{extension}"


def get_sat_output_dir(hsd_id: Optional[str] = None) -> str:
    """Return the root SAT output directory path: <toolkit_root>/SAT_{hsd_id}_Output.

    HSD ID lookup order: explicit arg -> GNAI_INPUT_HSD_ID -> GNAI_INPUT_ID -> 'unknown'.
    """
    resolved = (
        hsd_id
        or os.environ.get('GNAI_INPUT_HSD_ID')
        or os.environ.get('GNAI_INPUT_ID')
        or 'unknown'
    ).strip()
    safe = re.sub(r'[^0-9A-Za-z_-]+', '_', resolved)
    toolkit_root = (
        os.environ.get('GNAI_TOOLKIT_DIRECTORY')
        or os.getcwd()
    ).strip()
    return os.path.join(toolkit_root, f"SAT_{safe}_Output")


def load_all_log_txt_trace_files_from_temp():
    """Load log/txt/trace files from the combined JSON index created by check_attachments.py."""
    current_workspace = os.environ.get('GNAI_TEMP_WORKSPACE', '.')

    # Try combined index in multiple locations
    possible_paths = [
        os.path.join(current_workspace, 'all_log_txt_trace_csv_files.json'),
        'all_log_txt_trace_csv_files.json',
        os.path.join(tempfile.gettempdir(), 'all_log_txt_trace_csv_files.json'),
    ]

    for temp_file_path in possible_paths:
        if os.path.exists(temp_file_path):
            try:
                with open(temp_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                result = []
                for item in data:
                    file_path = item['file_path']
                    attach_info = item['attach_info']
                    if file_path.lower().endswith('.csv'):
                        continue  # CSV files handled by load_all_csv_files_from_temp
                    if os.path.exists(file_path):
                        result.append((file_path, attach_info))
                    else:
                        logging.debug(f"File not found: {file_path}")

                logging.debug(f"Loaded {len(result)} log/txt/trace files from JSON: {temp_file_path}")
                return result

            except Exception as e:
                logging.debug(f"Error loading from {temp_file_path}: {e}")
                continue

    logging.debug("No log/txt/trace file index found. Run check_attachments.py first.")
    return []


def load_all_csv_files_from_temp():
    """Return CSV files as (file_path, attach_info) tuples.

    Loads from the combined all_log_txt_trace_csv_files.json index written by
    check_attachments.py, filtering to .csv entries only.
    Falls back to scanning the workspace directories for .csv files.
    """
    workspace = os.environ.get('GNAI_TEMP_WORKSPACE', '.')
    csv_files = []

    # Primary: load from combined index, filtering to .csv entries
    json_path = os.path.join(workspace, 'all_log_txt_trace_csv_files.json')
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for item in data:
                file_path = item['file_path']
                if not file_path.lower().endswith('.csv'):
                    continue
                attach_info = item.get('attach_info', {'document.file_name': os.path.basename(file_path)})
                if os.path.exists(file_path):
                    csv_files.append((file_path, attach_info))
            if csv_files:
                logging.debug(f"Loaded {len(csv_files)} CSV files from {json_path}")
                return csv_files
        except Exception as e:
            logging.debug(f"Error loading {json_path}: {e}")

    # Fallback: scan workspace directories and SAT output dir
    logging.debug("Scanning workspace for CSV files (fallback scan)...")
    scan_dirs = [workspace] if os.path.isdir(workspace) else []
    sat_dir = get_sat_output_dir()
    if os.path.isdir(sat_dir) and sat_dir not in scan_dirs:
        scan_dirs.append(sat_dir)
    for scan_root in scan_dirs:
        for entry in os.scandir(scan_root):
            if entry.is_dir() and entry.name.startswith('extracted_'):
                for root, dirs, files in os.walk(entry.path):
                    for file in files:
                        if file.lower().endswith('.csv'):
                            file_path = os.path.join(root, file)
                            csv_files.append((file_path, {'document.file_name': file}))
    if os.path.isdir(workspace):
        # Also check workspace root for direct CSV attachments
        for entry in os.scandir(workspace):
            if entry.is_file() and entry.name.lower().endswith('.csv'):
                csv_files.append((entry.path, {'document.file_name': entry.name}))
        # Also check persistent_logs/ — Phase 4b copies CSVs there
        persistent_logs_dir = os.path.join(workspace, 'persistent_logs')
        if os.path.isdir(persistent_logs_dir):
            for entry in os.scandir(persistent_logs_dir):
                if entry.is_file() and entry.name.lower().endswith('.csv'):
                    csv_files.append((entry.path, {'document.file_name': entry.name}))

    # De-duplicate by absolute path to avoid repeated processing of the same file
    unique_csv_files = []
    seen_paths = set()
    for file_path, attach_info in csv_files:
        abs_path = os.path.abspath(file_path)
        if abs_path in seen_paths:
            continue
        seen_paths.add(abs_path)
        unique_csv_files.append((file_path, attach_info))

    logging.debug(f"Found {len(unique_csv_files)} unique CSV files via workspace scan")
    return unique_csv_files


def merge_log_results_to_attachment_info(
    log_type: str,
    log_results: List[Dict],
    workspace: Optional[str] = None,
    attachment_info_filename: str = 'attachment_info_file'
) -> bool:
    """
    Merge log analysis results into the attachment_info_file.
    
    Args:
        log_type (str): Type of log analysis ('gop', 'burnin', 'future_log_type', etc.)
        log_results (List[Dict]): List of log analysis results to merge
        workspace (str, optional): Workspace directory path. Defaults to GNAI_TEMP_WORKSPACE env var
        attachment_info_filename (str): Name of the attachment info file
        
    Returns:
        bool: True if merge was successful, False otherwise
    """
    
    if workspace is None:
        workspace = os.environ.get('GNAI_TEMP_WORKSPACE', '.')
    
    attachment_info_file_path = os.path.join(workspace, attachment_info_filename)
    
    if not os.path.exists(attachment_info_file_path):
        logging.error(f"attachment_info_file not found at {attachment_info_file_path}")
        return False
    
    try:
        # Read existing attachment_info_file
        with open(attachment_info_file_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        
        # Check the structure - it should have 'attachment_info' at root level
        if 'attachment_info' not in existing_data:
            logging.error("Invalid attachment_info_file structure - missing 'attachment_info' key")
            return False
        
        # Merge based on log type - pass the entire data structure
        success = _merge_by_log_type(existing_data, log_type, log_results)
        
        if success:
            # Write back the merged data
            with open(attachment_info_file_path, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2)
            
            logging.info(f"Successfully merged {len(log_results)} {log_type} analysis results into {attachment_info_file_path}")
            return True
        else:
            logging.error(f"Failed to merge {log_type} results - unsupported log type or merge error")
            return False
            
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse attachment_info_file JSON: {e}")
        return False
    except Exception as e:
        logging.error(f"Failed to merge {log_type} results into attachment_info_file: {e}")
        return False

def _merge_by_log_type(data: Dict, log_type: str, log_results: List[Dict]) -> bool:
    """
    Merge log results based on the log type.
    
    Args:
        data (Dict): The entire attachment_info_file data structure
        log_type (str): Type of log analysis
        log_results (List[Dict]): Log analysis results to merge
        
    Returns:
        bool: True if merge was successful, False otherwise
    """
    
    log_type = log_type.lower()
    
    if log_type == 'gop':
        return _merge_gop_results(data, log_results)
    elif log_type == 'burnin':
        return _merge_burnin_results(data, log_results)
    elif log_type == 'ptat':
        return _merge_ptat_results(data, log_results)
    elif log_type == 'gfxpnp':
        return _merge_gfxpnp_results(data, log_results)
    else:
        logging.warning(f"Unsupported log type: {log_type}")
        return False

def _merge_gop_results(data: Dict, gop_results: List[Dict]) -> bool:
    """Merge GOP analysis results into the attachment structure.
    
    Note: GOP logs are only found in .txt and .log files, never in .trace files.
    """
    try:
        if 'attachment_info' not in data:
            logging.error("No attachment_info found in data")
            return False
        
        attachment_info = data['attachment_info']
        
        for gop_result in gop_results:
            file_path = gop_result['file_path']
            
            # Extract original filename (remove ID prefix if present)
            file_name = os.path.basename(file_path)
            if '_' in file_name:
                parts = file_name.split('_', 1)
                if len(parts) > 1 and parts[0].isdigit():
                    file_name = parts[1]
            
            # Find the attachment and file in the structure
            merged = False
            for attachment_name, attachment_data in attachment_info.items():
                
                if attachment_data['attachment_type'] == 'archive':
                    sub_attachments = attachment_data.get('sub_attachments', {})
                    
                    if file_name in sub_attachments:
                        file_data = sub_attachments[file_name]
                        
                        # Update log_info with GOP results
                        if 'log_info' in file_data:
                            file_data['log_info'] = {
                                'log_type': 'gop_log',
                                'log_analysis_results': {
                                    'gop_version': gop_result['gop_version'],
                                    'pattern_matches': gop_result['pattern_matches']
                                }
                            }
                            merged = True
                            break
                        # Convert txt_info to log_info for GOP logs (GOP can be in .txt files)
                        elif 'txt_info' in file_data:
                            file_data['log_info'] = {
                                'log_type': 'gop_log',
                                'log_analysis_results': {
                                    'gop_version': gop_result['gop_version'],
                                    'pattern_matches': gop_result['pattern_matches']
                                }
                            }
                            del file_data['txt_info']
                            merged = True
                            break
                
                elif attachment_data['attachment_type'] == 'direct_file':
                    if attachment_name == file_name:
                        if 'log_info' in attachment_data:
                            attachment_data['log_info'] = {
                                'log_type': 'gop_log',
                                'log_analysis_results': {
                                    'gop_version': gop_result['gop_version'],
                                    'pattern_matches': gop_result['pattern_matches']
                                }
                            }
                            merged = True
                            break
                        elif 'txt_info' in attachment_data:
                            attachment_data['log_info'] = {
                                'log_type': 'gop_log',
                                'log_analysis_results': {
                                    'gop_version': gop_result['gop_version'],
                                    'pattern_matches': gop_result['pattern_matches']
                                }
                            }
                            del attachment_data['txt_info']
                            merged = True
                            break
            
            if not merged:
                logging.warning(f"Could not find location to merge GOP result for file: {file_name}")
        
        # Update file_type_counts in summary to include GOP files
        if 'summary' in data and 'file_type_counts' in data['summary']:
            data['summary']['file_type_counts']['gop_files'] = len(gop_results)
        
        return True
        
    except Exception as e:
        logging.error(f"Error merging GOP results: {e}")
        return False

def _merge_burnin_results(data: Dict, burnin_results: List[Dict]) -> bool:
    """Merge Burnin analysis results into the attachment structure.
    
    Note: Burnin logs are primarily found in .trace files, but can also be in .txt/.log files.
    """
    
    def _update_file_data_with_burnin_result(file_data: Dict, burnin_result: Dict):
        """Helper function to update file_data with burnin results, converting any info type to log_info."""
        # Update or convert to log_info with Burnin results
        for info_key in ['log_info', 'txt_info', 'trace_info']:
            if info_key in file_data:
                file_data['log_info'] = {
                    'log_type': 'burnin_test',
                    'log_analysis_results': burnin_result.get('burnin_result', {})
                }
                # Remove old info key if it was txt_info or trace_info
                if info_key != 'log_info':
                    del file_data[info_key]
                return True
        return False
    
    try:
        if 'attachment_info' not in data:
            logging.error("No attachment_info found in data")
            return False
        
        attachment_info = data['attachment_info']
        
        for burnin_result in burnin_results:
            file_path = burnin_result['file_path']
            
            # Extract original filename (remove ID prefix if present)
            file_name = os.path.basename(file_path)
            if '_' in file_name:
                parts = file_name.split('_', 1)
                if len(parts) > 1 and parts[0].isdigit():
                    file_name = parts[1]
            
            # Find the attachment and file in the structure
            merged = False
            for attachment_name, attachment_data in attachment_info.items():
                
                if attachment_data['attachment_type'] == 'archive':
                    sub_attachments = attachment_data.get('sub_attachments', {})
                    
                    if file_name in sub_attachments:
                        file_data = sub_attachments[file_name]
                        if _update_file_data_with_burnin_result(file_data, burnin_result):
                            merged = True
                            break
                
                elif attachment_data['attachment_type'] == 'direct_file':
                    if attachment_name == file_name:
                        if _update_file_data_with_burnin_result(attachment_data, burnin_result):
                            merged = True
                            break
            
            if not merged:
                logging.warning(f"Could not find location to merge Burnin result for file: {file_name}")
        
        # Update file_type_counts in summary to include Burnin files
        if 'summary' in data and 'file_type_counts' in data['summary']:
            data['summary']['file_type_counts']['burnin_files'] = len(burnin_results)
        
        return True
        
    except Exception as e:
        logging.error(f"Error merging Burnin results: {e}")
        return False


def _merge_ptat_results(data: Dict, ptat_results: List[Dict]) -> bool:
    """Merge PTAT CSV analysis results into the attachment structure."""
    try:
        if 'summary' in data and 'file_type_counts' in data['summary']:
            data['summary']['file_type_counts']['ptat_files'] = len(ptat_results)

        # Store PTAT results at the top level of the data structure so the LLM can access them
        data['ptat_analysis'] = []
        for result in ptat_results:
            if result.get('processed') and 'ptat_result' in result:
                data['ptat_analysis'].append({
                    'file': os.path.basename(result['file_path']),
                    'ptat_result': result['ptat_result'],
                })

        return True

    except Exception as e:
        logging.error(f"Error merging PTAT results: {e}")
        return False


def _merge_gfxpnp_results(data: Dict, gfxpnp_results: List[Dict]) -> bool:
    """Merge GfxPnp (GTMetrics) CSV analysis results into the attachment structure."""
    try:
        if 'summary' in data and 'file_type_counts' in data['summary']:
            data['summary']['file_type_counts']['gfxpnp_files'] = len(gfxpnp_results)

        data['gfxpnp_analysis'] = []
        for result in gfxpnp_results:
            if result.get('processed') and 'gfxpnp_result' in result:
                data['gfxpnp_analysis'].append({
                    'file': os.path.basename(result['file_path']),
                    'gfxpnp_result': result['gfxpnp_result'],
                })

        return True

    except Exception as e:
        logging.error(f"Error merging GfxPnp results: {e}")
        return False
