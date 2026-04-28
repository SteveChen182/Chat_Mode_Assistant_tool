import json
import os
import re
from typing import Any, Union

def search_keyword(keywords_list: list, data_rows: list):
    """
    Search for keywords in all HSD fields. 

    Args:
        keywords_list (list): List of keywords to search for in the HSD.
        data_rows (list): The list of HSD fields.
 
    Returns:
        tuple: (bool, list) - True if keywords found with list of found keywords, 
               otherwise False with empty list.
    """
    import re
    
    # Input validation
    if not keywords_list or not data_rows:
        return False, []
    
    if not isinstance(keywords_list, list) or not isinstance(data_rows, list):
        return False, []
    
    if len(data_rows) == 0:
        return False, []
    
    keywords_found = []
    data_rows_dict = data_rows[0] 
    
    # Ensure data_rows_dict is a dictionary
    if not isinstance(data_rows_dict, dict):
        return False, []
    
    for keyword in keywords_list:
        if not keyword:  # Skip empty keywords
            continue
            
        keyword_str = str(keyword).lower()
        found = False
        
        # Search in dictionary values
        for key, value in data_rows_dict.items():
            if value is not None:
                value_str = str(value).lower()
                # Use word boundary search for better matching
                pattern = re.compile(r'\b' + re.escape(keyword_str) + r'\b', re.IGNORECASE)
                if pattern.search(value_str):
                    found = True
                    break
        
        # Search in dictionary keys if not found in values
        if not found:
            for key in data_rows_dict.keys():
                if key is not None:
                    key_str = str(key).lower()
                    pattern = re.compile(r'\b' + re.escape(keyword_str) + r'\b', re.IGNORECASE)
                    if pattern.search(key_str):
                        found = True
                        break
        
        if found and keyword not in keywords_found:
            keywords_found.append(keyword)
    
    return len(keywords_found) > 0, keywords_found

def search_in_fields(keywords_list: list, data_fields: list, data_rows: list):
    """
    Search for keywords in specific HSD fields.

    Args:
        keywords_list (list): List of keywords to search for.
        data_fields (list): List of specific data fields to search in.
        data_rows (list): The list of HSD fields.
        
    Returns:
        tuple: (bool, list) - (keywords_found_flag, keywords_found)
    """
    import re
    
    # Input validation
    if not keywords_list or not data_fields or not data_rows:
        return False, []
    
    if not all(isinstance(arg, list) for arg in [keywords_list, data_fields, data_rows]):
        return False, []
    
    if len(data_rows) == 0:
        return False, []
    
    keywords_found = []
    data_rows_dict = data_rows[0]
    
    if not isinstance(data_rows_dict, dict):
        return False, []
    
    for field in data_fields:
        if not field:
            continue
            
        field_value = data_rows_dict.get(field)
        
        # Skip empty/missing fields silently - this is expected
        if field_value is None or not str(field_value).strip():
            continue
            
        field_content = str(field_value)
        
        for keyword in keywords_list:
            if not keyword:
                continue
                
            keyword_str = str(keyword)
            
            try:
                pattern = re.compile(r'\b' + re.escape(keyword_str) + r'\b', re.IGNORECASE)
                if pattern.search(field_content):
                    if keyword not in keywords_found:
                        keywords_found.append(keyword)
            except re.error:
                continue
    
    return len(keywords_found) > 0, keywords_found
