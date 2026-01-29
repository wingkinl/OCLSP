# OCLSP (OriginC Autocomplete)
Language support for OriginC in Code Builder for Origin

Code Builder is the integrated development environment (IDE) built directly into OriginPro and Origin software by OriginLab.

It supports Auto Complete and Go to definition for python script files through [LSP](https://microsoft.github.io/language-server-protocol/), but OriginC is not supported.

This app aims to support OriginC via [cpptools](https://github.com/microsoft/vscode-cpptools).

With the help of cpptools, Code Builder will support:

- Auto Complete
- Go to definition (Press F11 on a symbol)
- Show document when hover on a symbol
- List symbols in active document (Alt+M)
- Find all references to a selected symbol (Shift+Alt+F)

This tool depends on cpptools, a C/C++ Extension for Visual Studio Code by Microsoft.

**Use at your own risks.**

**Please read the license carefully:**

https://marketplace.visualstudio.com/items/ms-vscode.cpptools/license
https://github.com/microsoft/vscode-cpptools/blob/main/RuntimeLicenses/cpptools-LICENSE.txt
https://github.com/microsoft/vscode-cpptools/blob/main/RuntimeLicenses/cpptools-srv-LICENSE.txt



Auto Complete

![AutoComplete](AutoComplete.png)



Signature Help

![image-SignatureHelp](SignatureHelp.png)



List symbols in active document (Alt+M)

![image-ListSymbols](ListSymbols.png)



Hover symbol info

![image-HoverSymbol](HoverSymbol.png)

