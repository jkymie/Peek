# Gera o dist\Peek.exe: arquivo único, sem janela de terminal.
#
#   pyinstaller peek.spec
#
# Antes, host\bin precisa ter o peek-audio.exe (compilado do audio-helper) e o
# cloudflared.exe (baixado da Cloudflare). As páginas web\ e host\gui\ui\ já vêm
# geradas no repositório.

import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH)
BIN = ROOT / "host" / "bin"

for exe in ("peek-audio.exe", "cloudflared.exe"):
    if not (BIN / exe).is_file():
        raise SystemExit(f"Falta host\\bin\\{exe} (veja o README).")

VERSION = re.search(
    r'__version__ = "([^"]+)"', (ROOT / "host" / "__init__.py").read_text(encoding="utf-8")
).group(1)
numbers = tuple(int(n) for n in VERSION.split(".")) + (0,) * (4 - len(VERSION.split(".")))

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "041604B0",  # português (Brasil), Unicode
                    [
                        StringStruct("ProductName", "Peek"),
                        StringStruct("FileDescription", "Peek"),
                        StringStruct("FileVersion", VERSION),
                        StringStruct("ProductVersion", VERSION),
                        StringStruct("OriginalFilename", "Peek.exe"),
                        StringStruct("InternalName", "Peek"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
    ],
)

a = Analysis(
    [str(ROOT / "host" / "__main__.py")],
    # packaging\stubs vem antes das bibliotecas: troca o OpenCV por um módulo vazio.
    pathex=[str(ROOT), str(ROOT / "packaging" / "stubs")],
    datas=[
        (str(ROOT / "web"), "web"),
        (str(ROOT / "host" / "gui" / "ui"), "host/gui/ui"),
    ],
    binaries=[
        (str(BIN / "peek-audio.exe"), "host/bin"),
        (str(BIN / "cloudflared.exe"), "host/bin"),
    ],
    excludes=["tkinter", "pytest", "pytestqt", "tools", "tests"],
)
# Ferramentas de desenvolvedor do navegador embutido (~80 MB): não servem para quem
# transmite.
a.datas = [d for d in a.datas if "qtwebengine_devtools_resources" not in d[0]]
# O hook do OpenCV ainda junta os arquivos dele por causa do nome "cv2". O substituto
# fica: o mesmo hook o inclui como arquivo solto ("cv2.py"), não no PYZ.
a.binaries = [b for b in a.binaries if not b[0].startswith("cv2\\")]
a.datas = [d for d in a.datas if not d[0].startswith("cv2\\")]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="Peek",
    console=False,
    upx=False,  # UPX aumenta os falsos positivos de antivírus
    version=version_info,
)
