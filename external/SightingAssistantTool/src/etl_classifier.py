# /// script
# requires-python = ">=3.8"
# dependencies = [
#   # Add any external dependencies here if needed in the future, e.g.:
#   # "requests<3",
#   # "rich",
# ]
# ///
"""
EtlClassifier - ETL Type Detection Script

Description:
Parses ETL event traces using tracefmt.exe and determines the type of trace
(BootTrace, WPT, Display ETL, GPUview) 

Example Usage:
analyzer = ETLAnalyzer()
etl_type = analyzer.get_etl_type("your_trace.etl")
print(f"ETL Type: {etl_type}")
"""

import subprocess
import tempfile
import os
import logging
import hashlib
import time
import re
import json
from typing import Optional, List, Dict, Any


# --- Basic logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.disable(logging.CRITICAL)


def get_manifest_files(script_dir: str) -> List[str]:
    """
    Find all manifest files (.man) in the manifests folder.
    Returns list of manifest file paths.
    """
    manifests_dir = os.path.join(script_dir, "manifests")
    
    if not os.path.exists(manifests_dir):
        logging.warning(f"Manifests directory not found: {manifests_dir}")
        return []
    
    # Find all .man files in manifests directory and subdirectories
    manifest_files = []
    for root, dirs, files in os.walk(manifests_dir):
        for file in files:
            if file.lower().endswith('.man'):
                manifest_files.append(os.path.join(root, file))
    
    logging.info(f"Found {len(manifest_files)} manifest files in {manifests_dir}")
    for manifest in manifest_files:
        logging.debug(f"  - {os.path.relpath(manifest, script_dir)}")
    
    return manifest_files

def run_tracefmt(etl_file_path: str) -> Optional[str]:
    """
    Run tracefmt.exe with fixed output handling.
    """

    script_dir = os.path.dirname(os.path.abspath(__file__))
    tracefmt_path = os.path.join(script_dir,"bin","tracefmt.exe")
    
    if not os.path.exists(tracefmt_path):
        logging.error(f"tracefmt.exe not found at: {tracefmt_path}")
        logging.error("Please ensure tracefmt.exe is in the bin folder")
        return None   


    # Get manifest files
    manifest_files = get_manifest_files(script_dir)

    logging.info(f"Running tracefmt.exe on {etl_file_path} with {len(manifest_files)} manifest files.")

    # Create temp file with unique naming
    file_hash = hashlib.md5(etl_file_path.encode()).hexdigest()[:8]
    temp_name = f"tracefmt_{file_hash}_{int(time.time())}.txt"
    tmp_txt_path = os.path.join(tempfile.gettempdir(), temp_name)
    
    try:
        cmd = [
            tracefmt_path, 
            etl_file_path, 
            '-o', tmp_txt_path,
            '-nosummary'  
        ]
        
        # Add manifest files 
        for manifest_file in manifest_files:
            cmd.extend(['-man', manifest_file])

        logging.debug(f"Executing command: {' '.join(cmd)}")
        
        # Setup for Windows to hide console window
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
            startupinfo=startupinfo
        )

        # Debug output
        logging.debug(f"tracefmt return code: {process.returncode}")
        if process.stdout:
            logging.debug(f"tracefmt stdout: {process.stdout[:200]}")
        if process.stderr:
            logging.debug(f"tracefmt stderr: {process.stderr[:200]}")

        if os.path.exists(tmp_txt_path):
            file_size = os.path.getsize(tmp_txt_path)
            logging.debug(f"Output file size: {file_size} bytes")
            
            if file_size > 10:  
                logging.info(f"tracefmt completed successfully. Output: {tmp_txt_path} ({file_size} bytes)")
                
                # Debug: Show first few lines
                try:
                    with open(tmp_txt_path, 'r', encoding='utf-8', errors='ignore') as f:
                        first_line = f.readline().strip()
                        logging.debug(f"First line of output: {first_line[:100]}")
                except Exception:
                    pass
                
                return tmp_txt_path
            else:
                logging.warning(f"tracefmt produced very small output ({file_size} bytes)")
                return tmp_txt_path
        else:
            logging.warning("tracefmt did not create output file")
            
            temp_dir = tempfile.gettempdir()
            for file in os.listdir(temp_dir):
                if file.startswith('tracefmt_') and file.endswith('.txt'):
                    full_path = os.path.join(temp_dir, file)
                    if os.path.getctime(full_path) > time.time() - 60:  # Created in last minute
                        logging.info(f"Found alternative tracefmt output: {full_path}")
                        return full_path
        
        return None
            
    except subprocess.TimeoutExpired:
        logging.error("tracefmt timed out")
        return None
    except FileNotFoundError:
        logging.error("tracefmt.exe not found. Ensure it is in your system's PATH.")
        return None
    except Exception as e:
        logging.error(f"Error running tracefmt.exe: {e}")
        return None

def extract_driver_info(txt_path: str) -> Dict[str, Any]:
    """
    Extract Intel graphics driver information using regex patterns.
    """

# An example line which is used to collect the driver info is as follows :
# [14]0004.013C::12/14/2022-12:36:00.572 [Intel-Gfx-Driver-Display]{"Version":"9-8-2022,31.0.101.3425","BuildString":"iADLSD_w10_DS,Intel(R) UHD Graphics","BDF":[0,2,0,0],"meta":{"provider":"Intel-Gfx-Driver-Display","event":"181v1","time":"2022-12-14T12:36:00.572","cpu":14,"pid":4,"tid":316,"channel":"GfxDisplayAnalytic","task":"DriverBuild","keywords":"Diagnostics"}}

    driver_info = {
        'version': None,
        'build_string': None,
        'bdf': None,
        'found': False,
        'driver_build_type': None,
        'driver_version': None,
        'driver_build_date': None
    }
    
    # Regex patterns to extract specific fields
    version_pattern = r'\[Intel-Gfx-Driver-Display\].*?"Version":"([^"]+)"'
    build_pattern = r'\[Intel-Gfx-Driver-Display\].*?"BuildString":"([^"]+)"'
    
    def is_valid_version(version):
        """Check if version is valid"""
        if not version:
            return False
        if version in ["1", "0", "Unknown"]:
            return False
        return any(char in version for char in ['-', '.', ','])
    
    def parse_driver_info(version_str, build_str):
        """Parse driver build type, version, and build date"""
        if not version_str or not build_str:
            return None, None, None
        
        # Extract build date from version string (ex format: "date,version")
        build_date = None
        driver_version = None
        
        if ',' in version_str:
            parts = version_str.split(',', 1)
            build_date = parts[0].strip()
            version_part = parts[1].strip() if len(parts) > 1 else None
        else:
            version_part = version_str
        
        # Determine build type and driver version depending on 'R' or 'RI'
        build_type = None
        
        if ' RI ' in build_str or build_str.endswith(' RI'):
            # Release Internal build
            build_type = "Release Internal"
            
            # For Release Internal, parse version from build string

            # Look for patterns like "gfx-driver-ci-master-19454"
            import re
            version_match = re.search(r'gfx-driver-[^-]+-[^-]+-(\d+)', build_str)
            if version_match:
                driver_version = f"gfx-driver-ci-master-{version_match.group(1)}"
            else:
                # Fallback: look for any version-like pattern in build string
                version_match = re.search(r'(gfx-driver-[^\s,]+)', build_str)
                if version_match:
                    driver_version = version_match.group(1)
                else:
                    driver_version = version_part  
                    
        elif '(R)' in build_str:
            # Release build
            build_type = "Release"
            driver_version = version_part
        else:
            # Default case - treat as Release if we have version info
            build_type = "Release"
            driver_version = version_part
        
        return build_type, driver_version, build_date
    
    try:
        with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines_checked = 0
            
            for line in f:
                lines_checked += 1
                
                # Look for Version
                if not driver_info['version']:
                    version_match = re.search(version_pattern, line)
                    if version_match:
                        version = version_match.group(1)
                        if is_valid_version(version):
                            driver_info['version'] = version
                            driver_info['found'] = True
                            logging.debug(f"[DEBUG] Found valid Version: {version} at line {lines_checked}")
                        else:
                            logging.debug(f"[DEBUG] Skipping invalid Version: {version} at line {lines_checked}")
                
                # Look for BuildString
                if not driver_info['build_string']:
                    build_match = re.search(build_pattern, line)
                    if build_match:
                        driver_info['build_string'] = build_match.group(1)
                        logging.debug(f"[DEBUG] Found BuildString: {driver_info['build_string']}")
                
                # If found both, parse the driver info and we're done
                if driver_info['version'] and driver_info['build_string']:
                    build_type, driver_version, build_date = parse_driver_info(
                        driver_info['version'], 
                        driver_info['build_string']
                    )
                    
                    driver_info['driver_build_type'] = build_type
                    driver_info['driver_version'] = driver_version
                    driver_info['driver_build_date'] = build_date
                    
                    logging.debug(f"[DEBUG] Parsed - Build Type: {build_type}, Version: {driver_version}, Date: {build_date}")
                    return driver_info
    
    except Exception as e:
        logging.debug(f"[DEBUG] File reading error: {e}")
    
    return driver_info


def detect_pipe_underrun(txt_path: str) -> bool:
    """
    Detect if Pipe Underrun condition exists in the ETL trace.
    
    Returns:
        bool: True if pipe underrun pattern is found, False otherwise
    """
    # Pattern to detect pipe underrun - case insensitive
    underrun_pattern = r'DispPipeUnderRun'
    
    try:
        with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_number, line in enumerate(f, 1):
                # Search for underrun pattern (case insensitive)
                if re.search(underrun_pattern, line, re.IGNORECASE):
                    logging.info(f"[PIPE UNDERRUN] Pattern detected at line {line_number}")
                    return True
    
    except Exception as e:
        logging.debug(f"[DEBUG] Error detecting pipe underrun: {e}")
        return False
    
    logging.debug(f"[PIPE UNDERRUN] No pipe underrun patterns detected")
    return False



# --- Main ETL Analyzer ---
class ETLAnalyzer:
    """
    ETL analyzer with pattern-based classification.
    """

    def __init__(self):
        """Initialize the analyzer."""
        # cache 
        self._file_cache = {}
        self.etl_types = ["Boottrace", "WPT", "Display ETL", "GPUView"]
        
        logging.info("ETLAnalyzer initialized")

    def _get_file_signature(self, file_path: str) -> Optional[str]:
        """Generate a unique signature for a file based on its content and metadata."""
        try:
            stat = os.stat(file_path)
            file_size = stat.st_size
            modified_time = stat.st_mtime
            
            hasher = hashlib.sha256()
            hasher.update(f"{file_path}|{file_size}|{modified_time}".encode('utf-8'))
            
            # For files under 50MB, include content hash
            if file_size < 50 * 1024 * 1024:
                with open(file_path, 'rb') as f:
                    # First 64KB
                    chunk = f.read(64 * 1024)
                    hasher.update(chunk)
                    
                    # Last 64KB if file is large enough
                    if file_size > 128 * 1024:
                        f.seek(-64 * 1024, 2)
                        chunk = f.read(64 * 1024)
                        hasher.update(chunk)
            
            return hasher.hexdigest()
                
        except (OSError, IOError) as e:
            logging.warning(f"Could not generate file signature for {file_path}: {e}")
            return None

    def _get_cache_key(self, file_path: str) -> Optional[str]:
        """Generate a unique cache key."""
        file_signature = self._get_file_signature(file_path)
        if not file_signature:
            return None
        
        cache_key = file_signature
        return cache_key

    def _get_cached_result(self, file_path: str) -> Optional[dict]:
        """Get cached result if available and valid."""
        cache_key = self._get_cache_key(file_path)
        if not cache_key:
            return None
        
        cached_data = self._file_cache.get(cache_key)
        if cached_data:
            cached_signature = cached_data.get('file_signature')
            current_signature = self._get_file_signature(file_path)
            
            if cached_signature == current_signature:
                logging.debug(f"Using cached result for {os.path.basename(file_path)}")
                return cached_data.get('result')
            else:
                del self._file_cache[cache_key]
        
        return None

    def _cache_result(self, file_path: str, result: dict):
        """Cache the analysis result."""
        cache_key = self._get_cache_key(file_path)
        if not cache_key:
            return
        
        file_signature = self._get_file_signature(file_path)
        if file_signature:
            self._file_cache[cache_key] = {
                'file_signature': file_signature,
                'result': result,
                'timestamp': time.time()
            }
            logging.debug(f"Cached result for {os.path.basename(file_path)}")

    def validate_etl_file(self, etl_file_path: str) -> bool:
        """Validate if the ETL file exists and is accessible."""
        if not os.path.isfile(etl_file_path):
            logging.error(f"ETL file not found: {etl_file_path}")
            return False
        if not etl_file_path.lower().endswith(".etl"):
            logging.warning(f"File '{etl_file_path}' may not be an ETL file (extension mismatch).")
        return True

    # --- ETL ANALYSIS METHODS ---
    def analyze_etl(self, etl_file_path: str) -> dict:
        """
        ETL analysis - works with tracefmt output for classification.
        
        Classification Priority:
        1. Boot patterns -> BootTrace (early exit)
        2. Intel + Media -> WPT  
        3. Intel only -> Display ETL
        4. Media only -> GPUView
        5. None -> Unknown
        """
        if not self.validate_etl_file(etl_file_path):
            return {"error": "Invalid ETL file"}
        
        # Check cache first
        cached_result = self._get_cached_result(etl_file_path)
        if cached_result:
            return cached_result
        
        # Convert ETL to text using tracefmt
        txt_path = run_tracefmt(etl_file_path)
        if not txt_path:
            error_result = {"error": "tracefmt conversion failed"}
            return error_result
        
        try:
            # Pattern-based classification
            result = self._analyze_patterns(txt_path, etl_file_path)

            # Extract driver information
            driver_info = extract_driver_info(txt_path)
            result['driver_info'] = driver_info

            # Detect pipe underrun conditions
            pipe_underrun_detected = detect_pipe_underrun(txt_path)
            result['pipe_underrun_detected'] = pipe_underrun_detected

            return result
            
        except Exception as e:
            logging.error(f"Error in ETL analysis: {e}")
            error_result = {"error": str(e)}
            self._cache_result(etl_file_path, error_result)
            return error_result
        finally:
            # Cleanup temp file
            if txt_path and os.path.exists(txt_path):
                try:
                    os.remove(txt_path)
                except OSError:
                    pass


    def _analyze_patterns(self, txt_path: str, etl_file_path: str) -> dict:
        """
        Pattern analysis with exact requirements.
        
        Scenario 1: Find "DxgkDdiStartDevice" once -> early exit -> BootTrace
        Scenario 2: Complete scan, no_boot + intel + media -> WPT  
        Scenario 3: Complete scan, no_boot + intel only -> Display ETL
        Scenario 4: Complete scan, no_boot + media only -> GPUView
        """
        # Pattern counters
        pattern_counts = {
            'boot': 0,
            'intel_gfx': 0,
            'media': 0
        }
        
        # Provider patterns
        provider_patterns = {
            # Boot patterns - ONLY DxgkDdiStartDevice
            'boot_providers': [
                'DxgkDdiStartDevice',
                '4BEF168B-CA0E-4512-9D4F-63F1A5858719',  # DxgkDdiStartDevice GUID
            ],
            
            # Intel Graphics patterns  
            'intel_providers': [
                'Intel-Gfx-Driver', 'Intel-Gfx-Driver-Display',
                '6381F857-7661-4B04-9521-288319E75F12',  # Intel-Gfx-Driver GUID
                '6F556899-027A-45EC-A3F5-C58E7FB94FF5',  # Intel-Gfx-Driver-Display GUID
            ],
            
            # Media patterns
            'media_providers': [
                'Microsoft-Windows-MediaFoundation-Performance', 
                'Microsoft-Windows-MediaEngine',
                'Microsoft-Windows-Dwm-Core',
                'f404b94e-27e0-4384-bfe8-1d8d390b0aa3', # Microsoft-Windows-MediaFoundation-Performance GUID 
                '8f2048e0-f260-4f57-a8d1-932376291682', # Microsoft-Windows-MediaEngine GUID
                '9e9bba3c-2e38-40cb-99f4-9e8281425164', # Microsoft-Windows-Dwm-Core
            ]
        }
        
        buffer_size = 1024 * 1024  # 1MB chunks
        total_lines = 0
        chunks_processed = 0
        
        logging.info("Starting ETL analysis - checking for DxgkDdiStartDevice first...")
        
        with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
            while True:
                chunk = f.read(buffer_size)
                if not chunk:
                    break
                
                chunks_processed += 1
                chunk_lines = chunk.count('\n')
                total_lines += chunk_lines
                
                # SCENARIO 1: Check for DxgkDdiStartDevice - early exit if found
                boot_count = self._count_patterns(chunk, provider_patterns['boot_providers'])
                pattern_counts['boot'] += boot_count
                
                if pattern_counts['boot'] > 0:
                    # EARLY EXIT - found DxgkDdiStartDevice
                    result = {
                        "type": "Boottrace",
                        "confidence": "high", 
                        "reason": f"DxgkDdiStartDevice found ({pattern_counts['boot']} matches)",
                        "pattern_counts": pattern_counts,
                        "chunks_processed": chunks_processed,
                        "lines_processed": total_lines,
                        "early_exit": True,
                        "scenario": "Scenario 1 - Boot pattern detected"
                    }
                    self._cache_result(etl_file_path, result)
                    logging.info(f"Scenario 1: DxgkDdiStartDevice detected - early exit as Boottrace")
                    return result
                
                # Continue scanning for other patterns 
                pattern_counts['intel_gfx'] += self._count_patterns(chunk, provider_patterns['intel_providers'])
                pattern_counts['media'] += self._count_patterns(chunk, provider_patterns['media_providers'])
                
                # Progress logging
                if chunks_processed % 100 == 0:
                    logging.info(f"Processed {chunks_processed} chunks, {total_lines:,} lines - no boot patterns yet")
        
        # Complete file scan finished - no DxgkDdiStartDevice found
        # Apply scenarios 2, 3, 4
        result = self._classify_patterns(pattern_counts, chunks_processed, total_lines)
        result["early_exit"] = False
        
        self._cache_result(etl_file_path, result)
        return result

    def _count_patterns(self, text_chunk: str, patterns: list) -> int:
        """
        Count occurrences of patterns in a text chunk.
        Uses case-insensitive matching.
        """
        count = 0
        text_lower = text_chunk.lower()
        
        for pattern in patterns:
            pattern_lower = pattern.lower()
            count += text_lower.count(pattern_lower)
        
        return count

    def _classify_patterns(self, pattern_counts: dict, chunks_processed: int, total_lines: int) -> dict:
        """
        Apply exact scenario classification logic.
        """
        
        logging.info(f"Complete file scan finished. Pattern counts: {pattern_counts}")
        
        # SCENARIO 2: Intel + Media = WPT
        if pattern_counts['intel_gfx'] > 0 and pattern_counts['media'] > 0:
            return {
                "type": "WPT",
                "confidence": "high",
                "reason": f"Intel Graphics ({pattern_counts['intel_gfx']}) + Media ({pattern_counts['media']}) patterns found",
                "pattern_counts": pattern_counts,
                "chunks_processed": chunks_processed,
                "lines_processed": total_lines,
                "scenario": "Scenario 2 - Intel + Media detected"
            }
        
        # SCENARIO 3: Intel only = Display ETL  
        elif pattern_counts['intel_gfx'] > 0:
            return {
                "type": "Display ETL", 
                "confidence": "high",
                "reason": f"Intel Graphics patterns only ({pattern_counts['intel_gfx']} matches)",
                "pattern_counts": pattern_counts,
                "chunks_processed": chunks_processed,
                "lines_processed": total_lines,
                "scenario": "Scenario 3 - Intel only detected"
            }
        
        # SCENARIO 4: Media only = GPUView
        elif pattern_counts['media'] > 0:
            return {
                "type": "GPUView",
                "confidence": "medium", 
                "reason": f"Media patterns only ({pattern_counts['media']} matches)",
                "pattern_counts": pattern_counts,
                "chunks_processed": chunks_processed,
                "lines_processed": total_lines,
                "scenario": "Scenario 4 - Media only detected"
            }
        
        # No significant patterns found
        else:
            return {
                "type": "Unknown",
                "confidence": "low",
                "reason": "No significant patterns detected",
                "pattern_counts": pattern_counts,
                "chunks_processed": chunks_processed, 
                "lines_processed": total_lines,
                "scenario": "No matching scenario - Unknown"
            }

    def get_etl_type(self, etl_file_path: str) -> str:
        """
        Get ETL type classification.
        """
        result = self.analyze_etl(etl_file_path)
        
        if "error" in result:
            logging.error(f"ETL analysis failed: {result['error']}")
            return "Unknown"
        
        etl_type = result.get("type", "Unknown")
        chunks = result.get("chunks_processed", "unknown")
        lines = result.get("lines_processed", "unknown")
        
        logging.info(f"ETL classified as '{etl_type}' ({chunks} chunks, {lines} lines)")
        
        return etl_type

    # --- Cache Management ---
    def get_cache_stats(self) -> dict:
        """Get statistics about the current cache."""
        total_entries = len(self._file_cache)
        
        return {
            'total_entries': total_entries
        }

    def clear_cache(self):
        """Clear all cached results."""
        cleared_count = len(self._file_cache)
        self._file_cache.clear()
        logging.info(f"Cleared {cleared_count} cache entries")

    def clear_stale_cache(self, max_age_hours: int = 24):
        """Clear cache entries older than specified hours."""
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        stale_keys = []
        for cache_key, cache_data in self._file_cache.items():
            timestamp = cache_data.get('timestamp', 0)
            if current_time - timestamp > max_age_seconds:
                stale_keys.append(cache_key)
        
        for key in stale_keys:
            del self._file_cache[key]
        
        logging.info(f"Cleared {len(stale_keys)} stale cache entries (older than {max_age_hours} hours)")
