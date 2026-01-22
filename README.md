# OCLSP
Language support for OriginC in Code Builder for Origin

Code Builder is the integrated development environment (IDE) built directly into OriginPro and Origin software by OriginLab.

It supports Auto Complete and Go to definition for python script files through [LSP](https://microsoft.github.io/language-server-protocol/), but OriginC is not supported.

This app aims to support OriginC via [cpptools](https://github.com/microsoft/vscode-cpptools).

With the help of cpptools, Code Builder will support:

- Auto Complete
- Go to definition (Press F11 on a symbol)
- Show document when hover on a symbol
