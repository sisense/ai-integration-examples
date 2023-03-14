import sys
import os
path = os.path.dirname(__file__)
sys.path.append(path)
import requests
import json
import inspect
import pandas as pd
from custom_code_notebooks.utils import customcode_errors as err
import re


# ************************************************************
#       Class for Sisense API connection
# ************************************************************

class SisenseAPI:

    def __init__(self, jaql_internal_flag=True, sisense_user_authentication_token=None, is_token_cookie=False,
                 schema_id=None, query_building_cube=False, query_max_row_count=-1,
                 cube_name=None, additional_parameters=None):
        self.sisense_base_url = 'http://' + os.environ['API_GATEWAY_EXTERNAL_SERVICE_HOST'] + ':' + os.environ['API_GATEWAY_EXTERNAL_SERVICE_PORT']
        self.jaql_internal_flag = jaql_internal_flag
        self.schema_id = schema_id
        self.query_building_cube = query_building_cube
        # Attribute query_max_row_count, if set, serves as the upper bound of parameter count
        # in get_logical_sql. This allows SQL queries to force run on a small sample data
        # of the model -- for example, to speed up the inference of the output schema.         
        self.query_max_row_count = query_max_row_count
        self.cube_name = cube_name
        self.output_path = None
        self.add_param = json.loads(additional_parameters) if additional_parameters else None
        if sisense_user_authentication_token is None:
            cookie = os.getenv("Cookie").replace(" ", "")
            self.headers = {'Cookie': cookie}
            # include X-XSRF-TOKEN in the headers
            self.set_xsrf_token_header(cookie)
        elif not is_token_cookie:
             self.headers = {'authorization': 'Bearer ' + sisense_user_authentication_token}
        else:
             self.headers = {'Cookie':sisense_user_authentication_token}

    def set_xsrf_token_header(self, cookie):
        """
        Extract the XSRF-TOKEN from the cookie and set it as X-XSRF-TOKEN header.
        For more details on this Double Submit Cookie technique, 
        see https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html#double-submit-cookie
        """
        xsrf_cookie_name = 'XSRF-TOKEN'
        xsrf_header_name = 'X-XSRF-TOKEN'

        match = re.search(xsrf_cookie_name + '=([^;]+)', cookie)
        if match:
            self.headers[xsrf_header_name] = match.group(1)
                
    def set_parameters(self, cube_name=None, additional_parameters=None, output_path=None):
        if cube_name:
            self.cube_name = cube_name
        if additional_parameters:
            self.add_param = json.loads(additional_parameters)
        if output_path:
            self.output_path = output_path
        
    def call_api(self, http_method, url_suffix, params=None, payload=None, headers=None):
        if headers is None:
            headers = self.headers
        if payload:
            headers['Content-Type'] = 'application/json'
            if 'jaql' in url_suffix and self.jaql_internal_flag:
                headers['Internal'] = 'true'
            elif 'jaql' in url_suffix and self.jaql_internal_flag == False:
                headers['Internal'] = 'false'
        url = self.sisense_base_url + url_suffix

        response = None
        data = None
        if http_method == 'GET':
            response = requests.get(url, params=params, headers=headers)
        elif http_method == 'POST':
            data = json.dumps(payload, indent=2)
            try:
                response = requests.post(url, data=data, params=params, headers=headers, timeout=350)
            except Exception as ex:
                print('request url-> {0}\nrequest body-> {1}'.format(str(response.request.url),
                                                                     str(response.request.body)))
                print('-Fail- Machine Unresponsive\Stuck {0} on: {1}-> {2}'.format(url_suffix, inspect.stack()[1][3], ex))
        return response

    def call_api_custom(self, http_method, api_url, url_suffix, params=None, payload=None):
        headers = self.headers
        if payload:
            headers['Content-Type'] = 'application/json'
        url = api_url + url_suffix
        response = None
        data = None
        if http_method == 'GET':
            response = requests.get(url, params=params, headers=headers)
        elif http_method == 'POST':
            data = json.dumps(payload, indent=2)
            response = requests.post(url, data=data, params=params, headers=headers)
        return response

    def login(self, email, password):
        payload = {
            "username": email,
            "password": password
        }
        res = self.call_api('POST', '/api/v1/authentication/login', params=None, payload=payload)
        if res.reason == 'OK' and res.status_code == 200:
            token = json.loads(res.text)
            return token['access_token']
        else:
            print('-Fail- connected with {0} via api/v1/authentication/login'.format(email))
        return None
    
    def token(self, email, password):
        """ Get user authentication token via email and password"""
        return self.login(email, password)

    def get_system_secret(self):
        try:
            url_suffix = '/api/settings/security'
            result = self.call_api('GET', url_suffix, params=None, payload=None)
            return json.loads(result.text)["secret"]
        except Exception as ex:
            print('-Fail- execute {0} on: {1}-> {2}'.format(url_suffix, inspect.stack()[1][3], ex))

    def get_user_id(self, username):
        try:
            url_suffix = '/api/v1/users'
            params = {"userName": username}
            result = self.call_api('GET', url_suffix, params=params, payload=None)
            return json.loads(result.text)[0]["_id"]
        except Exception as ex:
            print('-Fail- execute {0} on: {1}-> {2}'.format(url_suffix, inspect.stack()[1][3], ex))

    def run_jaql(self, jaql_body, cube_name):
        try:
            url_suffix = '/api/datasources/{}/jaql'.format(cube_name)
            result = self.call_api('POST', url_suffix, params=None, payload=jaql_body)
            return result
        except Exception as ex:
            print('-Fail- execute {0} on: {1}-> {2}'.format(url_suffix, inspect.stack()[1][3], ex))
            return None
        
    def get_elasticubes_servers(self, withPermissions=False):
        try:
            url_suffix = '/api/elasticubes/servers'
            params = {"withPermissions": withPermissions}
            result = self.call_api('GET', url_suffix, params=params, payload=None)
            return json.loads(result.text)[0]
        except Exception as ex:
            print('-Fail- execute {0} on: {1}-> {2}'.format(url_suffix, inspect.stack()[1][3], ex))
            
    def get_logical_sql(self, query, cube_name, query_building_cube=None, count=None):
        try:
            if query_building_cube is None:
                query_building_cube = self.query_building_cube
            url_suffix = '/api/datasources/{}/sql'.format(cube_name)
            params = {"query": query}
            if query_building_cube and self.schema_id is not None:
                params = {"query": query, "queryBuildingCube": query_building_cube, "schemaId": self.schema_id}

            # if query_max_row_count is set, greater than -1, and smaller than count,
            # use it as count
            if count is None: count = -1
            max_count = self.query_max_row_count
            if max_count is None: max_count = -1
            if (max_count > -1) and (count == -1 or max_count < count):
                count = max_count

            params["count"] = count
            result = self.call_api('GET', url_suffix, params=params, payload=None)
            return json.loads(result.text)
        except Exception as ex:
            print('-Fail- execute {0} on: {1}-> {2}'.format(url_suffix, inspect.stack()[1][3], ex))
            
    def get_configuration(self, partition='custom-code', key=None):
        try:
            url_suffix = '/app/configuration/configurations/service/{}'.format(partition)
            result = self.call_api('GET', url_suffix)
            partition_json = json.loads(result.text)
            if key != None:
                return partition_json['service'][key]
            return partition_json['service'];        
        except Exception as ex:
            print('-Fail- execute {0} on: {1}-> {2}'.format(url_suffix, inspect.stack()[1][3], ex))

    def get_data_from_cube(self, table_name, columns=None, count=-1, df_columns_names=None, cube_name=None):
        try:
            if not cube_name:
                cube_name = self.cube_name
            columns_statement = '*'
            if columns:
                new_columns = []
                for item in columns:
                     new_columns.append(f'T.[' + item + ']')
                columns_statement = ', '.join(new_columns)

            logical_sql = (f'SELECT {columns_statement}\n'
                           f'FROM [{table_name}] as T')
            print("SQL Statement:\n" + logical_sql)

            logical_sql_res = self.get_logical_sql(query=logical_sql,
                                                           cube_name=cube_name,
                                                           count=count)
            if "error" in logical_sql_res:
                raise err.CustomCodeException(*err.ERROR_IN_LOGICAL_SQL, description=logical_sql_res.get("details"))

            sql_results = logical_sql_res['values']
            df_result = pd.DataFrame(sql_results, columns=logical_sql_res['headers'])
            if df_columns_names:
                df_result.rename(columns=df_columns_names, inplace=True)
            return df_result
        except Exception as ex:
            print('-Fail- execute {0} on: {1}'.format("get_data_from_cube", ex))
            raise

    def get_data(self):
        columns_dict = {}
        for i in self.add_param.keys():
            if "table" in self.add_param[i]:
                if self.add_param[i]["table"] not in columns_dict:
                    columns_dict[self.add_param[i]["table"]] = []
                if "column" in self.add_param[i]:
                    columns_dict[self.add_param[i]["table"]].append(self.add_param[i]["column"])

        df_dict = {}
        for i in columns_dict.keys():
           df_dict[i] = self.get_data_from_cube(i, columns_dict[i])

        return df_dict

    def get_logical_sql_Big(self, query, cube_name, query_building_cube=None, count=None):
        try:
            if query_building_cube is None:
                query_building_cube = self.query_building_cube
            if not cube_name:
                cube_name = self.cube_name
                
            url_suffix = '/api/datasources/{}/sql'.format(cube_name)
            params = {"query": query}
            if query_building_cube and self.schema_id is not None:
                params = {"query": query, "queryBuildingCube": query_building_cube, "schemaId": self.schema_id}
           
            offset = 0
            count = 1000000
            reading  = True
            import dask.dataframe as dd
            import pandas as pd
            import uuid
            
            mode='w'
            
            path = self.output_path + '/query-' + uuid.uuid4().hex + '.csv'
            index = 0
            while(reading):
                
                params["count"] = count
                params["offset"] = offset
                print('offset = ' + str(offset) + '  count = ' + str(count) + '  index = ' + str(index))
                res = (self.call_api('GET', url_suffix, params=params, payload=None)).json()
                values = res["values"]
             
                index = index + 1
                if not values:
                    break
                df_result = pd.DataFrame(values, columns=res['headers'])
               
                df_result.to_csv(path,mode=mode ,index=False)
                mode='a'
                if len(values) < count:
                    break
                offset = offset + count

            df_result =  dd.read_csv(urlpath=path,blocksize=None)   
            
            return df_result
        except Exception as ex:
            print('-Fail- execute {0} on: {1}-> {2}'.format(url_suffix, inspect.stack()[1][3], ex))
            import traceback
            traceback.print_exception(type(ex), ex, ex.__traceback__)
            
    def get_my_user_details(self):
        try:
            url_suffix = '/api/users/loggedin'
            result = self.call_api('GET', url_suffix)
            return json.loads(result.text)
        except Exception as ex:
            print('-Fail- execute {0} on: {1}-> {2}'.format(url_suffix, inspect.stack()[1][3], ex))
            raise

    def get_ipy_nb_name(self):
        """
        Reference: https://forums.fast.ai/t/jupyter-notebook-enhancements-tips-and-tricks/17064/39
        Returns the short name of the notebook w/o .ipynb
        or get a FileNotFoundError exception if it cannot be determined
        NOTE: works only when the security is token-based or there is also no password
        """
        from notebook import notebookapp
        import ipykernel, ntpath

        connection_file = os.path.basename(ipykernel.get_connection_file())
        kernel_id = connection_file.split('-', 1)[1].split('.')[0]
        for srv in notebookapp.list_running_servers():
            try:
                if srv['token'] == '' and not srv['password']:  # No token and no password, ahem...
                    response = requests.get(srv['url'] + 'api/sessions')
                else:
                    response = requests.get(srv['url'] + 'api/sessions?token=' + srv['token'])

                sessions = response.json()
                for sess in sessions:
                    if sess['kernel']['id'] == kernel_id:
                        nb_path = sess['notebook']['path']
                        return ntpath.basename(nb_path).replace('.ipynb', '')  # handles any OS
            except:
                pass  # There may be stale entries in the runtime directory
        raise FileNotFoundError("Can't identify the notebook name")

    def load_additional_parameters(self, cube_name=None, table_name=None):
        """
        Load the additional parameters of the custom code table using this Jupyter notebook.

            Parameters:
                cube_name (str): Cube name. If not specified, the method will attempt to load the value from the class.
                table_name (int): Table name. Required only when the model has more than one table using this notebook.

            Returns:
                additional_parameters (str): additional parameters. String is returned to be compatible with set_parameters()
        """
        try:
            if not cube_name:
                cube_name = self.cube_name

            # retrieve select details on tables from the ECM GraphQL API
            url_suffix = '/api/v2/ecm/'
            payload = {
                "query": "query elasticubeByTitle($title: String!, $server: String!) {elasticube: elasticubeByTitle("
                         "title: $title, server: $server) {...ecData} } fragment ecData on Elasticube { oid title "
                         "datasets { schema { tables { oid id name type lastUpdated customCode { noteBookId "
                         "additionalParameters codePath cellsDisable language mode timeout } } } } }",
                "variables": {"title": cube_name, "server": "LocalHost"},
                "operationName": "elasticubeByTitle"
            }

            response = self.call_api(http_method='POST', url_suffix=url_suffix, payload=payload)

            response_dict = json.loads(response.text)
            if response.status_code != 200:
                raise Exception('Status Code {0} - {1}'.format(response.status_code, response_dict['message']))

            if 'errors' in response_dict:
                raise Exception(response_dict['errors'][0]['error']['message'])

            datasets = response_dict['data']['elasticube']['datasets']

            nb_name = self.get_ipy_nb_name()
            params_dict = {}

            # iterate through the custom code tables and collect additional params into a dictionary
            for dataset in datasets:
                table = dataset['schema']['tables'][0]
                # if table_name is specified, match it with the current table
                if table_name and table_name != table['name']:
                    continue

                customCode = table['customCode']
                if customCode is not None:
                    # make sure the custom code table has a matching notebook name
                    if nb_name != customCode['noteBookId']:
                        continue
                    params_dict[table['name']] = customCode['additionalParameters']

            dict_size = len(params_dict)
            if dict_size == 1:
                # find exactly one custom code table, return it
                table_name = list(params_dict.keys())[0]
                additional_parameters = json.dumps(list(params_dict.values())[0])
                print(
                    '-SUCCESS- execute {0}: "{1}" is used by custom code table "{2}" with the following parameters:'.format(
                        inspect.stack()[0][3], nb_name, table_name))
                print(additional_parameters)
                return additional_parameters
            elif dict_size > 1:
                # find more than one custom code table, ask the user to specify table_name
                table_names = '"' + '", "'.join(list(params_dict.keys())) + '"'
                raise Exception(
                    'Notebook "{0}" is used by {1} custom code tables: {2}. To avoid ambiguity, please specify '
                    'table_name explicitly in your call of load_additional_parameters().'.format(
                        nb_name, dict_size, table_names))
            elif dict_size == 0 and table_name:
                # specified table_name not found
                raise Exception(
                    'Notebook "{0}" is not used by custom code table "{1}" in the "{2}" model.'.format(nb_name,
                                                                                                       table_name,
                                                                                                       cube_name))
            else:
                # no custom code table found
                raise Exception(
                    'Notebook "{0}" is not used by any custom code table in the "{1}" model.'.format(nb_name,
                                                                                                     cube_name))

        except Exception as ex:
            print('-FAILURE- execute {0}: {1}'.format(inspect.stack()[0][3], ex))
