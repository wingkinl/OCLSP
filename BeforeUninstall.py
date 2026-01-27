import originpro as op
from common import *
import json
import shutil

def OCLSP_ReadJsonFromFile(path):
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return data
            except json.JSONDecodeError as e:
                OCLSP_Print(f"Error parsing {path}: {e}")
    return None

def OCLSP_ReadLSPConfig():
    lsp_config = OCLSP_GetOriginLSPConfigJsonPath()
    return OCLSP_ReadJsonFromFile(lsp_config)

def OCLSP_RemoveOCLSPFromOriginLSPJson(installation_item):
    """
    Remove OCLSP from LSP.json
    Remove storage directory
    Update OCLSP.json
    The structure of OCLSP.json is:
    {
        "cpptools": "C:\\Users\\Kenny\\.vscode\\extensions\\ms-vscode.cpptools-1.29.3-win32-x64\\bin\\cpptools.exe",
        "installed_orgin_lsp": [
            {
                "config": "C:\\Users\\Kenny\\AppData\\Local\\OriginLab\\103\\LSP.json",
                "storage": "C:\\Users\\Kenny\\AppData\\Local\\OriginLab\\103\\OCLSP\\storage"
            }
        ]
    }
    """
    lsp_json_file = installation_item["config"]
    lsp_data = OCLSP_ReadJsonFromFile(lsp_json_file)
    if lsp_data:
        if (
            lsp_data
            and isinstance(lsp_data, dict)
            and "LSPList" in lsp_data
        ):
            lsp_list = lsp_data["LSPList"]
            if isinstance(lsp_list, list):
                for client in lsp_list:
                    if ( isinstance(client, dict) and client.get("Lang") == 1):
                        lsp_list.remove(client)
                        with open(lsp_json_file, "w", encoding="utf-8") as f:
                            try:
                                json.dump(lsp_data, f, indent=4, default=str)
                                OCLSP_Print(f"OCLSP is removed from {lsp_json_file}.")
                            except json.JSONDecodeError as e:
                                OCLSP_Print(f"Error writing to {lsp_json_file}: {e}")
    storage_dir = installation_item["storage"]
    if os.path.isdir(storage_dir):
        shutil.rmtree(storage_dir)
        OCLSP_Print(f"OCLSP storage directory {storage_dir} is removed.")


def OCLSP_RemoveLSPConfigInInstalledList(cur_lsp_json_file):
    config_json_path = os.path.join(OCLSP_GetOriginAppPath(), "OCLSP.json")
    if not os.path.exists(config_json_path):
        return
    setings = OCLSP_ReadJsonFromFile(config_json_path)
    if "installed_orgin_lsp" in setings:
        installed_lsp = setings["installed_orgin_lsp"]

        if isinstance(installed_lsp, list):
            for item in installed_lsp:
                if item["config"] != cur_lsp_json_file:
                    OCLSP_RemoveOCLSPFromOriginLSPJson(item)
            installed_lsp.clear()

        with open(config_json_path, "w", encoding="utf-8") as f:
            try:
                json.dump(setings, f, indent=4)
            except json.JSONDecodeError as e:
                OCLSP_Print(f"Error writing to {config_json_path}: {e}")

if __name__ == '__main__':
    lsp_json_file = OCLSP_GetOriginLSPConfigJsonPath()
    installation_item = {
        "config": lsp_json_file,
        "storage": OCLSP_GetStoragePath()
    }
    OCLSP_RemoveOCLSPFromOriginLSPJson(installation_item)
    OCLSP_RemoveLSPConfigInInstalledList(lsp_json_file)

    lsp_dir = OCLSP_GetDownloadDirForCpptools()
    if lsp_dir and os.path.isdir(lsp_dir):
        nn = op.messagebox(f"Are you sure to remove cpptools {lsp_dir}?", True)
        if nn:
            shutil.rmtree(lsp_dir)
            OCLSP_Print(f"cpptools directory {lsp_dir} is removed.")
    OCLSP_Print("Finished uninstalling.")