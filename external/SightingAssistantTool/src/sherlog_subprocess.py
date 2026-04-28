"""
Sherlog Subprocess 

Description:

Calls sherlog toolkit via a seperate command prompt window for each GDHM ID found in the HSD.

"""

import subprocess
import os
import json
from datetime import datetime
import time
import tempfile
import ast
import shutil

from utils.log_utils import get_sat_output_dir


def _is_valid_gdhm_id(value):
    normalized = str(value).strip()
    return normalized.isdigit() and len(normalized) == 10

def get_hsd_id():
    """Get HSD ID from environment variable (set by sighting_sherlog_sync hsd_id param)."""
    return (
        os.environ.get('GNAI_INPUT_HSD_ID', '').strip()
        or os.environ.get('GNAI_INPUT_ID', '').strip()
        or 'unknown'
    )


def get_gdhm_ids():
    """Get the list of GDHM IDs from environment variable"""
    gdhm_ids_str = os.environ.get('GNAI_INPUT_LIST_OF_GDHM_IDS', '')
    
    if not gdhm_ids_str:
        return []
    
    raw = gdhm_ids_str.strip()

    # Support direct single ID input, e.g. "3257606702"
    if _is_valid_gdhm_id(raw):
        return [raw]

    # Support comma-separated input, e.g. "3257606702,3257609179"
    if ',' in raw and not raw.startswith('['):
        tokens = [t.strip() for t in raw.split(',')]
        return [t for t in tokens if _is_valid_gdhm_id(t)]

    # Support list-literal input, e.g. "['3257606702','3257609179']"
    try:
        parsed_list = ast.literal_eval(raw)
        if not isinstance(parsed_list, list):
            return []

        return [
            str(item).strip()
            for item in parsed_list
            if _is_valid_gdhm_id(item)
        ]
    except (ValueError, SyntaxError):
        return []

def cleanup_dumps_folder(src_dir):
    """Remove .dumps folder if it exists"""
    dumps_folder = os.path.join(src_dir, ".dumps")
    try:
        if os.path.exists(dumps_folder):
            shutil.rmtree(dumps_folder)
            return True
    except Exception:
        pass
    return False

def execute_sherlog_analysis_separate_window(gdhm_id):
    """Execute Sherlog analysis in separate command prompt"""
    start_time = time.time()
    
    try:
        src_dir = os.getcwd()
        hsd_id = get_hsd_id()

        gnai_command = f'gnai ask "Analyze GDHM dump ID {gdhm_id}." --assistant=sherlog_complex_analyzer'
        
        # Create batch file content for separate window
        batch_content = f"""@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

cd /d "{src_dir}"

echo ============================================
echo GDHM Analysis for ID: {gdhm_id}
echo Started at: %date% %time%
echo Working Directory: {src_dir}
echo ============================================
echo.

echo %CD%^>{gnai_command}
echo.

set GNAI_TEMP_WORKSPACE=

{gnai_command}

echo.
echo ============================================
echo Analysis completed at: %date% %time%
echo ============================================
echo.
echo You can close this window or press any key...
pause
"""
        
        # Create temporary batch file
        temp_dir = tempfile.gettempdir()
        timestamp = int(time.time())
        batch_file = os.path.join(temp_dir, f"gdhm_analysis_{gdhm_id}_{timestamp}.bat")
        
        with open(batch_file, 'w', encoding='utf-8') as f:
            f.write(batch_content)
        
        # Launch the separate command prompt and wait for completion
        cmd_command = f'start "GDHM Analysis - ID {gdhm_id}" /wait cmd /c "{batch_file}"'
        
        process = subprocess.Popen(cmd_command, shell=True)
        return_code = process.wait()
        
        execution_time = round(time.time() - start_time, 2)

        # Sherlog writes its output natively to .output.md in the working directory.
        # Move it into SAT_{hsd_id}_Output/Sherlog_Output/sherlog_{gdhm_id}.md
        sherlog_native = os.path.join(src_dir, ".output.md")
        sherlog_out_dir = os.path.join(get_sat_output_dir(hsd_id), "Sherlog_Output")
        os.makedirs(sherlog_out_dir, exist_ok=True)
        output_path = os.path.join(sherlog_out_dir, f"sherlog_{gdhm_id}.md")

        sherlog_output_exists = False
        if os.path.exists(sherlog_native):
            os.replace(sherlog_native, output_path)
            sherlog_output_exists = True
        elif os.path.exists(output_path):
            # Already moved (e.g. re-run)
            sherlog_output_exists = True

        content = ""
        if sherlog_output_exists:
            with open(output_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

        # Clean up .dumps folder after sherlog execution
        dumps_cleaned = cleanup_dumps_folder(src_dir)
        
        # Clean up batch file
        try:
            if os.path.exists(batch_file):
                os.remove(batch_file)
        except Exception:
            pass
        
        success = (return_code == 0) and sherlog_output_exists and bool(content)
        
        return {
            "gdhm_id": gdhm_id,
            "command_executed": gnai_command,
            "success": success,
            "execution_time": execution_time,
            "return_code": return_code,
            "sherlog_output_file": output_path if sherlog_output_exists else None,
            "sherlog_output_exists": sherlog_output_exists,
            "content": content if content else None,
            "content_length": len(content) if content else 0,
            "dumps_folder_cleaned": dumps_cleaned,
            "window_opened": True,
            "note": f"Analysis completed in {execution_time}s. Separate CMD window was opened. .dumps folder {'removed' if dumps_cleaned else 'not found'}."
        }
        
    except Exception as e:
        return {
            "gdhm_id": gdhm_id,
            "success": False,
            "error": str(e),
            "execution_time": 0,
            "return_code": -1,
            "sherlog_output_file": None,
            "sherlog_output_exists": False,
            "content": None,
            "content_length": 0,
            "dumps_folder_cleaned": False,
            "window_opened": False
        }

def main():
    gdhm_ids = get_gdhm_ids()
    
    if not gdhm_ids:
        print(json.dumps({"error": "No valid GDHM IDs found"}, indent=2))
        return
    
    results = []
    start_time = time.time()
    
    for gdhm_id in gdhm_ids:
        result = execute_sherlog_analysis_separate_window(gdhm_id)
        results.append(result)
        
        # Small delay between analyses
        time.sleep(1)
    
    total_time = round(time.time() - start_time, 2)
    successful = sum(1 for r in results if r['success'])
    
    summary = {
        "sighting_sherlog_sync_output": {
            "timestamp": datetime.now().isoformat(),
            "status": "COMPLETED_SUCCESS" if len(results) == successful else f"COMPLETED_WITH_{len(results)-successful}_FAILURES",
            "total_gdhm_ids": len(gdhm_ids),
            "successful_executions": successful,
            "failed_executions": len(results) - successful,
            "success_rate_percent": round((successful/len(results)*100), 1),
            "total_execution_time_seconds": total_time,
            "gdhm_ids_processed": [r['gdhm_id'] for r in results],
            "individual_results": results
        }
    }
    
    print(json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
