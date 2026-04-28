"""
log_file_analyzer - Log File Analysis Script

Description:

A log file analyzer for .txt, .log, and .trace files.
Currently supports :
1. GOP (Graphics Output Protocol) log analysis.
2. Burnin Test log analysis.
3. PTAT Monitor CSV log analysis.
4. Gfx PnP (GTMetrics) CSV log analysis.

Designed to be extensible for other log types in the future.

"""

import re
import os
import json 
import argparse
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
import sys
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import logging
import csv as csv_module
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from utils.log_utils import LogProcessor, load_all_log_txt_trace_files_from_temp, merge_log_results_to_attachment_info


logging.basicConfig(level=logging.CRITICAL)

sys.stdout.reconfigure(encoding='utf-8')


def _matches_selected_target(file_path: str, attach_info: Dict, selected_target: str) -> bool:
    """Return True when file/attachment matches the user-selected target."""
    if not selected_target:
        return True

    target = selected_target.strip().lower()
    if not target:
        return True

    file_name = os.path.basename(file_path or "")
    attachment_name = (attach_info or {}).get('document.file_name', '')
    attach_id = str((attach_info or {}).get('id', '')).strip()

    candidates = set()
    if file_name:
        candidates.add(file_name.lower())
    if attachment_name:
        candidates.add(attachment_name.lower())

    # persistent_logs entries are prefixed as <attachment_id>_<basename>
    if file_name and attach_id:
        prefix = f"{attach_id}_"
        if file_name.startswith(prefix):
            candidates.add(file_name[len(prefix):].lower())

    # Exact match first, then fallback to substring match for robust menu naming.
    if any(target == c for c in candidates):
        return True
    return any(target in c for c in candidates)


def _filter_files_by_selected_target(all_files: List[Tuple], selected_target: str, label: str) -> List[Tuple]:
    """Filter indexed files to the user-selected target only."""
    if not selected_target:
        return all_files

    filtered = [
        (file_path, attach_info)
        for file_path, attach_info in all_files
        if _matches_selected_target(file_path, attach_info, selected_target)
    ]

    logging.debug(
        f"[{label}] Selected target filtering: target={selected_target!r}, "
        f"before={len(all_files)}, after={len(filtered)}"
    )
    return filtered


class GOPLogProcessor(LogProcessor):
    """ Graphics Output Protocol (GOP) log processor. """
    
    def __init__(self):
        self.gop_keywords = ['[IntelGOP]', '[InteluGOP]', '[IntelPEIM]', '[INFO]']
        self.new_gop_keywords = ['[IntelGOP]', '[InteluGOP]', '[IntelPEIM]']


    def detect_log_type(self, file_path: str) -> Tuple[bool, str]:
        """ Check if the file is a GOP log by looking for GOP-specific keywords.
        
        Args:
            file_path (str): Path to the .txt or .log file
            
        Returns:
            Tuple[bool, str]: (is_gop_log, reason)
        """
        total_lines = 0
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                for line_number, line in enumerate(file, 1):
                    total_lines = line_number
                    line = line.strip()
                    
                    # Check if line contains any GOP keyword 
                    for keyword in self.gop_keywords:
                        if keyword in line:
                            return True, f"Found GOP keyword '{keyword}' at line {line_number}"
            
            return False, f"No GOP keywords found in the entire file ({total_lines} lines processed)"
            
        except Exception as e:
            return False, f"Error reading file: {str(e)}"
    


    def _determine_gop_version(self, file_path: str) -> Tuple[str, str]:
        """
        Determine GOP version based on keywords found and extract version number.
        
        Returns:
            Tuple[str, str]: (gop_type, version_number)
            - ('new', version_number) if new GOP pattern found with version
            - ('old', version_number) if old GOP pattern found with version
            - ('unknown', 'unknown') if none found
        """
        # Get patterns
        new_patterns = self._get_new_gop_patterns()
        old_patterns = self._get_old_gop_patterns()
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                for line in file:
                    line = line.strip()
                    
                    # Check for new GOP pattern first
                    match = re.search(new_patterns['gop_version_number'], line, re.IGNORECASE)
                    if match:
                        version_number = match.group(1)
                        logging.debug(f"Found NEW GOP version: {version_number} in line: {line[:100]}...")
                        return 'new', version_number  
                    
                    # Check for old GOP pattern
                    match = re.search(old_patterns['gop_version_number'], line, re.IGNORECASE)
                    if match:
                        version_number = match.group(1)
                        logging.debug(f"Found OLD GOP version: {version_number} in line: {line[:100]}...")
                        return 'old', version_number  
                
                return 'unknown', 'unknown'  

        except (IOError, OSError, UnicodeDecodeError) as e:
            logging.error(f"Error reading file {file_path}: {str(e)}")
            return 'unknown', 'unknown'  
        except Exception as e:
            logging.error(f"Unexpected error while determining GOP version for {file_path}: {str(e)}")
            return 'unknown', 'unknown'  


    def _get_new_gop_patterns(self) -> Dict:
        """Return regex patterns for new GOP version with all keyword variants."""
        
        return {
            'gop_version_number': r'\[Intel(?:u?GOP|PEIM)\]:\s*PeiGraphicsEntryPoint\(\d+\)::\s*Controller Name:\s*Intel\(R\)\s*Graphics\s*Pei\s*Module\s*\[([\d.]+)\]',
            'link_training': r'\[Intel(?:u?GOP|PEIM)\]:\s*BdlDisplayLinkTraining\((\d+)\)::\s*Full Link Training\s+(passed|failed)\s*$',
            'fast_link_training': r'\[Intel(?:u?GOP|PEIM)\]:\s*BdlDisplayLinkTraining\((\d+)\)::\s*Fast Link Training\s+(Failed|Passed)',
            'clock_recovery': r'\[Intel(?:u?GOP|PEIM)\]:\s*BdlDisplayClockRecovery\((\d+)\)::\s*CR (Done|Failed) after\s+(\d+)\s+cycles?,\s*(\d+)\s+Same req',
            'equalization': r'\[Intel(?:u?GOP|PEIM)\]:\s*BdlDisplayEqualization\((\d+)\)::\s*EQ\s+(Done|Failed)\s+after\s+(\d+)\s+cycles?,\s*(\d+)\s+Same req',
            'mode_setting': r'\[Intel(?:u?GOP|PEIM)\]:\s*BdlDisplaySetMode\((\d+)\)::\s*In BdlDisplaySetMode::\s*for Display Id::([x0-9A-Fa-f]+)\s*for pipe\s*(\d+)\s*and Mode X:(\d+)\s*and Y:(\d+)',
            'frame_buffer': r'\[Intel(?:u?GOP|PEIM)\]:\s*BdlDisplaySetFb\((\d+)\)::\s*GTT config done:FB size\s+(\d+)',
            'display_status': r'\[Intel(?:u?GOP|PEIM)\]:\s*BdlGetDisplayStatus\((\d+)\)::\s*Display\s+(0x[0-9A-Fa-f]+)\s+is\s+connected',
            
            # PrintDisplayInfo Basic Info Patterns
            'print_display_info_display_id': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayId:\s*(0x[0-9A-Fa-f]+)',
            'print_display_info_port': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayId:Port\s+(\d+)',
            'print_display_info_instance': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayId:Instance\s+(\d+)',
            'print_display_info_connector': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayId:Connector\s+(\d+)',
            'print_display_info_aux_channel': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*AuxChannel:\s+(\d+)',
            'print_display_info_port_value': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*Port:\s+(\d+)',
            
            # DisplayCaps Section Patterns
            'print_display_caps_header': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*Display Info::\s*DisplayCaps',
            'print_display_caps_max_lane_count': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.MaxLaneCount:\s+(\d+)',
            'print_display_caps_max_link_rate': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.MaxLinkRateMbps:\s+(\d+)',
            'print_display_caps_supported_link_rate_count': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.SupportedLinkRateCount:\s+(\d+)',
            'print_display_caps_supported_link_rate': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.SupportedLinkRate:\s+(\d+)',
            'print_display_caps_max_supported_color_depth': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.MaxSupportedColorDepth:\s+(\d+)',
            'print_display_caps_max_tmds_char_rate': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.MaxTmdsCharRate:\s+(\d+)',
            'print_display_caps_repeater_count': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.RepeaterCount:\s+(\d+)',
            'print_display_caps_is_dsc_supported': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.IsDscSupported:\s+([01])',
            'print_display_caps_is_fec_supported': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.IsFecSupported:\s+([01])',
            'print_display_caps_is_psr_supported': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.IsPsrSupported:\s+([01])',
            'print_display_caps_is_psr2_supported': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.IsPsr2Supported:\s+([01])',
            'print_display_caps_is_pr_supported': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.IsPrSupported:\s+([01])',
            'print_display_caps_is_assr_supported': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.IsAssrSupported:\s+([01])',
            'print_display_caps_is_enhanced_framing_supported': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.IsEnhancedFramingSupported:\s+([01])',
            'print_display_caps_is_tps3_supported': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.IsTps3Supported:\s+([01])',
            'print_display_caps_is_tps4_supported': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*DisplayCaps\.IsTps4Supported:\s+([01])',
            
            # TimingInfo Section Patterns
            'print_timing_info_header': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*Display Info::\s*TimingInfo',
            'print_timing_info_pixel_clock': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.PixelClockInHz:\s+(\d+)',
            'print_timing_info_h_total': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.HTotal:\s+(\d+)',
            'print_timing_info_h_active': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.HActive:\s+(\d+)',
            'print_timing_info_h_blank_start': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.HBlankStart:\s+(\d+)',
            'print_timing_info_h_blank_end': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.HBlankEnd:\s+(\d+)',
            'print_timing_info_h_sync_start': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.HSyncStart:\s+(\d+)',
            'print_timing_info_h_sync_end': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.HSyncEnd:\s+(\d+)',
            'print_timing_info_h_refresh': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.HRefresh:\s+(\d+)',
            'print_timing_info_v_total': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.VTotal:\s+(\d+)',
            'print_timing_info_v_active': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.VActive:\s+(\d+)',
            'print_timing_info_v_blank_start': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.VBlankStart:\s+(\d+)',
            'print_timing_info_v_blank_end': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.VBlankEnd:\s+(\d+)',
            'print_timing_info_v_sync_start': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.VSyncStart:\s+(\d+)',
            'print_timing_info_v_sync_end': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.VSyncEnd:\s+(\d+)',
            'print_timing_info_v_rounded_rr': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.VRoundedRR:\s+(\d+)',
            'print_timing_info_h_sync_polarity': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.HSyncPolarity:\s+([01])',
            'print_timing_info_v_sync_polarity': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.VSyncPolarity:\s+([01])',
            'print_timing_info_link_rate': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.LinkRateMbps:\s+(\d+)',
            'print_timing_info_num_links': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.NumLinks:\s+(\d+)',
            'print_timing_info_is_spread_enabled': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.IsSpreadEnabled:\s+([01])',
            'print_timing_info_is_fec_enabled': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.IsFecEnabled:\s+([01])',
            'print_timing_info_color_depth': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.ColorDepth:\s+(\d+)',
            'print_timing_info_link_m': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.LinkM:\s+(\d+)',
            'print_timing_info_link_n': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.LinkN:\s+(\d+)',
            'print_timing_info_data_m': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.DataM:\s+(\d+)',
            'print_timing_info_data_n': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.DataN:\s+(\d+)',
            'print_timing_info_data_tu': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\((\d+)\)::\s*TimingInfo\.DataTU:\s+(\d+)',
            
            # T-values patterns 
            'panel_power_header': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\(\d+\)::\s*Display Info::\s*PanelPower Values',
            't3_value': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\(\d+\)::\s*BrightnessData\.PpsDelays\.T3:\s*(\d+)',
            't5_value': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\(\d+\)::\s*BrightnessData\.PpsDelays\.T5:\s*(\d+)',
            't8_value': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\(\d+\)::\s*BrightnessData\.PpsDelays\.T8:\s*(\d+)',
            't10_value': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\(\d+\)::\s*BrightnessData\.PpsDelays\.T10:\s*(\d+)',
            'dpcd_timeout_value': r'\[Intel(?:u?GOP|PEIM)\]:\s*PrintDisplayInfo\(\d+\)::\s*BrightnessData\.PpsDelays\.DpcdTimeoutValue:\s*(\d+)'
        }

    def _get_old_gop_patterns(self) -> Dict:
        """Return regex patterns for old GOP version."""
        return {
            'gop_version_number': r'\[INFO\]:\[PeiGraphicsEntryPoint\(\)\]:\[PreMem PEI Module\s*:\s*([\d.]+)\]',
            'link_training': r'\[INFO\]:\[EdpEnableDisplayDevice\(\)\]:\[Link training is completed (successfully|unsuccessfully)\]',
            'clock_recovery': r'\[INFO\]:\[TrainPattern1\(\)\]:\[Clock Recovery (Done|Failed)\]',
            'equalization': r'\[INFO\]:\[TrainPattern3\(\)\]:\[Channel Equalization (Successful|Failed)\]',
            'mode_setting': r'\[INFO\]:\[GalSetMode\(\)\]:\[Mode set called for mode number:\s*(\d+)x(\d+)\s*with\s*(\d+)\s*bytes per pixel\.\]', 
            'max_frame_buffer' : r'\[INFO\]:\[GetMaxFrameBufferSizeInBytes\(\)\]:\[PTL Frame Buffer Size in Bytes:\s+(\d+)\]' , 
            'calculated_frame_buffer' : r'\[INFO\]:\[CalculateFrameBufferSize\(\)\]:\[Calculated Frame Buffer Size in MB=\s*(\d+)\s*MB\]'
        }
    
    def find_last_successful_configuration(self, file_path: str) -> Dict:
        """
        Find the last successful link training configuration values.
        
        Returns:
            Dict containing lane_count, vswing_level, pre_emphasis_level, main_link_status
        """
        
        # Initialize result structure with the specific values needed
        result = {
            'found': False,
            'lane_count': None,
            'vswing_level': None,
            'pre_emphasis_level': None,
            'main_link_status': None,
            'link_training_line': None,
            'channel_eq_line': None,
            'lane_config_line': None,
            'error': None
        }
        
        # Read all lines into memory for backward searching
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                all_lines = file.readlines()
        except Exception as e:
            result['error'] = f"Error reading file: {str(e)}"
            return result
        
        # Pattern definitions
        link_training_pattern = r'\[INFO\]:\[EdpEnableDisplayDevice\(\)\]:\[Link training is completed successfully\]'
        channel_eq_pattern = r'\[INFO\]:\[IsChannelEqualizationDone\(\)\]:\[Main Link Status = (0x[0-9A-Fa-f]+)\]'
        lane_config_pattern = r'\[INFO\]:\[SetSnpsPhyVswingPreEmphValues\(\)\]:\[Lane Count: (\d+), Vswing Level: (\d+), Pre Emphasis Level: (\d+)\]'
        
        # Step 1: Find the last successful link training
        last_successful_line_number = None
        
        for line_number, line in enumerate(all_lines, 1):
            line = line.strip()
            if re.search(link_training_pattern, line, re.IGNORECASE):
                last_successful_line_number = line_number
                result['link_training_line'] = line_number
        
        if not last_successful_line_number:
            result['error'] = 'No successful link training found'
            return result
        
        # Step 2: Search backwards for channel equalization status
        for line_number in range(last_successful_line_number - 1, 0, -1):
            line = all_lines[line_number - 1].strip()
            match = re.search(channel_eq_pattern, line, re.IGNORECASE)
            if match:
                result['main_link_status'] = match.group(1)  # Extract the hex value
                result['channel_eq_line'] = line_number
                break
        
        # Step 3: Search backwards for lane configuration
        search_start = (result['channel_eq_line'] - 1 
                       if result['channel_eq_line'] 
                       else last_successful_line_number - 1)
        
        for line_number in range(search_start, 0, -1):
            line = all_lines[line_number - 1].strip()
            match = re.search(lane_config_pattern, line, re.IGNORECASE)
            if match:
                result['lane_count'] = int(match.group(1))          # Extract lane count
                result['vswing_level'] = int(match.group(2))        # Extract vswing level  
                result['pre_emphasis_level'] = int(match.group(3))  # Extract pre emphasis level
                result['lane_config_line'] = line_number
                break
        
        # Mark as found if we have at least the link training
        result['found'] = True
        
        return result
    
    def _decode_display_id(self, display_id_hex: str) -> Dict:
        """
        Decode Display ID hex value into its components.
        
        
        Bit layout: Reserved(15-12) | Connector(11-8) | Instance(7-4) | Port(3-0)
        
        struct {
            uint16_t Port : 4;      // bits 0-3 
            uint16_t Instance : 4;  // bits 4-7
            uint16_t Connector : 4; // bits 8-11
            uint16_t Reserved : 4;  // bits 12-15 
        };
        """
        try:
            # Convert hex string to integer
            if display_id_hex.startswith('0x') or display_id_hex.startswith('0X'):
                display_id_value = int(display_id_hex, 16)
            else:
                display_id_value = int(display_id_hex, 16)
            
            # Extract using bit shifts 
            # For 0x100 = 256 = 0000 0001 0000 0000
            port = display_id_value & 0xF               # bits 0-3 
            instance = (display_id_value >> 4) & 0xF    # bits 4-7
            connector = (display_id_value >> 8) & 0xF   # bits 8-11
            reserved = (display_id_value >> 12) & 0xF   # bits 12-15 
            
            return {
                'raw_value': display_id_hex,
                'decimal_value': display_id_value,
                'port': port,
                'instance': instance,
                'connector': connector,
                'reserved': reserved,
                'port_type': self._get_port_type_name(port),
                'connector_type': self._get_connector_type_name(connector)
            }
            
        except ValueError:
            return {
                'raw_value': display_id_hex,
                'error': f"Invalid hex value: {display_id_hex}",
                'port': None,
                'instance': None,
                'connector': None,
                'reserved': None,
                'port_type': 'UNKNOWN',
                'connector_type': 'UNKNOWN'
            }

    def _get_port_type_name(self, port_value: int) -> str:
        """Convert port value to port type name."""
        port_types = {
            0: 'DDI_A',
            1: 'DDI_B', 
            2: 'TC1 (Port E)',
            3: 'TC2 (Port F)',
            4: 'TC3 (Port G)',
            5: 'TC4 (Port H)',
            6: 'PORT_TYPE_MAX'
        }
        return port_types.get(port_value, f'UNKNOWN({port_value})')

    def _get_connector_type_name(self, connector_value: int) -> str:
        """Convert connector value to connector type name."""
        connector_types = {
            0: 'NONE',
            1: 'EMBEDDED_DP',
            2: 'EXTERNAL_DP', 
            3: 'EXTERNAL_HDMI',
            4: 'EXTERNAL_DVI',
            5: 'TYPE_C_ALT_MODE',
            6: 'THUNDERBOLT',
            7: 'CONNECTOR_MAX'
        }
        return connector_types.get(connector_value, f'UNKNOWN({connector_value})')

    def _analyze_frame_buffer_changes(self, frame_buffer_results: Dict) -> Dict:
        """Analyze frame buffer size changes throughout the log."""
        analysis = {
            'max_frame_buffer_mb': None,
            'calculated_frame_buffer_changes': [],
            'frame_buffer_trend': 'stable'
        }
        
        # Process max frame buffer
        if frame_buffer_results.get('max_frame_buffer_result'):
            max_fb = frame_buffer_results['max_frame_buffer_result'][0]
            analysis['max_frame_buffer_mb'] = max_fb.get('fb_size_mb', 0)
        
        # Process calculated frame buffer changes
        calculated_fbs = frame_buffer_results.get('calculated_frame_buffer_result', [])
        if calculated_fbs:
            sizes = [fb['fb_size_mb'] for fb in calculated_fbs]
            analysis['calculated_frame_buffer_changes'] = [
                {
                    'line_number': fb['line_number'],
                    'size_mb': fb['fb_size_mb'],
                    'change_from_previous': fb['fb_size_mb'] - sizes[i-1] if i > 0 else 0
                }
                for i, fb in enumerate(calculated_fbs)
            ]
            
            # Determine trend
            if len(set(sizes)) == 1:
                analysis['frame_buffer_trend'] = 'stable'
            elif sizes == sorted(sizes):
                analysis['frame_buffer_trend'] = 'increasing'
            elif sizes == sorted(sizes, reverse=True):
                analysis['frame_buffer_trend'] = 'decreasing'
            else:
                analysis['frame_buffer_trend'] = 'variable'
        
        return analysis



    def _group_link_status_events(self, link_training_matches: List, fast_link_training_matches: List, clock_recovery_matches: List, equalization_matches: List) -> List[Dict]:
        """
        Group link training events based on CR -> EQ -> LT sequence.
        Each group ends when a Link Training (LT or FLT) pattern is found.
        
        Args:
            link_training_matches: List of link training matches
            fast_link_training_matches: List of fast link training matches
            clock_recovery_matches: List of clock recovery matches  
            equalization_matches: List of equalization matches
            
        Returns:
            List of grouped link status events
        """
        # Combine all events with their types
        all_events = []
        
        for event in link_training_matches:
            all_events.append({
                'type': 'link_training',
                'line_number': event['line_number'],
                'data': event
            })
            
        for event in fast_link_training_matches:
            all_events.append({
                'type': 'fast_link_training',
                'line_number': event['line_number'],
                'data': event
            })

        for event in clock_recovery_matches:
            all_events.append({
                'type': 'clock_recovery', 
                'line_number': event['line_number'],
                'data': event
            })
            
        for event in equalization_matches:
            all_events.append({
                'type': 'equalization',
                'line_number': event['line_number'], 
                'data': event
            })
        
        # Sort by line number
        all_events.sort(key=lambda x: x['line_number'])
        
        # Group events based on CR -> EQ -> LT sequence
        grouped_events = []
        current_group = []
        
        for event in all_events:
            event_type = event['type']
            
            # Add current event to the group
            current_group.append(event)
            
            if event_type in ['link_training', 'fast_link_training']:
                # End the current group when we hit any LT event
                if current_group:
                    grouped_events.append(self._create_link_status_group(current_group))
                current_group = []  # Start new group
        
        return grouped_events

    def _create_link_status_group(self, events: List[Dict]) -> Dict:
        """Create a link status group from a list of related events."""
        group = {
            'start_line': events[0]['line_number'],
            'end_line': events[-1]['line_number'],
            'line_range': events[-1]['line_number'] - events[0]['line_number'],
            'event_count': len(events),
            'events': {
                'link_training': [],
                'fast_link_training': [],  
                'clock_recovery': [],
                'equalization': []
            },
            'overall_status': 'unknown'
        }
        
        for event in events:
            group['events'][event['type']].append(event['data'])
        
        group['overall_status'] = self._determine_group_status(group['events'])
        
        return group

    def _determine_group_status(self, events: Dict) -> str:
        """Determine the overall status based only on link training results."""
        
        link_training_events = events.get('link_training', [])
        fast_link_training_events = events.get('fast_link_training', [])
        all_training_events = link_training_events + fast_link_training_events

        if not all_training_events:
            return 'unknown'
        
        # Return PASS only if ALL link training attempts passed

        all_passed = all(
            (event.get('status') == 'passed') 
            for event in all_training_events
        )
        
        return 'pass' if all_passed else 'fail'



    def _parse_new_gop_line(self, line: str, line_number: int, patterns: Dict, results: Dict):
        """Parse a line from new GOP version log."""
        # Link Training 
        match = re.search(patterns['link_training'], line, re.IGNORECASE)
        if match:
            status = match.group(2).lower()
            
            match_result = {
                'line_number': line_number, 
                'status': status,
                'raw_line': line
            }
            results['link_training_result'].append(match_result)
            
        # Fast Link Training 
        match = re.search(patterns['fast_link_training'], line, re.IGNORECASE)
        if match:
            function_id = match.group(1)
            status = match.group(2).lower()
            
            match_result = {
                'line_number': line_number,
                'function_id': function_id,
                'status': status,
                'training_type': 'fast',
                'raw_line': line
            }
            results['fast_link_training_result'].append(match_result)


        # Clock Recovery
        match = re.search(patterns['clock_recovery'], line, re.IGNORECASE)
        if match:

            cr_id = match.group(1)          # function_id
            cr_status = match.group(2)      # "Done" or "Failed"  
            cycles = match.group(3)         # cycles 
            same_req = match.group(4)       # same_req 
            
            match_result = {
                'line_number': line_number,
                'clock_recovery_id': cr_id,
                'status': cr_status.lower(),    
                'cycles': int(cycles),          
                'same_requests': int(same_req), 
                'raw_line': line
            }
            results['clock_recovery_result'].append(match_result)
        
        # Equalization
        match = re.search(patterns['equalization'], line, re.IGNORECASE)
        if match:
            eq_id = match.group(1)          # function_id
            eq_status = match.group(2)      # "Done" or "Failed"
            cycles = match.group(3)         # cycles 
            same_req = match.group(4)       # same_req 
            
            match_result = {
                'line_number': line_number,
                'equalization_id': eq_id,
                'status': eq_status.lower(),    
                'cycles': int(cycles),          
                'same_requests': int(same_req), 
                'raw_line': line
            }
            results['equalization_result'].append(match_result)

        # Mode Setting
        match = re.search(patterns['mode_setting'], line, re.IGNORECASE)
        if match:
            mode_id = match.group(1)
            display_id = match.group(2)
            pipe = match.group(3)
            x_resolution = int(match.group(4))
            y_resolution = int(match.group(5))
            
            match_result = {
                'line_number': line_number,
                'mode_id': mode_id,
                'display_id': display_id,
                'pipe': pipe,
                'resolution': {
                    'x': x_resolution,
                    'y': y_resolution,
                },
                'raw_line': line
            }
            results['display_mode_setting'].append(match_result)

        # Frame Buffer 
        match = re.search(patterns['frame_buffer'], line, re.IGNORECASE)
        if match:
            fb_id = match.group(1)
            fb_size = match.group(2)
            match_result = {
                'line_number': line_number,
                'fb_id': fb_id,
                'fb_size_mb': int(fb_size),  
                'raw_line': line
            }
            # For new GOP, we only have calculated frame buffer
            results['frame_buffer_result']['calculated_frame_buffer_result'].append(match_result)

        # T-Values Processing
        def _has_all_t_values():
            return (len(results['t_values_result']['t3_values']) > 0 and
                    len(results['t_values_result']['t5_values']) > 0 and
                    len(results['t_values_result']['t8_values']) > 0 and
                    len(results['t_values_result']['t10_values']) > 0 and
                    len(results['t_values_result']['dpcd_timeout_values']) > 0)
        
        # Only process T-values if we haven't found all of them yet
        if not _has_all_t_values():
            # Panel Power Header (indicates start of T-values section)
            match = re.search(patterns['panel_power_header'], line, re.IGNORECASE)
            if match:
                match_result = {
                    'line_number': line_number,
                    'section_start': True,
                    'raw_line': line
                }
                results['t_values_result']['panel_power_headers'].append(match_result)

            # T3 Value
            if len(results['t_values_result']['t3_values']) == 0:
                match = re.search(patterns['t3_value'], line, re.IGNORECASE)
                if match:
                    t3_value = int(match.group(1))
                    match_result = {
                        'line_number': line_number,
                        'value': t3_value,
                        'raw_line': line
                    }
                    results['t_values_result']['t3_values'].append(match_result)

            # T5 Value
            if len(results['t_values_result']['t5_values']) == 0:
                match = re.search(patterns['t5_value'], line, re.IGNORECASE)
                if match:
                    t5_value = int(match.group(1))
                    match_result = {
                        'line_number': line_number,
                        'value': t5_value,
                        'raw_line': line
                    }
                    results['t_values_result']['t5_values'].append(match_result)

            # T8 Value
            if len(results['t_values_result']['t8_values']) == 0:
                match = re.search(patterns['t8_value'], line, re.IGNORECASE)
                if match:
                    t8_value = int(match.group(1))
                    match_result = {
                        'line_number': line_number,
                        'value': t8_value,
                        'raw_line': line
                    }
                    results['t_values_result']['t8_values'].append(match_result)

            # T10 Value
            if len(results['t_values_result']['t10_values']) == 0:
                match = re.search(patterns['t10_value'], line, re.IGNORECASE)
                if match:
                    t10_value = int(match.group(1))
                    match_result = {
                        'line_number': line_number,
                        'value': t10_value,
                        'raw_line': line
                    }
                    results['t_values_result']['t10_values'].append(match_result)

            # DPCD Timeout Value
            if len(results['t_values_result']['dpcd_timeout_values']) == 0:
                match = re.search(patterns['dpcd_timeout_value'], line, re.IGNORECASE)
                if match:
                    dpcd_value = int(match.group(1))
                    match_result = {
                        'line_number': line_number,
                        'value': dpcd_value,
                        'raw_line': line
                    }
                    results['t_values_result']['dpcd_timeout_values'].append(match_result)

        # Display Status
        match = re.search(patterns['display_status'], line, re.IGNORECASE)
        if match:
            display_id_hex = match.group(2)
            
            # Decode the Display ID
            decoded_display_id = self._decode_display_id(display_id_hex)
            
            match_result = {
                'line_number': line_number,
                'display_id': decoded_display_id,
                'raw_line': line
            }
            results['display_status_result'].append(match_result)

        # PrintDisplayInfo Basic Info Parsing with skip flag
        skip_display_id_parsing = False
        
        # DisplayId
        match = re.search(patterns['print_display_info_display_id'], line, re.IGNORECASE)
        if match:
            display_id_hex = match.group(2)
            
            # Check if we already have this display ID from display_status
            existing_display_ids = [d['display_id']['raw_value'] for d in results['display_status_result'] 
                                   if 'display_id' in d and 'raw_value' in d['display_id']]
            
            if display_id_hex in existing_display_ids:
                skip_display_id_parsing = True
                match_result = {
                    'line_number': line_number,
                    'display_id': display_id_hex,
                    'field_type': 'display_id',
                    'skipped_parsing': True,
                    'reason': 'Already parsed in display_status',
                    'raw_line': line
                }
            else:
                decoded_display_id = self._decode_display_id(display_id_hex)
                match_result = {
                    'line_number': line_number,
                    'display_id': decoded_display_id,
                    'field_type': 'display_id',
                    'skipped_parsing': False,
                    'raw_line': line
                }
            
            results['print_display_info_result']['basic_info'].append(match_result)

        # Skip individual parsing if we already have the info
        if not skip_display_id_parsing:
            # Port
            match = re.search(patterns['print_display_info_port'], line, re.IGNORECASE)
            if match:
                port_value = int(match.group(2))
                match_result = {
                    'line_number': line_number,
                    'port': port_value,
                    'port_type': self._get_port_type_name(port_value),
                    'field_type': 'port',
                    'raw_line': line
                }
                results['print_display_info_result']['basic_info'].append(match_result)

            # Instance
            match = re.search(patterns['print_display_info_instance'], line, re.IGNORECASE)
            if match:
                instance_value = int(match.group(2))
                match_result = {
                    'line_number': line_number,
                    'instance': instance_value,
                    'field_type': 'instance',
                    'raw_line': line
                }
                results['print_display_info_result']['basic_info'].append(match_result)

            # Connector
            match = re.search(patterns['print_display_info_connector'], line, re.IGNORECASE)
            if match:
                connector_value = int(match.group(2))
                match_result = {
                    'line_number': line_number,
                    'connector': connector_value,
                    'connector_type': self._get_connector_type_name(connector_value),
                    'field_type': 'connector',
                    'raw_line': line
                }
                results['print_display_info_result']['basic_info'].append(match_result)

        # AuxChannel 
        match = re.search(patterns['print_display_info_aux_channel'], line, re.IGNORECASE)
        if match:
            aux_channel = int(match.group(2))
            match_result = {
                'line_number': line_number,
                'aux_channel': aux_channel,
                'field_type': 'aux_channel',
                'raw_line': line
            }
            results['print_display_info_result']['basic_info'].append(match_result)

        # Port Value 
        match = re.search(patterns['print_display_info_port_value'], line, re.IGNORECASE)
        if match:
            port_value = int(match.group(2))
            match_result = {
                'line_number': line_number,
                'port_value': port_value,
                'field_type': 'port_value',
                'raw_line': line
            }
            results['print_display_info_result']['basic_info'].append(match_result)

        # DisplayCaps Section Headers
        match = re.search(patterns['print_display_caps_header'], line, re.IGNORECASE)
        if match:
            match_result = {
                'line_number': line_number,
                'section_type': 'display_caps',
                'raw_line': line
            }
            results['print_display_info_result']['section_headers'].append(match_result)

        # DisplayCaps Values 
        display_caps_patterns = [
            ('print_display_caps_max_lane_count', 'max_lane_count'),
            ('print_display_caps_max_link_rate', 'max_link_rate_mbps'),
            ('print_display_caps_supported_link_rate_count', 'supported_link_rate_count'),
            ('print_display_caps_supported_link_rate', 'supported_link_rate'),
            ('print_display_caps_max_supported_color_depth', 'max_supported_color_depth'),
            ('print_display_caps_max_tmds_char_rate', 'max_tmds_char_rate'),
            ('print_display_caps_repeater_count', 'repeater_count'),
            ('print_display_caps_is_dsc_supported', 'is_dsc_supported'),
            ('print_display_caps_is_fec_supported', 'is_fec_supported'),
            ('print_display_caps_is_psr_supported', 'is_psr_supported'),
            ('print_display_caps_is_psr2_supported', 'is_psr2_supported'),
            ('print_display_caps_is_pr_supported', 'is_pr_supported'),
            ('print_display_caps_is_assr_supported', 'is_assr_supported'),
            ('print_display_caps_is_enhanced_framing_supported', 'is_enhanced_framing_supported'),
            ('print_display_caps_is_tps3_supported', 'is_tps3_supported'),
            ('print_display_caps_is_tps4_supported', 'is_tps4_supported')
        ]

        for pattern_key, field_name in display_caps_patterns:
            match = re.search(patterns[pattern_key], line, re.IGNORECASE)
            if match:
                value = match.group(2)
                # Convert to appropriate type
                if field_name.startswith('is_'):
                    value = bool(int(value))
                else:
                    value = int(value)
                
                match_result = {
                    'line_number': line_number,
                    'field_name': field_name,
                    'value': value,
                    'raw_line': line
                }
                results['print_display_info_result']['display_caps'].append(match_result)

        # TimingInfo Section Header
        match = re.search(patterns['print_timing_info_header'], line, re.IGNORECASE)
        if match:
            match_result = {
                'line_number': line_number,
                'section_type': 'timing_info',
                'raw_line': line
            }
            results['print_display_info_result']['section_headers'].append(match_result)

        # TimingInfo Values 
        timing_info_patterns = [
            ('print_timing_info_pixel_clock', 'pixel_clock_hz'),
            ('print_timing_info_h_total', 'h_total'),
            ('print_timing_info_h_active', 'h_active'),
            ('print_timing_info_h_blank_start', 'h_blank_start'),
            ('print_timing_info_h_blank_end', 'h_blank_end'),
            ('print_timing_info_h_sync_start', 'h_sync_start'),
            ('print_timing_info_h_sync_end', 'h_sync_end'),
            ('print_timing_info_h_refresh', 'h_refresh'),
            ('print_timing_info_v_total', 'v_total'),
            ('print_timing_info_v_active', 'v_active'),
            ('print_timing_info_v_blank_start', 'v_blank_start'),
            ('print_timing_info_v_blank_end', 'v_blank_end'),
            ('print_timing_info_v_sync_start', 'v_sync_start'),
            ('print_timing_info_v_sync_end', 'v_sync_end'),
            ('print_timing_info_v_rounded_rr', 'v_rounded_rr'),
            ('print_timing_info_h_sync_polarity', 'h_sync_polarity'),
            ('print_timing_info_v_sync_polarity', 'v_sync_polarity'),
            ('print_timing_info_link_rate', 'link_rate_mbps'),
            ('print_timing_info_num_links', 'num_links'),
            ('print_timing_info_is_spread_enabled', 'is_spread_enabled'),
            ('print_timing_info_is_fec_enabled', 'is_fec_enabled'),
            ('print_timing_info_color_depth', 'color_depth'),
            ('print_timing_info_link_m', 'link_m'),
            ('print_timing_info_link_n', 'link_n'),
            ('print_timing_info_data_m', 'data_m'),
            ('print_timing_info_data_n', 'data_n'),
            ('print_timing_info_data_tu', 'data_tu')
        ]

        for pattern_key, field_name in timing_info_patterns:
            match = re.search(patterns[pattern_key], line, re.IGNORECASE)
            if match:
                value = match.group(2)
                # Convert to appropriate type
                if field_name in ['h_sync_polarity', 'v_sync_polarity', 'is_spread_enabled', 'is_fec_enabled']:
                    value = bool(int(value))
                else:
                    value = int(value)
                
                match_result = {
                    'line_number': line_number,
                    'field_name': field_name,
                    'value': value,
                    'raw_line': line
                }
                results['print_display_info_result']['timing_info'].append(match_result)

    def _parse_old_gop_line(self, line: str, line_number: int, patterns: Dict, results: Dict):
        """Parse a line from old GOP version log."""
        
        # Link Training
        match = re.search(patterns['link_training'], line, re.IGNORECASE)
        if match:
            status = match.group(1).lower()
            
            match_result = {
                'line_number': line_number,
                'status': 'passed' if status == 'successfully' else 'failed',
                'raw_line': line
            }
            results['link_training_result'].append(match_result)
        
        # Clock Recovery
        match = re.search(patterns['clock_recovery'], line, re.IGNORECASE)
        if match:
            status = match.group(1).lower()
            
            match_result = {
                'line_number': line_number,
                'status': status,
                'raw_line': line
            }
            results['clock_recovery_result'].append(match_result)
        
        # Equalization
        match = re.search(patterns['equalization'], line, re.IGNORECASE)
        if match:
            status = match.group(1).lower()
            
            match_result = {
                'line_number': line_number,
                'status': status,
                'raw_line': line
            }
            results['equalization_result'].append(match_result)
        
        # Mode Setting
        match = re.search(patterns['mode_setting'], line, re.IGNORECASE)
        if match:
            x_resolution = int(match.group(1))
            y_resolution = int(match.group(2))
            bytes_per_pixel = int(match.group(3))
            
            match_result = {
                'line_number': line_number,
                'resolution': {
                    'x': x_resolution,
                    'y': y_resolution,
                },
                'bytes_per_pixel': bytes_per_pixel,
                'raw_line': line
            }
            results['display_mode_setting'].append(match_result)

        # Max Frame Buffer (only capture once as it doesn't change)
        if not len(results['frame_buffer_result']['max_frame_buffer_result']):
            match = re.search(patterns['max_frame_buffer'], line, re.IGNORECASE)
            if match: 
                fb_size = match.group(1)
                match_result = {
                    'line_number': line_number,
                    'fb_size_bytes': int(fb_size),  # Store as integer for easier processing
                    'fb_size_mb': round(int(fb_size) / (1024 * 1024), 2),  # Convert to MB
                    'raw_line': line
                }
                results['frame_buffer_result']['max_frame_buffer_result'].append(match_result)

        # Calculated Frame Buffer (can occur multiple times)
        match = re.search(patterns['calculated_frame_buffer'], line, re.IGNORECASE)
        if match: 
            fb_size = match.group(1)
            match_result = {
                'line_number': line_number,
                'fb_size_mb': int(fb_size),
                'raw_line': line
            }
            results['frame_buffer_result']['calculated_frame_buffer_result'].append(match_result)

    def process_log(self, file_path: str) -> Dict:
        """
        Parse GOP log file and extract insights about display operations.
        
        Args:
            file_path (str): Path to the .txt or .log file
            
        Returns:
            Dict: Dictionary containing parsed insights
        """

        # Validate file extension
        if not file_path.lower().endswith(('.txt', '.log')):
            return {
                'file_path': file_path,
                'error': "File must be a .txt or .log file",
                'processed': False
            }
        
        # Check if file exists
        if not os.path.exists(file_path):
            return {
                'file_path': file_path,
                'error': f"File not found: {file_path}",
                'processed': False
            }
        
        results = {
            'file_path': file_path,
            'processed': True,
            'gop_version': 'unknown',
            'link_training_result': [], 
            'fast_link_training_result': [], 
            'clock_recovery_result': [],
            'equalization_result': [],
            'display_mode_setting': [], 
            'display_status_result': [],  
           'print_display_info_result': {  
                'basic_info': [],           
                'display_caps': [],         
                'timing_info': [],          
                'section_headers': []      
            },
            'frame_buffer_result': { 'max_frame_buffer_result' : [], 'calculated_frame_buffer_result' : []},
            't_values_result': {
                'panel_power_headers': [],
                't3_values': [],
                't5_values': [],
                't8_values': [],
                't10_values': [],
                'dpcd_timeout_values': []
            },
            'last_successful_config_result': {
                'found': False,
                'lane_count': None,
                'vswing_level': None,
                'pre_emphasis_level': None,
                'main_link_status': None,
                'link_training_line': None,
                'channel_eq_line': None,
                'lane_config_line': None,
                'error': None
            }
        }
        
        # Determine GOP version
        # Populate results with gop version number 
        gop_version, gop_version_number = self._determine_gop_version(file_path)


        # Add debug logging
        logging.debug(f"GOP version detection result: gop_version='{gop_version}', gop_version_number='{gop_version_number}'")
    

        results['gop_version'] = gop_version_number
        
        # Define patterns based on GOP version
        if gop_version == 'new':
            patterns = self._get_new_gop_patterns()
        else:
            patterns = self._get_old_gop_patterns()
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                line_number = 0
                
                for line in file:
                    line_number += 1
                    line = line.strip()
                    
                    # Parse based on GOP version
                    if gop_version == 'new':
                        self._parse_new_gop_line(line, line_number, patterns, results)
                    else:
                        self._parse_old_gop_line(line, line_number, patterns, results)
        
        except Exception as e:
            return {
                'file_path': file_path,
                'error': f"Error reading file: {str(e)}",
                'pattern_matches': []
            }
        
        # Add last successful configuration analysis (only for old GOP)
        if gop_version == 'old':
            last_successful_config = self.find_last_successful_configuration(file_path)
            results['last_successful_config_result'] = last_successful_config
        

        # Group link status events
        link_status_groups = self._group_link_status_events(
            results['link_training_result'],
            results['fast_link_training_result'],  
            results['clock_recovery_result'], 
            results['equalization_result']
        )
        
        # Convert to grouped format - ONLY include grouped link status
        pattern_matches = []
        
        # Add Link Status groups if any exist
        if link_status_groups:
            pattern_matches.append({
                'pattern_type': 'link_status',
                'matches': link_status_groups
            })
        
        if results['display_mode_setting']:
            pattern_matches.append({
                'pattern_type': 'mode_setting',
                'matches': results['display_mode_setting']
            })
        

        # Only add frame buffer if there are actual results
        frame_buffer_data = results['frame_buffer_result']
        has_frame_buffer_data = (
            frame_buffer_data.get('max_frame_buffer_result') or 
            frame_buffer_data.get('calculated_frame_buffer_result')
        )
        
        if has_frame_buffer_data:
            pattern_matches.append({
                'pattern_type': 'frame_buffer',
                'matches': results['frame_buffer_result']
            })

        # Add T-values to pattern matches (only for new GOP)
        if gop_version == 'new' and any(results['t_values_result'].values()):
            pattern_matches.append({
                'pattern_type': 't_values',
                'matches': results['t_values_result']
            })

        # Add last successful configuration if found (only for old GOP)
        if (gop_version == 'old' and 
            results['last_successful_config_result'].get('found')):
            pattern_matches.append({
                'pattern_type': 'last_successful_configuration',
                'matches': results['last_successful_config_result']
            })
       
        # Add Display Status to pattern matches (only for new GOP)
        if gop_version == 'new' and results['display_status_result']:
            pattern_matches.append({
                'pattern_type': 'display_status',
                'matches': results['display_status_result']
            })

        # Add PrintDisplayInfo to pattern matches (only for new GOP)
        if gop_version == 'new' and any(results['print_display_info_result'].values()):
            pattern_matches.append({
                'pattern_type': 'print_display_info',
                'matches': results['print_display_info_result']
            })


        return {
            'file_path': file_path,
            'gop_version': gop_version_number,
            'pattern_matches': pattern_matches
        }

    def coordinate_batch_processing(self, all_log_txt_files: List[Tuple]) -> Tuple[Dict, List]:
        """
        Coordinate parallel processing of multiple files for GOP analysis.
        
        Args:
            all_log_txt_files: List of (file_path, attach_info) tuples
        
        Returns:
            Tuple: (attachment_results_dict, gop_analysis_results_list)
        """
        attachment_results = defaultdict(list)
        gop_analysis_results = []
        
        if not all_log_txt_files:
            logging.debug("No .log or .txt files to process")
            return attachment_results, gop_analysis_results
        
        logging.debug(f"Processing {len(all_log_txt_files)} files for GOP analysis")
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(self._process_single_file, file_path, attach_info): (file_path, attach_info)
                for file_path, attach_info in all_log_txt_files
            }
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        attach_name, gop_data = result
                        self._handle_processing_result(attach_name, gop_data, attachment_results, gop_analysis_results)
                        
                except Exception as e:
                    file_path, attach_info = futures[future]
                    self._handle_processing_error(file_path, attach_info, e, attachment_results)
        
        return dict(attachment_results), gop_analysis_results

    def _process_single_file(self, file_path: str, attach_info: Dict) -> Optional[Tuple[str, Dict]]:
        """
        Process a single file for GOP analysis.
        
        Args:
            file_path: Path to the file
            attach_info: Attachment metadata
            
        Returns:
            Tuple of (document_name, gop_result) or None if not a GOP log
        """
        try:
            file_name = os.path.basename(file_path)
            logging.debug(f"[GOP] Analyzing file: {file_name}")
            
            # Check if it's a GOP log
            is_gop, reason = self.detect_log_type(file_path)
            logging.debug(f"[GOP] Detection result for {file_name}: {is_gop} - {reason}")
            
            if is_gop:
                # Process the GOP log
                result = self.process_log(file_path)
                logging.debug(f"[GOP] Processing completed for {file_name}")
                return attach_info['document.file_name'], result
            else:
                logging.debug(f"[GOP] {file_name} - Not a GOP log: {reason}")
                return None
                
        except Exception as e:
            logging.error(f"[GOP] Error processing {file_path}: {str(e)}")
            raise  # Re-raise to be handled by caller

    def _handle_processing_result(self, attach_name: str, gop_data: Dict, 
                                attachment_results: Dict, gop_analysis_results: List):
        """Handle successful GOP processing result using the generic helper."""
        self._handle_generic_processing_result(
            attach_name=attach_name,
            data=gop_data,
            attachment_results=attachment_results,
            analysis_results=gop_analysis_results,
            result_key='pattern_matches',
            log_display='GOP Log'
        )

    def _handle_processing_error(self, file_path: str, attach_info: Dict, 
                               error: Exception, attachment_results: Dict):
        """Handle GOP processing error using the generic error helper."""
        self._handle_common_processing_error(
            log_prefix='GOP',
            file_path=file_path,
            attach_info=attach_info,
            error=error,
            attachment_results=attachment_results
        )


def process_gop_files():
    """Process gop files using data from check_attachments.py.

    Primary source: all_log_txt_trace_csv_files.json written by check_attachments /
    extract_attachment.

    Fallback: if the JSON index is empty or missing, scan workspace directories
    (persistent_logs/ and extracted_<id>/) directly so that GOP logs extracted
    via archive_utils are still analysed even when the JSON wasn't updated (e.g.
    after a previous session left extracted directories behind).
    """
    selected_target = os.environ.get('GNAI_INPUT_GOP_TARGET', '').strip()
    all_log_txt_files = load_all_log_txt_trace_files_from_temp()

    if not all_log_txt_files:
        # Fallback: scan workspace for GOP log files directly.
        workspace = os.environ.get('GNAI_TEMP_WORKSPACE', '.')
        scan_dirs = []
        persistent_logs = os.path.join(workspace, 'persistent_logs')
        if os.path.isdir(persistent_logs):
            scan_dirs.append(persistent_logs)
        # Also scan any extracted_<id>/ directories.
        try:
            for entry in os.scandir(workspace):
                if entry.is_dir() and entry.name.startswith('extracted_'):
                    scan_dirs.append(entry.path)
        except OSError:
            pass

        fallback_files = []
        for scan_dir in scan_dirs:
            for root, _, files in os.walk(scan_dir):
                for fname in files:
                    if fname.lower().endswith(('.log', '.txt')):
                        full_path = os.path.join(root, fname)
                        fallback_files.append((full_path, {'document.file_name': fname, 'id': 'unknown'}))

        if not fallback_files:
            return {}, []
        logging.debug(f"[GOP] JSON index empty; falling back to workspace scan: {len(fallback_files)} candidate(s)")
        all_log_txt_files = fallback_files

    all_log_txt_files = _filter_files_by_selected_target(all_log_txt_files, selected_target, 'GOP')

    if not all_log_txt_files:
        return {}, []

    gop_processor = GOPLogProcessor()
    return gop_processor.coordinate_batch_processing(all_log_txt_files)


class BurninLogProcessor(LogProcessor):
    """Burnin Test Log processor for GPGPU Integer Verification Error analysis."""
    
    def __init__(self):
        self.burnin_keywords = ['GPGPU Integer Verification Error', 'GPGPU,', 'LOG NOTE:']
        self.prefix_pattern = re.compile(r"GPGPU,\s*(.*)$")
        self.out_header_text = "GPGPU Integer Verification Error - Thread 0 Out"
        self.expected_header_text = "GPGPU Integer Verification Error - Thread 0 Expected"

    def detect_log_type(self, file_path: str) -> Tuple[bool, str]:
        """Check if the file is a Burnin test log by looking for PassMark header.

        Reads the first 2000 bytes once and checks the first 5 lines across
        multiple encodings. Accepts both 'Log' and 'Trace' file types.
        """
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(2000)
            
            if not raw_data:
                return False, "File is empty"
            
            encodings_to_try = ['utf-8', 'utf-16-le', 'utf-16', 'latin-1']
            
            if raw_data.startswith(b'\xff\xfe') or raw_data.startswith(b'\xfe\xff'):
                encodings_to_try = ['utf-16', 'utf-16-le'] + encodings_to_try
            elif b'\x00' in raw_data[:100]:  # Null bytes suggest UTF-16
                encodings_to_try = ['utf-16-le', 'utf-16'] + encodings_to_try
            
            for encoding in encodings_to_try:
                try:
                    decoded = raw_data.decode(encoding, errors='ignore')
                    lines = [l.strip() for l in decoded.split('\n')[:5] if l.strip()]

                    if not lines:
                        continue

                    logging.debug(f"[BURNIN] Trying encoding {encoding}: first line='{lines[0][:100]}'")

                    # Required: both "PassMark" and "BurnInTest" must appear on the same line.
                    # Optional: "https://www.passmark.com" strengthens confidence.
                    # "Log" or "Trace" are both accepted (log files vs trace files).
                    for line in lines:
                        normalized = ' '.join(line.split()).lower()
                        if not normalized or len(normalized) < 10:
                            continue
                        has_passmark = 'passmark' in normalized
                        has_burnintest = 'burnintest' in normalized
                        has_type = 'log' in normalized or 'trace' in normalized
                        has_url = 'passmark.com' in normalized
                        if has_passmark and has_burnintest and (has_type or has_url):
                            return True, f"Found PassMark BurnInTest header with encoding {encoding}: '{line}'"

                except (UnicodeDecodeError, UnicodeError):
                    continue
                except Exception as e:
                    logging.debug(f"[BURNIN] Error with encoding {encoding}: {e}")
                    continue

            return False, "Could not find PassMark BurnInTest header with any supported encoding"
                        
        except Exception as e:
            return False, f"Error reading file: {str(e)}"


    def _validate_burnin_content(self, lines: List[str]) -> bool:
        """Validate that the content looks like a valid BurnIn log."""
        if not lines:
            return False
        
        header_found = False
        for i, line in enumerate(lines[:5]):  # Check first 5 lines
            line_clean = line.strip()
            if not line_clean:
                continue
                
            if "passmark" in line_clean.lower() and "burnintest" in line_clean.lower():
                header_found = True
                break
        
        if not header_found:
            return False
        
        gpgpu_found = False
        lines_to_scan = min(1000, len(lines))
        
        for line in lines[:lines_to_scan]:
            line_lower = line.lower()
            if any(keyword.lower() in line_lower for keyword in self.burnin_keywords):
                gpgpu_found = True
                break
        
        return gpgpu_found


    def process_log(self, file_path: str) -> Dict:
        """Process burnin test log and extract GPGPU verification errors using original format."""
        
        if not file_path.lower().endswith(('.txt', '.log', '.trace')):
            return {
                'file_path': file_path,
                'error': "File must be a .txt, .log, or .trace file",
                'processed': False
            }
        
        # Check if file exists
        if not os.path.exists(file_path):
            return {
                'file_path': file_path,
                'error': f"File not found: {file_path}",
                'processed': False
            }
        
        try:
            lines = self._read_lines_with_fallback(file_path)
            if lines is None:
                return {
                    'file_path': file_path,
                    'error': "Failed to read file with supported encodings",
                    'processed': False
                }
            
            if not self._validate_burnin_content(lines):
                return {
                    'file_path': file_path,
                    'error': "File does not contain valid BurnIn test content",
                    'processed': False
                }
            
            events = self._find_events_original_format(lines)
            
            result = {"events": []}
            for idx, ev in enumerate(events, start=1):
                item = {
                    "index": idx,
                    "error_line_no": ev.get('error_line'),
                    "error_line_text": (lines[ev['error_line'] - 1].rstrip("\n") if ev.get('error_line') else None),
                    "out_header_line": (ev['out_section']['header_line'] if ev.get('out_section') else None),
                    "expected_header_line": (ev['expected_section']['header_line'] if ev.get('expected_section') else None),
                    "differences": [],
                    "extra_test_bytes_count": 0,
                    "extra_expected_bytes_count": 0,
                }
                
                if ev.get('out_section') and ev.get('expected_section'):
                    mismatches, extra_out, extra_exp = self._compare_sections_original_format(
                        ev['out_section'], ev['expected_section'], lines
                    )
                    
                    for pos, t, e in mismatches:
                        item["differences"].append({
                            "index": pos,
                            "expected_value": e['value'],
                            "test_value": t['value'],
                            "expected_line_no": e['line_no'],
                            "test_line_no": t['line_no'],
                            "expected_line_text": lines[e['line_no'] - 1].rstrip("\n"),
                            "test_line_text": self._annotate_line_at_pos(lines[t['line_no'] - 1], t['pos_in_line']),
                        })
                    
                    item["extra_test_bytes_count"] = len(extra_out)
                    item["extra_expected_bytes_count"] = len(extra_exp)
                
                result["events"].append(item)
            
            return {
                'file_path': file_path,
                'processed': True,
                'log_type': 'burnin_test',
                'burnin_result': result  
            }
            
        except Exception as e:
            return {
                'file_path': file_path,
                'error': f"Error processing burnin log: {str(e)}",
                'processed': False
            }


    def _read_lines_with_fallback(self, path: str) -> Optional[List[str]]:
        """Read file with multiple encoding attempts, prioritizing UTF-16 for BurnIn logs."""
        # Reorder encodings to try UTF-16 variants first for BurnIn logs
        encodings = ["utf-16-le", "utf-16", "utf-8", "latin-1"]
        
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc, errors='ignore') as f:
                    lines = f.readlines()
                    # Validate that we got reasonable content
                    if lines and len(lines[0].strip()) > 0:
                        logging.debug(f"[BURNIN] Successfully read file with encoding: {enc}")
                        return lines
            except Exception as e:
                logging.debug(f"[BURNIN] Failed to read with encoding {enc}: {e}")
                continue
        
        # Final fallback: binary read + decode latin-1
        try:
            logging.debug("[BURNIN] Trying binary fallback")
            with open(path, "rb") as f:
                data = f.read()
            
            # Try to detect if it's UTF-16 by looking for BOM or null bytes pattern
            if data.startswith(b'\xff\xfe') or data.startswith(b'\xfe\xff'):
                # Has BOM, try UTF-16
                try:
                    decoded = data.decode('utf-16', errors='ignore')
                    return decoded.splitlines(True)
                except UnicodeDecodeError:
                    pass
            elif b'\x00' in data[:100]:  # Null bytes in first 100 bytes suggest UTF-16
                try:
                    decoded = data.decode('utf-16-le', errors='ignore')
                    return decoded.splitlines(True)
                except UnicodeDecodeError:
                    pass
            
            # Last resort
            return data.decode("latin-1", errors="ignore").splitlines(True)
        except Exception as e:
            logging.error(f"[BURNIN] All encoding attempts failed: {e}")
            return None




    def _parse_token_to_int(self, tok: str) -> Optional[int]:
        """Parse token to integer, handling hex format used in BurnIn GPGPU logs.
        
        In BurnIn logs, all GPGPU byte values are hexadecimal (e.g., '64', 'C8', 'F4').
        This includes tokens without A-F characters like '64' which represents 0x64 (100 decimal).
        """
        tok = tok.strip()
        if not tok:
            return None
        
        # Try parsing as hexadecimal first (BurnIn GPGPU bytes are always hex)
        try:
            return int(tok, 16)
        except ValueError:
            # If hex parsing fails, try decimal as fallback
            try:
                return int(tok, 10)
            except ValueError:
                return None

    def _find_events_original_format(self, lines: List[str]) -> List[Dict]:
        """Find events using original algorithm from burnin_test_analyzer.py"""
        events = []
        out_idxs = [i for i, ln in enumerate(lines) if self.out_header_text in ln]
        exp_idxs = [i for i, ln in enumerate(lines) if self.expected_header_text in ln]
        
        # Only capture the actual error message line (with trailing comma), not the section headers
        err_idxs = [
            i for i, ln in enumerate(lines)
            if "gpgpu integer verification error," in ln.lower() and "thread 0" not in ln.lower()
        ]

        for out_idx in out_idxs:
            # Pair with next expected after this out
            next_exp_candidates = [e for e in exp_idxs if e > out_idx]
            if not next_exp_candidates:
                out_section, _ = self._collect_section_original_format(lines, out_idx)
                # Find closest error line at or before out_idx
                err_line = None
                if err_idxs:
                    pos = bisect_right(err_idxs, out_idx) - 1
                    if pos >= 0:
                        err_line = err_idxs[pos] + 1
                events.append({
                    'error_line': err_line, 
                    'out_section': out_section, 
                    'expected_section': None
                })
                continue

            exp_idx = next_exp_candidates[0]
            out_section, _ = self._collect_section_original_format(lines, out_idx)
            expected_section, _ = self._collect_section_original_format(lines, exp_idx)

            # Find closest error line at or before out_idx
            err_line = None
            if err_idxs:
                pos = bisect_right(err_idxs, out_idx) - 1
                if pos >= 0:
                    err_line = err_idxs[pos] + 1

            events.append({
                'error_line': err_line, 
                'out_section': out_section, 
                'expected_section': expected_section
            })

        return events

    def _collect_section_original_format(self, lines: List[str], start_idx: int) -> Tuple[Dict, int]:
        """Collect section using original format with ByteEntry-like structure."""
        header_line_no = start_idx + 1  # 1-based
        bytes_collected = []
        raw_lines = []
        
        i = start_idx + 1
        while i < len(lines):
            line = lines[i]
            # Stop if we hit another header or a line that doesn't look like a GPGPU bytes line
            if (self.out_header_text in line) or (self.expected_header_text in line) or ("gpgpu integer verification error" in line.lower()):
                break
            if "LOG NOTE:" in line and "GPGPU," in line:
                entries = self._parse_gpgpu_bytes_from_line_original_format(line, i + 1)
                if entries:
                    bytes_collected.extend(entries)
                    raw_lines.append((i + 1, line.rstrip("\n")))
                    i += 1
                    continue
            # If it's not a GPGPU bytes line, stop collecting
            break
        
        return {
            'header_line': header_line_no,
            'bytes': bytes_collected,
            'raw_lines': raw_lines
        }, i

    def _parse_gpgpu_bytes_from_line_original_format(self, line: str, line_no: int) -> List[Dict]:
        """Parse GPGPU bytes using original ByteEntry format."""
        m = self.prefix_pattern.search(line)
        if not m:
            return []
        
        tail = m.group(1)
        tokens = tail.strip().split()
        entries = []
        
        for idx, tok in enumerate(tokens):
            val = self._parse_token_to_int(tok)
            if val is not None:
                entries.append({
                    'value': val,
                    'line_no': line_no,
                    'pos_in_line': idx
                })
        
        return entries

    def _compare_sections_original_format(self, out_section: Dict, exp_section: Dict, lines: List[str]) -> Tuple[List, List, List]:
        """Compare sections using original format that returns tuples."""
        out_bytes = out_section['bytes']
        exp_bytes = exp_section['bytes']
        
        mismatches = []
        extra_out = []
        extra_exp = []

        n = min(len(out_bytes), len(exp_bytes))
        for idx in range(n):
            t = out_bytes[idx]
            e = exp_bytes[idx]
            if t['value'] != e['value']:
                mismatches.append((idx, t, e))

        if len(out_bytes) > n:
            extra_out = out_bytes[n:]
        if len(exp_bytes) > n:
            extra_exp = exp_bytes[n:]
        
        return mismatches, extra_out, extra_exp

    def _annotate_line_at_pos(self, line: str, pos_in_line: int) -> str:
        """Annotate line by adding '*' before the token at specified position."""
        original = line.rstrip("\n")
        m = self.prefix_pattern.search(original)
        if not m:
            return original
        
        tail_start = m.start(1)
        tail = original[tail_start:]
        
        # Find tokens without altering whitespace
        token_matches = list(re.finditer(r"\S+", tail))
        if 0 <= pos_in_line < len(token_matches):
            t = token_matches[pos_in_line]
            annotated_tail = tail[:t.start()] + "*" + tail[t.start():]
            return original[:tail_start] + annotated_tail
        
        return original

    def coordinate_batch_processing(self, all_log_txt_files: List[Tuple]) -> Tuple[Dict, List]:
        """Coordinate parallel processing of multiple files for Burnin analysis."""
        attachment_results = defaultdict(list)
        burnin_analysis_results = []
        
        if not all_log_txt_files:
            logging.debug("No .log, .txt, or .trace files to process for Burnin analysis")
            return attachment_results, burnin_analysis_results
        
        logging.debug(f"Processing {len(all_log_txt_files)} files for Burnin analysis")
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(self._process_single_file, file_path, attach_info): (file_path, attach_info)
                for file_path, attach_info in all_log_txt_files
            }
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        attach_name, burnin_data = result
                        self._handle_processing_result(attach_name, burnin_data, attachment_results, burnin_analysis_results)
                        
                except Exception as e:
                    file_path, attach_info = futures[future]
                    self._handle_processing_error(file_path, attach_info, e, attachment_results)
        
        return dict(attachment_results), burnin_analysis_results

    def _process_single_file(self, file_path: str, attach_info: Dict) -> Optional[Tuple[str, Dict]]:
        """Process a single file for Burnin analysis."""
        try:
            file_name = os.path.basename(file_path)
            logging.debug(f"[BURNIN] Analyzing file: {file_name}")
            
            # Check if it's a Burnin log
            is_burnin, reason = self.detect_log_type(file_path)
            logging.debug(f"[BURNIN] Detection result for {file_name}: {is_burnin} - {reason}")
            
            if is_burnin:
                # Process the Burnin log
                result = self.process_log(file_path)
                logging.debug(f"[BURNIN] Processing completed for {file_name}")
                return attach_info['document.file_name'], result
            else:
                logging.debug(f"[BURNIN] {file_name} - Not a Burnin log: {reason}")
                return None
                
        except Exception as e:
            logging.error(f"[BURNIN] Error processing {file_path}: {str(e)}")
            raise

    def _handle_processing_result(self, attach_name: str, burnin_data: Dict, 
                                attachment_results: Dict, burnin_analysis_results: List):
        """Handle successful Burnin processing result using the generic helper."""
        self._handle_generic_processing_result(
            attach_name=attach_name,
            data=burnin_data,
            attachment_results=attachment_results,
            analysis_results=burnin_analysis_results,
            result_key='burnin_result',
            log_display='Burnin Test Log'
        )

    def _handle_processing_error(self, file_path: str, attach_info: Dict, 
                               error: Exception, attachment_results: Dict):
        """Handle Burnin processing error using the generic error helper."""
        self._handle_common_processing_error(
            log_prefix='BURNIN',
            file_path=file_path,
            attach_info=attach_info,
            error=error,
            attachment_results=attachment_results
        )


def process_burnin_files():
    """Process burnin files using data from check_attachments.py"""
    selected_target = os.environ.get('GNAI_INPUT_BURNIN_TARGET', '').strip()
    all_log_txt_trace_files = load_all_log_txt_trace_files_from_temp()
    all_log_txt_trace_files = _filter_files_by_selected_target(all_log_txt_trace_files, selected_target, 'BURNIN')

    if not all_log_txt_trace_files:
        return {}, []

    burnin_processor = BurninLogProcessor()
    return burnin_processor.coordinate_batch_processing(all_log_txt_trace_files)


# ========================================================================================
#   PTAT Monitor CSV Log Processor
# ========================================================================================

class PTATLogProcessor(LogProcessor):
    """PTAT Monitor CSV log processor for GFX frequency and GT throttle analysis."""

    # Required headers are the minimum columns needed to identify and process a PTAT log.
    REQUIRED_HEADERS = [
        'Relative Time(mS)',
        'Gfx Component-Current Slice-Gfx Frequency(MHz)',
        'Turbo Parameters-Gt Clip Reason',
    ]

    # Required plot columns are the specific columns we want to visualize in the generated plot.

    # TO-DO: In the future, we will consider making some of these optional if giving the user a choice in interactive mode. 
    REQUIRED_PLOT_COLUMNS = [
        ('Gfx Component-Current Slice-Gfx Frequency(MHz)', '#00d2ff'),  # primary freq subplot
        ('Turbo Parameters-Gt Clip Reason',                '#ff4757'),  # GT clip binary fill subplot
        ('CPU-Info-P-Core Average Frequency(MHz)',         'purple'),
        ('CPU-Info-E-Core Average Frequency(MHz)',         'mediumpurple'),
        ('Power-IA Power(Watts)',                          'firebrick'),
        ('Power-GT Power(Watts)',                          'darkorange'),
        ('Power-Rest of Package Power(Watts)',             'goldenrod'),
        ('Power-Package Power(Watts)',                     'darkred'),
    ]

    OPTIONAL_PLOT_COLUMNS = []  # reserved for future plot series

    def detect_log_type(self, file_path: str) -> Tuple[bool, str]:
        if not file_path.lower().endswith('.csv'):
            return False, "Not a CSV file"
        try:
            with open(file_path, 'rb') as f:
                # Read enough bytes to cover the full header row.
                # PTAT CSVs have 50+ columns; in UTF-16 (2 bytes/char) a ~3000-char
                # header requires ~6000 bytes, so 4096 is not enough.  Use 16384 to
                # ensure the entire first line is captured regardless of encoding.
                raw = f.read(16384)
            if not raw:
                return False, "File is empty"

            # Try encodings in priority order; UTF-16 is common for Windows PTAT exports.
            encodings = ['utf-8-sig', 'utf-16', 'utf-16-le', 'utf-8', 'latin-1']
            if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                encodings = ['utf-16', 'utf-16-le'] + encodings

            for enc in encodings:
                try:
                    header_line = raw.decode(enc, errors='ignore').split('\n')[0]
                    missing = [col for col in self.REQUIRED_HEADERS if col not in header_line]
                    if not missing:
                        logging.debug(f"[PTAT] Detected as PTAT log with encoding {enc}")
                        return True, f"Found PTAT Log (encoding={enc})"
                except (UnicodeDecodeError, UnicodeError):
                    continue

            # Log what was actually in the header to help diagnose unexpected formats.
            try:
                first_line = raw.decode('utf-8', errors='replace').split('\n')[0]
                logging.debug(f"[PTAT] detect_log_type failed for {os.path.basename(file_path)}. "
                              f"Header (utf-8): {repr(first_line[:200])}")
            except Exception:
                pass
            return False, f"Missing PTAT columns (checked encodings: {encodings})"
        except Exception as e:
            return False, f"Error reading file: {str(e)}"

    def process_log(self, file_path: str) -> Dict:
        # Detect encoding first — PTAT Monitor can export as UTF-16 on Windows.
        _encoding = 'utf-8'
        try:
            with open(file_path, 'rb') as _f:
                _bom = _f.read(2)
            if _bom in (b'\xff\xfe', b'\xfe\xff'):
                _encoding = 'utf-16'
        except Exception:
            pass

        try:
            with open(file_path, 'r', encoding=_encoding, errors='ignore') as f:
                reader = csv_module.reader(f)
                headers = next(reader)

                try:
                    time_idx = headers.index('Relative Time(mS)')
                except ValueError as e:
                    return {'file_path': file_path, 'error': f"Column not found: {e}", 'processed': False}

                # Discover all plot columns uniformly from REQUIRED_PLOT_COLUMNS
                col_meta = []
                for col_name, color in self.REQUIRED_PLOT_COLUMNS + self.OPTIONAL_PLOT_COLUMNS:
                    try:
                        col_meta.append((headers.index(col_name), col_name, color))
                    except ValueError:
                        logging.warning(f"Required plot column not found in CSV: {col_name}")

                col_idx_map = {name: idx for idx, name, _ in col_meta}
                freq_idx = col_idx_map.get('Gfx Component-Current Slice-Gfx Frequency(MHz)')
                clip_idx = col_idx_map.get('Turbo Parameters-Gt Clip Reason')
                if freq_idx is None or clip_idx is None:
                    return {'file_path': file_path, 'error': "Required plot columns (freq/clip) missing from CSV", 'processed': False}

                # freq and clip are treated separately due to their different data types to other columns :
                #   freq → continuous numeric with avg line annotation
                #   clip → categorical string converted to binary fill with reason labels
                # All remaining columns are uniform numeric series fed into plot_series subplots.
                _dedicated = {freq_idx, clip_idx}
                series_meta = [(idx, name, color) for idx, name, color in col_meta if idx not in _dedicated]

                time_data, freq_data, clip_data = [], [], []
                col_data = [[] for _ in series_meta]

                for row in reader:
                    try:
                        t = float(row[time_idx]) / 1000.0  # ms -> seconds
                    except (ValueError, IndexError):
                        continue
                    try:
                        freq = float(row[freq_idx])
                    except (ValueError, IndexError):
                        freq = float('nan')
                    clip = row[clip_idx].strip() if clip_idx < len(row) else ''
                    time_data.append(t)
                    freq_data.append(freq)
                    clip_data.append(clip)
                    for i, (oi, _, _) in enumerate(series_meta):
                        try:
                            val = float(row[oi])
                        except (ValueError, IndexError):
                            val = float('nan')
                        col_data[i].append(val)

            if not time_data:
                return {'file_path': file_path, 'error': "No valid time data rows found", 'processed': False}

            plot_series = [
                (col_name, color, data)
                for (_, col_name, color), data in zip(series_meta, col_data)
            ]

            plot_path = self._generate_plot(file_path, time_data, freq_data, clip_data, plot_series)

            valid_freqs = [f for f in freq_data if not math.isnan(f)]
            clip_events = [(t, c) for t, c in zip(time_data, clip_data) if c]
            unique_clip_reasons = sorted(set(c for _, c in clip_events))

            return {
                'file_path': file_path,
                'log_type': 'ptat_csv',
                'processed': True,
                'ptat_result': {
                    'total_samples': len(time_data),
                    'duration_seconds': round(time_data[-1] - time_data[0], 2) if len(time_data) > 1 else 0,
                    'gfx_freq_stats': {
                        'min_mhz': round(min(valid_freqs), 1) if valid_freqs else None,
                        'max_mhz': round(max(valid_freqs), 1) if valid_freqs else None,
                        'avg_mhz': round(sum(valid_freqs) / len(valid_freqs), 1) if valid_freqs else None,
                    },
                    'gt_clip_events': len(clip_events),
                    'unique_clip_reasons': unique_clip_reasons,
                    'plot_path': plot_path,
                }
            }

        except Exception as e:
            return {
                'file_path': file_path,
                'error': f"Error processing PTAT log: {str(e)}",
                'processed': False
            }

    def _generate_plot(self, file_path: str, time_data: List, freq_data: List, clip_data: List, plot_series: list = None) -> Optional[str]:
        try:
            from matplotlib.ticker import AutoMinorLocator
            import matplotlib.patheffects as pe

            from utils.log_utils import get_sat_output_dir
            src_dir = os.getcwd()
            plots_dir = os.path.join(get_sat_output_dir(), 'PTAT_logs_plots')
            os.makedirs(plots_dir, exist_ok=True)

            original_file_name = os.path.splitext(os.path.basename(file_path))[0]
            prefix_match = re.match(r'^(\d+_)', original_file_name)
            stable_prefix = prefix_match.group(1) if prefix_match else ''
            base_file_name = re.sub(r'^\d+_', '', original_file_name)
            plot_file_name = f"{stable_prefix}{base_file_name}_ptat_plot.png"
            plot_path = os.path.join(plots_dir, plot_file_name)

            clip_indicator = [1 if c else 0 for c in clip_data]

            # --- Theme ---
            BG       = '#1a1a2e'
            PANEL    = '#16213e'
            GRID_CLR = '#2a2a4a'
            TEXT     = '#e0e0e0'
            ACCENT   = '#00d2ff'

            n_series = len(plot_series) if plot_series else 0
            n_plots = 2 + n_series
            height_ratios = [3] + [2] * n_series + [1.5]

            fig, axes = plt.subplots(n_plots, 1,
                                     figsize=(16, 2.5 * n_plots + 1.5),
                                     gridspec_kw={'height_ratios': height_ratios, 'hspace': 0.35})
            if n_plots == 1:
                axes = [axes]

            fig.patch.set_facecolor(BG)
            fig.suptitle(f'PTAT Analysis  ·  {base_file_name}',
                         fontsize=14, fontweight='bold', color=TEXT,
                         y=0.98, fontfamily='monospace')

            def style_ax(ax, ylabel, title):
                ax.set_facecolor(PANEL)
                ax.set_ylabel(ylabel, fontsize=9, color=TEXT, fontweight='semibold')
                ax.set_xlabel('Time (seconds)', fontsize=8, color=TEXT)
                ax.set_title(title, fontsize=9, color=ACCENT, loc='left', pad=4, fontweight='semibold')
                ax.tick_params(colors=TEXT, labelsize=8)
                ax.grid(True, linestyle=':', alpha=0.25, color=GRID_CLR)
                ax.xaxis.set_minor_locator(AutoMinorLocator(2))
                for spine in ax.spines.values():
                    spine.set_color(GRID_CLR)
                    spine.set_linewidth(0.5)

            ax_idx = 0

            # --- GFX Slice Frequency ---
            axes[ax_idx].fill_between(time_data, freq_data, alpha=0.15, color=ACCENT)
            axes[ax_idx].plot(time_data, freq_data, color=ACCENT, linewidth=0.9,
                              path_effects=[pe.Stroke(linewidth=1.8, foreground=ACCENT, alpha=0.3), pe.Normal()])
            valid_freqs = [f for f in freq_data if not math.isnan(f)]
            if valid_freqs:
                avg_freq = sum(valid_freqs) / len(valid_freqs)
                axes[ax_idx].axhline(avg_freq, color='#ffb347', linewidth=0.7, linestyle='--', alpha=0.7)
                axes[ax_idx].text(time_data[-1], avg_freq, f'  avg {avg_freq:.0f}',
                                  fontsize=7, color='#ffb347', va='center')
            style_ax(axes[ax_idx], 'MHz', 'GFX Slice Frequency')
            ax_idx += 1

            # --- Plot series (CPU freq, power channels) ---
            palette = ['#e056fd', '#a29bfe', '#ff6b6b', '#ffa502', '#eccc68', '#ff4757']
            if plot_series:
                for i, (label, _color, data) in enumerate(plot_series):
                    c = palette[i % len(palette)]
                    unit = 'Watts' if 'Power' in label else 'MHz'
                    axes[ax_idx].fill_between(time_data, data, alpha=0.10, color=c)
                    axes[ax_idx].plot(time_data, data, color=c, linewidth=0.8)
                    short_label = label.replace('CPU-Info-', '').replace('Power-', '').replace('(MHz)', '').replace('(Watts)', '').strip()
                    style_ax(axes[ax_idx], unit, short_label)
                    ax_idx += 1

            # --- GT Clip Reason ---
            axes[ax_idx].fill_between(time_data, clip_indicator, step='post', alpha=0.5,
                                      color='#ff4757', label='GT Clipped')
            axes[ax_idx].fill_between(time_data, clip_indicator, step='post', alpha=0.08,
                                      color='#ff4757')
            style_ax(axes[ax_idx], 'Clipped', 'GT Clip Reason')
            axes[ax_idx].set_yticks([0, 1])
            axes[ax_idx].set_yticklabels(['No', 'Yes'], fontsize=8, color=TEXT)
            axes[ax_idx].set_ylim([-0.05, 1.7])

            seen_reasons: set = set()
            label_idx = 0
            for t, c in zip(time_data, clip_data):
                if c and c not in seen_reasons:
                    y_offset = 1.12 + (label_idx % 2) * 0.18
                    axes[ax_idx].annotate(c, xy=(t, 1.0), xytext=(t, y_offset),
                                          fontsize=6, rotation=0, ha='center', va='bottom',
                                          color='#ff6b6b', annotation_clip=False,
                                          fontweight='semibold',
                                          path_effects=[pe.withStroke(linewidth=2, foreground=PANEL)])
                    seen_reasons.add(c)
                    label_idx += 1

            axes[ax_idx].set_xlim(left=time_data[0] if time_data else 0)

            # --- Duration + samples watermark ---
            if len(time_data) > 1:
                duration = time_data[-1] - time_data[0]
                fig.text(0.99, 0.005,
                         f'{len(time_data)} samples  ·  {duration:.1f}s',
                         fontsize=7, color=GRID_CLR, ha='right', fontfamily='monospace')

            plt.savefig(plot_path, dpi=180, bbox_inches='tight',
                        facecolor=fig.get_facecolor(), edgecolor='none')
            plt.close(fig)
            return plot_path

        except Exception as e:
            logging.error(f"[PTAT] Failed to generate plot for {file_path}: {e}")
            return None

    def coordinate_batch_processing(self, all_csv_files: List[Tuple]) -> Tuple[Dict, List]:
        attachment_results = defaultdict(list)
        ptat_analysis_results = []

        if not all_csv_files:
            logging.debug("No .csv files to process")
            return dict(attachment_results), ptat_analysis_results

        logging.debug(f"[PTAT] Processing {len(all_csv_files)} CSV files")

        # Process sequentially to avoid thread-safety issues with matplotlib.pyplot
        for file_path, attach_info in all_csv_files:
            try:
                result = self._process_single_file(file_path, attach_info)
                if result:
                    attach_name, ptat_data = result
                    self._handle_processing_result(
                        attach_name, ptat_data, attachment_results, ptat_analysis_results
                    )
            except Exception as e:
                self._handle_processing_error(file_path, attach_info, e, attachment_results)

        return dict(attachment_results), ptat_analysis_results

    def _process_single_file(self, file_path: str, attach_info: Dict) -> Optional[Tuple[str, Dict]]:
        try:
            file_name = os.path.basename(file_path)
            logging.debug(f"[PTAT] Analyzing file: {file_name}")
            is_ptat, reason = self.detect_log_type(file_path)
            logging.debug(f"[PTAT] Detection result for {file_name}: {is_ptat} - {reason}")
            if is_ptat:
                result = self.process_log(file_path)
                logging.debug(f"[PTAT] Processing completed for {file_name}")
                return attach_info.get('document.file_name', file_name), result
            else:
                logging.debug(f"[PTAT] {file_name} - Not a PTAT log: {reason}")
                return attach_info.get('document.file_name', file_name), {
                    'file_path': file_path,
                    'log_type': 'ptat_csv',
                    'processed': False,
                    'error': f"Not a PTAT log: {reason}",
                }
        except Exception as e:
            logging.error(f"[PTAT] Error processing {file_path}: {str(e)}")
            raise

    def _handle_processing_result(self, attach_name: str, ptat_data: Dict,
                                  attachment_results: Dict, ptat_analysis_results: List):
        if ptat_data and 'ptat_result' in ptat_data and 'error' not in ptat_data:
            ptat_analysis_results.append(ptat_data)
            file_name = os.path.basename(ptat_data.get('file_path', 'Unknown'))
            result = ptat_data['ptat_result']
            total_samples = result.get('total_samples', 0)
            gt_clip_events = result.get('gt_clip_events', 0)
            attachment_results[attach_name].append(
                f"{file_name} : PTAT CSV processed successfully "
                f"({total_samples} samples, {gt_clip_events} clip events)"
            )
        elif ptat_data and 'error' in ptat_data:
            ptat_analysis_results.append(ptat_data)
            error_msg = ptat_data.get('error', 'Unknown error')
            file_name = os.path.basename(ptat_data.get('file_path', 'Unknown'))
            attachment_results[attach_name].append(
                f"{file_name} : PTAT CSV Processing Failed - {error_msg}"
            )

    def _handle_processing_error(self, file_path: str, attach_info: Dict,
                                 error: Exception, attachment_results: Dict):
        self._handle_common_processing_error(
            log_prefix='PTAT',
            file_path=file_path,
            attach_info=attach_info,
            error=error,
            attachment_results=attachment_results,
        )


def process_ptat_files():
    """Process PTAT Monitor CSV files found in the workspace."""
    selected_target = os.environ.get('GNAI_INPUT_PTAT_TARGET', '').strip()
    from utils.log_utils import load_all_csv_files_from_temp
    all_csv_files = load_all_csv_files_from_temp()
    all_csv_files = _filter_files_by_selected_target(all_csv_files, selected_target, 'PTAT')
    if not all_csv_files:
        return {}, []
    ptat_processor = PTATLogProcessor()
    att_results, analysis_results = ptat_processor.coordinate_batch_processing(all_csv_files)
    return att_results, analysis_results


# ========================================================================================
#   Gfx PnP (GTMetrics) CSV Log Processor
# ========================================================================================

class GfxPnpLogProcessor(LogProcessor):
    """GTMetrics / Gfx PnP CSV log processor."""

    REQUIRED_HEADERS = [
        'Time[Sec]',
        'RenderFreqEffective[MHz]',
        'IaBias',
        'RenderBias',
        'MediaBias',
    ]

    PLOT_COLUMNS = [
        ('RenderFreqEffective[MHz]', 'MHz',  '#00d2ff'),
        ('IaBias',                   'Bias', '#e056fd'),
        ('RenderBias',               'Bias', '#ff6b6b'),
        ('MediaBias',                'Bias', '#ffa502'),
    ]

    def detect_log_type(self, file_path: str) -> Tuple[bool, str]:
        if not file_path.lower().endswith('.csv'):
            return False, "Not a CSV file"
        try:
            with open(file_path, 'rb') as f:
                raw = f.read(4096)
            if not raw:
                return False, "File is empty"

            encodings = ['utf-8-sig', 'utf-16', 'utf-16-le', 'utf-8', 'latin-1']
            if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                encodings = ['utf-16', 'utf-16-le'] + encodings

            for enc in encodings:
                try:
                    header_line = raw.decode(enc, errors='ignore').split('\n')[0]
                    missing = [col for col in self.REQUIRED_HEADERS if col not in header_line]
                    if not missing:
                        logging.debug(f"[GFXPNP] Detected as GfxPnP log with encoding {enc}")
                        return True, f"Found Gfx PnP Log (encoding={enc})"
                except (UnicodeDecodeError, UnicodeError):
                    continue

            return False, f"Missing GTMetrics columns (checked encodings: {encodings})"
        except Exception as e:
            return False, f"Error reading file: {str(e)}"

    def process_log(self, file_path: str) -> Dict:
        _encoding = 'utf-8'
        try:
            with open(file_path, 'rb') as _f:
                _bom = _f.read(2)
            if _bom in (b'\xff\xfe', b'\xfe\xff'):
                _encoding = 'utf-16'
        except Exception:
            pass

        try:
            with open(file_path, 'r', encoding=_encoding, errors='ignore') as f:
                reader = csv_module.reader(f)
                headers = next(reader)

                try:
                    time_idx = headers.index('Time[Sec]')
                except ValueError as e:
                    return {'file_path': file_path, 'error': f"Column not found: {e}", 'processed': False}

                col_meta = []
                for col_name, unit, color in self.PLOT_COLUMNS:
                    try:
                        col_meta.append((headers.index(col_name), col_name, unit, color))
                    except ValueError:
                        pass

                if not col_meta:
                    return {'file_path': file_path, 'error': "No plot columns found in headers", 'processed': False}

                time_data: List[float] = []
                series_data: List[List[float]] = [[] for _ in col_meta]

                for row in reader:
                    try:
                        t = float(row[time_idx])
                    except (ValueError, IndexError):
                        continue
                    time_data.append(t)
                    for i, (ci, _, _, _) in enumerate(col_meta):
                        try:
                            series_data[i].append(float(row[ci]))
                        except (ValueError, IndexError):
                            series_data[i].append(float('nan'))

            if not time_data:
                return {'file_path': file_path, 'error': "No valid time data rows found", 'processed': False}

            plot_series = [
                (col_name, unit, color, data)
                for (_, col_name, unit, color), data in zip(col_meta, series_data)
            ]

            plot_path = self._generate_plot(file_path, time_data, plot_series)

            # Build per-column stats
            col_stats = {}
            for col_name, _unit, _color, data in plot_series:
                valid = [v for v in data if not math.isnan(v)]
                if valid:
                    col_stats[col_name] = {
                        'min': round(min(valid), 2),
                        'max': round(max(valid), 2),
                        'avg': round(sum(valid) / len(valid), 2),
                    }

            return {
                'file_path': file_path,
                'log_type': 'gfxpnp_csv',
                'processed': True,
                'gfxpnp_result': {
                    'total_samples': len(time_data),
                    'duration_seconds': round(time_data[-1] - time_data[0], 2) if len(time_data) > 1 else 0,
                    'column_stats': col_stats,
                    'plot_path': plot_path,
                }
            }

        except Exception as e:
            return {
                'file_path': file_path,
                'error': f"Error processing Gfx PnP log: {str(e)}",
                'processed': False
            }

    def _generate_plot(self, file_path: str, time_data: List, plot_series: list) -> Optional[str]:
        try:
            from matplotlib.ticker import AutoMinorLocator
            import matplotlib.patheffects as pe

            from utils.log_utils import get_sat_output_dir
            src_dir = os.getcwd()
            plots_dir = os.path.join(get_sat_output_dir(), 'GfxPnp_logs_plots')
            os.makedirs(plots_dir, exist_ok=True)

            attachment_file_name = os.path.splitext(os.path.basename(file_path))[0]
            base_file_name = re.sub(r'^\d+_', '', attachment_file_name)
            plot_path = os.path.join(plots_dir, f"{attachment_file_name}_gfxpnp_plot.png")

            BG       = '#1a1a2e'
            PANEL    = '#16213e'
            GRID_CLR = '#2a2a4a'
            TEXT     = '#e0e0e0'

            n_plots = len(plot_series)
            if n_plots == 0:
                return None

            fig, axes = plt.subplots(n_plots, 1,
                                     figsize=(16, 2.5 * n_plots + 1.5),
                                     gridspec_kw={'hspace': 0.4})
            if n_plots == 1:
                axes = [axes]

            fig.patch.set_facecolor(BG)
            fig.suptitle(f'Gfx PnP Analysis  ·  {base_file_name}',
                         fontsize=14, fontweight='bold', color=TEXT,
                         y=0.98, fontfamily='monospace')

            for idx, (col_name, unit, color, data) in enumerate(plot_series):
                ax = axes[idx]
                ax.set_facecolor(PANEL)
                short_label = col_name.replace('[MHz]', '').replace('[%]', '').strip()
                ax.set_title(short_label, fontsize=9, color=color, loc='left', pad=4, fontweight='semibold')
                ax.set_ylabel(unit, fontsize=9, color=TEXT, fontweight='semibold')
                ax.set_xlabel('Time (seconds)', fontsize=8, color=TEXT)
                ax.tick_params(colors=TEXT, labelsize=8)
                ax.grid(True, linestyle=':', alpha=0.25, color=GRID_CLR)
                ax.xaxis.set_minor_locator(AutoMinorLocator(2))
                for spine in ax.spines.values():
                    spine.set_color(GRID_CLR)
                    spine.set_linewidth(0.5)

                ax.fill_between(time_data, data, alpha=0.15, color=color)
                ax.plot(time_data, data, color=color, linewidth=0.9,
                        path_effects=[pe.Stroke(linewidth=1.8, foreground=color, alpha=0.3), pe.Normal()])

                valid = [v for v in data if not math.isnan(v)]
                if valid:
                    avg_val = sum(valid) / len(valid)
                    ax.axhline(avg_val, color='#ffb347', linewidth=0.7, linestyle='--', alpha=0.7)
                    ax.text(time_data[-1], avg_val, f'  avg {avg_val:.1f}',
                            fontsize=7, color='#ffb347', va='center')

            if len(time_data) > 1:
                duration = time_data[-1] - time_data[0]
                fig.text(0.99, 0.005,
                         f'{len(time_data)} samples  ·  {duration:.1f}s',
                         fontsize=7, color=GRID_CLR, ha='right', fontfamily='monospace')

            plt.savefig(plot_path, dpi=180, bbox_inches='tight',
                        facecolor=fig.get_facecolor(), edgecolor='none')
            plt.close(fig)
            return plot_path

        except Exception as e:
            logging.error(f"[GfxPnp] Failed to generate plot for {file_path}: {e}")
            return None

    def coordinate_batch_processing(self, all_csv_files: List[Tuple]) -> Tuple[Dict, List]:
        attachment_results = defaultdict(list)
        analysis_results = []

        if not all_csv_files:
            logging.debug("No .csv files to process for GfxPnp")
            return dict(attachment_results), analysis_results

        logging.debug(f"[GfxPnp] Processing {len(all_csv_files)} CSV files")

        # Process sequentially to avoid thread-safety issues with matplotlib.pyplot
        for file_path, attach_info in all_csv_files:
            try:
                result = self._process_single_file(file_path, attach_info)
                if result:
                    attach_name, data = result
                    self._handle_processing_result(
                        attach_name, data, attachment_results, analysis_results
                    )
            except Exception as e:
                self._handle_processing_error(file_path, attach_info, e, attachment_results)

        return dict(attachment_results), analysis_results

    def _process_single_file(self, file_path: str, attach_info: Dict) -> Optional[Tuple[str, Dict]]:
        try:
            file_name = os.path.basename(file_path)
            logging.debug(f"[GfxPnp] Analyzing file: {file_name}")
            is_gfxpnp, reason = self.detect_log_type(file_path)
            logging.debug(f"[GfxPnp] Detection result for {file_name}: {is_gfxpnp} - {reason}")
            if is_gfxpnp:
                result = self.process_log(file_path)
                logging.debug(f"[GfxPnp] Processing completed for {file_name}")
                return attach_info.get('document.file_name', file_name), result
            else:
                logging.debug(f"[GfxPnp] {file_name} - Not a Gfx PnP log: {reason}")
                return None
        except Exception as e:
            logging.error(f"[GfxPnp] Error processing {file_path}: {str(e)}")
            raise

    def _handle_processing_result(self, attach_name: str, data: Dict,
                                  attachment_results: Dict, analysis_results: List):
        if data and 'gfxpnp_result' in data and 'error' not in data:
            analysis_results.append(data)
            file_name = os.path.basename(data.get('file_path', 'Unknown'))
            result = data['gfxpnp_result']
            total_samples = result.get('total_samples', 0)
            num_columns = len(result.get('column_stats', {}))
            attachment_results[attach_name].append(
                f"{file_name} : Gfx PnP CSV processed successfully "
                f"({total_samples} samples, {num_columns} stats columns)"
            )
        elif data and 'error' in data:
            error_msg = data.get('error', 'Unknown error')
            file_name = os.path.basename(data.get('file_path', 'Unknown'))
            attachment_results[attach_name].append(
                f"{file_name} : Gfx PnP CSV Processing Failed - {error_msg}"
            )

    def _handle_processing_error(self, file_path: str, attach_info: Dict,
                                 error: Exception, attachment_results: Dict):
        self._handle_common_processing_error(
            log_prefix='GfxPnp',
            file_path=file_path,
            attach_info=attach_info,
            error=error,
            attachment_results=attachment_results,
        )


def process_gfxpnp_files():
    """Process Gfx PnP (GTMetrics) CSV files found in the workspace."""
    selected_target = os.environ.get('GNAI_INPUT_GFXPNP_TARGET', '').strip()
    from utils.log_utils import load_all_csv_files_from_temp
    all_csv_files = load_all_csv_files_from_temp()
    all_csv_files = _filter_files_by_selected_target(all_csv_files, selected_target, 'GFXPNP')
    if not all_csv_files:
        return {}, []
    processor = GfxPnpLogProcessor()
    att_results, analysis_results = processor.coordinate_batch_processing(all_csv_files)
    return att_results, analysis_results


if __name__ == "__main__":
    # Parse positional argument for log type
    parser = argparse.ArgumentParser(description='Log File Analyzer for GOP, Burnin Test, and PTAT logs')
    parser.add_argument(
        'log_type',
        choices=['gop', 'burnin', 'ptat', 'gfxpnp'],
        help='Type of log analysis to perform: gop, burnin, ptat, or gfxpnp'
    )
    args = parser.parse_args()
    
    try: 
        # ------------------------------------------------------------------------------------
        #    Run only the requested log analysis
        # ------------------------------------------------------------------------------------
        
        workspace = os.environ.get('GNAI_TEMP_WORKSPACE', '.')
        
        if args.log_type == 'gop':
            # Process GOP files only
            log_attachment_results, gop_analysis_results = process_gop_files()
            
            # Merge GOP results
            gop_success = merge_log_results_to_attachment_info(
                log_type='gop',
                log_results=gop_analysis_results,
                workspace=workspace
            )
            if not gop_success:
                logging.warning("GOP merge into attachment_info failed")
            
            # Output GOP results only
            output = {
                "gop_analysis_results": gop_analysis_results
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
            
        elif args.log_type == 'burnin':
            # Process Burnin files only
            burnin_attachment_results, burnin_analysis_results = process_burnin_files()
            
            # Merge Burnin results
            burnin_success = merge_log_results_to_attachment_info(
                log_type='burnin',
                log_results=burnin_analysis_results,
                workspace=workspace
            )
            if not burnin_success:
                logging.warning("Burnin merge into attachment_info failed")
            
            # Output Burnin results only (cleaned up format)
            output = {
                "burnin_analysis_results": []
            }
            
            for result in burnin_analysis_results:
                if 'burnin_result' in result and 'events' in result['burnin_result']:
                    clean_result = {
                        "file_path": result['file_path'],
                        "log_type": result.get('log_type', 'burnin_test'),
                        "processed": result.get('processed', True),
                        "events": result['burnin_result']['events']
                    }
                    output["burnin_analysis_results"].append(clean_result)
            
            print(json.dumps(output, indent=2, ensure_ascii=False))

        elif args.log_type == 'ptat':
            # Process PTAT CSV files only
            ptat_attachment_results, ptat_analysis_results = process_ptat_files()

            # Merge PTAT results
            ptat_success = merge_log_results_to_attachment_info(
                log_type='ptat',
                log_results=ptat_analysis_results,
                workspace=workspace
            )
            if not ptat_success:
                logging.warning("PTAT merge into attachment_info failed")

            # Output PTAT results
            output = {"ptat_analysis_results": []}

            for result in ptat_analysis_results:
                if result.get('processed') and 'ptat_result' in result:
                    pr = result['ptat_result']
                    output["ptat_analysis_results"].append({
                        "file_path": result['file_path'],
                        "log_type": result.get('log_type', 'ptat_csv'),
                        "processed": True,
                        "total_samples": pr.get('total_samples'),
                        "duration_seconds": pr.get('duration_seconds'),
                        "gfx_freq_stats": pr.get('gfx_freq_stats'),
                        "gt_clip_events": pr.get('gt_clip_events'),
                        "unique_clip_reasons": pr.get('unique_clip_reasons'),
                        "plot_path": pr.get('plot_path'),
                    })
                else:
                    output["ptat_analysis_results"].append({
                        "file_path": result.get('file_path', 'unknown'),
                        "log_type": result.get('log_type', 'ptat_csv'),
                        "processed": False,
                        "error": result.get('error', 'PTAT processing failed'),
                    })

            ptat_json_path = os.path.join(workspace, "ptat_results.json")
            with open(ptat_json_path, 'w', encoding='utf-8') as _f:
                json.dump(output, _f, indent=2, ensure_ascii=False)
            print(f"PTAT JSON saved to: {ptat_json_path}")

            # Human-readable summary for sighting_assistant context
            lines = ["\n=== PTAT Analysis Summary ==="]
            processed = [r for r in output["ptat_analysis_results"] if r.get("processed")]
            failed = [r for r in output["ptat_analysis_results"] if not r.get("processed")]
            for r in processed:
                fname = os.path.basename(r.get("file_path", "unknown"))
                freq = r.get("gfx_freq_stats") or {}
                clips = r.get("gt_clip_events", 0)
                reasons = ", ".join(r.get("unique_clip_reasons") or []) or "None"
                dur = r.get("duration_seconds", 0)
                samples = r.get("total_samples", 0)
                plot = r.get("plot_path", "N/A")
                lines.append(f"\nFile: {fname}")
                lines.append(f"  Duration: {dur}s  |  Samples: {samples}")
                lines.append(f"  GFX Slice Freq: Min={freq.get('min_mhz')} MHz  Max={freq.get('max_mhz')} MHz  Avg={freq.get('avg_mhz')} MHz")
                lines.append(f"  GT Clip Events: {clips}  |  Clip Reasons: {reasons}")
                lines.append(f"  Plot: {plot}")
                if clips > 0:
                    lines.append(f"  Status: THROTTLING DETECTED — {clips} clip events ({reasons})")
                else:
                    lines.append("  Status: No throttling detected")
            for r in failed:
                fname = os.path.basename(r.get("file_path", "unknown"))
                lines.append(f"\nFile: {fname} — FAILED: {r.get('error', 'unknown error')}")
            if processed:
                total_clips = sum(r.get("gt_clip_events", 0) for r in processed)
                all_reasons = sorted(set(reason for r in processed for reason in (r.get("unique_clip_reasons") or [])))
                lines.append(f"\nSummary: {len(processed)} file(s) processed, {len(failed)} failed")
                lines.append(f"  Total GT clip events across all files: {total_clips}")
                if all_reasons:
                    lines.append(f"  All clip reasons: {', '.join(all_reasons)}")
                lines.append("  Classification: " + (
                    "Sustained throttle" if total_clips > 100 else
                    "Intermittent throttle" if total_clips > 0 else
                    "No throttle"
                ))
            print("\n".join(lines))

        elif args.log_type == 'gfxpnp':
            # Process Gfx PnP (GTMetrics) CSV files only
            gfxpnp_attachment_results, gfxpnp_analysis_results = process_gfxpnp_files()

            gfxpnp_success = merge_log_results_to_attachment_info(
                log_type='gfxpnp',
                log_results=gfxpnp_analysis_results,
                workspace=workspace
            )
            if not gfxpnp_success:
                logging.warning("GfxPnp merge into attachment_info failed")

            output = {"gfxpnp_analysis_results": []}

            for result in gfxpnp_analysis_results:
                if result.get('processed') and 'gfxpnp_result' in result:
                    gr = result['gfxpnp_result']
                    output["gfxpnp_analysis_results"].append({
                        "file_path": result['file_path'],
                        "log_type": result.get('log_type', 'gfxpnp_csv'),
                        "processed": True,
                        "total_samples": gr.get('total_samples'),
                        "duration_seconds": gr.get('duration_seconds'),
                        "column_stats": gr.get('column_stats'),
                        "plot_path": gr.get('plot_path'),
                    })
                else:
                    output["gfxpnp_analysis_results"].append({
                        "file_path": result.get('file_path', 'unknown'),
                        "log_type": result.get('log_type', 'gfxpnp_csv'),
                        "processed": False,
                        "error": result.get('error', 'GfxPnP processing failed'),
                    })

            gfxpnp_json_path = os.path.join(workspace, "gfxpnp_results.json")
            with open(gfxpnp_json_path, 'w', encoding='utf-8') as _f:
                json.dump(output, _f, indent=2, ensure_ascii=False)
            print(f"GfxPnP JSON saved to: {gfxpnp_json_path}")

            # Human-readable summary for sighting_assistant context
            lines = ["\n=== GfxPnP Analysis Summary ==="]
            processed = [r for r in output["gfxpnp_analysis_results"] if r.get("processed")]
            failed = [r for r in output["gfxpnp_analysis_results"] if not r.get("processed")]
            for r in processed:
                fname = os.path.basename(r.get("file_path", "unknown"))
                dur = r.get("duration_seconds", 0)
                samples = r.get("total_samples", 0)
                plot = r.get("plot_path", "N/A")
                col_stats = r.get("column_stats") or {}
                lines.append(f"\nFile: {fname}")
                lines.append(f"  Duration: {dur}s  |  Samples: {samples}")
                for col, stats in col_stats.items():
                    short = col.replace('[MHz]', '').replace('[%]', '').strip()
                    lines.append(f"  {short}: Min={stats.get('min')}  Max={stats.get('max')}  Avg={stats.get('avg')}")
                lines.append(f"  Plot: {plot}")
            for r in failed:
                fname = os.path.basename(r.get("file_path", "unknown"))
                lines.append(f"\nFile: {fname} — FAILED: {r.get('error', 'unknown error')}")
            lines.append(f"\nSummary: {len(processed)} GfxPnP file(s) processed, {len(failed)} failed")
            print("\n".join(lines))

    except Exception as e:
        # Output error as JSON for tool compatibility
        log_type_key = f"{args.log_type}_analysis_results" if hasattr(args, 'log_type') else "error_analysis_results"
        error_output = {
            "error": str(e),
            log_type_key: []
        }
        print(json.dumps(error_output, indent=2))
        import traceback
        logging.error("Error processing files: %s", traceback.format_exc())
