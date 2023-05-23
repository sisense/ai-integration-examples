import sys
sys.path.append('../utils/')
import re
import pandas as pd
import SisenseAPI
import requests
import urllib.parse
import json
from dateutil import parser
import os
from datetime import datetime

# *****************************************************************************************
#       Class for all sisense API, holds sisense connection object and responsible 
#       for all needed API calls. Responsible for different utilities that are shared
#       between different notebooks (such as generate html output based on pandas dataframe)
#       Also holds time logger and query logger, that holds the execution logs.
# ****************************************************************************************** 
class AIUtils:
    def __init__(self, inputWidgetId:str, model_name:str, additional_parameters:dict, cookie:str, is_token_cookie:bool = False):
        """
        Create AIUtils class
        @param inputWidgetId: string, widget id
        @param model_name: string, model name to connect to
        @param additional_parameters: dict, the notebook parameters
        @param cookie: string, sisense user authentication token
        @param is_token_cookie: bool, determine authentication type
        return: AIUtils class
        """
            
        # Remove escape chacter from additional_parameters
        if 'question' in additional_parameters:
            additional_parameters['question'] = ""
        additional_parameters = json.dumps(additional_parameters)
        
        self.sisense_conn = SisenseAPI.SisenseAPI(cube_name=model_name, additional_parameters=additional_parameters, is_token_cookie=False, sisense_user_authentication_token=cookie)
        
        self.time_log = []        
        self.query_log = []
        self.inputWidgetId = inputWidgetId
        # log file location for remote develop
        self.log_update_file_path = "/opt/sisense/storage/branding/BloxAI/"+inputWidgetId+".html"
        # log file location for local develop
        # if not os.path.exists("../logs"):
        #     os.makedirs("../logs")
        # self.log_update_file_path = os.path.join(os.getcwd(), '../logs', inputWidgetId + ".html")

    
# *****************************************************************************************
#   dynamic log functionality     
# ****************************************************************************************** 

    def add_time(self,message:str):
        """
        add message with timestamp to time log
        """
        self.time_log.append([message,datetime.now().strftime("%H:%M:%S.%f")])
        
        
    def add_to_query_log(self,query_request:str, query_response:str, is_from_cache:str, index:int = None):
        """
        add query data to the end of query log, if index given, insert in index
        """
        if index:
            self.query_log[index] = [query_request,query_response,is_from_cache]
        else:
            self.query_log.append([query_request,query_response,is_from_cache])
    
    def write_text_to_log_updates(self, text:str):
        """
        write text to log file
        """
        with open(self.log_update_file_path, "wt") as f:
            f.write(text)            
            
    def get_query_log_size(self):
        """
        return the size of query log
        """
        return len(self.query_log)
    
    def get_query_log(self):
        """
        return query log
        """
        return self.query_log
    
    def get_time_log(self):
        """
        return time log
        """
        return self.time_log
    
    def write_log_updates(self):
        """
        write query log to log file
        """
        with open(self.log_update_file_path, "wt") as f:
            f.write(self.df_to_html_table(pd.DataFrame(data=self.query_log,columns=['Query','Response','Caching'])))
    
# *****************************************************************************************
#   Sisense API functionality     
# ******************************************************************************************    
    
    def run_jaql(self, jaql:dict, model_name:str):
        """
        run jaql via Sisense API
        """
        return self.sisense_conn.run_jaql(jaql, model_name)
    
    def create_relation(self, datamodelId:str, relation:str):
        """
        create relation between two columns via Sisense API
        """
        relation_path = '/api/v2/datamodels/' + datamodelId + "/schema/relations"        
        res = self.sisense_conn.call_api('POST',relation_path, payload=relation)
        return res.text
    
    def get_model(self, model_name:str):
        """
        return model schema corresponding to model_name 
        """
        param = {"title": model_name}
        res = self.sisense_conn.call_api('GET','/api/v2/datamodels/schema?'+urllib.parse.urlencode(param))
        model = json.loads(res.text)
        return model
    
    def get_all_models(self):  
        """
        return all models schema 
        """
        res = self.sisense_conn.call_api('GET','/api/v2/datamodels/schema?fields=title')
        models = json.loads(res.text) 
        return models
    
    def get_all_dashboards_for_model(self, model_name:str):
        """
        return all dashboards connected to model  
        """
        param = {"datasourceTitle": model_name}
        res = self.sisense_conn.call_api('GET','/api/v1/dashboards?'+urllib.parse.urlencode(param))
        dashboards = json.loads(res.text)
        return dashboards
    
    def get_all_widgets_for_dashboard(self, dashboard_oid:str):
        """
        return all widgets within dashboard  
        """
        res = self.sisense_conn.call_api('GET','/api/v1/dashboards/'+dashboard_oid+'/widgets')        
        widgets = json.loads(res.text)
        return widgets
    
    def get_dashboard_title(self, doid:str): 
        """
        return dashboard title for dashboard with oid 
        """
        res = self.sisense_conn.call_api('GET','/api/v1/dashboards/'+doid)
        dashboard = json.loads(res.text)
        dashboard_name = dashboard['title']
        return dashboard_name
    
    
    def get_widget_type_and_title(self, doid:str, woid:str):
        """
        return widget type and title for widget with oid and dashboard oid  
        """
        res = self.sisense_conn.call_api('GET','/api/v1/dashboards/'+doid+'/widgets/'+woid)
        widget = json.loads(res.text)
        wtype = widget['type']
        widget_title = widget['title']
        return wtype, widget_title

    
    def get_configuration(self, key:str):
        """
        return configuration for key  
        """
        return self.sisense_conn.get_configuration(key=key)
                         
    def get_relation_schema(self, relation:str, model:dict):
        """
        build a relation schema based on column ids (in relation)  
        """
        relation_ids = relation.split(':')
        datasetId_1, tableId_1 = self.find_dataset_and_table_id(model,relation_ids[0])
        datasetId_2, tableId_2 = self.find_dataset_and_table_id(model,relation_ids[1])
        relation_schema = {
            "columns": [
                {
                    "dataset": datasetId_1,
                    "table": tableId_1,
                    "column": relation_ids[0],
                },
                {
                    "dataset": datasetId_2,
                    "table": tableId_2,
                    "column": relation_ids[1],
                }            
            ]
        }
        return relation_schema
    
    def publish_model(self,model_name:str, datamodelId:str):  
        """
        publish live model  
        """
        build_path = '/api/v2/builds'
        build_payload = {
            "datamodelId": datamodelId,
            "buildType": "publish",
            "rowLimit": 0
        }
        res = self.sisense_conn.call_api('POST',build_path, payload=build_payload)
        print(f"model: {model_name} was publish \nstatus: {res}")

        self.add_time('after publish model')

    def delete_table(self, model: dict, table_name: str):
        """
        delete table with table_name
        """
        for i in range(len(model['datasets'])):
            table_schema = model['datasets'][i]['schema']['tables']
            for table in table_schema:
                if table['name'] == table_name:
                    datamodelId = model['oid']
                    datasetId = model['datasets'][i]['oid']
                    delete_path = '/api/v2/datamodels/' + datamodelId + '/schema/datasets/' + datasetId + '/tables/' + \
                                  table['oid']
                    res = requests.delete(self.sisense_conn.sisense_base_url + delete_path,
                                          headers=self.sisense_conn.headers)
                    print(f"table: {table_name} was deleted \npath {delete_path}\nstatus: {res}")
                    return res
    
    
    def create_table_with_query(self, model:dict, sql_import_query:str, table_name:str, types:list, df_result_keys:list):
        """
        create table from sql_import_query  
        """
        datamodelId = model['oid']
        datasetId = model['datasets'][0]['oid']
        
        sub_path = '/api/v2/datamodels/' + datamodelId + '/schema/datasets/' + datasetId + '/tables'
        new_table = {
            "id": table_name,
            "name": table_name,
            "columns": [
            ],
            "configOptions": {
                "importQuery": sql_import_query
            },
            "type": "base"
        }
        k = 0
        for i in df_result_keys:
            k+=1
            id = 'COLUMN' + str(k)
            cell = {
                "id": id,
                "name": i,
                "type": int(types[k-1]),
                "isCustom": False,
            }
            new_table['columns'].append(cell)
        res = self.sisense_conn.call_api('POST',sub_path, payload=new_table)
        print(f"table: {table_name} was created \nstatus: {res}")

        self.add_time('after create table')
        
    
# *****************************************************************************************
#  utils functionality     
# ****************************************************************************************** 

    def get_all_tables_info_for_model(self, model_name:str):
        """
        returns all tables info in model.
        tables is a list of Sisense tables
        table_to_oid is a dict with table names as keys, 
        values are dict with column names as keys and column oid as values
        """
        model = self.get_model(model_name)        
        datamodelId = model['oid']
        datasetId = model['datasets'][0]['oid']
        
        model_desc = ""
        tables = []
        table_to_oid = {}
        
        for dataset in model['datasets']: 
            for table_schema in dataset['schema']['tables']:         
                table_d = { "name":  table_schema['name'] }
                column_vec = []
                model_desc += table_schema['name']+": " 
                table_to_oid[table_schema['name']] = {}
                for column_schema in table_schema['columns']:
                    model_desc += column_schema['name'] + ", " 
                    column_vec.append(column_schema['name'])
                    table_to_oid[table_schema['name']][column_schema['name']] =  column_schema['oid']
                model_desc = model_desc[0:-2] + ".\n"
                table_d['columns'] = column_vec
                tables.append(table_d)
            
        return tables, model_desc, table_to_oid
    
    def find_dataset_and_table_id(self, model, column_oid):
        """
        returns table oid and dataset oid which contain column corresponding to column oid       
        """
        for dataset in model['datasets']: 
            datasetId = dataset['oid']

            for table_schema in dataset['schema']['tables']:            
                table_oid = table_schema['oid']
                for column in table_schema['columns']:
                    if column['oid'] == column_oid:
                        return datasetId, table_oid
                
    def get_column_index_in_jaql(self, jaql, cname, qtype):  
        """
        identify the index of the requested column in jaql
        """
        for index, column_data in enumerate(jaql['metadata']):
            if qtype in [2]:
                # extracting column names by column/dim for table jaqls   
                if 'column' in column_data['jaql']:
                    if column_data['jaql']['column'] == cname:
                        return index
                elif 'dim' in column_data['jaql']:
                    dim = column_data['jaql']['dim']
                    # remove unwanted charecters from'[table_name.column_name]' 
                    dim = re.search(r'\[(.*?)\]', dim).group(1)           
                    if dim.split('.')[1] == cname:
                        return index
            # extracting column names by title for widget jaqls                
            if qtype in [4]:
                if 'title' in column_data['jaql']:
                    if column_data['jaql']['title'] == cname:
                        return index
        return -1
    
    def get_import_query(self, df_result: pd.DataFrame, model:dict, types:list):
        """
        create import query for values in df_result, column types presented in types list
        implemented both for snowflake and redshift dialects
        """
        keys = df_result.keys()       
        is_snowflake_model = False
        sql_import_query = ""
        new_row = ""
        end_query =""       
        is_snowflake_model = model['datasets'][0]['connection']['provider'] == 'SnowflakeJDBC'
        if is_snowflake_model:
            sql_import_query = 'select * from ( values '
            new_row = '('
            end_query = '), '
        else:
            sql_import_query = 'select * from (  '
            new_row = "select "
            end_query = '\nunion all \n'
            
        for index, row in df_result.iterrows():
            k = 0
            sql_import_query += new_row
            for i in keys:
                val = row[i]
                val = re.sub('\'','\\\'',str(val))
                val_fin = ', '
                if index == 0 and not is_snowflake_model:
                    val_fin = ' as \"' + i + '\", '
                val_out = '\''+str(val)+'\''+ val_fin
                if types[k] == "8":
                    try:
                        val = int(re.compile("(\d+)").match(val).group(1))
                    except:
                        print ("Fail on #" + str(val)+"#")
                    val_out = str(val)+val_fin
                if types[k] == "31":
                    try:
                        val = parser.parse(val)
                        if is_snowflake_model:
                            val_out = 'to_date(\''+str(val)+'\')'+val_fin
                        else:
                            val_out = 'to_date(\''+str(val)+'\', \'yyyy-MM-DD HH:MI:SS\', FALSE)'+val_fin
                    except:
                        print ("Fail on #" + str(val)+"#")
                        val_out = 'NULL\,'

                sql_import_query += val_out
                k+=1
            sql_import_query = sql_import_query[:-2]
            sql_import_query += end_query
        sql_import_query = sql_import_query[:-(len(end_query)-1)]
        sql_import_query += ')'

        print (sql_import_query)
        self.add_time('after building query')
        return sql_import_query

        
    def get_output_widget_jaql(self, table_name:str, types:list, df_result_keys:list):
        """
        create widget jaql based on df_result_keys and types
        """
        widget_pararm = []
        k = 0
        for i in df_result_keys:
            k+=1
            dim = "[" + table_name + "." + str(i) + ']'
            datatype = "text"
            jaql =  {
                "jaql": 
                    {
                        "column": i,
                        "datatype": datatype,
                        "dim":   dim,
                        "table": table_name,
                        "title": i 
                    }
                }
            if int(types[k-1]) == 31:
                jaql['jaql']['datatype'] = "datetime"
                jaql['jaql']['level'] = "days"
            widget_pararm.append(jaql)
        widget_pararm_str =  json.dumps(widget_pararm, indent=4)
        self.add_time('after prepare auto widget')
        return widget_pararm_str
    
# *****************************************************************************************
#   generate html output functionality     
# ******************************************************************************************  

    def df_to_html_table(self,df: pd.DataFrame):
        """
        create html table out of DataFrame 
        """        
        s = df.style
        css_alt_rows = 'background-color: powderblue; color: black;'
        css_indexes = 'background-color: steelblue; color: white; padding: 30px'
        s.set_properties(**{'white-space': 'pre-wrap',})
        s.set_table_styles([
            {'selector': 'tr:nth-child(even)', 'props': css_alt_rows},
            {'selector': 'th', 'props': css_indexes},
            {"selector": "", "props": [("border", "1px solid grey")]},
            {"selector": "tbody td", "props": [("border", "1px solid grey")]},
            {"selector": "th", "props": [("border", "1px solid grey"),("padding", "20px")]}
        ])
        s.hide(axis="index")
        return s.to_html()
    
    def generate_html_result(self, response:str, df_result:pd.DataFrame, table_title:str=""):
        """
        create dataframe with html result 
        """  
        self.add_time('Last')
        html = table_title       
        html += self.df_to_html_table(df_result)
        tspd = pd.DataFrame(data=self.get_time_log(), columns=['Log','time'])
        html += "<br><br><H2>AI Request response</H2><br>"
        html += self.df_to_html_table(pd.DataFrame(data=self.get_query_log(),columns=['Query','Response','Caching']))
        html += "<br><H2>Timing Log</H2><br>"
        html += self.df_to_html_table(tspd)
        data = [html]
        if len(response)>0:
#             data.append(re.sub(r'\n',r'<br>',response))
            data.append(response)
        df_result = pd.DataFrame(data=data, columns=['output']) 
        return df_result
