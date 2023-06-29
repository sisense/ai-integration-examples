import argparse
import pandas as pd
from custom_code_notebooks.utils import SisenseAPI
import sys
import os
import base64
import io
import csv
import json
from paramiko import SSHClient
import paramiko
from scp import SCPClient
import logging
import requests

logger = logging.getLogger("Installer")
logging.basicConfig(level=logging.INFO)


def set_environ(config):
    ip = config["ip"]
    port = str(config["sisense_port"])
    os.environ["API_GATEWAY_EXTERNAL_SERVICE_HOST"] = ip
    os.environ["API_GATEWAY_EXTERNAL_SERVICE_PORT"] = port


def copy_files_to_instance(config: dict):
    user = config["user"]
    ip = config["ip"]
    password = config["password"]
    ssh_key = config["ssh_key"]
    ssh_key = None if ssh_key == "" else ssh_key
    ssh = SSHClient()
    ssh.load_system_host_keys()
    logger.info("Connecting to instance")
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip, 22, user, password, key_filename=ssh_key)
    logger.info("Connected")
    destination_full_path = '/opt/sisense/storage/notebooks/custom_code_notebooks/notebooks'
    source_notebook_files_path = './custom_code_notebooks'
    custom_libraries = ['AIIntegration.py', 'AIQueries.py', 'AIUtils.py', 'InferenceQuestionType.py']
    with SCPClient(ssh.get_transport()) as scp:
        logger.info("Copying data to server")
        for custom_lib in os.listdir(os.path.join(source_notebook_files_path, "utils")):
            if custom_lib not in custom_libraries:
                continue
            dest = os.path.dirname(destination_full_path)
            path = os.path.join(source_notebook_files_path, "utils", custom_lib)
            logger.info(f"SCP: {path}->{dest}")
            scp.put(path, dest)
        # move notebook flow image to notebook dir
        for dir_name in os.listdir(source_notebook_files_path):
            path = os.path.join(source_notebook_files_path, dir_name)
            if not os.path.isdir(path):
                continue
            for fname in os.listdir(path):
                if ".png" in fname:
                    source_image_path = path + '/' + fname
                    destination_image_path = os.path.join(destination_full_path, dir_name)
                    logger.info(f"SCP: {source_image_path}->{destination_image_path}")
                    scp.put(source_image_path, destination_image_path)
        # upload blox related stuff
        source_images = "./blox_examples/images"
        dest = "/opt/sisense/storage/branding/BloxAI"
        logger.info(f"SCP: {source_images}->{dest}")
        scp.put(source_images, dest, recursive=True)
        source_plugin = "./blox_examples/plugin/BloxAISummary"
        dest = "/opt/sisense/storage/plugins/BloxAISummary"
        logger.info(f"SCP: {source_plugin}->{dest}")
        scp.put(source_plugin, dest, recursive=True)


def get_sisense_api(config: dict):
    logger.info("Connecting API")
    user = config["sisense_username"]
    password = config["sisense_password"]
    ip = os.environ['API_GATEWAY_EXTERNAL_SERVICE_HOST']
    port = str(config["sisense_port"])
    os.environ["API_GATEWAY_EXTERNAL_SERVICE_PORT"] = port
    response = requests.post(f"http://{ip}:{port}/api/v1/authentication/login",
                             json={"username": user, "password": password},
                             headers={'Content-Type': 'application/json'})

    token = response.json()["access_token"]
    sisense_api = SisenseAPI.SisenseAPI(sisense_user_authentication_token=token)
    logger.info("API connected")
    return sisense_api


def install_custom_code_notebooks(sisense_conn: SisenseAPI.SisenseAPI):
    # Get CustomCode Notebooks that already exist
    source_notebook_files_path = './custom_code_notebooks'
    # import notebook into Sisense
    for dir_name in os.listdir(source_notebook_files_path):
        path = os.path.join(source_notebook_files_path, dir_name)
        if not os.path.isdir(path):
            continue
        for fname in os.listdir(path):
            if ".sipynb" in fname:
                logger.info(f"Uploading: {path + '/' + fname}")
                with open(path + '/' + fname) as f:
                    data = json.load(f)
                    data['notebookType'] = "CustomCodeTransformation"
                    res = sisense_conn.call_api('POST', '/api/v1/notebooks', payload=data)
                    logger.info(f"Upload result: {res.status_code}")


def install_blox_actions(sisense_conn):
    blox_files_path = "./blox_examples/action_snippets"
    for fname in os.listdir(blox_files_path):
        if ".json" in fname and "blox" in fname:
            logger.info(f"Adding action: {fname.replace('.json', '')}")
            with open(blox_files_path + '/' + fname) as f:
                data = json.load(f)
                res = sisense_conn.call_api('POST', '/api/v1/saveCustomAction/BloX', payload=data)
                logger.info(f"Save action result:{res.status_code}")


def install_dashboard(sisense_conn):
    dashboard_file_path = './common/BloxAI.dash'
    logger.info("Creating BLOX dashboard")
    with open(dashboard_file_path) as f:
        data = json.load(f)
        res = sisense_conn.call_api('POST', '/api/v1/dashboards/import/bulk', payload=[data])
        logging.info(f"Dashboard upload: {res.status_code} {res.text}")


def install_data_model(sisense_conn: SisenseAPI.SisenseAPI):
    data_model_path = './common/AITransformation.sdata'
    logger.info("Installing data model")
    url_suffix = '/api/v2/datamodel-imports/stream/full?newTitle=AITransformation'
    url = sisense_conn.sisense_base_url + url_suffix
    headers = {
        'authorization': sisense_conn.headers["authorization"],
        'Content-Encoding': 'gzip'
    }
    files = {'fileToUpload': open(data_model_path, 'rb')}
    res = requests.post(url, headers=headers, files=files, timeout=350)
    logger.info(f"Data model upload: {res.status_code}")


def set_api_key(config, sisense_conn):
    logger.info("Setting API key")
    api_key = config["lm_api_key"]
    config_name = "AI-API-KEY"
    logger.info(f'Set config {config_name}: {api_key}')
    payload = {f'{config_name}.value': api_key, f'{config_name}.setbyuser': True}
    resp = sisense_conn.call_api(http_method='POST', payload=payload,
                                 url_suffix='/app/configuration/configurations/service/custom-code')
    return resp


def install(config: dict):
    api = get_sisense_api(config)
    install_custom_code_notebooks(api)
    install_blox_actions(api)
    install_dashboard(api)
    install_data_model(api)
    copy_files_to_instance(config)
    set_api_key(config, api)


def uninstall_notebooks(sisense_conn):
    logger.info("Removing notebooks")
    current_notebooks_name = [
        'Data Search',
        'Dashboard Summary',
        'Create Relations',
        'WidgetSummary',
        'SuggestRelation'
    ]
    res = sisense_conn.call_api('GET', '/api/v1/notebooks?notebookType=CustomCodeTransformation')
    current_trans = json.loads(res.text)
    for i in current_trans:
        logger.info(f"Found notebook {i['id']}-{i['uuid']} at {i['codePath']}")
    for i in current_trans:
        if i['notebookType'] == 'CustomCodeTransformation':
            if i['displayName'] in current_notebooks_name:
                logger.info(f"Deleting {i['uuid']}")
                url_suffix = '/api/v1/notebooks/' + i['uuid']
                url = sisense_conn.sisense_base_url + url_suffix
                res = requests.delete(url, headers=sisense_conn.headers, timeout=350)
                logger.info(f'Delete result: {res.status_code}')


def uninstall_blox_actions(sisense_conn):
    res = sisense_conn.call_api('GET', '/api/v1/getSnippets/BloX?snippetType=actions')
    res_json = res.json()
    bloxType = {
        "DataSuggest",
        "DataSearch",
        "DataConnect",
        "WidgetSummary",
        "DashboardSummary"
    }
    for i in res_json:
        if i['title'] == 'My Actions':
            for element in i['elements']:
                if element['title'] in bloxType:
                    logger.info(f"Removing action {element['title']}")
                    data = {"type": element['title']}
                    res = sisense_conn.call_api('POST', '/api/v1/deleteCustomAction/BloX', payload=data)
                    logger.info(f"Remove result: {res.status_code}")


def uninstall_dashboard(sisense_conn):
    logger.info("Removing dashboard")
    res = sisense_conn.call_api('GET', '/api/v1/dashboards')
    res_json = res.json()
    for i in res_json:
        if i['title'] == 'Blox AI':
            url_suffix = '/api/v1/dashboards/' + i['oid']
            url = sisense_conn.sisense_base_url + url_suffix
            res = requests.delete(url, headers=sisense_conn.headers, timeout=350)
            logger.info(f"Removal result: {res.status_code}-{res.text}")


def uninstall_data_model(sisense_conn):
    logger.info(f"Stopping cube AITransformation")
    res = sisense_conn.call_api('POST', '/api/elasticubes/LocalHost/AITransformation/stop')
    logger.info(f"Stop results: {res.text}")
    res = sisense_conn.call_api('GET', '/api/v2/datamodels/schema')
    res_json = res.json()
    for i in res_json:
        if i['title'] == "AITransformation":
            logger.info(f"Removing {i['title']}: {i['oid']}")
            url_suffix = '/api/v2/datamodels/' + i['oid']
            url = sisense_conn.sisense_base_url + url_suffix
            res = requests.delete(url, headers=sisense_conn.headers, timeout=350)
            logger.info(f"Delete result: {res.text}")


def delete_remote_files(config, sisense_conn):
    user = config["user"]
    ip = config["ip"]
    password = config["password"]
    ssh_key = config["ssh_key"]
    ssh_key = None if ssh_key == "" else ssh_key
    ssh = SSHClient()
    ssh.load_system_host_keys()
    logger.info("Connecting to instance")
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip, 22, user, password, key_filename=ssh_key)
    logger.info("Connected")
    destination_full_path = '/opt/sisense/storage/notebooks/custom_code_notebooks'
    custom_libraries = ['AIIntegration.py', 'AIQueries.py', 'AIUtils.py', 'InferenceQuestionType.py']
    for lib in custom_libraries:
        full_path = os.path.join(destination_full_path, lib)
        cmd_to_execute = f"rm {full_path}"
        logger.info(f"Executing {cmd_to_execute}")
        ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(cmd_to_execute)
    notebooks = os.path.join(destination_full_path, "notebooks")
    list_dir = f"ls {notebooks}"
    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(list_dir)
    output = ssh_stdout.read().decode("utf-8").split("\n")
    candidates = ["DashboardSummary", "DataConnect", "DataSearch", "DataSuggest", "WidgetSummary"]
    for file in output:
        if any([i in file for i in candidates]):
            full_path = os.path.join(notebooks, file)
            cmd_to_execute = f"rm -rf {full_path}"
            logger.info(f"Executing {cmd_to_execute}")
            ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(cmd_to_execute)

    command = "rm -rf /opt/sisense/storage/plugins/BloxAISummary /opt/sisense/storage/branding/BloxAI"
    logger.info(f"Executing {command}")
    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(command)

def fix_files():
    ai_queries_file_name = './custom_code_notebooks/utils/AIQueries.py'
    with open(ai_queries_file_name, 'r+') as file:
        data = file.read()
        res = data.replace('# Un comment OPENAI #','')
        file.seek(0)
        file.write(res)
        file.truncate()
def uninstall(config: dict):
    api = get_sisense_api(config)
    uninstall_notebooks(api)
    uninstall_dashboard(api)
    uninstall_data_model(api)
    uninstall_blox_actions(api)
    delete_remote_files(config, api)


if __name__ == '__main__':
    with open("config.json") as src:
        config = json.load(src)
    mode = config["mode"]
    confirm = input(f"Confirm {mode} [y/n]:\t")
    if confirm.lower() != "y":
        sys.exit(0)
    set_environ(config)
    if config["mode"] == "install":
        fix_files()
        install(config)
    else:
        uninstall(config)
