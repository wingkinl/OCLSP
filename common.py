import originpro as op
import os
from pathlib import Path
import tkinter as tk
import json

APP_NAME = "OriginC Autocomplete"

def OCLSP_Print(*args, **kwargs):
    print(f"[OCLSP]", *args, **kwargs)

def OCLSP_PrintAppBanner():
    OCLSP_Print(f"{APP_NAME} 2026.01")
    OCLSP_Print("Powered by cpptools, introduces IntelliSense for Origin C.")
    OCLSP_Print("This app is not affiliated with, endorsed by, or sponsored by")
    OCLSP_Print("OriginLab, Microsoft, or any other organization, in any way.")
    OCLSP_Print("Kenny Liu.")
    OCLSP_Print("Installing...")

def OCLSP_PopupChoice(title, message, buttons):
    """
    Creates a popup window with custom buttons.
    Returns the text of the button clicked, or None if the window was closed.
    """
    root = tk.Tk()
    root.withdraw()  # Hide the main root window

    popup = tk.Toplevel(root)
    popup.title(title)
    
    # 1. Prevent resizing (optional, but looks better for popups)
    popup.resizable(False, False)

    # 2. Create the content
    # We use a main frame with padding to ensure content isn't touching the edges
    main_frame = tk.Frame(popup, padx=20, pady=20)
    main_frame.pack(fill=tk.BOTH, expand=True)

    # Label: We set a wraplength so long text doesn't make the window extremely wide
    # Justify LEFT or CENTER depending on preference
    lbl = tk.Label(
        main_frame, 
        text=message, 
        font=("Arial", 11), 
        wraplength=400,  # Max width in pixels before wrapping text
        justify=tk.LEFT
    )
    lbl.pack(side=tk.TOP, fill=tk.X, pady=(0, 15)) # Add space below label

    choice = {"value": None}

    def on_click(btn_text):
        choice["value"] = btn_text
        popup.destroy()

    # Button Container
    btn_frame = tk.Frame(main_frame)
    btn_frame.pack(side=tk.TOP, fill=tk.X)

    for btn_text in buttons:
        b = tk.Button(
            btn_frame, 
            text=btn_text, 
            # We remove fixed 'width' so it auto-fits text, 
            # but use pack(fill=tk.X) to make them all stretch to the same width
            command=lambda t=btn_text: on_click(t)
        )
        # ipadx/ipady adds internal padding to make buttons look "chunky" and clickable
        b.pack(side=tk.TOP, fill=tk.X, pady=3, ipadx=10, ipady=3)

    # --- AUTO-CENTERING LOGIC ---
    
    # 3. Force Tkinter to calculate the size of the widgets
    popup.update_idletasks() 

    # 4. Get the calculated size
    width = popup.winfo_width()
    height = popup.winfo_height()

    # 5. Get the screen size
    screen_width = popup.winfo_screenwidth()
    screen_height = popup.winfo_screenheight()

    # 6. Calculate the X and Y coordinates to center the window
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)

    # 7. Apply the geometry position (without forcing a specific size)
    popup.geometry(f"+{x}+{y}")

    # ----------------------------

    popup.grab_set()
    root.wait_window(popup)
    root.destroy()
    
    return choice["value"]

def OCLSP_GetDownloadDirForCpptools():
    uff = op.path()
    cpptools_path = os.path.join(uff, "OCLSP")
    return cpptools_path

def OCLSP_GetOriginLSPConfigJsonPath():
    org_ver = op.org_ver()
    if org_ver < 10.35:
        lsp_config = os.path.join(op.path(), "LSP.json")
    else:
        lsp_config = os.path.join(OCLSP_GetCurUserOriginAppDataPath(), "LSP.json")
    return lsp_config

def OCLSP_GetOriginAppPath():
    # C:\Users\Kenny\AppData\Local\OriginLab\Apps\OC LSP
    return op.get_lt_str("%@A") + op.get_lt_str("%@X")

def OCLSP_GetAllUserOriginAppDataPath():
    # C:\ProgramData\OriginLab\103b\
    return op.get_lt_str('%@R')

def OCLSP_GetCurUserOriginAppDataPath():
    # C:\Users\kenny\AppData\Local\OriginLab\103b\
    return op.get_lt_str('%@Y')

def OCLSP_GetCpptoolsExtensionPath():
    """
    Locates the ms-vscode.cpptools extension folder.
    Returns: list of Path objects (empty if not found)
    """
    # Standard VS Code extension directory is ~/.vscode/extensions
    home_dir = Path.home()
    extensions_dir = home_dir / ".vscode" / "extensions"

    if not extensions_dir.exists():
        OCLSP_Print(f"Extension directory not found at: {extensions_dir}")
        return []

    found_candidates = []
    # We look for folders starting with "ms-vscode.cpptools"
    # Example: ms-vscode.cpptools-1.22.11-win32-x64
    target_prefix = "ms-vscode.cpptools"

    downloaded_cpptools_path = OCLSP_GetDownloadDirForCpptools()
    downloaded_cpptools_path += "\\extension\\bin\\cpptools.exe"
    if os.path.isfile(downloaded_cpptools_path):
        found_candidates.append(downloaded_cpptools_path)
        OCLSP_Print(f"Downloaded cpptools path is at {downloaded_cpptools_path}")

    config_json_path = os.path.join(OCLSP_GetOriginAppPath(), "OCLSP.json")
    OCLSP_Print(f"config path is at {config_json_path}")
    if os.path.isfile(config_json_path):
        with open(config_json_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            if "cpptools" in config:
                last_used_cpptools_path = config["cpptools"]
                if last_used_cpptools_path not in found_candidates:
                    OCLSP_Print(f"Last used cpptools path is at {last_used_cpptools_path}")
                    found_candidates.append(last_used_cpptools_path)

    try:
        for entry in extensions_dir.iterdir():
            if entry.is_dir() and entry.name.startswith(target_prefix):
                cpptools_exe = os.path.join(entry, "bin", "cpptools.exe")
                if os.path.isfile(cpptools_exe) and cpptools_exe not in found_candidates:
                    found_candidates.append(str(cpptools_exe))
                    OCLSP_Print(f"Found cpptools extension at: {cpptools_exe}")
    except Exception as e:
        OCLSP_Print(f"Error reading extension directory: {e}")
        return []

    if len(found_candidates) == 0:
        return []

    return found_candidates
