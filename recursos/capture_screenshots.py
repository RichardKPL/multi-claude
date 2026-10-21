"""Render the real Tk UI with isolated, fictional profiles for the website.

Run on Windows: python recursos/capture_screenshots.py [language ...]
No Claude processes, account data or registry settings are accessed.
"""
import ctypes
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    "en": ("Personal", "Work", "Studies"),
    "pt": ("Pessoal", "Trabalho", "Estudos"),
    "es": ("Personal", "Trabajo", "Estudios"),
    "fr": ("Personnel", "Travail", "Études"),
    "de": ("Privat", "Arbeit", "Studium"),
    "it": ("Personale", "Lavoro", "Studio"),
    "ru": ("Личное", "Работа", "Учёба"),
    "ja": ("個人", "仕事", "学習"),
    "zh": ("个人", "工作", "学习"),
    "ko": ("개인", "업무", "학습"),
}


def capture(widget, path):
    widget.update()
    time.sleep(0.25)
    widget.update()
    hwnd = ctypes.windll.user32.GetParent(widget.winfo_id())
    ImageGrab.grab(window=hwnd).save(path)
    print(path.relative_to(ROOT), flush=True)


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    with tempfile.TemporaryDirectory(prefix="multi-claude-screenshots-") as sandbox:
        os.environ["MULTI_CLAUDE_HOME"] = sandbox
        loader = importlib.machinery.SourceFileLoader("multi_claude_demo", str(ROOT / "Multi Claude.pyw"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        app_module = importlib.util.module_from_spec(spec)
        loader.exec_module(app_module)
        app_module.achar_claude = lambda: "demo-only"
        app_module.devolver_registros = lambda: None
        app_module.App.vigiar_login = lambda self: None
        app_module.App.atualizar_estado = lambda self: None
        app_module.cfg_set("idioma", "en")
        app_module.cfg_set("tema", "claro")
        app_module.cfg_set("geometria", "1100x650+30+30")
        app = app_module.App()
        try:
            for lang in sys.argv[1:] or NAMES:
                out = ROOT / "docs" / "img" / lang
                out.mkdir(parents=True, exist_ok=True)
                with app_module.db() as db:
                    db.execute("DELETE FROM perfis")
                    for number, (name, photo) in enumerate(zip(NAMES[lang], ("astronaut.png", "fox.png", "owl.png"))):
                        app._inserir(db, name, pasta=str(Path(sandbox) / f"profile-{number}"), foto=photo)
                app.lang = lang
                app.estado = {p[2]: state for p, state in zip(app.perfis(), ((True, True), (True, False), (False, False)))}
                app.mudar_tema("claro")
                capture(app, out / "principal-claro.png")
                app.mudar_tema("escuro")
                capture(app, out / "principal-escuro.png")
                for filename, show in (
                    ("fotos", lambda: app.escolher_foto(app.perfis()[0])),
                    ("boas-vindas", app.boas_vindas),
                    ("configuracoes", app.configuracoes),
                ):
                    show()
                    dialog = next(w for w in app.winfo_children() if isinstance(w, app_module.Janela))
                    if filename == "configuracoes":
                        dialog.geometry("560x850+50+30")
                    capture(dialog, out / (filename + ".png"))
                    dialog.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    main()
