import originpro as op
import os
import json
from common import *
import json
import platform
import zipfile
import tkinter as tk
from tkinter import filedialog
import glob
import shutil
import urllib.request
import urllib.error

def OCLSP_FindClient():
    lsp_config = OCLSP_GetLSPConfigJsonPath()
    if os.path.isfile(lsp_config):
        with open(lsp_config, "r", encoding="utf-8") as f:
            try:
                lsp_data = json.load(f)
                if (
                    lsp_data
                    and isinstance(lsp_data, dict)
                    and "LSPList" in lsp_data
                ):
                    lsp_list = lsp_data["LSPList"]
                    if isinstance(lsp_list, list):
                        for client in lsp_list:
                            if ( isinstance(client, dict) and client.get("Lang") == 1):  # 1 means OC
                                # Found LSP client for OC
                                OCLSP_Print(f"LSP client for OC is found in {lsp_config}")
                                return True
            except json.JSONDecodeError as e:
                OCLSP_Print(f"Error parsing {lsp_config}: {e}")
    return False

def OCLSP_GetCpptoolsExtensionUrl():
    # Determine platform suffix
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        plat = "windows-x64"
    else:
        OCLSP_Print("No suitable cpptools VSIX found for", plat)
        return None

    # Query GitHub API for latest release
    api_url = "https://api.github.com/repos/microsoft/vscode-cpptools/releases/latest"
    try:
        OCLSP_Print("Querying for latest release info of cpptools...")
        with urllib.request.urlopen(api_url) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        OCLSP_Print("Failed to fetch latest release info of cpptools:", e)
        return None

    # Find the matching asset
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".vsix") and plat in name:
            download_url = asset["browser_download_url"]
            OCLSP_Print("Latest cpptools VSIX:", download_url)
            return download_url

    OCLSP_Print("No suitable cpptools VSIX found for", plat)
    return None

def OCLSP_DownloadCpptoolsExtension():
    url = OCLSP_GetCpptoolsExtensionUrl()
    if url:
        OCLSP_Print("Downloading the extension from:")
        OCLSP_Print(url)
        cpptools_path = OCLSP_GetDownloadDirForCpptools()
        if not os.path.isdir(cpptools_path):
            os.makedirs(cpptools_path)
        # Download the file
        vsix_filename = url.split("/")[-1]
        vsix_path = os.path.join(cpptools_path, vsix_filename)
        op.lt_exec(f'break.open("Downloading cpptools")')
        op.lt_exec(f'break.min=0')
        op.lt_exec(f'break.max=100')
        try:
            def download_progress(block_num, block_size, total_size):
                if op.lt_int('break.abort'):
                    raise Exception("Download aborted by user")
                downloaded = block_num * block_size
                percent = min(downloaded * 100 / total_size, 100)
                op.lt_exec(f'break.set({percent})')
            urllib.request.urlretrieve(url, vsix_path, reporthook=download_progress)
            op.lt_exec(f'break.close()')
            OCLSP_Print("Downloaded VSIX to:")
            OCLSP_Print(vsix_path)
        except Exception as e:
            op.lt_exec(f'break.close()')
            OCLSP_Print("Failed to download VSIX:", e)
            return None

        # Unzip the file
        try:
            with zipfile.ZipFile(vsix_path, 'r') as zip_ref:
                OCLSP_Print("Removing old extension directory...")
                ext_dir = os.path.join(cpptools_path, "extension")
                if os.path.isdir(ext_dir):
                    shutil.rmtree(ext_dir)
                OCLSP_Print("Extracting VSIX...")   
                zip_ref.extractall(cpptools_path)
                OCLSP_Print("Extracted VSIX to:")
                OCLSP_Print(cpptools_path)
        except zipfile.BadZipFile as e:
            OCLSP_Print("Failed to extract VSIX (bad zip):", e)
            return None
        except Exception as e:
            OCLSP_Print("Failed to extract VSIX:", e)
            return None

        # Remove the downloaded VSIX file
        try:
            os.remove(vsix_path)
            OCLSP_Print("Removed downloaded VSIX file:")
            OCLSP_Print(vsix_path)
        except Exception as e:
            OCLSP_Print("Failed to remove VSIX file:", e)
        cpptools_path = os.path.join(cpptools_path, "extension", "bin", "cpptools.exe")
        if not os.path.isfile(cpptools_path):
            OCLSP_Print("cpptools.exe not found in the downloaded VSIX.")
            return None
        OCLSP_Print("cpptools extension installed successfully at:")
        OCLSP_Print(cpptools_path)
        return cpptools_path
    else:
        OCLSP_Print("Could not retrieve download URL.")
        OCLSP_Print("Please download the extension from:")
        OCLSP_Print("https://github.com/microsoft/vscode-cpptools/releases/latest")
        return None

def OCLSP_BrowseForCpptools():
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    file_path = filedialog.askopenfilename(
        title="Select cpptools.exe",
        filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
    )
    root.destroy()
    return file_path

def OCLSP_GetOriginPythonDLLPath():
    exeDir = op.path('e')
    origin_python_dll_path = os.path.join(exeDir, "64bit", "PyDLLs")
    return origin_python_dll_path

def OCLSP_GetOriginPythonLibPaths():
    exeDir = op.path('e')
    # Search for python*.zip under exeDir
    zip_pattern = os.path.join(exeDir, "python*.zip")
    python_zips = glob.glob(zip_pattern)
    python_zip_path = python_zips[0] if python_zips else os.path.join(exeDir, "Python311.zip")
    origin_python_dll_path = os.path.join(exeDir, "64bit", "PyDLLs")
    appDataPath = OCLSP_GetAllUserOriginAppDataPath()
    origin_py_lib_path = [
        python_zip_path,
        os.path.join(python_zip_path, "site-packages"),
        origin_python_dll_path,
        os.path.join(appDataPath, "PyPackage", "Py3")
    ]
    return origin_py_lib_path

def OCLSP_GetOrignPythonPath():
    origin_python_dll_path = OCLSP_GetOriginPythonDLLPath()
    origin_python_path = os.path.join(origin_python_dll_path, "python.exe")
    return origin_python_path

def OCLSP_UpdateLSPWithCpptools(cpptools_path):
    uff = op.path()
    lsp_json_path = OCLSP_GetLSPConfigJsonPath()
    lsp_data = {}
    if os.path.isfile(lsp_json_path):
        try:
            with open(lsp_json_path, "r") as f:
                lsp_data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            OCLSP_Print("Error loading LSP.json:", e)
    # Ensure lsp_data is a dict and contains "LSPList" as a list
    if not isinstance(lsp_data, dict):
        lsp_data = {}
    if "LSPList" not in lsp_data or not isinstance(lsp_data["LSPList"], list):
        lsp_data["LSPList"] = []
    oclsp_py_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "OCLSP.py")

    # Look for an existing LSP entry with Lang = 1 (Origin C)
    existing_entry = None
    for idx, entry in enumerate(lsp_data["LSPList"]):
        if isinstance(entry, dict) and entry.get("Lang") == 1:
            existing_entry = idx
            break
    oclsp_py_path_quote = f'"{oclsp_py_path}"'
    cpptools_path_quote = f'"{cpptools_path}"'

    new_entry = {
        "Lang": 1,
        "Name": "OCLSP_cpptools",
        "Options": {
            "ipc": "stdio",
            "process": {
                "exe": OCLSP_GetOrignPythonPath(),
                "arg": [oclsp_py_path_quote, cpptools_path_quote],
                "env" : {
                    "PYTHONPATH": ";".join(OCLSP_GetOriginPythonLibPaths()),
                    "PYTHONHOME": OCLSP_GetOriginPythonDLLPath(),
                    "OCLSP_TRACE": False,
                    "OCLSP_LOG": False,
                    "ORGDIR_EXE": op.path('e'),
                    "ORGDIR_UFF": uff,
                    "ORGDIR_USER_APPDATA": OCLSP_GetCurUserOriginAppDataPath(),
                    "ORG_VER": op.org_ver()
                }
            }
        }
    }
    if existing_entry is None:
        lsp_data["LSPList"].append(new_entry)
    else:
        lsp_data["LSPList"][existing_entry] = new_entry
    
    try:
        with open(lsp_json_path, "w") as f:
            json.dump(lsp_data, f, indent=4, default=str)
    except IOError as e:
        OCLSP_Print(f"Error saving {lsp_json_path}:", e)
        return None
    OCLSP_Print("LSP.json updated to use cpptools extension for Origin C at:")
    OCLSP_Print(cpptools_path)
    OCLSP_Print("You may need to restart Origin for the changes to take effect.")
    config_json_path = os.path.join(OCLSP_GetOriginAppPath(), "OCLSP.json")

    settings = {
        "cpptools": cpptools_path
    }

    try:
        with open(config_json_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        OCLSP_Print("Error loading config file:", e)
        return None

    if "cpptools" not in settings:
        settings["cpptools"] = cpptools_path

    # Ensure the list exists and avoid duplicates
    if "installed_orgin_lsp" not in settings:
        settings["installed_orgin_lsp"] = []
    if lsp_json_path not in settings["installed_orgin_lsp"]:
        settings["installed_orgin_lsp"].append(lsp_json_path)

    try:
        with open(config_json_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        OCLSP_Print(f"Error saving config file {config_json_path}:", e)
        return None
    return None

def OCLSP_SelectCpptoolsFromList(cpptools_paths):
    root = tk.Tk()
    root.withdraw()
    popup = tk.Toplevel(root)
    popup.title("OC LSP")
    main_frame = tk.Frame(popup, padx=20, pady=20)
    main_frame.pack(fill=tk.BOTH, expand=True)
    label_text = (
        "cpptools installations found.\n\n"
        "Double-click an item to use it, or click Download to get a new copy."
    )
    lbl = tk.Label(
        main_frame,
        text=label_text,
        font=("Arial", 11),
        justify=tk.LEFT
    )
    lbl.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))
    list_frame = tk.Frame(main_frame)
    list_frame.pack(fill=tk.BOTH, expand=True)
    max_len = max(len(str(p)) for p in cpptools_paths)
    list_width = min(max_len + 2, 100)
    list_height = min(len(cpptools_paths), 10)
    scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    listbox = tk.Listbox(
        list_frame,
        width=list_width,
        height=list_height,
        yscrollcommand=scrollbar.set,
        selectmode=tk.SINGLE
    )
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=listbox.yview)
    for p in cpptools_paths:
        listbox.insert(tk.END, str(p))
    if cpptools_paths:
        listbox.selection_set(0)
    result = {"action": None, "path": None}
    def use_selected(event=None):
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        result["action"] = "use"
        result["path"] = cpptools_paths[idx]
        popup.destroy()
    def on_download():
        result["action"] = "download"
        popup.destroy()
    def on_browse():
        result["action"] = "browse"
        popup.destroy()
    def on_cancel():
        result["action"] = "cancel"
        popup.destroy()
    listbox.bind("<Double-Button-1>", use_selected)
    listbox.bind("<Return>", use_selected)
    btn_frame = tk.Frame(main_frame)
    btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
    download_btn = tk.Button(btn_frame, text="Download", command=on_download)
    download_btn.pack(side=tk.LEFT, padx=(0, 5))
    browse_btn = tk.Button(btn_frame, text="Browse", command=on_browse)
    browse_btn.pack(side=tk.LEFT, padx=(0, 5))
    cancel_btn = tk.Button(btn_frame, text="Cancel", command=on_cancel)
    cancel_btn.pack(side=tk.LEFT)
    popup.update_idletasks()
    width = popup.winfo_width()
    height = popup.winfo_height()
    screen_width = popup.winfo_screenwidth()
    screen_height = popup.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    popup.geometry(f"+{x}+{y}")
    popup.grab_set()
    root.wait_window(popup)
    root.destroy()
    return result["action"], result["path"]

def OCLSP_TryInstall(from_installer):
    OCLSP_PrintAppBanner()
    # Warn user about cpptools dependency and license
    OCLSP_Print("This tool depends on cpptools, a C/C++ Extension for Visual Studio Code by Microsoft.")
    OCLSP_Print("Use at your own risks. Please read the license carefully:")
    OCLSP_Print("https://marketplace.visualstudio.com/items/ms-vscode.cpptools/license")
    if from_installer:
        warning_msg = (
            "This tool depends on cpptools, a C/C++ Extension for Visual Studio Code by Microsoft.\n\n"
            "Use at your own risks. Please read the license carefully:\n\n"
            "https://marketplace.visualstudio.com/items/ms-vscode.cpptools/license\n\n"
            "Do you want to continue?"
        )
        if OCLSP_PopupChoice(title="OC LSP - Warning", message=warning_msg, buttons=["Yes", "No"]) != "Yes":
            OCLSP_Print("User declined to continue.")
            return
    cpptools_paths = OCLSP_GetCpptoolsExtensionPath()
    if not cpptools_paths:
        OCLSP_Print("cpptools extension not found.")
        choice = OCLSP_PopupChoice(title="OC LSP", message="cpptools extension not found, do you want to download it or browse the one on your computer?\n", buttons=["Download", "Browse"])
        if choice == "Download":
            cpptools_path = OCLSP_DownloadCpptoolsExtension()
            if cpptools_path:
                OCLSP_UpdateLSPWithCpptools(cpptools_path)
        elif choice == "Browse":
            cpptools_path = OCLSP_BrowseForCpptools()
            if cpptools_path and os.path.isfile(cpptools_path):
                OCLSP_UpdateLSPWithCpptools(cpptools_path)
            else:
                OCLSP_Print("Invalid path provided.")
        else:
            OCLSP_Print("No valid option selected.")
    else:
        action, cpptools_path = OCLSP_SelectCpptoolsFromList(cpptools_paths)
        if action == "use":
            if cpptools_path and os.path.isfile(cpptools_path):
                OCLSP_UpdateLSPWithCpptools(cpptools_path)
            else:
                OCLSP_Print("Invalid path selected.")
        elif action == "download":
            cpptools_path = OCLSP_DownloadCpptoolsExtension()
            if cpptools_path and os.path.isfile(cpptools_path):
                OCLSP_UpdateLSPWithCpptools(cpptools_path)
        elif action == "browse":
            cpptools_path = OCLSP_BrowseForCpptools()
            if cpptools_path and os.path.isfile(cpptools_path):
                OCLSP_UpdateLSPWithCpptools(cpptools_path)
            else:
                OCLSP_Print("Invalid path provided.")
        else:
            OCLSP_Print("User cancelled.")

def InstallOCLSP(from_installer):
    if OCLSP_FindClient():
        nn = op.messagebox('OC LSP already configured, do you want to update it?', True)
        if nn:
            OCLSP_TryInstall(from_installer)
    else:
        OCLSP_TryInstall(from_installer)

if __name__ == "__main__":
    InstallOCLSP(True)
