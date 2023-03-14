import re
import traceback
import copy

try:
    import strenum
except ImportError:
    from pip._internal import main as pip
    pip(['install', 'StrEnum'])
    import strenum
    
from strenum import StrEnum


# ****************************************************************************
#       Classes for Question type inference, each class 
#       represent different question type, which needs to be 
#       inferred from the prompt generated by the user.
#       Each class will extract the relevant entities from the prompt
#       and will map the entities to sisense elements.
#       Also, each class will create the relevant jaql for the sisense elements.
# ***************************************************************************** 
class QType(StrEnum):
    TypeDashboardWidget = '1',
    TypeColumnTable = '2',
    TypeDashboardWidgetColumn = '4',
    TypeDashboard = '5',
    TypeModelDashboardWidget = '7',
    TypeModelDashboard = '8'
    
class InferenceQuestionType(object):
    def __init__(self, ai_queries, utils, to_validate_entities_from_question:bool):
        """
        @param to_validate_entities_from_question: bool, true if data entities shuold be infered from prompt
        """
        self.utils = utils
        self.ai_queries = ai_queries
        self.to_validate_entities_from_question = to_validate_entities_from_question
        
        
    def extract_data_entities_from_prompt(self, prompt:str):
        """
        extract data entities from prompt by asking AI model 
        """
        if self.to_validate_entities_from_question:           
            question = self.get_question_for_entity_extraction(prompt)       
            print(f"question for entity extraction: \n{question}")
            self.utils.add_time('Before ai extract entities from prompt')
            response = self.ai_queries.ask_ai_with_cache('model_queries',question)
            self.utils.add_time('After ai extract entities from prompt')
            self.utils.write_log_updates()
            res_text = response['choices'][0]['text'].lower()
            res_pd = self.ai_queries.clean_json_response(res_text)
            print(f"response for entity extraction: \n{res_pd}")

            try:    
                self.extract_entities_with_ai_response(res_pd)
            except BaseException as error:
                self.utils.add_to_query_log("question_type_object.entity_extraction",re.sub(r'\n',r'<br>',"Error: " + 'An exception occurred: {}'.format(error) + "\n" + traceback.format_exc()),'Fail')
                self.utils.write_log_updates()
                return ["Errors" ,"Error: " + 'An exception occurred: {}'.format(error) + "\n" + traceback.format_exc()]

            except ValueError as error:
                self.utils.add_to_query_log("question_type_object.entity_extraction",re.sub(r'\n',r'<br>',"Error: " + 'An exception occurred: {}'.format(error) + "\n" + traceback.format_exc()),'Fail')
                self.utils.write_log_updates()
                return ["Errors" ,"Error: " + 'An exception occurred: {}'.format(error) + "\n" + traceback.format_exc()]
        
        else:
            self.extract_entities_with_regex(prompt)
                
    def get_question_for_entity_extraction(self, prompt:str):
        """
        create question to extract entities from prompt  
        """
        question = self.entity_extraction_question          
        question += " ".join(self.entity_extraction_few_shot_samples) 
        question += "Response as json\n\n"
        question += "Sentence: "+ prompt + "\n Result:"  
        return question
    
    def get_key_from_response(self, response: dict, key_name: str) -> str:
        """
        extract from response value of key_name  
        """
        names_options = ["", "_name", "name"]
        names_options = [key_name+name for name in names_options]
        found_key = False  
        if 'key' in response.keys():            
            for key in names_options:               
                if key in response['key'].values:
                    key_value = response[response['key'] == key]['value'].values[0]
                    found_key = True
                    break
                    
        for key in response.keys():
            if key.lower() in names_options:
                key_value = response[key] 
                found_key = True
                break
              
        if not found_key:
            print(f"failed to extract {key_name} entity from response {response}")
            raise ValueError(f'failed to extract {key_name} entity from response', response)
            
        return key_value
    
    def get_sisense_model_element(self, model_name:str)->str:
        """
        get model name (in sisense) from model name in prompt        
        """
        models = self.utils.get_all_models()          
        match_list = []
        for i in range(len(models)):
            match_list.append(models[i]['title'])
        selected_model = self.ai_queries.get_item_from_list(model_name, match_list)
        print (f"sisense model detected is:{selected_model} from prompt {model_name}")            
        return selected_model 
    
    def get_sisense_dashboard_element(self):   
        """
        identify dashboard element (in sisense) from prompt entity        
        """
        dashboards = self.utils.get_all_dashboards_for_model(self.sisense_model_element)
        if self.to_validate_entities_from_question:                
            match_list = []
            for i in range(len(dashboards)):
                match_list.append(dashboards[i]['title'])
            selected_dashboard = self.ai_queries.get_item_from_list(self.prompt_dashboard_entity,match_list)
        else:
            selected_dashboard = self.prompt_dashboard_entity
        print (f"sisense dashboard detected is:{selected_dashboard} from prompt {self.prompt_dashboard_entity}")            

        for i in range(len(dashboards)):
            if selected_dashboard == dashboards[i]['title']:
                dashboardObject = dashboards[i]
                dname = dashboards[i]['title']
                doid = dashboards[i]['oid']
        print (f"dashboard oid is:{doid} dashboard title is {dname}")   
        return {"dashboardObject":dashboardObject, "dname":dname, "doid":doid}

    def match_widget_name_to_widget_element(self, widgets:list, widget_name:str): 
        """
        return the corresponding sisense widget element for widget name        
        """
        for i in range(len(widgets)):
            if widget_name == widgets[i]['title']:
                wname = widgets[i]['title']
                woid = widgets[i]['oid']
                widObject = widgets[i]
                
        return {"wname":wname, "woid":woid, "widObject":widObject}
    
    def get_sisense_widget_element(self):  
        """
        identify widget element (in sisense) from prompt entity        
        """
        widgets = self.utils.get_all_widgets_for_dashboard(self.sisense_dashboard_element["doid"])
        if self.to_validate_entities_from_question:
            match_list = []
            for i in range(len(widgets)):
                match_list.append(widgets[i]['title'])    
            selected_widget = self.ai_queries.get_item_from_list(self.prompt_widget_entity,match_list)
        else:
            selected_widget = self.prompt_widget_entity
        print (f"sisense widget detected is:{selected_widget} from prompt {self.prompt_widget_entity}")            

        widget_element = self.match_widget_name_to_widget_element(widgets, selected_widget)  
        return widget_element
                
    def get_sisense_table_element(self): 
        """
        identify table element (in sisense) from prompt entity        
        """
        tables, model_desc, table_to_oid = self.utils.get_all_tables_info_for_model(self.sisense_model_element)

        match_list=[]
        i = 0
        for tableObj in tables:
            i = i+1
            match_list.append(tableObj['name'])
        selected_table = self.ai_queries.get_item_from_list(self.prompt_table_entity,match_list)
        model = self.utils.get_model(self.sisense_model_element)
        for i in range(len(model['datasets'])):
            if selected_table == model['datasets'][i]['schema']['tables'][0]['name']:
                tableObj = model['datasets'][i]['schema']['tables'][0]   
                
        print (f"sisense table detected is:{selected_table} from prompt {self.prompt_table_entity}") 
        return {"table_name":selected_table, "tableObj":tableObj}    
        
    def get_sisense_column_element_from_table(self):
        """
        identify column element in table (in sisense) from prompt entity        
        """
        match_list = []
        tableObj = self.sisense_table_element["tableObj"]
        for i in range(len(tableObj['columns'])):
            match_list.append(tableObj['columns'][i]['name'])
        selected_column = self.ai_queries.get_item_from_list(self.prompt_column_entity,match_list)
        return selected_column
    
    def get_sisense_column_element_from_widget(self):
        """
        identify column element in widget (in sisense) from prompt entity        
        """
        match_list = []
        widObject = self.sisense_widget_element["widObject"]
        widgetPanels =  widObject['metadata']['panels']
        for i in range(len(widgetPanels)):
            if  widgetPanels[i]['name'] != "filters":
                items = widgetPanels[i]['items']
                for j in range(len(items)):
                    match_list.append(items[j]['jaql']['title'])
        selected_column = self.ai_queries.get_item_from_list(self.prompt_column_entity,match_list)
        print (f"sisense column detected is:{selected_column} from prompt {self.prompt_column_entity}") 
        return selected_column
    
    
    def get_base_jaql(self, model_name:str):
        """
        return jaql with datasource (model_name) description        
        """
        jaql = { 
                "datasource": {
                    "title": model_name
                },
                "metadata": [],
                "offset":0,
                "count":256,
                "isFilter": "false",
                "queryGuid":"83722-0ACC-5843-615B-FAEA-B7C7-520D-1234-E"
            }
        return jaql
    
    def insert_dashboard_filters_to_jaql(self, widgetPanels:dict, jaql:dict):
        """
        insert dashboard filters to jaql         
        """
        dashboardObject = self.sisense_dashboard_element["dashboardObject"]       
        ### Add dashboard filters 
        for dashboard_filter in dashboardObject['filters']:                 
            used = False
            for widget_panel in widgetPanels:                
                for widget_panel_item in widget_panel['items']:
                    item = { "jaql": widget_panel_item['jaql'] }
                    # add dashboard filter if needed
                    if 'dim' in item['jaql'] and item['jaql']['dim'] == dashboard_filter['jaql']['dim'] and 'agg' not in item['jaql']:
                        used = True
                    else:
                        if 'context' in item['jaql']:
                            for context in item['jaql']['context'].values():
                                if 'dim' in context and context['dim'] == dashboard_filter['jaql']['dim']:
                                    used = True
            if not used and not ('disabled' in dashboard_filter and dashboard_filter['disabled'] == True):
                dashboard_filter['panel'] = "scope"
                jaql['metadata'].append(dashboard_filter)
        
        return jaql
        
    def insert_widget_data_and_filters_to_jaql(self, widgetPanels, jaql):
        """
        return jaql with datasource (model_name) description        
        """
        dashboardObject = self.sisense_dashboard_element["dashboardObject"]     
        ### Add widget items
        for widget_panel in widgetPanels:            
            for widget_panel_item in widget_panel['items']:
                item = { "jaql": widget_panel_item['jaql'] }
                if "panel" in widget_panel_item:
                    item["panel"] = widget_panel_item['panel']
                # add dashboard filter if needed
                if "filter" not in item:
                    #check for dashboard filter
                    for dashboard_filter in dashboardObject['filters']:
                        if 'dim' in item['jaql'] and item['jaql']['dim'] == dashboard_filter['jaql']['dim'] and 'agg' not in item['jaql']:
                                   item['jaql']['filter'] = dashboard_filter['jaql']['filter']
                        else:
                            if 'context' in item['jaql']:
                                for context in item['jaql']['context'].values():
                                    if 'dim' in context and context['dim'] == dashboard_filter['jaql']['dim']:
                                        print ("identified filter on formula")
                jaql['metadata'].append(item)
        return jaql
     
    
    def get_widget_jaql(self, widgets:list, jaql:dict, widget_name:str):
        """
        built a jaql representation for a widget
        """
        dname = self.sisense_dashboard_element["dname"]
        doid = self.sisense_dashboard_element["doid"]

        widget_element = self.match_widget_name_to_widget_element(widgets,widget_name)  
        widObject = widget_element["widObject"]
        wname = widget_element["wname"]
        woid = widget_element["woid"]
        try:
            widgetPanels =  widObject['metadata']['panels']                           
            info = [dname,doid,wname,woid]
            jaql = self.insert_widget_data_and_filters_to_jaql(widgetPanels, jaql)
            jaql = self.insert_dashboard_filters_to_jaql(widgetPanels, jaql)
        except BaseException as error:           
            return [jaql, ["Error: " + 'An exception occurred: {}'.format(error) + "\n" + traceback.format_exc()]]
           
        return [jaql,info]
    
    def get_jaqls_for_all_widgets(self):
        """
        collect jaql representations for all widgets in a dashboard
        """
        widgets = self.utils.get_all_widgets_for_dashboard(self.sisense_dashboard_element["doid"])
        jaql = self.get_base_jaql(self.sisense_model_element)       
        all_wigdets_info = []
        jaql_per_widget = {}
        for i in range(len(widgets)):        
                        
            woid = widgets[i]['oid']
            widget_name = widgets[i]['title']            
            widget_jaql = copy.deepcopy(jaql)
            widget_jaql, info = self.get_widget_jaql(widgets, widget_jaql, widget_name)
            jaql_per_widget[woid] =  [widget_jaql, info]
            all_wigdets_info += info
        return [jaql_per_widget, all_wigdets_info]
   
            
        
class InferenceDashboard(InferenceQuestionType): 
    def __init__(self, ai_queries, utils, to_validate_entities_from_question):
        super().__init__(ai_queries, utils, to_validate_entities_from_question)
        self.qtype=5        
        self.few_shot_samples = ["Sentence: dashboard \"dashboard name\" \n Type: 5 \n",
                                "Sentence: what dashboard \"dashboard name\" is about \n Type: 5 \n",
                                "Sentence: please summarize dashboard \"dashboard name\" \n Type: 5 \n",
                                "Sentence: provide valuable info regarding \"dashboard name\" dashboard \n Type: 5 \n"]
                    
        self.entity_extraction_few_shot_samples = ["Sentence: dashboard \"dashboard_name\" \n Result: {\"dashboard_name\": \"dashboard_name\"}  \n",                                               
                                                   "Sentence: dashboard Sample Healthcare \n Result: {\"dashboard_name\": \"Sample Healthcare\"}  \n",
                                                   "Sentence: dashboard Ecommerce \n Result: {\"dashboard_name\": \"Ecommerce\"} \n",
                                                   "Sentence: dashboard Retail \n Result: {\"dashboard_name\": \"Retail\"}\n"] 
        
        self.entity_extraction_question = "Please return the name of the dashboard from the following text:\n" 
        
        self.prompt_dashboard_entity = None
        self.sisense_dashboard_element = None
        
    def extract_entities_with_ai_response(self, ai_response):        
        self.prompt_dashboard_entity = self.get_key_from_response(ai_response, "dashboard")  
        print(f"extracted {self.prompt_dashboard_entity} as dashboard from prompt with ai")
    
    def extract_entities_with_regex(self, prompt):      
        self.prompt_dashboard_entity = re.search( r'dashboard (.*)$', prompt).group(1) 
        print(f"extracted {self.prompt_dashboard_entity} as dashboard from prompt with regex")
        
    def map_data_entities_to_sisense_elements(self, default_model_name:str):
        self.sisense_model_element = default_model_name
        self.sisense_dashboard_element = self.get_sisense_dashboard_element()
        
    def get_jaql_from_elements(self):
        jaql_per_widget = self.get_jaqls_for_all_widgets()        
        return jaql_per_widget
        

        
        
class InferenceDashboardWidgetColumn(InferenceQuestionType):
    def __init__(self, ai_queries, utils, to_validate_entities_from_question): 
        super().__init__(ai_queries, utils, to_validate_entities_from_question)
        self.qtype=4
        self.few_shot_samples = ["Sentence: column \"column name\" from widget \"widget name\" in a dashboard \"dashboard name\" \n Type: 4 \n",
                                "Sentence: column \"column name\" widget \"widget name\" dashboard \"dashboard name\" \n Type: 4 \n"]
                               
                    
        self.entity_extraction_few_shot_samples = ["Sentence: column \"column_name\" from widget \"widget_name\" in a dashboard \"dashboard_name\" \n Result: {\"dashboard_name\": \"dashboard_name\", \"column_name\": \"column_name\", \"widget_name\":\"widget_name\"} \n",  
                                                   "Sentence: column diagnosis widget admissions dashboard healthcare \n Result: {\"dashboard_name\": \"healthcare\", \"column_name\": \"diagnosis\", \"widget_name\":\"admissions\"}  \n"                         
                                                  ]
        
        self.entity_extraction_question = "Please return the name of the column, widget and dashboard from the following text:\n"
        
        self.prompt_dashboard_entity = None
        self.sisense_dashboard_element = None
        self.prompt_widget_entity = None
        self.sisense_widget_element = None
        self.prompt_column_entity = None
        self.sisense_column_element = None
        self.sisense_model_element = None
        
    def extract_entities_with_ai_response(self, ai_response):         
        self.prompt_dashboard_entity = self.get_key_from_response(ai_response, "dashboard")  
        print(f"extracted {self.prompt_dashboard_entity} as dashboard from prompt with ai response")
        self.prompt_widget_entity = self.get_key_from_response(ai_response, "widget")   
        print(f"extracted {self.prompt_widget_entity} as widget from prompt with ai response")
        self.prompt_column_entity = self.get_key_from_response(ai_response, "column")  
        print(f"extracted {self.prompt_column_entity} as column from prompt with ai response")
    
    def map_data_entities_to_sisense_elements(self, default_model_name:str):
        self.sisense_model_element = default_model_name
        self.sisense_dashboard_element = self.get_sisense_dashboard_element()
        self.sisense_widget_element = self.get_sisense_widget_element()
        self.sisense_column_element = self.get_sisense_column_element_from_widget()
        
    def get_jaql_from_elements(self):
        widgets = self.utils.get_all_widgets_for_dashboard(self.sisense_dashboard_element["doid"])
        jaql = self.get_base_jaql(self.sisense_model_element)
        return self.get_widget_jaql(widgets, jaql, self.sisense_widget_element["wname"])

    

class InferenceModelDashboardWidget(InferenceQuestionType):
    def __init__(self, ai_queries, utils, to_validate_entities_from_question):  
        super().__init__(ai_queries, utils, to_validate_entities_from_question)
        self.qtype=7
        self.few_shot_samples = ["Sentence: model \"model name\" dashboard \"dashboard name\" widget \"widget name\" \n Type: 7 \n"                              
                                ]
                               
        self.entity_extraction_few_shot_samples = ["Sentence: model \"model_name\" dashboard \"dashboard_name\" widget \"widget_name\" \n Result: {\"dashboard_name\": \"dashboard_name\", \"model_name\": \"model_name\", \"widget_name\":\"widget_name\"} \n",
                                                  "Sentence: model ecommerce dashboard products widget revenue\n Result: {\"dashboard_name\": \"ecommerce\", \"model_name\": \"ecommerce\", \"widget_name\":\"revenue\"} \n"]  
        
        self.entity_extraction_question = "Please return the name of the model, dashboard and widget from the following text:\n"
  
        self.prompt_dashboard_entity = None
        self.sisense_dashboard_element = None
        self.prompt_widget_entity = None
        self.sisense_widget_element = None
        self.prompt_model_entity = None
        self.sisense_model_element = None
        
    def extract_entities_with_ai_response(self, ai_response):       
        self.prompt_dashboard_entity = self.get_key_from_response(ai_response, "dashboard")  
        print(f"extracted {self.prompt_dashboard_entity} as dashboard from prompt with ai response")
        self.prompt_model_entity = self.get_key_from_response(ai_response, "model")        
        print(f"extracted {self.prompt_model_entity} as model from prompt with ai response")
        self.prompt_widget_entity = self.get_key_from_response(ai_response, "widget") 
        print(f"extracted {self.prompt_widget_entity} as widget from prompt with ai response")
   
        
    def map_data_entities_to_sisense_elements(self, default_model_name:str):
        self.sisense_model_element = self.get_sisense_model_element(self.prompt_model_entity)
        self.sisense_dashboard_element = self.get_sisense_dashboard_element()
        self.sisense_widget_element = self.get_sisense_widget_element()
        
        
    def get_jaql_from_elements(self):
        widgets = self.utils.get_all_widgets_for_dashboard(self.sisense_dashboard_element["doid"])
        jaql = self.get_base_jaql(self.sisense_model_element)
        return self.get_widget_jaql(widgets, jaql, self.sisense_widget_element["wname"])

    
class InferenceModelDashboard(InferenceQuestionType):    
    def __init__(self, ai_queries, utils,to_validate_entities_from_question):
        super().__init__(ai_queries, utils, to_validate_entities_from_question)
        self.qtype=8        
        self.few_shot_samples = ["Sentence: model \"model name\" dashboard \"dashboard name\" \n Type: 8 \n",
                                "Sentence: what dashboard \"dashboard name\" is about from model \"model name\"\n Type: 8 \n",
                                "Sentence: please summarize dashboard \"dashboard name\" from model \"model name\"\n Type: 5 \n"]
                            
        self.entity_extraction_few_shot_samples = ["Sentence: model \"model_name\" dashboard \"dashboard_name\"\n Result: {\"dashboard_name\": \"dashboard_name\", \"model_name\": \"model_name\"} \n",
                                                  "Sentence: model ecommerce dashboard products\n Result: {\"dashboard_name\": \"products\", \"model_name\": \"ecommerce\"} \n"] 
        self.entity_extraction_question = "Please return the name of the model and dashboard from the following text:\n"   
        
        self.prompt_dashboard_entity = None
        self.sisense_dashboard_element = None
        self.prompt_model_entity = None
        self.sisense_model_element = None
    
    
    def extract_entities_with_ai_response(self, ai_response):         
        self.prompt_dashboard_entity = self.get_key_from_response(ai_response, "dashboard")  
        print(f"extracted {self.prompt_dashboard_entity} as dashboard from prompt with ai response")
        self.prompt_model_entity = self.get_key_from_response(ai_response, "model")   
        print(f"extracted {self.prompt_model_entity} as model from prompt with ai response")
        
       
    def map_data_entities_to_sisense_elements(self, default_model_name:str):
        self.sisense_model_element = self.get_sisense_model_element(self.prompt_model_entity)
        self.sisense_dashboard_element = self.get_sisense_dashboard_element()
        
    def get_jaql_from_elements(self):
        jaql_per_widget = self.get_jaqls_for_all_widgets()        
        return jaql_per_widget
    
    
    
        
class InferenceDashboardWidget(InferenceQuestionType):    
    def __init__(self, ai_queries, utils, to_validate_entities_from_question):
        super().__init__(ai_queries, utils, to_validate_entities_from_question)
        self.qtype=1
        self.few_shot_samples = ["Sentence: what widget \"widget name\" in dashboard \"dashboard name\" is about \n Type: 1 \n",
                                "Sentence: please summarize widget \"widget name\" in dashboard \"dashboard name\" \n Type: 1 \n",
                                "Sentence: widget \"widget name\" in dashboard \"dashboard name\" summary \n Type: 1 \n"]
                            
        self.entity_extraction_few_shot_samples = ["Sentence: widget \"widget_name\" dashboard \"dashboard_name\"\n Result: {\"dashboard_name\": \"dashboard_name\", \"widget_name\": \"widget_name\"} \n",
                                                  "Sentence: widget revenue dashboard ecommerce\n Result: {\"dashboard_name\": \"ecommerce\", \"widget_name\": \"revenue\"} \n"] 
        self.entity_extraction_question = "Please return the name of the widget and dashboard from the following text:\n" 
        
        self.prompt_dashboard_entity = None
        self.sisense_dashboard_element = None
        self.prompt_widget_entity = None
        self.sisense_widget_element = None   
        self.sisense_model_element = None
        
    def extract_entities_with_ai_response(self, ai_response):       
        self.prompt_dashboard_entity = self.get_key_from_response(ai_response, "dashboard")  
        print(f"extracted {self.prompt_dashboard_entity} as dashboard from prompt with ai response")       
        self.prompt_widget_entity = self.get_key_from_response(ai_response, "widget") 
        print(f"extracted {self.prompt_widget_entity} as widget from prompt with ai response")
    
    def extract_entities_with_regex(self, prompt):         
        self.prompt_dashboard_entity = re.search( r'dashboard.(.*?) widget', prompt).group(1)
        print(f"extracted {self.prompt_dashboard_entity} as dashboard from prompt with regex")
        self.prompt_widget_entity = re.search( r'widget (.*)$', prompt).group(1)
        print(f"extracted {self.prompt_widget_entity} as widget from prompt with regex")
        
    def map_data_entities_to_sisense_elements(self, default_model_name:str):
        self.sisense_model_element = default_model_name
        self.sisense_dashboard_element = self.get_sisense_dashboard_element()
        self.sisense_widget_element = self.get_sisense_widget_element()        
        
    def get_jaql_from_elements(self):
        widgets = self.utils.get_all_widgets_for_dashboard(self.sisense_dashboard_element["doid"])
        jaql = self.get_base_jaql(self.sisense_model_element)
        return self.get_widget_jaql(widgets, jaql, self.sisense_widget_element["wname"])
    
    
class InferenceColumnTable(InferenceQuestionType):    
    def __init__(self, ai_queries, utils, to_validate_entities_from_question): 
        super().__init__(ai_queries, utils, to_validate_entities_from_question)
        self.qtype=2
        self.few_shot_samples = ["Sentence: column column_name from a table table_name in the model/database \n Type: 2 \n",
                                "Sentence: table.column \n Type: 2 \n",
                                "Sentence: column \"column name\" in table \"table name\" \n Type: 2 \n"]
                    
        self.entity_extraction_few_shot_samples = ["Sentence: column \"column_name\" table \"table_name\"\n Result: {\"column_name\": \"column_name\", \"table_name\": \"table_name\"} \n", 
                                                  "Sentence: table_name.column_name \n Result: {\"column_name\": \"column_name\", \"table_name\": \"table_name\"} \n",
                                                  "Sentence: ecommerce.revenue \n Result: {\"column_name\": \"revenue\", \"table_name\": \"ecommerce\"} \n"] 
        self.entity_extraction_question = "Please return the name of the column and the table from the following text:\n"  
        
        self.prompt_table_entity = None
        self.sisense_table_element = None
        self.prompt_column_entity = None
        self.sisense_column_element = None        
        self.sisense_model_element = None
        
    def extract_entities_with_ai_response(self, ai_response):       
        self.prompt_table_entity = self.get_key_from_response(ai_response, "table")  
        print(f"extracted {self.prompt_table_entity} as table from prompt with ai response")
        self.prompt_column_entity = self.get_key_from_response(ai_response, "column")        
        print(f"extracted {self.prompt_column_entity} as column from prompt with ai response")
        
    def map_data_entities_to_sisense_elements(self, default_model_name:str):
        self.sisense_model_element = default_model_name
        self.sisense_table_element = self.get_sisense_table_element()
        self.sisense_column_element = self.get_sisense_column_element_from_table()
        
    def get_jaql_from_elements(self):
        tableObj = self.sisense_table_element["tableObj"] 
        jaql = self.get_base_jaql(self.sisense_model_element)
        requested_column = "[" + tableObj['name'] + "." + self.sisense_column_element +  "]"
        jaql['metadata'].append({"jaql": {"dim":requested_column,"sort":"asc"}})
        return [jaql, self.sisense_column_element]
       
        
class InferenceUnknown(InferenceQuestionType):    
    def __init__(self, ai_queries, utils, to_validate_entities_from_question): 
        super().__init__(ai_queries, utils, to_validate_entities_from_question)
        self.qtype=6
        self.few_shot_samples = ["Sentence: Other\n Type: 6\n"]                               
                                

        self.entity_extraction_question = "Unknown"
        self.entity_extraction_few_shot_samples = []
        
    def extract_entities_with_ai_response(self, ai_response): 
        pass
    
    def map_data_entities_to_sisense_elements(self, default_model_name:str):
        pass
    
    def get_jaql_from_elements(self):
        pass