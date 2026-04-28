import os
import sys
import requests
from requests_kerberos import HTTPKerberosAuth
import certifi
from gnai.client import GnaiClient, GnaiChatFile
import pprint
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

print(f"The issue that was assigned to the HSD :{str(os.environ['GNAI_INPUT_CATEGORY'])}")
checklist_prompt = str(os.environ['GNAI_INPUT_CHECKLIST_PROMPT'])
print(f"The checklist prompt that is sent to the gnai client :{checklist_prompt}")
script_dir = os.path.dirname(os.path.abspath(__file__))
checklist_filepath= os.path.join(script_dir, "artifacts/DFD_Checklist.doc")
client = GnaiClient(os.environ['INTEL_USERNAME'], os.environ['INTEL_PASSWORD'])
file = GnaiChatFile(path = checklist_filepath)
response = client.chat.ask_question(checklist_prompt, profile='public', files=[file])
print(f"The response of answer that was assigned to the HSD :{response.answer}")
