import os
import sys
from hsdes import HSDESAPI
import logging
import json
logging.basicConfig(level = logging.INFO, format = '%(asctime)s - %(levelname)s - %(message)s', stream = sys.stdout)
import re


# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

if __name__ == "__main__":
    hsd = HSDESAPI()
    id = int(os.environ['GNAI_INPUT_ID'])
    status, data = hsd.similarity_search(id)


    try:
        if status:
            print(f"HSDs that are similar to HSD {id} are :")
            combined_output = {"sighting_similarity_search_output": data}
            output = json.dumps(combined_output,indent =2)
            print(output)
        else:
            print(f"[FAIL] Similarity Search by id failed for the HSD ID {id}")
    except json.JSONEncodeError as e:
        print(f"[ERROR] Failed to format response data as JSON: {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error occurred: {e}")
    
