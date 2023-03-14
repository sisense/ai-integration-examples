import sys
sys.path.append('../utils/')
import json
import pandas as pd
import threading
import re
import numpy as np
from AIQueries import AIQueries
import InferenceQuestionType as question_type
from InferenceQuestionType import QType

# ************************************************************
#       Class for OpenAI integration, contains different  
#       functionalities to parse, submit and process requests 
# ************************************************************ 

class AIIntegration:
    def __init__(self, utils):       
        self.utils = utils
        self.ai_queries = AIQueries(utils)
        
# *****************************************************************************************
#   question type functionality     
# ****************************************************************************************** 
    def get_elements(self, model_name, prompt, options, to_validate_entities_from_question=True):
        """build jaql(s) for the requested question.
           contains several steps:
           1. given a prompt [orig_question] detect the relevant question type
           2. based on the detected question type, extract all relevant entities in the question (dashboard name/ widget name..)
           3. match the extracted entities to their proper sisense objects (dashboard, widget, table, column..)
           4. build jaql(s) for the requested widget(s)
           
           In case of request of single widget - will return [jaql, additional info].
           In case of multiple widgets (via dashboard summary) - will return [{widget_oid:[jaql, additional info]}, additional info] 
           additional info can be [dashboard name,dashboard oid,widget name,widget oid] or column name (depends on the question type)
        """
        
#       get question type object
        question_type_object = self.get_question_type_object(prompt, options, to_validate_entities_from_question)
#       extract data entities from prompt (dashboard name/ widget name..)
        question_type_object.extract_data_entities_from_prompt(prompt)      
#       get corresponding entities from sisense
        question_type_object.map_data_entities_to_sisense_elements(model_name)      
#       get jaql(s) based in the question type
        [jaql,info] = question_type_object.get_jaql_from_elements() 
        
        return [jaql, info, question_type_object]            


    def get_question_type(self, number_type: str, to_validate_entities_from_question:str = True):
        """
        map between question type number (as string) to type of inference question object
        """        
        question_class=None
        if number_type == QType.TypeDashboardWidget:
            question_class = question_type.InferenceDashboardWidget(self.ai_queries, self.utils, to_validate_entities_from_question)
        elif number_type == QType.TypeColumnTable:
            question_class = question_type.InferenceColumnTable(self.ai_queries, self.utils, to_validate_entities_from_question)
        elif number_type == QType.TypeDashboardWidgetColumn:
            question_class = question_type.InferenceDashboardWidgetColumn(self.ai_queries, self.utils, to_validate_entities_from_question)
        elif number_type == QType.TypeDashboard:
            question_class = question_type.InferenceDashboard(self.ai_queries, self.utils, to_validate_entities_from_question)
        elif number_type == QType.TypeModelDashboardWidget:
            question_class = question_type.InferenceModelDashboardWidget(self.ai_queries, self.utils, to_validate_entities_from_question)
        elif number_type == QType.TypeModelDashboard:
            question_class = question_type.InferenceModelDashboard(self.ai_queries, self.utils, to_validate_entities_from_question)
        else:
            question_class = question_type.InferenceUnknown(self.ai_queries, self.utils, to_validate_entities_from_question)
 
        return question_class

    def detect_question_type(self, prompt:str, options:list)->str:
        """
        detect question type by asking AI model
        use few shot samples to provide examples for training        
        """
        question = "Select type for the sentence:\n"
        few_shot_samples = []
        for i in options:
            few_shot_samples+= self.get_question_type(str(i)).few_shot_samples      

        question += " ".join(few_shot_samples)

        question += "Sentence: "+ prompt + "\n Type: "            

        print (f"question used for question type inference: \n{question}")

        self.utils.add_time('Before ai define pattern')
        response = self.ai_queries.ask_ai_with_cache('model_queries',question)
        self.utils.add_time('After ai define pattern')
        
        self.utils.write_log_updates()
        qtype = response['choices'][0]['text']
        print(f"detected question type is: \n{qtype}")
        return qtype
        
    def get_question_type_object(self, prompt:str, options:list, to_validate_entities_from_question:bool):
        """
        returns the most relevant question type object based on prompt and options
        """ 
        if to_validate_entities_from_question:
            qtype = self.detect_question_type(prompt, options)                   
            question_type_object = self.get_question_type(qtype, to_validate_entities_from_question)
        else:
            qtype = options[0] 
            question_type_object = self.get_question_type(str(qtype), to_validate_entities_from_question)
        return question_type_object
    
    
# *****************************************************************************************
#   ai queries manager functionality    
# ******************************************************************************************
              
    def ask_ai_in_batch_mode(self, prompt_vec: list):
        """
        send and recieve requests to GPT, in batch mode, prompt vector is the question texts 
        """ 
        counter_lock = threading.Lock()
        printer_lock = threading.Lock()
        print ("------------------------- Ask in batch mode -------------------------")
        global counter 
        counter = 0
        responses = []
        def worker():
            global counter
            i = 0
            with counter_lock:
                i = counter
                counter += 1
                self.utils.add_time('before ai ' + str(i))
            response = self.ai_queries.ask_ai_with_cache('cachefile',prompt_vec[i])
            with counter_lock:
                self.utils.add_time('after ai ' + str(i))
                responses.append(response)
            with printer_lock:
                print('The end of %d' % counter)

        with printer_lock:
            print('Starting up')

        worker_threads = []
        for i in range(len(prompt_vec)):
            t = threading.Thread(target=worker)
            worker_threads.append(t)
            t.start()
        for t in worker_threads:
            t.join()

        with printer_lock:
            print('Finishing up')
            
        return responses
    
    def check_for_parsing_errors(self, res_text:str, df_result:pd.DataFrame):
        """
        validate GPT response and check known errrors 
        """
        question_too_long_error = "less than the minimum of 0 - 'max_tokens'"
        abort = False
        if question_too_long_error in res_text:
            abort = True
            print("Recieved error - question too long --> abort")
            df_result.iloc[0]="Recieved error - question too long --> abort"

        elif df_result.columns.values[0] == 'Could not parse result':
            abort = True
            print("Could not parse result --> abort")
            df_result.iloc[0]="Could not parse result --> abort" 
        return abort, df_result
    
    def combine_responses_in_batch_mode(self, prompt_vec:list, responses:list, num_item_per_split: int):  
        """
        combine GPT responses to a single dataframe 
        """
        print ("------------------------- Combine all answers -------------------------")
        values_witout_answer =[]   
        df_with_answer = []
        abort = False
        for i in range(0, len(prompt_vec)):
            res_text = responses[i]['choices'][0]['text']            
            df_result = self.ai_queries.clean_json_response(res_text)
            if len(df_result)==1:
                # could not parse result 
                prompt = prompt_vec[i]        
                values_witout_answer += prompt.split('\n')[2:num_item_per_split+2]
            else:      
                df_with_answer.append(df_result)

        #  if all responses contain errors - present it to the user
        if len(df_with_answer)==0:
            abort, df_result = self.check_for_parsing_errors(res_text, df_result)

        # now merge all dataframe with results 
        if len(df_with_answer)>1:
            df_result = df_with_answer[0]
            for i in range(1, len(df_with_answer)):
                r = df_with_answer[i]
                equal_key = True       
                if len(df_result.keys()) == len(r.keys()):
                    for i in range(0,len(df_result.keys())):
                        if r.keys()[i] != df_result.keys()[i]:
                            equal_key = False
                            print("rename - " + df_result.keys()[i] + " " + r.keys()[i] )
                            r.rename(columns={r.keys()[i]:df_result.keys()[i]},inplace=True)
                    df_result = pd.concat([df_result,r])
                else:
                    print("DataFrames with diffrenet size answer skip it")

            df_result = df_result.reset_index(drop=True) 
            print("didn't got answer for the values: \n"+", \n".join(values_witout_answer))
            
        print (f"result for combine all responses: \n{df_result}")
        return abort, df_result
    
# *****************************************************************************************
#   suggest relation functionality    
# ******************************************************************************************

    def get_question_for_suggest_relation(self, tables:dict, table_name:str):
        """
        create question to AI model for relation suggestion
        """
        question = "The following json vector represnt tables and their columns:\n" + \
        json.dumps(tables, indent=4)
        question += "\nBetween which columns I should create relationship to table \""+table_name+"\"?\nPlease output in JSON format"
        question += " with this structure: [{\"table1\":\"table_name\",\"table2\":\"table_name\", \"column1\":\column_name\", \"column2\":\"column_name\"}]\n\n"
        return question
    
    def get_table_columns_names(self, tables_schema:dict, table_name:str):
        """
        return the names of all columns in table 
        """
        for table in tables_schema:
            if table_name==table['name'].lower():
                return [column_name.lower() for column_name in table['columns']]
        return []
    
    def validate_columns_exist_in_tables(self, df_result:pd.DataFrame, tables, table_name):
        """
        check that columns exist in tables - remove suggestions with miss match  
        """
        index_to_remove = []
        for index, row in df_result.iterrows():       
            for i in range(1,3):
                suffix=str(i)
                table_name = row['table'+suffix].lower()
                column_name = row['column'+suffix].lower()
                table_columns_names = self.get_table_columns_names(tables, table_name)  
                if column_name not in table_columns_names:
                    print(f"row id {index} will be remove from output since column {column_name} not in {table_name}")
                    index_to_remove.append(index)

        df_result = df_result.drop(index_to_remove) 
        return df_result
    
    def build_output_table_for_suggest_relation(self, df_result:pd.DataFrame, table_to_oid:dict, tables:dict, table_name:str):
        """
        build output table - change table headers if needed, add column with columns ids
        """
        if "from" in df_result.keys():
            df_result.rename(columns={"from":"table1","to":"table2","columns":"column1"},inplace=True)
            df_result['column2'] = df_result['column1']    
        df_result.insert(loc = 0,column = 'Select', value  = "<input type=\"checkbox\" />")
        # add step to check that the suggested columns belong to tables    
        df_result = self.validate_columns_exist_in_tables(df_result, tables, table_name)
        df_result = self.add_column_with_column_ids(df_result, table_to_oid)
        return df_result

    def add_column_with_column_ids(self, df_result:pd.DataFrame, table_to_oid:dict):
        """
        add to output dataframe (df_result) a column with selection type and suggested columns oid  
        """
        for i,row in df_result.iterrows():
            for column_name in row.keys():            
                if isinstance(row[column_name], list):       
                    row[column_name]= row[column_name][-1] 

            relation_table1 = row['table1']
            relation_table2 = row['table2']
            relation_column1 = row['column1']
            relation_column2 = row['column2']

            # check that tables exist    
            if relation_table1 in table_to_oid and relation_table2 in table_to_oid:
               # check that columns exist in tables
                if relation_column1 in table_to_oid[relation_table1] and relation_column2 in table_to_oid[relation_table2]:
                    columns_ids = table_to_oid[relation_table1][relation_column1]+":"+table_to_oid[relation_table2][relation_column2]
                    df_result['Select'][i] = "<input type=\"checkbox\" id=\""+columns_ids+"\" class=\"checkBoxClass\"  />"
        df_result = df_result[['Select','table1', 'column1', 'table2', 'column2']]    
        return df_result


    def ask_ai_for_suggest_relation(self, tables:list, table_name:str, df_result:pd.DataFrame):
        """
        send and receive suggest relation request to GPT
        """
        question = self.get_question_for_suggest_relation(tables, table_name)
        response = self.ai_queries.ask_ai_with_cache('model_queries',question)
        res_text = response['choices'][0]['text']        
        abort, df_result = self.check_for_parsing_errors(res_text, df_result)
        if not abort:
            df_result = self.ai_queries.clean_json_response(res_text)
        return abort, df_result
    
# *****************************************************************************************
#   Data types inference functionality    
# ******************************************************************************************  

    def get_question_for_data_types(self, df_result: pd.DataFrame)->str:
        """
        returns question to inference the data types in df_result
        """
        types_prompt = "What are the Data Types of the following values:\n"
        data_type_few_shot = ['"Value": "Music is power" \n "Type": "string" \n',
        '"Value": "15:03" \n "Type": "Numeric" \n',
        '"Value": "November 35, 2017" \n "Type": "date" \n',
        '"Value": "The Friends" \n "Type": "string" \n',
        '"Value": "English" \n "Type": "string" \n',
        '"Value": "v" \n "Type": "Char" \n',
        '"Value": "true" \n "Type": "boolean" \n',
        '"Value": "12.589" \n "Type": "Float" \n',
        '"Value": "12" \n "Type": "Integer" \n']
        types_prompt += " ".join(data_type_few_shot)

        types_prompt += "\n\n"
        select_row = df_result.iloc[0]
        for i,row in df_result.iterrows():
            found_good_row = True
            for x in row.values:
                try:
                    if len(str(x)) == 0:
                        found_good_row = False
                except:
                    found_good_row = False
            if found_good_row:
                select_row = row
                break
        for i in select_row.values:
            types_prompt += '"Value":  "'+str(i) + '" \n'
        types_prompt += '\nPlease output as list of dictionaries with format [{"Value": , "Type": }] as JSON.\n\n'
        print (f"data types question {types_prompt}")
        return types_prompt
        
    
    def parse_response_for_data_types(self, types_response, df_result:pd.DataFrame):   
        """
        parse GPT response for data types inference
        """
        DataTypes = {
          "BigInt": "0",
          "Boolean": "2",
          "boolean": "2",
          "Char": "3",
          "Timestamp": "4",
          "timestamp": "4",
          "Decimal": "5",
          "Float": "6",
          "Integer": "8",
          "integer": "8",
          "int": "8",
          "Real": "13",
          "SmallInt": "16",
          "VarChar": "18",
          "String": "18",
          "string": "18",
          "Text": "18",
          "TinyInt": "20",
          "Date": "31",
          "date": "31",
          "Time": "32",
          "Double": "40",
          "Numeric": "41",
          "TimestampWithTimezone": "43",
          "TimeWithTimezone": "44"
        }
        types = []
        print(f"response for data types question: {types_response['choices'][0]['text']}")
        type_reponses = self.ai_queries.clean_json_response(types_response['choices'][0]['text'])
        if 'Value' in type_reponses:
            for index, row in type_reponses.iterrows():
                ctype = 18
                column_type = row['Type']
                if column_type in DataTypes.keys():
                    ctype = DataTypes[column_type]                                
                types.append(ctype)
        # add deafult type as string if data type is missing
        if len(types) < len(df_result.keys()):
            for i in range(len(df_result.keys())-len(types)):
                types.append(18)
                
        return types
    
    def get_data_types_for_response(self, df_result: pd.DataFrame):
        """
        identifies the data types for the values in df_result
        """
        types_prompt = self.get_question_for_data_types(df_result)
        types_response = self.ai_queries.ask_ai_with_cache('datatypes',types_prompt)
        types = self.parse_response_for_data_types(types_response, df_result)
        return types
    
# *****************************************************************************************
#   Data extraction from Sisense functionality    
# ****************************************************************************************** 

    def get_data_from_jaql(self, jaql:dict, model_name:str):
        """
        run jaql and returns query result 
        """
        abort = False
        res = self.utils.run_jaql(jaql,model_name)
        data = []
        try:
            data = json.loads(res.text)
        except ValueError:
            print ("Bad response")
        if ('error' in data and data['error']):
            print(f"error in loading jaql response : {data}")
            abort = True    
        return abort, data
    
    def get_column_data(self, data, jaql, question_type_object): 
        """
        filter and return only the data in column 
        """
        column_vec = []  
        # in case of specific column requested from a widget/table - will return only the data in that column
        cname_index_in_jaql = self.utils.get_column_index_in_jaql(jaql, question_type_object.sisense_column_element, question_type_object.qtype)
        assert not cname_index_in_jaql==-1, 'did not found requested column in data model'
        for column_values in data['values']:
            val = column_values[cname_index_in_jaql]['data'] 
            if val not in column_vec:
                column_vec.append(val)
        self.utils.add_to_query_log(jaql, re.sub(r'\n',r'<br>',json.dumps(column_vec, indent=4)), 'JAQL Query')
        return column_vec
    
    
    def generate_query_to_ai_based_on_column_data(self, orig_question:str, requested_data:str, column_data:list, num_item_per_split:int)->list:
        """
        generate query in batch mode, split the data in column to batches and return questions in batches
        """
        question = orig_question.replace(requested_data,"")
        prompt_vec = []        
        # If many items split the request to multiple ai queries
        data_length = len(column_data)
        data_length_remainder = data_length % num_item_per_split   
        if data_length > num_item_per_split:
            split_counter = int((data_length-data_length_remainder)/num_item_per_split)
            for split_index in range(0,split_counter):
                limit_r = '\n'.join(column_data[num_item_per_split*split_index:num_item_per_split*(split_index+1)])               
                limit_q = question + "\n" + limit_r + "\n\nPlease include the request column in the response.\nPlease output as JSON vector.\n"
                prompt_vec.append(limit_q)
            #  if a reminder exist then add it too
            if data_length_remainder > 0:
                limit_r = '\n'.join(column_data[-data_length_remainder:])
                limit_q = question + "\n" + limit_r + "\n\nPlease include the request column in the response.\nPlease output as JSON vector.\n"
                prompt_vec.append(limit_q)
        else:
            limit_q = question + "\n" + '\n'.join(column_data) + "\n\nPlease include the request column in the response.\nPlease output as JSON vector.\n"
            prompt_vec.append(limit_q)
        return prompt_vec 
                       
              
    def get_df_from_jaql(self, jaql, model_name:str, is_indicator_widget_data:bool=False):
        """
        build dataframe out of jaql 
        """
        jaql['count'] = -1
        abort, data = self.get_data_from_jaql(jaql,model_name)
        try:                    
            col = data['headers']
            vec = []
            if is_indicator_widget_data:
                vec.append([i['data'] for i in data['values']])
            else:    
                for i in data['values']:          
                    v = []  
                    if type(i) == type(v):               
                        for j in i:
                            v.append(j['data'])
                    else:
                        v = [i['data']]
                    vec.append(v)
            df_result = pd.DataFrame(data=vec, columns=col)
            if is_indicator_widget_data:
                # remove columns with 'N\\A' values
                df_result = df_result.replace('N\\A', np.nan)
                df_result = df_result.dropna(axis=1, how='any')            
            else:
                # remove columns duplication
                df_result = df_result.loc[:,~df_result.columns.duplicated()].copy()
                # remove columns with 1 unique value
                df_result = df_result[[index for index, value in df_result.nunique().items() if value>1]]
                # remove columns with ID 
                df_result = df_result[[column_name for column_name in df_result.columns if 'id' not in column_name.lower()]]

        except ValueError:
            print (f"error in get_df_from_jaql, error in response: {data}")
            df_result = self.handle_error_in_element_extraction(data)
        return abort, df_result
    
    def handle_error_in_element_extraction(self, info:str):   
        """
        error handeling in element extraction
        """
        abort = True
        return pd.DataFrame(data=[info], columns=['Error']) 
    
# *****************************************************************************************
#   summarization functionality    
# ******************************************************************************************

    def get_widget_summary(self, df_result_as_csv, wtype, widget_title, dashboard_name):
        """
        create question for widget summary, send to GPT and parse the response  
        """
        question = "The following table represent data of "+wtype+".\n"
        question += "The data title is " + widget_title + " and belongs to "+dashboard_name+"\n"
        question += "Please summarize the data and identify valuable info regarding the domain: " + df_result_as_csv + "\n"
        question += "output the answer as text and not inside a table\n"
        
        self.utils.add_time('Before ai describe table')        
        response = self.ai_queries.ask_ai_with_cache('describe',question)
        self.utils.add_time('After ai describe table')
        response = self.ai_queries.parse_respone(response)
        return response
    
    def get_dashboard_summary(self, widget_summary, dashboard_name):
        """
        create question for dashboard summary, send to GPT and parse the response  
        """
        widget_summary_as_paragraph = " \n\n ".join(widget_summary.values())   
        question = "The following paragraphs represents data from a dashboard.\n"
        question += "The dashboard title is " + dashboard_name + "\n"
        question += "Please summarize the paragraphs and identify valuable info regarding the domain: \n" + widget_summary_as_paragraph + "\n"
        
        self.utils.add_time('Before ai describe table')      
        response = self.ai_queries.ask_ai_with_cache('describe',question)
        self.utils.add_time('After ai describe table')
        response = self.ai_queries.parse_respone(response)
        return response
    