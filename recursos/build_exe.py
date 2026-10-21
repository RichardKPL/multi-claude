# =============================================================================
#  Multi Claude — script de build do executável
#  Copyright (C) 2026 Richard KPL — https://github.com/RichardKPL
#  Licensed under the GNU GPL v3 with additional terms (see LICENSE and NOTICE).
# =============================================================================
"""Gera "Multi Claude.exe" (portátil, arquivo único) na pasta do app.

O .exe leva só o ícone e as fotos de perfil padrão. Nada de dados do usuário
(perfis.db, log.txt, dados/, fotos enviadas pelo usuário) entra no executável.

Uso:  python recursos/build_exe.py
Precisa de: pip install pyinstaller pillow
"""
import os
import re
import shutil
import subprocess
import sys

from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
BUILD = os.path.join(RAIZ, "build")
FONTE = os.path.join(RAIZ, "Multi Claude.pyw")


def versao():
    with open(FONTE, encoding="utf8") as f:
        return re.search(r'^VERSAO = "([\d.]+)"', f.read(), re.M).group(1)


def icone_valido():
    """Gera recursos/icone.ico de verdade (vários tamanhos) a partir do icone.png."""
    png = os.path.join(AQUI, "icone.png")
    ico = os.path.join(AQUI, "icone.ico")
    origem = png if os.path.exists(png) else ico
    img = Image.open(origem).convert("RGBA")
    img.save(ico, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return ico


def arquivo_versao(v):
    n = tuple(int(x) for x in (v.split(".") + ["0"] * 4)[:4])
    caminho = os.path.join(BUILD, "versao.txt")
    os.makedirs(BUILD, exist_ok=True)
    with open(caminho, "w", encoding="utf8") as f:
        f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={n}, prodvers={n}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', 'Richard KPL'),
      StringStruct('FileDescription', 'Multi Claude'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'Multi Claude'),
      StringStruct('LegalCopyright', '© 2026 Richard KPL — github.com/RichardKPL — GPL-3.0'),
      StringStruct('OriginalFilename', 'Multi Claude.exe'),
      StringStruct('ProductName', 'Multi Claude'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x0416, 1200])])
  ]
)
""")
    return caminho


def fotos_padrao():
    """Copia só as fotos padrão do app (sem as enviadas pelo usuário: usuario_*)."""
    destino = os.path.join(BUILD, "profile_pictures")
    shutil.rmtree(destino, ignore_errors=True)
    os.makedirs(destino)
    origem = os.path.join(RAIZ, "profile_pictures")
    for nome in sorted(os.listdir(origem)):
        if not nome.startswith("usuario_") and os.path.isfile(os.path.join(origem, nome)):
            shutil.copy2(os.path.join(origem, nome), destino)
    return destino


def main():
    v = versao()
    ico = icone_valido()
    fotos = fotos_padrao()
    sep = os.pathsep
    args = [
        sys.executable, "-m", "PyInstaller", FONTE,
        "--onefile", "--windowed", "--noconfirm", "--clean",
        "--name", "Multi Claude",
        "--icon", ico,
        "--version-file", arquivo_versao(v),
        "--add-data", f"{ico}{sep}recursos",
        "--add-data", f"{os.path.join(AQUI, 'icone.png')}{sep}recursos",
        "--add-data", f"{fotos}{sep}profile_pictures",
        "--distpath", os.path.join(RAIZ, "dist"),
        "--workpath", os.path.join(BUILD, "work"),
        "--specpath", BUILD,
    ]
    subprocess.run(args, check=True)
    shutil.rmtree(BUILD, ignore_errors=True)
    print(f"\nPronto: {os.path.join(RAIZ, 'dist', 'Multi Claude.exe')} (v{v})")


if __name__ == "__main__":
    main()
