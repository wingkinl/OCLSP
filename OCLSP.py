import os
import sys
import subprocess
import threading
import json
import itertools
import queue
import time
import traceback
import ctypes
from pathlib import Path
from enum import IntEnum

_enable_log = False
_enable_trace = False
_enable_cpptools_trace = False
_ORGDIR_EXE = ""
_ORGDIR_UFF = ""
_ORGDIR_USER_APPDATA = ""
_DATASTORAGE_DIR = ""
_GLOBAL_OCLSP_CONFIG_JSON_PATH = ""
_GLOBAL_OCLSP_CONFIG = None
_CUR_VER_OCLSP_CONFIG_JSON_PATH = ""
_CUR_VER_OCLSP_CONFIG = None
# _ORG_VERSION is a floating numer, e.g. 10.350049
_ORG_VERSION = 10.350001
_CPPTOOLS_PATH = ""

# Global state for shutdown and synchronization
_shutdown_event = threading.Event()
_shutdown_lock = threading.Lock()
_cpptools_process = None
_server_stdin_lock = threading.Lock()
_client_stdout_lock = threading.Lock()
_log_lock = None
_log_lock_lazy_store = {}

def get_log_lock():
    global _log_lock
    if _log_lock is None:
        _log_lock = _log_lock_lazy_store.setdefault("lock", threading.Lock())
    return _log_lock

def get_oclsp_config():
    global _GLOBAL_OCLSP_CONFIG
    if _GLOBAL_OCLSP_CONFIG is None:
        # Load Global Config
        global_config = {}
        if _GLOBAL_OCLSP_CONFIG_JSON_PATH and os.path.isfile(_GLOBAL_OCLSP_CONFIG_JSON_PATH):
            try:
                with open(_GLOBAL_OCLSP_CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
                    global_config = json.load(f)
            except Exception as e:
                _trace_log(f"Error reading global config {_GLOBAL_OCLSP_CONFIG_JSON_PATH}: {e}")
                global_config = {}
        
        # Load User Config (Versioned)
        user_config = {}
        if _CUR_VER_OCLSP_CONFIG_JSON_PATH and os.path.isfile(_CUR_VER_OCLSP_CONFIG_JSON_PATH):
            try:
                with open(_CUR_VER_OCLSP_CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
            except Exception as e:
                _trace_log(f"Error reading user config {_CUR_VER_OCLSP_CONFIG_JSON_PATH}: {e}")
                user_config = {}

        # Merge Configs
        # Start with global config
        _GLOBAL_OCLSP_CONFIG = global_config.copy()
        
        # Update with user config (scalars overwrite)
        for key, value in user_config.items():
            if key not in ["workspaceFolders", "additionalIncludePath"]:
                _GLOBAL_OCLSP_CONFIG[key] = value

        # Smart Merge: workspaceFolders
        # We want to merge workspace entries by matching URI (path).
        # If a workspace exists in both, we merge their properties (e.g. combine includePath).
        wf_global = global_config.get("workspaceFolders", [])
        wf_user = user_config.get("workspaceFolders", [])
        if not isinstance(wf_global, list): wf_global = []
        if not isinstance(wf_user, list): wf_user = []

        # Map normalized URI -> workspace dict
        wf_map = {}

        def normalize_wf_uri(folder_item):
            uri = folder_item.get("uri", "")
            # Normalize to lower case for key matching
            return uri.strip().lower()

        # 1. Add Global Workspaces
        for wf in wf_global:
            if isinstance(wf, dict):
                key = normalize_wf_uri(wf)
                if key:
                    # Deep copy to avoid mutating original global config if needed
                    wf_map[key] = json.loads(json.dumps(wf))

        # 2. Merge User Workspaces
        for wf in wf_user:
            if isinstance(wf, dict):
                key = normalize_wf_uri(wf)
                if not key:
                    continue
                
                if key in wf_map:
                    # Exists in global, merge it
                    existing = wf_map[key]
                    
                    # Merge includePath lists
                    existing_inc = existing.get("includePath", [])
                    new_inc = wf.get("includePath", [])
                    if not isinstance(existing_inc, list): existing_inc = []
                    if not isinstance(new_inc, list): new_inc = []
                    
                    # Combine and deduplicate include paths
                    # Use a set for deduplication, preserving order if possible
                    merged_inc = []
                    seen_inc = set()
                    for p in (existing_inc + new_inc):
                        if p and p not in seen_inc:
                            merged_inc.append(p)
                            seen_inc.add(p)
                    existing["includePath"] = merged_inc

                    # Overwrite other scalar properties from user config (e.g. name)
                    for k, v in wf.items():
                        if k != "includePath":
                            existing[k] = v
                else:
                    # New workspace, just add it
                    wf_map[key] = json.loads(json.dumps(wf))
        
        # 3. Inject Default Workspaces (XFC, AppXFC) if missing
        default_wfs = []
        if _ORGDIR_EXE:
            default_wfs.append({"name": "XFC", "path": os.path.join(_ORGDIR_EXE, "XFC")})
        if _ORGDIR_USER_APPDATA:
            default_wfs.append({"name": "AppXFC", "path": os.path.join(_ORGDIR_USER_APPDATA, "TMP", "OriginC", "X-Functions")})
            
        for item in default_wfs:
            try:
                uri_str = item["path"]
                key = uri_str.strip().lower()
                if key not in wf_map:
                    wf_map[key] = {
                        "uri": uri_str,
                        "name": item["name"]
                    }
            except Exception:
                pass

        _GLOBAL_OCLSP_CONFIG["workspaceFolders"] = list(wf_map.values())

        # Smart Merge: additionalIncludePath
        # Concatenate and deduplicate
        inc_global = global_config.get("additionalIncludePath", [])
        inc_user = user_config.get("additionalIncludePath", [])
        if not isinstance(inc_global, list): inc_global = []
        if not isinstance(inc_user, list): inc_user = []
        
        merged_additional_inc = []
        seen_additional_inc = set()
        for p in (inc_global + inc_user):
            if p and p not in seen_additional_inc:
                merged_additional_inc.append(p)
                seen_additional_inc.add(p)
                
        _GLOBAL_OCLSP_CONFIG["additionalIncludePath"] = merged_additional_inc

    return _GLOBAL_OCLSP_CONFIG

###############################################################################
# LSP framing (binary-safe)
###############################################################################

def read_exactly(stream, n):
    """
    Read exactly n bytes from stream.
    Returns bytes, or None if EOF is hit before n bytes are read.
    """
    data = b""
    while len(data) < n:
        chunk = stream.read(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def read_lsp_message(stream, from_lsp_server):
    """
    Read exactly one LSP message from stream.
    Returns raw JSON bytes, or None on EOF.
    """
    while True:
        # Check shutdown before blocking read (though readline might still block)
        if _shutdown_event.is_set():
            return None

        headers = {}
        while True:
            # readline on binary stream includes \n
            try:
                line = stream.readline()
            except (ValueError, OSError):
                return None

            if not line:
                return None
            
            # Decode carefully. LSP headers are ASCII.
            line_str = line.decode("ascii", errors="replace").strip()
            
            if line_str == "":
                break
            
            if ":" in line_str:
                key, value = line_str.split(":", 1)
                headers[key.lower()] = value.strip()

        length_str = headers.get("content-length")
        if length_str is None:
            continue

        try:
            length = int(length_str)
        except ValueError:
            continue
        
        body = read_exactly(stream, length)
        if body is None or len(body) != length:
            return None
            
        return body


def write_lsp_message(stream, body_bytes, to_lsp_server, lock=None):
    if _shutdown_event.is_set():
        return

    header = f"Content-Length: {len(body_bytes)}\r\n\r\n"
    data = header.encode("ascii") + body_bytes
    
    try:
        if lock:
            with lock:
                stream.write(data)
                stream.flush()
        else:
            stream.write(data)
            stream.flush()
    except (BrokenPipeError, OSError):
        # If pipe is broken, we probably should shut down
        trigger_shutdown("Write failed (BrokenPipe)")


def send_notification(stream, method, params, to_lsp_server, lock=None):
    msg = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params
    }
    body = json.dumps(msg).encode("utf-8")
    write_lsp_message(stream, body, to_lsp_server, lock)

###############################################################################
# Proxy request ID management
###############################################################################

_proxy_id_gen = itertools.count(start=1)
_pending_proxy_requests = set()
_id_map_cpptools_to_client = {}

###############################################################################
# Interception hooks
###############################################################################

def _handle_origin_initialize(msg, inject_queue):
    params = msg.setdefault("params", {})
    params["clientInfo"] = {
        "name": "Visual Studio Code",
        "version": "1.108.1",
    }
    opts = params.setdefault("initializationOptions", {})
    ocPath = os.path.join(_ORGDIR_EXE, "OriginC")
    params["rootPath"] = ocPath
    workspace_folders = [{
        "uri": Path(ocPath).absolute().as_uri(),
        "name": "OriginC"
    }]
    
    config = get_oclsp_config()
    if "workspaceFolders" in config:
        extra_folders = config["workspaceFolders"]
        if isinstance(extra_folders, list):
            for folder in extra_folders:
                if "uri" in folder and "name" in folder:
                    folder_copy = folder.copy()
                    uri = folder_copy.get("uri")
                    if uri and not uri.startswith("file://"):
                        uri = Path(uri).absolute().as_uri()
                        folder_copy["uri"] = uri
                    workspace_folders.append(folder_copy)
                    _trace_log(f"added extra workspace folder: {folder_copy}")

    params["workspaceFolders"] = workspace_folders
    if _enable_cpptools_trace:
        opts["loggingLevel"] = 1
        params["trace"] = "verbose"
    _trace_log(f"modified initalize request: {msg}")
    out = [json.dumps(msg).encode("utf-8")]
    return out

def send_cpptools_didChangeCppProperties(inject_queue, workspace_item):
    json_path = Path(__file__).with_name("cpptools_didChangeCppProperties.json")
    try:
        with json_path.open("r", encoding="utf-8") as f:
            params = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        params = {}  # fallback to empty dict if file missing or invalid
    ocPath = os.path.join(_ORGDIR_EXE, "OriginC")

    # Extract folder_path from workspace_item
    folder_path = None
    if workspace_item:
        uri = workspace_item.get("uri", "")
        if uri.lower().startswith("file:///"):
            folder_path = uri[8:]
            folder_path = os.path.normpath(folder_path)
        elif os.path.isabs(uri):
             folder_path = uri

    if not folder_path:
        _trace_log(f"send_cpptools_didChangeCppProperties: could not determine folder_path for {workspace_item}")
        return

    is_oc_folder = folder_path == ocPath

    # Always use ocPath/** as include path
    params["configurations"][0]["includePath"] = [f"{ocPath}/**"]

    config = get_oclsp_config()
    if not is_oc_folder:
        # 1. Global Additional Include Paths
        if "additionalIncludePath" in config:
            additional_paths = config["additionalIncludePath"]
            if isinstance(additional_paths, list):
                for path in additional_paths:
                    if path:
                        params["configurations"][0]["includePath"].append(f"{path}/**")
        
        # 2. Per-Workspace Include Paths
        if workspace_item and "includePath" in workspace_item:
            wf_includes = workspace_item["includePath"]
            if isinstance(wf_includes, list):
                for inc in wf_includes:
                    if inc:
                        params["configurations"][0]["includePath"].append(f"{inc}/**")

    # Extract major and first two decimals
    # Ensure we have a string representation of the version with enough decimals
    ver_str = f"{_ORG_VERSION:.6f}"
    parts = ver_str.split(".")
    major = int(parts[0])
    minor_str = (parts[1] + "00")[:2]
    # e.g. 10.35 -> 0x0A35 (Major converted to Hex, Minor kept as digits)
    orgOCVerHex = f"0x{major:02X}{minor_str}"
    params["configurations"][0]["defines"].append(f"_OC_VER={orgOCVerHex}")
    params["configurations"][0]["forcedInclude"] = [
        # somehow cpptools doesn't recognize Folder class, it seems like folder.h is ignored
        # Forcing it to include fixes it
        os.path.join(ocPath, "System", "folder.h")
    ]
    params["workspaceFolderUri"] = Path(folder_path).absolute().as_uri()
    proxy_id = next(_proxy_id_gen)
    _trace_log(f"[IDGEN] injected cpptools/didChangeCppProperties proxy_id={proxy_id}")
    injected = {
        "jsonrpc": "2.0",
        "id": proxy_id,
        "method": "cpptools/didChangeCppProperties",
        "params": params,
    }
    _pending_proxy_requests.add(proxy_id)
    inject_queue.put(json.dumps(injected).encode("utf-8"))

def send_cpptools_initialize(inject_queue):
    # example: \UFF\OCLSP\extension\bin\cpptools.exe
    cpptoolsBinDir = os.path.dirname(_CPPTOOLS_PATH)
    cpptoolsExtDir = os.path.dirname(cpptoolsBinDir)

    # Load base cpptools initialization parameters from JSON file
    json_path = Path(__file__).with_name("cpptools_initialize.json")
    try:
        with json_path.open("r", encoding="utf-8") as f:
            cpptools_init_params = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cpptools_init_params = {}  # fallback to empty dict if file missing or invalid

    # Override/customize with runtime paths
    cpptools_init_params.update({
        "extensionPath": cpptoolsExtDir,
        "databaseStoragePath": os.path.join(_DATASTORAGE_DIR, "OCLSP", "storage", "databaseStorage"),
        "workspaceStoragePath": os.path.join(_DATASTORAGE_DIR, "OCLSP", "storage", "workspaceStorage"),
        "cacheStoragePath": os.path.join(_DATASTORAGE_DIR, "OCLSP", "storage", "cacheStorage"),
        "edgeMessagesDirectory": os.path.join(cpptoolsBinDir, "messages", "en-us"),
    })

    # Ensure settings and workspaceFolderSettings exist
    if "settings" not in cpptools_init_params:
        cpptools_init_params["settings"] = {}

    if "workspaceFolderSettings" not in cpptools_init_params["settings"]:
        cpptools_init_params["settings"]["workspaceFolderSettings"] = [{}]
    elif not isinstance(cpptools_init_params["settings"]["workspaceFolderSettings"], list) or not cpptools_init_params["settings"]["workspaceFolderSettings"]:
        cpptools_init_params["settings"]["workspaceFolderSettings"] = [{}]

    # Update the uri in the first element
    ocPath = os.path.join(_ORGDIR_EXE, "OriginC")
    firstWorkspaceFolderSettings = cpptools_init_params["settings"]["workspaceFolderSettings"][0]
    firstWorkspaceFolderSettings.update({
        "defaultSystemIncludePath": [f"{ocPath}/System"],
        "uri": Path(ocPath).absolute().as_uri(),
    })

    config = get_oclsp_config()
    if "workspaceFolders" in config:
        extra_folders = config["workspaceFolders"]
        if isinstance(extra_folders, list):
            for folder in extra_folders:
                if "uri" in folder:
                    uri = folder.get("uri")
                    if uri and not uri.startswith("file://"):
                        uri = Path(uri).absolute().as_uri()
                    
                    new_settings = firstWorkspaceFolderSettings.copy()
                    new_settings["uri"] = uri
                    cpptools_init_params["settings"]["workspaceFolderSettings"].append(new_settings)

    proxy_id = next(_proxy_id_gen)
    _trace_log(f"[IDGEN] injected cpptools/initialize proxy_id={proxy_id}")
    injected = {
        "jsonrpc": "2.0",
        "id": proxy_id,
        "method": "cpptools/initialize",
        "params": cpptools_init_params,
    }
    _pending_proxy_requests.add(proxy_id)
    inject_queue.put(json.dumps(injected).encode("utf-8"))

def _handle_origin_initialized(msg, inject_queue):
    
    send_cpptools_initialize(inject_queue)

    ocPath = os.path.join(_ORGDIR_EXE, "OriginC")
    
    # Create a temporary workspace item for OriginC
    oc_workspace_item = {
        "uri": ocPath,
        "name": "OriginC"
    }
    send_cpptools_didChangeCppProperties(inject_queue, oc_workspace_item)

    config = get_oclsp_config()
    if "workspaceFolders" in config:
        extra_folders = config["workspaceFolders"]
        if isinstance(extra_folders, list):
            for folder in extra_folders:
                if "uri" in folder:
                    send_cpptools_didChangeCppProperties(inject_queue, folder)

    return None


def _handle_origin_textDocument_hover(msg, inject_queue):
    # cpptools does not handle textDocument/hover, but handles cpptools/hover
    msg["method"] = "cpptools/hover"
    return [json.dumps(msg).encode("utf-8")]

def _handle_origin_textDocument_documentSymbol(msg, inject_queue):
    # cpptools does not handle textDocument/documentSymbol, but handles cpptools/getDocumentSymbols
    msg["method"] = "cpptools/getDocumentSymbols"
    
    # Align payload shape to VS Code's format: move uri at the top level
    if "params" in msg and "textDocument" in msg["params"]:
        uri = msg["params"]["textDocument"].get("uri")
        if uri:
            msg["params"] = {"uri": uri}
    
    return [json.dumps(msg).encode("utf-8")]

def _handle_origin_textDocument_references(msg, inject_queue):
    # cpptools does not handle textDocument/references, but handles cpptools/findAllReferences
    # Note: cpptools/findAllReferences params structure is very similar to RenameParams (includes newName)
    msg["method"] = "cpptools/findAllReferences"
    
    if "params" in msg:
        params = msg["params"]
        # Standard params: { textDocument, position, context }
        # cpptools params: { textDocument, position, newName }
        if "newName" not in params:
            params["newName"] = ""
        # Remove context if present (cpptools doesn't seem to use it in this custom request)
        if "context" in params:
            del params["context"]
            
    return [json.dumps(msg).encode("utf-8")]

_origin_method_handlers = {
    "initialize": _handle_origin_initialize,
    "initialized": _handle_origin_initialized,
    "textDocument/hover": _handle_origin_textDocument_hover,
    "textDocument/documentSymbol": _handle_origin_textDocument_documentSymbol,
    "textDocument/references": _handle_origin_textDocument_references,
}


def handle_origin_client_message(body_bytes, inject_queue):
    """
    Handle messages from Origin → cpptools.
    Return a list of messages (bytes) to forward.
    """
    msg = json.loads(body_bytes)
    _trace_log(f"[Client]: {msg}")
    method = msg.get("method")
    handler = _origin_method_handlers.get(method)
    if handler is not None:
        out = handler(msg, inject_queue)
        if out is not None:
            return out
    return [body_bytes]


def _fix_completion_documentation(msg):
    result = msg.get("result")
    if not result:
        return
    
    items = []
    if isinstance(result, list):
        items = result
    elif isinstance(result, dict):
        items = result.get("items", [])
    
    # Sort items by sortText (fall back to label) and then by length
    def sort_key(item):
        if not isinstance(item, dict):
            return ("", 0)
        sort_text = item.get("sortText", "")
        if not sort_text:
            sort_text = item.get("label", "")
        return (sort_text, len(str(sort_text)))

    items.sort(key=sort_key)

    for item in items:
        if not isinstance(item, dict):
            continue
        doc = item.get("documentation")
        if isinstance(doc, dict):
            # MarkupContent: {kind: "...", value: "..."}
            # Replace with string value for older Origin versions
            item["documentation"] = doc.get("value", "")

def _handle_lsp_initialize(msg):
    # Modify the initialize response to enable hoverProvider
    # Ensure the result and capabilities exist
    if "result" not in msg:
        msg["result"] = {}
    if "capabilities" not in msg["result"]:
        msg["result"]["capabilities"] = {}
    if "general" not in msg["result"]["capabilities"]:
        msg["result"]["capabilities"]["general"] = {}
    if "result" in msg and "capabilities" in msg["result"]:
        msg["result"]["capabilities"]["hoverProvider"] = True
        msg["result"]["capabilities"]["documentSymbolProvider"] = True
        msg["result"]["capabilities"]["referencesProvider"] = True
        msg["result"]["capabilities"]["general"]["positionEncodings"] = ["utf-8"]
    _trace_log(f"modified initialize response: {msg}")
    out = [json.dumps(msg).encode("utf-8")]
    return out

def _handle_lsp_completion(msg):
    if _ORG_VERSION < 10.35:
        _fix_completion_documentation(msg)


def _handle_lsp_hover(msg):
    """
    Intercept and modify the hover response from cpptools before sending to Origin.
    """
    _trace_log(f"Intercepted cpptools/hover response: {msg}")
    
    result = msg.get("result")
    if result and "contents" in result:
        # contents: MarkedString | MarkedString[] | MarkupContent;
        contents = result["contents"]
        # Normalize contents to a list of {kind, value} objects
        if isinstance(contents, list):
            if len(contents) == 1 and "value" in contents[0] and "kind" not in contents[0]:
                contents[0]["kind"] = "markdown"
        elif isinstance(contents, dict):
            if "value" in contents and "kind" not in contents:
                contents["kind"] = "markdown"

def _flatten_symbols(symbols, parent_name=None):
    flat_list = []
    for sym in symbols:
        # Create a shallow copy to avoid modifying the original dict in nested calls unexpectedly
        # though we are popping children, so we are modifying it.
        
        # 1. Handle detail
        if parent_name:
            sym['detail'] = parent_name
        else:
            # Ensure detail is a string if it exists, or empty string
            detail = sym.get('detail')
            if detail is None or not isinstance(detail, str):
                sym['detail'] = ""
        
        # 2. Extract children
        children = sym.pop('children', [])
        
        flat_list.append(sym)
        
        if children:
            flat_list.extend(_flatten_symbols(children, sym.get('name', '')))
            
    return flat_list

def _handle_lsp_documentSymbol(msg):
    """
    Intercept and modify the documentSymbol response from cpptools.
    cpptools returns { "symbols": [...] }, but LSP expects [...] or null.
    """
    _trace_log(f"Intercepted cpptools/getDocumentSymbols response: {msg}")
    
    result = msg.get("result")
    if isinstance(result, dict) and "symbols" in result:
        msg["result"] = result["symbols"]
    
    # For older Origin versions, flatten the symbols list
    if _ORG_VERSION < 10.35:
        symbols = msg.get("result")
        if isinstance(symbols, list):
            msg["result"] = _flatten_symbols(symbols)


class ReferenceType(IntEnum):
    Confirmed = 0
    ConfirmationInProgress = 1
    Comment = 2
    String = 3
    Inactive = 4
    CannotConfirm = 5
    NotAReference = 6

def _handle_lsp_references(msg):
    """
    Intercept and modify the references response from cpptools.
    cpptools returns { "referenceInfos": [...] }, but LSP expects Location[].
    """
    _trace_log(f"Intercepted cpptools/findAllReferences response: {msg}")
    
    result = msg.get("result")
    locations = []

    allowed_ref_type = [
        ReferenceType.Confirmed,
        ReferenceType.ConfirmationInProgress,
        #ReferenceType.Comment,
        #ReferenceType.String,
        ReferenceType.Inactive,
        ReferenceType.CannotConfirm,
        #ReferenceType.NotAReference
    ]
    config = get_oclsp_config()
    if "allowed_ref_type" in config:
        allowed_ref_type = config["allowed_ref_type"]
    
    if isinstance(result, dict) and "referenceInfos" in result:
        infos = result["referenceInfos"]
        for info in infos:
            # cpptools ReferenceInfo: { file: string, position: Position, text: string, type: ReferenceType }
            # standard Location: { uri: string, range: Range }
            
            file_path = info.get("file")
            position = info.get("position")
            
            if file_path and position:
                ref_type = info.get("type", 0)
                if ref_type not in allowed_ref_type:
                    continue
                uri = Path(file_path).as_uri()
                
                # cpptools returns just a start position. We need a range.
                # We'll create a zero-length range or try to guess length from text if reliable.
                # For now, safe bet is zero-length range at the start position.

                # enum ReferenceType {
                #     Confirmed,
                #     ConfirmationInProgress,
                #     Comment,
                #     String,
                #     Inactive,
                #     CannotConfirm,
                #     NotAReference
                # }
                
                loc = {
                    "uri": uri,
                    "range": {
                        "start": position,
                        "end": position
                    },
                    "text": info.get("text", ""),
                    "type": ref_type
                }
                locations.append(loc)
                
    msg["result"] = locations


_lsp_method_handlers = {
    "initialize": _handle_lsp_initialize,
    "textDocument/completion": _handle_lsp_completion,
    "cpptools/hover": _handle_lsp_hover,
    "cpptools/getDocumentSymbols": _handle_lsp_documentSymbol,
    "cpptools/findAllReferences": _handle_lsp_references,
}


def handle_lsp_server_message(body_bytes):
    """
    Handle messages from cpptools -> Origin.
    Return modified bytes, or None to swallow.
    """
    try:
        msg = json.loads(body_bytes)
    except Exception:
        _trace_log(f"[LSP Server raw]: {body_bytes!r}")
        return None

    _trace_log(f"[LSP Server]: {msg}")

    if "id" in msg:
        msg_id = msg["id"]
        if msg_id in _pending_proxy_requests:
            _trace_log(f"[IDMAP] swallow injected response id={msg_id}")
            _pending_proxy_requests.discard(msg_id)
            return None
        if msg_id in _id_map_cpptools_to_client:
            entry = _id_map_cpptools_to_client.pop(msg_id)
            
            # Handle tuple (client_id, method) or legacy client_id
            if isinstance(entry, tuple):
                client_id, method = entry
            else:
                client_id = entry
                method = None

            _trace_log(f"[IDMAP] map back cpptools_id={msg_id} -> client_id={client_id}")
            msg["id"] = client_id

            # Dispatch to handler based on method
            handler = _lsp_method_handlers.get(method)
            if handler:
                handler(msg)

            return json.dumps(msg).encode("utf-8")

    return body_bytes

###############################################################################
# Worker threads
###############################################################################

def origin_client_to_lsp_server(client_in, server_out, inject_queue):
    try:
        while not _shutdown_event.is_set():
            body = read_lsp_message(client_in, from_lsp_server=False)
            if body is None:
                # EOF from client means we should shut down
                trigger_shutdown("EOF from Origin client")
                break

            out_messages = handle_origin_client_message(body, inject_queue)
            for out in out_messages:
                try:
                    msg = json.loads(out)
                except Exception:
                    # Forward raw bytes if not valid JSON
                    write_lsp_message(server_out, out, to_lsp_server=True, lock=_server_stdin_lock)
                    continue

                if "id" in msg:
                    client_id = msg["id"]
                    method = msg.get("method")
                    cpptools_id = next(_proxy_id_gen)
                    _id_map_cpptools_to_client[cpptools_id] = (client_id, method)
                    msg["id"] = cpptools_id
                    _trace_log(f"[IDMAP] client_id={client_id} -> cpptools_id={cpptools_id}")
                    out = json.dumps(msg).encode("utf-8")

                write_lsp_message(server_out, out, to_lsp_server=True, lock=_server_stdin_lock)
    except Exception as e:
        log_exception(f"origin_client_to_lsp_server: {e}")
        trigger_shutdown("Exception in origin_client_to_lsp_server")


def lsp_server_to_origin_client(server_in, client_out):
    try:
        while not _shutdown_event.is_set():
            body = read_lsp_message(server_in, from_lsp_server=True)
            if body is None:
                trigger_shutdown("EOF from LSP server")
                break

            out = handle_lsp_server_message(body)
            if out is not None:
                write_lsp_message(client_out, out, to_lsp_server=False, lock=_client_stdout_lock)
    except Exception as e:
        log_exception(f"lsp_server_to_origin_client: {e}")
        trigger_shutdown("Exception in lsp_server_to_origin_client")


def msg_injection_to_lsp_server(server_out, inject_queue):
    try:
        while not _shutdown_event.is_set():
            try:
                body = inject_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            _trace_log(f"[Injected to LSP]: {body}")
            write_lsp_message(server_out, body, to_lsp_server=True, lock=_server_stdin_lock)
    except Exception as e:
        log_exception(f"msg_injection_to_lsp_server: {e}")
        trigger_shutdown("Exception in msg_injection_to_lsp_server")


def handle_lsp_server_stderr(stderr, client_out):
    try:
        while not _shutdown_event.is_set():
            try:
                line = stderr.readline()
            except (ValueError, OSError):
                break

            if not line:
                break

            text = line.decode("utf-8", errors="replace").rstrip()
            _trace_log(f"[LSP Server stderr]: {text}")
            send_notification(
                client_out,
                method="cpptools/stderr",
                params={
                    "message": text,
                    "timestamp": time.time()
                }
                , to_lsp_server=False,
                lock=_client_stdout_lock
            )
    except Exception as e:
        log_exception(f"handle_lsp_server_stderr: {e}")
        # Don't necessarily shutdown on stderr error, but logging it is good
        pass

###############################################################################
# Logging (NEVER stdout)
###############################################################################
def log_to_file(file, msg):
    try:
        with get_log_lock():
            with open(file, "a", encoding="utf-8") as f:
                ts = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
                f.write(f"\n[{ts}] {msg}\n")
    except Exception:
        pass

def log_exception(where):
    try:
        with get_log_lock():
            with open(os.path.join(_DATASTORAGE_DIR, "OCLSP", "oclsp_proxy_error.log"), "a", encoding="utf-8") as f:
                ts = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
                f.write(f"\n[{ts}] {where}\n")
                traceback.print_exc(file=f)
    except Exception:
        pass

def trace_log_noop(msg):
    pass

_trace = trace_log_noop
_log = trace_log_noop
_trace_log = trace_log_noop

def trace_impl(msg):
    ctypes.windll.kernel32.OutputDebugStringW(msg)

def log_impl(msg):
    log_to_file(os.path.join(_DATASTORAGE_DIR, "OCLSP", "oclsp_proxy.log"), msg)

def trace_log_impl(msg):
    msg = "[OCLSP] " + msg + "\n"
    _trace(msg)
    _log(msg)

###############################################################################
# Main
###############################################################################

def trigger_shutdown(reason):
    global _cpptools_process
    with _shutdown_lock:
        if _shutdown_event.is_set():
            return
        _shutdown_event.set()
        
        msg = f"Triggering shutdown: {reason}"
        if reason != "EOF from Origin client":
            log_exception(msg)
        _trace_log(msg)  # Also log to main trace/log file so it's visible
        
        # Try to send exit notification if possible
        # Note: We don't do this because writing might block or be the cause of crash.
        # Direct termination is safer for cleanup in crash scenarios.

        if _cpptools_process:
            try:
                _trace_log("Terminating cpptools...")
                _cpptools_process.terminate()
            except Exception:
                pass

def main(cpptools_path):
    global _enable_log, _enable_trace, _enable_cpptools_trace
    global _cpptools_process
    global _ORGDIR_EXE, _ORGDIR_UFF, _ORGDIR_USER_APPDATA
    _enable_log = os.environ.get("OCLSP_LOG", "False").lower() == "true"
    _enable_trace = os.environ.get("OCLSP_TRACE", "False").lower() == "true"
    _enable_cpptools_trace = os.environ.get("OCLSP_CPPTOOLS_TRACE", "False").lower() == "true"
    _ORGDIR_EXE = os.environ.get("ORGDIR_EXE", "")
    _ORGDIR_UFF = os.environ.get("ORGDIR_UFF", "")
    _ORGDIR_USER_APPDATA = os.environ.get("ORGDIR_USER_APPDATA", "")
    global _DATASTORAGE_DIR
    _DATASTORAGE_DIR = _ORGDIR_USER_APPDATA if os.path.exists(_ORGDIR_USER_APPDATA) else _ORGDIR_UFF
    global _GLOBAL_OCLSP_CONFIG_JSON_PATH
    _GLOBAL_OCLSP_CONFIG_JSON_PATH = os.environ.get("OCLSP_CONFIG_JSON_PATH", "")
    global _CUR_VER_OCLSP_CONFIG_JSON_PATH
    _CUR_VER_OCLSP_CONFIG_JSON_PATH = os.path.join(_DATASTORAGE_DIR, "OCLSP", "OCLSP_User.json")

    global _trace_log, _trace, _log
    _trace = trace_impl if _enable_trace else trace_log_noop
    _log = log_impl if _enable_log else trace_log_noop
    _trace_log = trace_log_impl if (_enable_trace or _enable_log) else trace_log_noop
    _trace_log("Starting up..")
    
    global _CPPTOOLS_PATH
    _CPPTOOLS_PATH = cpptools_path
    global _ORG_VERSION
    _ORG_VERSION = float(os.environ.get("ORG_VER", "10.0"))

    _cpptools_process = subprocess.Popen(
        [cpptools_path, "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0
    )

    injected_msg_queue = queue.Queue()

    threads = [
        threading.Thread(
            target=origin_client_to_lsp_server,
            args=(sys.stdin.buffer, _cpptools_process.stdin, injected_msg_queue),
            daemon=True
        ),
        threading.Thread(
            target=lsp_server_to_origin_client,
            args=(_cpptools_process.stdout, sys.stdout.buffer),
            daemon=True
        ),
        threading.Thread(
            target=msg_injection_to_lsp_server,
            args=(_cpptools_process.stdin, injected_msg_queue),
            daemon=True
        ),
        threading.Thread(
            target=handle_lsp_server_stderr,
            args=(_cpptools_process.stderr, sys.stdout.buffer),
            daemon=True
        ),
    ]

    for t in threads:
        t.start()

    # Wait for cpptools to exit or shutdown signal
    while True:
        try:
            # Check if process has exited
            code = _cpptools_process.poll()
            if code is not None:
                _trace_log(f"cpptools exited with code {code}")
                trigger_shutdown(f"cpptools exited with code {code}")
                break
            
            if _shutdown_event.is_set():
                _trace_log("Shutdown event detected in main loop")
                try:
                    _cpptools_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    _trace_log("Killing cpptools...")
                    _cpptools_process.kill()
                break
                
            time.sleep(0.1)
        except KeyboardInterrupt:
            trigger_shutdown("KeyboardInterrupt")
            break
        except Exception as e:
            trigger_shutdown(f"Main loop exception: {e}")
            break

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cpptools_path = sys.argv[1]
        try:
            main(cpptools_path)
        except Exception as e:
            log_exception("Caught exception in main")
