import os
import sys
from hsdes import HSDESAPI
import json
from concurrent.futures import ThreadPoolExecutor
# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

#hsd_info_file = os.environ['GNAI_INPUT_HSD_INFO_FILE']

hsd_info_file = "hsd_info_file" 

if __name__ == "__main__":
    hsd = HSDESAPI()
    hsd_id = int(os.environ['GNAI_INPUT_ID'])

    # Retreiving only necessary fields.
    with ThreadPoolExecutor(max_workers=2) as executor:
        article_future = executor.submit(hsd.read_article_by_id_select_fields, hsd_id)
        comments_future = executor.submit(hsd.get_comments_list, hsd_id)

        article_result = article_future.result()
        if isinstance(article_result, tuple) and len(article_result) == 2:
            success, data_rows = article_result
        else:
            success, data_rows = False, []

        comments = comments_future.result()

    # write output to a file
    file_output = os.path.join(os.environ['GNAI_TEMP_WORKSPACE'], f'{hsd_info_file}')

    # Combined output
    combined_output = {
        "output": {
            "hsd_info_file" : file_output,
            "data_rows": data_rows,
            "comments": comments
        }
    }


    output = json.dumps(combined_output)

    try:
        with open(file_output, 'w', encoding='utf-8') as f:
            f.write(output)
            hsd_info_file = file_output
        print(output)
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
