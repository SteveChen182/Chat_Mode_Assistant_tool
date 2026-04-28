##########################
# HSDES REST API https://hsdes-api.intel.com/rest/doc/
# HSDES Python API https://wiki.ith.intel.com/display/HSDESWIKI/Python
##########################
import os
import threading
import requests
from requests_kerberos import HTTPKerberosAuth, OPTIONAL
import json
import urllib3

urllib3.disable_warnings()
# Note : All API calls use (verify = False) rather than (verify = certipath) to bypass intel's internal certificates verification 
proxy = {'http': '', 'https': ''}

class HSDESAPI:
    # ------------------------------------------------------------------------------------
    #    __init__()
    #        FUNCTION： constructor，define data members, generate input and output folder if doesn't exist
    #        IN: None
    #        RETURN: None
    # ------------------------------------------------------------------------------------
    def __init__(self):
        self.id = 0
        self.attachments = [] #Keep the attachment file names and delete them when exiting.
        self._session_local = threading.local()
        self._sessions = []
        self._sessions_lock = threading.Lock()

    def _build_session(self):
        session = requests.Session()
        session.verify = False
        session.auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)
        session.headers.update({'Content-type': 'application/json'})
        session.proxies.update(proxy)
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
        session.mount('https://', adapter)
        return session

    def _get_session(self):
        session = getattr(self._session_local, 'session', None)
        if session is None:
            session = self._build_session()
            self._session_local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    def __del__(self):
        while self.has_attachment():
            file_path = self.attachments.pop()
            if os.path.exists(file_path):
                os.remove(file_path) #Remove downloaded attachments when exiting. 
        for session in getattr(self, '_sessions', []):
            try:
                session.close()
            except Exception:
                pass

    def has_attachment(self):
        if len(self.attachments) > 0:
            return True
        else:
            return False

    def read_article_by_id(self, id):
        self.id = id
        
        url = 'https://hsdes-api.intel.com/rest/article/'+str(id)
        response = self._get_session().get(url)
        if (response.status_code == 200):
            if 'application/json' in response.headers.get('Content-Type'):
                try:
                    data = response.json()['data']
                except KeyError:
                    # Handle cases where 'data' key is missing
                    print("Unexpected Error: data is missing.\n")
                    pass
                return True, data
            else:
                # Handle non-JSON responses
                print('Error: Response content is not in JSON format.')
                return False, None
    
        else:
            print(f"HTTP Error {response.status_code}")
            return False, None


    def get_artical_children(self, id, subject):
        url = 'https://hsdes-api.intel.com/rest/article/{}/children'.format(id)
        payload = {'tenant':'ip_sw_graphics', 'child_subject':subject }
        response = self._get_session().get(url, params=payload)
        if (response.status_code == 200):
            if 'application/json' in response.headers.get('Content-Type'):
                try:
                    data = response.json()['data']
                except KeyError:
                    # Handle cases where 'data' key is missing
                    print("Unexpected Error: data is missing.\n")
                    pass
                return True, data 
            else:
                # Handle non-JSON responses
                print('Error: Response content is not in JSON format.')
                return False, None
    
        else:
            print(f"HTTP Error {response.status_code}")
            return False, None


    def get_attachments_list(self, hsd_id):
        success, attachments = self.get_artical_children(hsd_id, 'attachment') 
        if success is True:
            return attachments
        else:
            return None


    def get_comments_list(self, hsd_id):
        success, comments = self.get_artical_children(hsd_id, 'comment') 
        if success is True:
            return comments
        else:
            return None


    def download_attachment(self, file_name, file_id):
        url = 'https://hsdes-api.intel.com/rest/binary/' + file_id
        response = self._get_session().get(url, stream=True)
        if (response.status_code == 200):
            self.attachments.append(file_name)
            with open(file_name, "wb") as w:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        w.write(chunk)
        else:
            print(f"HTTP Error {response.status_code}")
            return

    def update_article(self, article_id, subject, tenant, update_field, update_field_content):
    # ------------------------------------------------------------------------------------
    #    update_article()
    #        FUNCTION： This is a generic method to update an article ( can be an article as well as a attachment)
    #        IN: article id, subject, tenant, update_field (field that needs to be updated), update_field_content (new value of the field)
    #        RETURN: True if update was successful. Otherwise False. 
    # ------------------------------------------------------------------------------------
        # Description : This is a generic method to update an article ( can be an article as well as a attachment)
        # 1. Inputs :Get the article id, subject, tenant, update_field (field that needs to be updated), update_field_content (new value of the field)
        # 2. Update the required field  
        url = f'https://hsdes-api.intel.com/rest/article/{article_id}?fetch=false&debug=false'
        payload_dict = {
            "subject": subject, 
            "tenant": tenant,
            "fieldValues": [ 
                { 
                    update_field: update_field_content 
                },
                { 
                    "send_mail": "false" 
                }
            ]
        }
        
        # Convert to JSON string
        payload = json.dumps(payload_dict)
        response = self._get_session().put(url, data=payload)
        
        if (response.status_code == 200):
            print(f'[SUCCESS]: The field {update_field} was updated to {update_field_content} in the article {article_id}')
            return True
        else:
            print(f"HTTP Error {response.status_code}")
            return False


    def read_article_by_id_select_fields(self, id):
        self.id = id
        
        url = 'https://hsdes-api.intel.com/rest/article/'+str(id)


        #https://hsdes-api.intel.com/rest/article/15018275324?fields=id%2Ctitle
        payload = {'fields': '''id, 
        title,
        tenant,
        component, 
        component_affected, 
        platform_affected, 
        test_name,
        description, 
        to_reproduce,
        regression,
        regression_build_label,
        is_regression,
        internal_summary,
        attachments,
        reason,  
        bug.fix_description,
        bug.closed_reason, 
        bug.to_reproduce, 
        status,
        bug.reproducibility,
        ip_sw_graphics.bug.form_factor,
        from_release,
        status_reason,
        subject,
        ip_sw_graphics.bug.media_rtl_release,
        ip_sw_graphics.bug.game_release_date'''
        }


        response = self._get_session().get(url, params=payload)

        if (response.status_code == 200):
            if 'application/json' in response.headers.get('Content-Type'):
                try:
                    data = response.json()['data']
                except KeyError:
                    # Handle cases where 'data' key is missing
                    print("Unexpected Error: data is missing.\n")
                    pass
                return True, data
            else:
                # Handle non-JSON responses
                print('Error: Response content is not in JSON format.')
                return False, None
    
        else:
            print(f"HTTP Error {response.status_code}")

    def retrieve_article_ids_from_query(self, id):
        """
        Retrieves article IDs from an HSDES query execution.
        
        Args:
            id (str/int): HSDES query execution ID
        
        Returns:
            tuple: (success_bool, list_of_article_ids or None)
        """
        
        self.id = id
        
        url = f'https://hsdes-api.intel.com/rest/query/execution/{id}?include_text_fields=Y&start_at=1&fields=id&include_query_fields=Y'
        
        try:
            response = self._get_session().get(url)
            
            # Check HTTP status
            if response.status_code != 200:
                print(f"HTTP Error {response.status_code}: {response.reason}")
                return False, None
            
            # Check content type
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' not in content_type:
                print(f'Error: Expected JSON response, got {content_type}')
                return False, None
            
            # Parse JSON response
            try:
                response_data = response.json()
            except ValueError as e:
                print(f"Error: Invalid JSON response - {e}")
                return False, None
            
            # Extract data
            if 'data' not in response_data:
                print("Error: 'data' field missing from response")
                return False, None
            
            data = response_data['data']
            
            # Handle empty results
            if not data:
                print("Warning: Query returned no results")
                return True, []
            
            # Extract IDs more efficiently
            ids_from_query = [item['id'] for item in data if 'id' in item]
            
            # Validate results
            if len(ids_from_query) != len(data):
                missing_ids = len(data) - len(ids_from_query)
                print(f"Warning: {missing_ids} items missing 'id' field")
            
            print(f"Successfully retrieved {len(ids_from_query)} article IDs")
            return True, ids_from_query
            
        except requests.exceptions.ConnectionError:
            print("Error: Connection failed - check network connectivity")
            return False, None
        except requests.exceptions.RequestException as e:
            print(f"Error: Request failed - {e}")
            return False, None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False, None



    def similarity_search(self, id):
        """
        Retrieves article details (id,title) that are similar to a HSD ID.
        
        Args:
            id (str/int): HSDES query execution ID
        
        Returns:
            dict: In the format of {id:title} 
        """
        
        self.id = id
        url = f'https://hsdes-api.intel.com/rest/similarity/similar/{id}/elastic'

        try:
            response = self._get_session().get(url)
            
            # Check HTTP status
            if response.status_code != 200:
                print(f"HTTP Error {response.status_code}: {response.reason}")
                return False, None
            
            # Check content type
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' not in content_type:
                print(f'Error: Expected JSON response, got {content_type}')
                return False, None
            
            # Parse JSON response
            try:
                response_data = response.json()
                
            except ValueError as e:
                print(f"Error: Invalid JSON response - {e}")
                return False, None
            
            # Extract data
            if 'data' not in response_data:
                print("Error: 'data' field missing from response")
                return False, None
            
            data = response_data['data']
            
            # Check if data is empty before processing
            if not data:
                print("Warning: Query returned no results")
                return True, {}
            
            sub_data = {}
            for item in data:
                sub_data[item['id']] = {"title": item['title'], "score": item['score']}
            
            #print(f"Successfully retrieved similar articles related to {id}")
            return True, sub_data
            
        except requests.exceptions.ConnectionError:
            print("Error: Connection failed - check network connectivity")
            return False, None
        except requests.exceptions.RequestException as e:
            print(f"Error: Request failed - {e}")
            return False, None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False, None
