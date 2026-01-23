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
    lsp_config = OCLSP_GetLSPConfigJsonPath()
    return OCLSP_ReadJsonFromFile(lsp_config)

def OCLSP_RemoveOCLSPFromOriginLSPJson(lsp_file):
    lsp_data = OCLSP_ReadJsonFromFile(lsp_file)
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
                        with open(lsp_file, "w", encoding="utf-8") as f:
                            try:
                                json.dump(lsp_data, f, indent=4, default=str)
                                cache_dir = os.path.join(os.path.dirname(lsp_file), "OCLSP", "cache")
                                if os.path.isdir(cache_dir):
                                    shutil.rmtree(cache_dir)
                                    OCLSP_Print(f"OCLSP cache directory {cache_dir} is removed.")

                                OCLSP_Print(f"OCLSP is removed from {lsp_file}.")
                                return True
                            except json.JSONDecodeError as e:
                                OCLSP_Print(f"Error writing to {lsp_file}: {e}")
    return False


def OCLSP_RemoveLSPConfigInInstalledList(lsp_config):
    config_json_path = os.path.join(OCLSP_GetOriginAppPath(), "OCLSP.json")
    if not os.path.exists(config_json_path):
        return
    setings = OCLSP_ReadJsonFromFile(config_json_path)
    if "installed_orgin_lsp" in setings:
        installed_lsp = setings["installed_orgin_lsp"]
        if lsp_config in installed_lsp:
            installed_lsp.remove(lsp_config)

        if isinstance(installed_lsp, list):
            for item in installed_lsp:
                OCLSP_RemoveOCLSPFromOriginLSPJson(item)
            installed_lsp.clear()

        with open(config_json_path, "w", encoding="utf-8") as f:
            try:
                json.dump(setings, f, indent=4)
            except json.JSONDecodeError as e:
                OCLSP_Print(f"Error writing to {config_json_path}: {e}")

if __name__ == '__main__':
    lsp_config = OCLSP_GetLSPConfigJsonPath()
    if OCLSP_RemoveOCLSPFromOriginLSPJson(lsp_config):
        OCLSP_RemoveLSPConfigInInstalledList(lsp_config)

    lsp_dir = OCLSP_GetDownloadDirForCpptools()
    if lsp_dir and os.path.isdir(lsp_dir):
        nn = op.messagebox(f"Are you sure to remove OCLSP directory {lsp_dir}?", True)
        if nn:
            shutil.rmtree(lsp_dir)
            OCLSP_Print(f"OCLSP directory {lsp_dir} is removed.")
    OCLSP_Print("Finished uninstalling.")