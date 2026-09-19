"""組込版Pythonが、Windowsに標準で入っているDLLと、フォルダ内のDLLだけに、依存していることを確認する（#168）。

使い方（pefileが要る）:
    pip install pefile
    python scripts/check-embed-dependencies.py dist/stage/Obunzu-<バージョン>-win-x64/python-embed

フォルダの中にも、Windowsの標準にもないDLLがあれば、その名前を出して、終了コード1で終わる。
Microsoft Visual C++の再頒布可能パッケージ（vcruntime140など）は、フォルダに同梱されているため、
別のインストールは要らない。`api-ms-win-*`・`ext-ms-*`は、Windowsが提供するAPIセット（Universal CRTを含む）である。
"""
import os
import sys

import pefile

# Windows 10/11に、標準で入っているDLL（System32）。これらは、クリーンなWindowsにもある。
WINDOWS_DLLS = {
    "kernel32.dll", "user32.dll", "advapi32.dll", "ws2_32.dll", "bcrypt.dll", "crypt32.dll", "rpcrt4.dll",
    "ole32.dll", "oleaut32.dll", "version.dll", "cabinet.dll", "msi.dll", "winmm.dll", "iphlpapi.dll",
    "propsys.dll", "shell32.dll", "gdi32.dll", "shlwapi.dll", "ntdll.dll", "ucrtbase.dll", "mswsock.dll",
}


def main(root):
    bundled = {name.lower() for name in os.listdir(root)}
    unknown = {}
    for name in sorted(os.listdir(root)):
        if not name.lower().endswith((".exe", ".dll", ".pyd")):
            continue
        pe = pefile.PE(os.path.join(root, name), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        entries = list(getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])) + list(getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []))
        for entry in entries:
            dll = entry.dll.decode().lower()
            if dll in bundled or dll in WINDOWS_DLLS or dll.startswith(("api-ms-win-", "ext-ms-")):
                continue
            unknown.setdefault(dll, []).append(name)
    for dll, users in sorted(unknown.items()):
        print(f"NG  {dll}  （{', '.join(users[:3])}が必要）")
    print("すべて、フォルダ内か、Windows標準のDLLです。" if not unknown else f"\n標準にないDLLが {len(unknown)} 件あります。")
    return 1 if unknown else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
