# =============================================================================
#  Multi Claude — https://github.com/RichardKPL/multi-claude
#  Copyright (C) 2026 Richard KPL — https://github.com/RichardKPL
#
#  This program is free software: you can redistribute it and/or modify it
#  under the terms of the GNU General Public License version 3 as published by
#  the Free Software Foundation, with the additional terms of section 7 listed
#  in the NOTICE file (preservation of the original author attribution).
#
#  This program is distributed in the hope that it will be useful, but WITHOUT
#  ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
#  FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file for details.
#
#  Multi Claude is an independent project, not affiliated with Anthropic.
# =============================================================================
"""Multi Claude - abre várias instâncias do Claude Desktop, cada uma com sua conta.

Cada perfil usa uma pasta de dados própria (--user-data-dir), então o login
de um não interfere no outro. Os perfis ficam salvos em perfis.db (SQLite) e
as fotos de perfil na pasta profile_pictures (qualquer imagem lá vira opção).

Login: o navegador devolve o login por um link claude://. O Claude da Microsoft
Store registra esse protocolo no próprio pacote, então o Windows sempre manda o
link para o Claude principal: ele inicia um Claude.exe passageiro com o link na
linha de comando. Durante o "modo login" o programa vigia os processos novos,
lê esse link, encerra o processo passageiro (para o Claude principal não abrir)
e entrega o link ao Claude do perfil. Como alternativa manual, dá para copiar o
link claude:// (área de transferência) ou usar o botão "Colar link".
"""
import contextlib
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
import winreg
from tkinter import filedialog

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:  # sem Pillow: avatares só com a inicial
    Image = None

APP = "Multi Claude"
VERSAO = "2.1.0"
AUTOR = "Richard KPL"
GITHUB = "https://github.com/RichardKPL"
REPO = "https://github.com/RichardKPL/multi-claude"
COPYRIGHT = f"© 2026 {AUTOR}"

CONGELADO = getattr(sys, "frozen", False)
PASTA_APP = os.path.dirname(sys.executable if CONGELADO else os.path.abspath(__file__))
RECURSOS = getattr(sys, "_MEIPASS", PASTA_APP)  # dentro do .exe, os arquivos embutidos ficam aqui
# Portátil: tudo fica ao lado do programa (MULTI_CLAUDE_HOME troca o local, útil para testes).
BASE = os.path.abspath(os.environ.get("MULTI_CLAUDE_HOME") or PASTA_APP)
DB = os.path.join(BASE, "perfis.db")
LOG = os.path.join(BASE, "log.txt")
FOTOS = os.path.join(BASE, "profile_pictures")
DADOS = os.path.join(BASE, "dados")  # pastas de dados dos Claude de cada perfil
ICONE = os.path.join(RECURSOS, "recursos", "icone.ico")
ICONE_PNG = os.path.join(RECURSOS, "recursos", "icone.png")
EXT_IMAGEM = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tif", ".tiff")
LOGIN_TIMEOUT = 300  # segundos esperando o login
LINK_LOGIN = re.compile(r"^claude://(login/|claude\.ai/(magic-link|sso-callback|login)|.*[?&#](code|token)=)")
FONTE = "Segoe UI"

# ---------- temas ----------

TEMAS = {
    "escuro": dict(BG="#1a1918", PAINEL="#232220", CARD="#262523", HOVER="#2f2e2b", BORDA="#36342f",
                   TEXTO="#f5f4ef", SUB="#a39f95", BTN="#33312d", BTN_HOVER="#3f3c37",
                   CHIP="#2f2d2a", MENU="#2a2926"),
    "claro": dict(BG="#f4f2ec", PAINEL="#ffffff", CARD="#ffffff", HOVER="#faf8f3", BORDA="#e2ded5",
                  TEXTO="#1f1e1d", SUB="#6d6a62", BTN="#ece8df", BTN_HOVER="#e1dcd1",
                  CHIP="#f1eee7", MENU="#ffffff"),
}
FIXAS = dict(ACCENT="#d97757", ACCENT_HOVER="#e4876a", VERDE="#5fa85e", AMARELO="#d39b33", VERMELHO="#d9534f")
AVATARES = ["#d97757", "#6a9bd8", "#5fa85e", "#b77fd0", "#d39b33", "#4fb0a8", "#d86a8f"]
C = {}  # paleta ativa


def idioma_do_windows():
    """Idioma sugerido na primeira abertura, a partir do idioma do Windows."""
    try:
        primario = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except Exception:
        return "en"
    return {0x16: "pt", 0x09: "en", 0x0A: "es", 0x0C: "fr", 0x07: "de", 0x10: "it",
            0x19: "ru", 0x11: "ja", 0x04: "zh", 0x12: "ko"}.get(primario, "en")


def tema_sistema():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "claro" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "escuro"
    except OSError:
        return "escuro"


def aplicar_tema(escolha):
    efetivo = tema_sistema() if escolha == "sistema" else escolha
    C.clear()
    C.update(TEMAS[efetivo], **FIXAS)
    C["nome"] = efetivo
    return efetivo


def barra_titulo(janela):
    """Deixa a barra de título do Windows no mesmo tema (escuro/claro) da janela."""
    try:
        janela.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(janela.winfo_id())
        valor = ctypes.c_int(1 if C.get("nome") == "escuro" else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(valor), ctypes.sizeof(valor))
    except Exception:
        pass


def por_icone(janela):
    try:
        janela.iconbitmap(ICONE)
        return
    except tk.TclError:
        pass
    # .ico inválido (ex.: PNG renomeado): usa o PNG direto.
    for arq in (ICONE, ICONE_PNG):
        try:
            img = ImageTk.PhotoImage(Image.open(arq).convert("RGBA").resize((64, 64), Image.LANCZOS))
            janela.iconphoto(False, img)
            janela._icone = img
            return
        except Exception:
            continue


# ---------- idiomas ----------

IDIOMAS = [("pt", "Português (BR)"), ("en", "English"), ("es", "Español"), ("fr", "Français"),
           ("de", "Deutsch"), ("it", "Italiano"), ("ru", "Русский"), ("ja", "日本語"),
           ("zh", "中文"), ("ko", "한국어")]

T = {
    "pt": dict(
        sub="Várias contas do Claude Desktop, cada uma na sua janela.",
        ausente="Claude Desktop não encontrado. Instale-o primeiro.",
        novo="Novo perfil", nenhum="Nenhum perfil ainda", nenhum_sub="Crie um perfil para cada conta do Claude.",
        conectado="Conectado", desconectado="Sem login", aberto="Aberto", fechado="Fechado",
        aguard="Aguardando login…", abrir="Abrir", fechar="Fechar", entrar="Entrar", sair="Sair da conta",
        renomear="Renomear", pasta="Pasta de dados", excluir="Excluir", erro="Erro", foto="Foto de perfil",
        aguardando="Login em “{n}”: na janela do Claude, clique em “Continuar com Google” e escolha a conta. "
                   "Se o navegador perguntar, clique em “Abrir Claude”. O resto é automático.",
        colar="Colar link", cancelar="Cancelar", colar_pergunta="Cole o link claude:// do navegador:",
        invalido="O link precisa começar com claude://",
        enviado="✓ Login enviado para “{n}”.", esgotado="Tempo de login esgotado. Tente “Entrar” de novo.",
        novo_pergunta="Nome do perfil (ex.: Conta Trabalho):", existe="Já existe um perfil com esse nome.",
        renomear_pergunta="Novo nome:", excluir_q="Excluir o perfil “{n}”?",
        excluir_dados="Apagar também os dados desse perfil (login, sessões)?",
        sair_q="Sair da conta no perfil “{n}”?\nO Claude desse perfil será fechado.",
        saiu="Você saiu da conta em “{n}”.", idioma="Idioma", config="Configurações",
        aparencia="Aparência", claro="Claro", escuro="Escuro", sistema="Sistema", sobre="Sobre",
        versao="Versão", direitos="Todos os direitos reservados.", fotos_titulo="Foto de “{n}”",
        adicionar_img="Adicionar imagem…", abrir_fotos="Abrir pasta", sem_foto="Sem foto",
        fotos_dica="Qualquer imagem colocada na pasta profile_pictures aparece aqui.",
        imagens="Imagens", ok="OK", sim="Sim", nao="Não", img_erro="Não foi possível abrir essa imagem.",
        padrao=["Conta 1", "Conta 2"]),
    "en": dict(
        sub="Several Claude Desktop accounts, each in its own window.",
        ausente="Claude Desktop not found. Please install it first.",
        novo="New profile", nenhum="No profiles yet", nenhum_sub="Create one profile for each Claude account.",
        conectado="Signed in", desconectado="Not signed in", aberto="Open", fechado="Closed",
        aguard="Waiting for sign-in…", abrir="Open", fechar="Close", entrar="Sign in", sair="Sign out",
        renomear="Rename", pasta="Data folder", excluir="Delete", erro="Error", foto="Profile picture",
        aguardando="Signing in to “{n}”: in the Claude window, click “Continue with Google” and pick the account. "
                   "If the browser asks, click “Open Claude”. The rest is automatic.",
        colar="Paste link", cancelar="Cancel", colar_pergunta="Paste the claude:// link from the browser:",
        invalido="The link must start with claude://",
        enviado="✓ Sign-in sent to “{n}”.", esgotado="Sign-in timed out. Try “Sign in” again.",
        novo_pergunta="Profile name (e.g. Work account):", existe="A profile with that name already exists.",
        renomear_pergunta="New name:", excluir_q="Delete profile “{n}”?",
        excluir_dados="Also erase this profile's data (sign-in, sessions)?",
        sair_q="Sign out of profile “{n}”?\nThis profile's Claude will be closed.",
        saiu="You signed out of “{n}”.", idioma="Language", config="Settings",
        aparencia="Appearance", claro="Light", escuro="Dark", sistema="System", sobre="About",
        versao="Version", direitos="All rights reserved.", fotos_titulo="Picture for “{n}”",
        adicionar_img="Add image…", abrir_fotos="Open folder", sem_foto="No picture",
        fotos_dica="Any image placed in the profile_pictures folder shows up here.",
        imagens="Images", ok="OK", sim="Yes", nao="No", img_erro="Could not open that image.",
        padrao=["Account 1", "Account 2"]),
    "es": dict(
        sub="Varias cuentas de Claude Desktop, cada una en su ventana.",
        ausente="Claude Desktop no encontrado. Instálalo primero.",
        novo="Nuevo perfil", nenhum="Aún no hay perfiles", nenhum_sub="Crea un perfil para cada cuenta de Claude.",
        conectado="Conectado", desconectado="Sin sesión", aberto="Abierto", fechado="Cerrado",
        aguard="Esperando inicio de sesión…", abrir="Abrir", fechar="Cerrar", entrar="Iniciar sesión",
        sair="Cerrar sesión", renomear="Renombrar", pasta="Carpeta de datos", excluir="Eliminar", erro="Error",
        foto="Foto de perfil",
        aguardando="Iniciando sesión en “{n}”: en la ventana de Claude, haz clic en “Continuar con Google” y elige la cuenta. "
                   "Si el navegador pregunta, haz clic en “Abrir Claude”. El resto es automático.",
        colar="Pegar enlace", cancelar="Cancelar", colar_pergunta="Pega el enlace claude:// del navegador:",
        invalido="El enlace debe empezar con claude://",
        enviado="✓ Sesión enviada a “{n}”.", esgotado="Se agotó el tiempo. Prueba “Iniciar sesión” de nuevo.",
        novo_pergunta="Nombre del perfil (ej.: Cuenta Trabajo):", existe="Ya existe un perfil con ese nombre.",
        renomear_pergunta="Nuevo nombre:", excluir_q="¿Eliminar el perfil “{n}”?",
        excluir_dados="¿Borrar también los datos de este perfil (sesión, historial)?",
        sair_q="¿Cerrar sesión en el perfil “{n}”?\nEl Claude de este perfil se cerrará.",
        saiu="Cerraste sesión en “{n}”.", idioma="Idioma", config="Configuración",
        aparencia="Apariencia", claro="Claro", escuro="Oscuro", sistema="Sistema", sobre="Acerca de",
        versao="Versión", direitos="Todos los derechos reservados.", fotos_titulo="Foto de “{n}”",
        adicionar_img="Añadir imagen…", abrir_fotos="Abrir carpeta", sem_foto="Sin foto",
        fotos_dica="Cualquier imagen en la carpeta profile_pictures aparece aquí.",
        imagens="Imágenes", ok="OK", sim="Sí", nao="No", img_erro="No se pudo abrir esa imagen.",
        padrao=["Cuenta 1", "Cuenta 2"]),
    "fr": dict(
        sub="Plusieurs comptes Claude Desktop, chacun dans sa fenêtre.",
        ausente="Claude Desktop introuvable. Installez-le d'abord.",
        novo="Nouveau profil", nenhum="Aucun profil", nenhum_sub="Créez un profil pour chaque compte Claude.",
        conectado="Connecté", desconectado="Non connecté", aberto="Ouvert", fechado="Fermé",
        aguard="En attente de connexion…", abrir="Ouvrir", fechar="Fermer", entrar="Se connecter",
        sair="Se déconnecter", renomear="Renommer", pasta="Dossier de données", excluir="Supprimer",
        erro="Erreur", foto="Photo de profil",
        aguardando="Connexion à « {n} » : dans la fenêtre de Claude, cliquez sur « Continuer avec Google » et choisissez le compte. "
                   "Si le navigateur demande, cliquez sur « Ouvrir Claude ». Le reste est automatique.",
        colar="Coller le lien", cancelar="Annuler", colar_pergunta="Collez le lien claude:// du navigateur :",
        invalido="Le lien doit commencer par claude://",
        enviado="✓ Connexion envoyée à « {n} ».", esgotado="Délai dépassé. Réessayez « Se connecter ».",
        novo_pergunta="Nom du profil (ex. : Compte travail) :", existe="Un profil porte déjà ce nom.",
        renomear_pergunta="Nouveau nom :", excluir_q="Supprimer le profil « {n} » ?",
        excluir_dados="Effacer aussi les données de ce profil (connexion, sessions) ?",
        sair_q="Se déconnecter du profil « {n} » ?\nLe Claude de ce profil sera fermé.",
        saiu="Vous êtes déconnecté de « {n} ».", idioma="Langue", config="Paramètres",
        aparencia="Apparence", claro="Clair", escuro="Sombre", sistema="Système", sobre="À propos",
        versao="Version", direitos="Tous droits réservés.", fotos_titulo="Photo de « {n} »",
        adicionar_img="Ajouter une image…", abrir_fotos="Ouvrir le dossier", sem_foto="Sans photo",
        fotos_dica="Toute image placée dans le dossier profile_pictures apparaît ici.",
        imagens="Images", ok="OK", sim="Oui", nao="Non", img_erro="Impossible d'ouvrir cette image.",
        padrao=["Compte 1", "Compte 2"]),
    "de": dict(
        sub="Mehrere Claude-Desktop-Konten, jedes im eigenen Fenster.",
        ausente="Claude Desktop nicht gefunden. Bitte zuerst installieren.",
        novo="Neues Profil", nenhum="Noch keine Profile", nenhum_sub="Lege für jedes Claude-Konto ein Profil an.",
        conectado="Angemeldet", desconectado="Nicht angemeldet", aberto="Geöffnet", fechado="Geschlossen",
        aguard="Warte auf Anmeldung…", abrir="Öffnen", fechar="Schließen", entrar="Anmelden", sair="Abmelden",
        renomear="Umbenennen", pasta="Datenordner", excluir="Löschen", erro="Fehler", foto="Profilbild",
        aguardando="Anmeldung bei „{n}“: Klicke im Claude-Fenster auf „Mit Google fortfahren“ und wähle das Konto. "
                   "Wenn der Browser fragt, klicke auf „Claude öffnen“. Der Rest geht automatisch.",
        colar="Link einfügen", cancelar="Abbrechen", colar_pergunta="Füge den claude://-Link aus dem Browser ein:",
        invalido="Der Link muss mit claude:// beginnen",
        enviado="✓ Anmeldung an „{n}“ gesendet.", esgotado="Zeit abgelaufen. Versuche „Anmelden“ erneut.",
        novo_pergunta="Profilname (z. B. Arbeitskonto):", existe="Ein Profil mit diesem Namen existiert bereits.",
        renomear_pergunta="Neuer Name:", excluir_q="Profil „{n}“ löschen?",
        excluir_dados="Auch die Daten dieses Profils (Anmeldung, Sitzungen) löschen?",
        sair_q="Vom Profil „{n}“ abmelden?\nDas Claude dieses Profils wird geschlossen.",
        saiu="Du hast dich von „{n}“ abgemeldet.", idioma="Sprache", config="Einstellungen",
        aparencia="Darstellung", claro="Hell", escuro="Dunkel", sistema="System", sobre="Über",
        versao="Version", direitos="Alle Rechte vorbehalten.", fotos_titulo="Bild für „{n}“",
        adicionar_img="Bild hinzufügen…", abrir_fotos="Ordner öffnen", sem_foto="Kein Bild",
        fotos_dica="Jedes Bild im Ordner profile_pictures erscheint hier.",
        imagens="Bilder", ok="OK", sim="Ja", nao="Nein", img_erro="Dieses Bild konnte nicht geöffnet werden.",
        padrao=["Konto 1", "Konto 2"]),
    "it": dict(
        sub="Più account di Claude Desktop, ognuno nella sua finestra.",
        ausente="Claude Desktop non trovato. Installalo prima.",
        novo="Nuovo profilo", nenhum="Nessun profilo", nenhum_sub="Crea un profilo per ogni account Claude.",
        conectado="Connesso", desconectado="Non connesso", aberto="Aperto", fechado="Chiuso",
        aguard="In attesa di accesso…", abrir="Apri", fechar="Chiudi", entrar="Accedi", sair="Esci dall'account",
        renomear="Rinomina", pasta="Cartella dati", excluir="Elimina", erro="Errore", foto="Foto profilo",
        aguardando="Accesso a “{n}”: nella finestra di Claude, fai clic su “Continua con Google” e scegli l'account. "
                   "Se il browser lo chiede, fai clic su “Apri Claude”. Il resto è automatico.",
        colar="Incolla link", cancelar="Annulla", colar_pergunta="Incolla il link claude:// dal browser:",
        invalido="Il link deve iniziare con claude://",
        enviado="✓ Accesso inviato a “{n}”.", esgotado="Tempo scaduto. Riprova “Accedi”.",
        novo_pergunta="Nome del profilo (es.: Account lavoro):", existe="Esiste già un profilo con questo nome.",
        renomear_pergunta="Nuovo nome:", excluir_q="Eliminare il profilo “{n}”?",
        excluir_dados="Cancellare anche i dati di questo profilo (accesso, sessioni)?",
        sair_q="Uscire dall'account nel profilo “{n}”?\nIl Claude di questo profilo verrà chiuso.",
        saiu="Sei uscito da “{n}”.", idioma="Lingua", config="Impostazioni",
        aparencia="Aspetto", claro="Chiaro", escuro="Scuro", sistema="Sistema", sobre="Informazioni",
        versao="Versione", direitos="Tutti i diritti riservati.", fotos_titulo="Foto di “{n}”",
        adicionar_img="Aggiungi immagine…", abrir_fotos="Apri cartella", sem_foto="Nessuna foto",
        fotos_dica="Qualsiasi immagine nella cartella profile_pictures appare qui.",
        imagens="Immagini", ok="OK", sim="Sì", nao="No", img_erro="Impossibile aprire questa immagine.",
        padrao=["Account 1", "Account 2"]),
    "ru": dict(
        sub="Несколько аккаунтов Claude Desktop, каждый в своём окне.",
        ausente="Claude Desktop не найден. Сначала установите его.",
        novo="Новый профиль", nenhum="Профилей пока нет", nenhum_sub="Создайте профиль для каждого аккаунта Claude.",
        conectado="Вход выполнен", desconectado="Не выполнен вход", aberto="Открыт", fechado="Закрыт",
        aguard="Ожидание входа…", abrir="Открыть", fechar="Закрыть", entrar="Войти", sair="Выйти",
        renomear="Переименовать", pasta="Папка данных", excluir="Удалить", erro="Ошибка", foto="Фото профиля",
        aguardando="Вход в «{n}»: в окне Claude нажмите «Продолжить с Google» и выберите аккаунт. "
                   "Если браузер спросит, нажмите «Открыть Claude». Остальное — автоматически.",
        colar="Вставить ссылку", cancelar="Отмена", colar_pergunta="Вставьте ссылку claude:// из браузера:",
        invalido="Ссылка должна начинаться с claude://",
        enviado="✓ Вход отправлен в «{n}».", esgotado="Время вышло. Попробуйте «Войти» снова.",
        novo_pergunta="Имя профиля (напр.: Рабочий):", existe="Профиль с таким именем уже есть.",
        renomear_pergunta="Новое имя:", excluir_q="Удалить профиль «{n}»?",
        excluir_dados="Удалить также данные профиля (вход, сессии)?",
        sair_q="Выйти из аккаунта в профиле «{n}»?\nClaude этого профиля будет закрыт.",
        saiu="Вы вышли из «{n}».", idioma="Язык", config="Настройки",
        aparencia="Оформление", claro="Светлая", escuro="Тёмная", sistema="Системная", sobre="О программе",
        versao="Версия", direitos="Все права защищены.", fotos_titulo="Фото для «{n}»",
        adicionar_img="Добавить изображение…", abrir_fotos="Открыть папку", sem_foto="Без фото",
        fotos_dica="Любое изображение в папке profile_pictures появится здесь.",
        imagens="Изображения", ok="OK", sim="Да", nao="Нет", img_erro="Не удалось открыть изображение.",
        padrao=["Аккаунт 1", "Аккаунт 2"]),
    "ja": dict(
        sub="複数の Claude Desktop アカウントを、それぞれ別のウィンドウで。",
        ausente="Claude Desktop が見つかりません。先にインストールしてください。",
        novo="新しいプロフィール", nenhum="プロフィールがありません", nenhum_sub="Claude アカウントごとにプロフィールを作成します。",
        conectado="ログイン済み", desconectado="未ログイン", aberto="起動中", fechado="終了",
        aguard="ログイン待ち…", abrir="開く", fechar="閉じる", entrar="ログイン", sair="ログアウト",
        renomear="名前を変更", pasta="データフォルダー", excluir="削除", erro="エラー", foto="プロフィール画像",
        aguardando="「{n}」にログイン：Claude ウィンドウで「Google で続行」をクリックしてアカウントを選択。"
                   "ブラウザーに聞かれたら「Claude を開く」をクリック。あとは自動です。",
        colar="リンクを貼り付け", cancelar="キャンセル", colar_pergunta="ブラウザーの claude:// リンクを貼り付けてください：",
        invalido="リンクは claude:// で始まる必要があります",
        enviado="✓ 「{n}」にログインを送信しました。", esgotado="時間切れです。もう一度「ログイン」してください。",
        novo_pergunta="プロフィール名（例：仕事用）：", existe="同じ名前のプロフィールがあります。",
        renomear_pergunta="新しい名前：", excluir_q="プロフィール「{n}」を削除しますか？",
        excluir_dados="このプロフィールのデータ（ログイン、セッション）も消去しますか？",
        sair_q="プロフィール「{n}」からログアウトしますか？\nこのプロフィールの Claude は終了します。",
        saiu="「{n}」からログアウトしました。", idioma="言語", config="設定",
        aparencia="外観", claro="ライト", escuro="ダーク", sistema="システム", sobre="このアプリについて",
        versao="バージョン", direitos="All rights reserved.", fotos_titulo="「{n}」の画像",
        adicionar_img="画像を追加…", abrir_fotos="フォルダーを開く", sem_foto="画像なし",
        fotos_dica="profile_pictures フォルダーに置いた画像はすべてここに表示されます。",
        imagens="画像", ok="OK", sim="はい", nao="いいえ", img_erro="この画像を開けませんでした。",
        padrao=["アカウント 1", "アカウント 2"]),
    "zh": dict(
        sub="多个 Claude Desktop 账号，各自独立窗口。",
        ausente="未找到 Claude Desktop，请先安装。",
        novo="新建配置", nenhum="还没有配置", nenhum_sub="为每个 Claude 账号创建一个配置。",
        conectado="已登录", desconectado="未登录", aberto="已打开", fechado="已关闭",
        aguard="等待登录…", abrir="打开", fechar="关闭", entrar="登录", sair="退出登录",
        renomear="重命名", pasta="数据文件夹", excluir="删除", erro="错误", foto="头像",
        aguardando="登录“{n}”：在 Claude 窗口中点击“使用 Google 继续”并选择账号。"
                   "如果浏览器询问，点击“打开 Claude”。其余自动完成。",
        colar="粘贴链接", cancelar="取消", colar_pergunta="粘贴浏览器中的 claude:// 链接：",
        invalido="链接必须以 claude:// 开头",
        enviado="✓ 已将登录发送到“{n}”。", esgotado="登录超时，请重新点击“登录”。",
        novo_pergunta="配置名称（例如：工作账号）：", existe="已存在同名配置。",
        renomear_pergunta="新名称：", excluir_q="删除配置“{n}”？",
        excluir_dados="同时清除此配置的数据（登录、会话）？",
        sair_q="退出配置“{n}”的账号？\n此配置的 Claude 将被关闭。",
        saiu="已退出“{n}”。", idioma="语言", config="设置",
        aparencia="外观", claro="浅色", escuro="深色", sistema="跟随系统", sobre="关于",
        versao="版本", direitos="保留所有权利。", fotos_titulo="“{n}”的头像",
        adicionar_img="添加图片…", abrir_fotos="打开文件夹", sem_foto="无头像",
        fotos_dica="放入 profile_pictures 文件夹的任何图片都会显示在这里。",
        imagens="图片", ok="确定", sim="是", nao="否", img_erro="无法打开此图片。",
        padrao=["账号 1", "账号 2"]),
    "ko": dict(
        sub="여러 Claude Desktop 계정을 각각 다른 창에서.",
        ausente="Claude Desktop을 찾을 수 없습니다. 먼저 설치하세요.",
        novo="새 프로필", nenhum="프로필이 없습니다", nenhum_sub="Claude 계정마다 프로필을 만드세요.",
        conectado="로그인됨", desconectado="로그인 안 됨", aberto="열림", fechado="닫힘",
        aguard="로그인 대기 중…", abrir="열기", fechar="닫기", entrar="로그인", sair="로그아웃",
        renomear="이름 바꾸기", pasta="데이터 폴더", excluir="삭제", erro="오류", foto="프로필 사진",
        aguardando="“{n}” 로그인: Claude 창에서 “Google로 계속”을 누르고 계정을 선택하세요. "
                   "브라우저가 물으면 “Claude 열기”를 누르세요. 나머지는 자동입니다.",
        colar="링크 붙여넣기", cancelar="취소", colar_pergunta="브라우저의 claude:// 링크를 붙여넣으세요:",
        invalido="링크는 claude:// 로 시작해야 합니다",
        enviado="✓ “{n}”에 로그인을 보냈습니다.", esgotado="시간이 초과되었습니다. 다시 “로그인”하세요.",
        novo_pergunta="프로필 이름 (예: 업무 계정):", existe="같은 이름의 프로필이 이미 있습니다.",
        renomear_pergunta="새 이름:", excluir_q="“{n}” 프로필을 삭제할까요?",
        excluir_dados="이 프로필의 데이터(로그인, 세션)도 지울까요?",
        sair_q="“{n}” 프로필에서 로그아웃할까요?\n이 프로필의 Claude가 닫힙니다.",
        saiu="“{n}”에서 로그아웃했습니다.", idioma="언어", config="설정",
        aparencia="모양", claro="라이트", escuro="다크", sistema="시스템", sobre="정보",
        versao="버전", direitos="All rights reserved.", fotos_titulo="“{n}” 사진",
        adicionar_img="이미지 추가…", abrir_fotos="폴더 열기", sem_foto="사진 없음",
        fotos_dica="profile_pictures 폴더에 넣은 모든 이미지가 여기에 표시됩니다.",
        imagens="이미지", ok="확인", sim="예", nao="아니요", img_erro="이미지를 열 수 없습니다.",
        padrao=["계정 1", "계정 2"]),
}

# Textos da v2.1 (boas-vindas, importação, zona de perigo, licença)
_EXTRA = {
    "pt": dict(
        bv_titulo="Bem-vindo ao Multi Claude", continuar="Continuar",
        bv_sub="Escolha o idioma do programa. Dá para mudar depois em ⚙ Configurações.",
        importar="Importar perfis", importar_sub="Perfis do Claude encontrados nesta máquina que ainda não estão no Multi Claude:",
        nenhum_encontrado="Nenhum perfil novo encontrado. Use “Procurar pasta…” para escolher um manualmente.",
        procurar_pasta="Procurar pasta…", procurar_db="Importar perfis.db…",
        pasta_invalida="Essa pasta não parece ser um perfil do Claude (faltam config.json e Local State).",
        importar_sel="Importar selecionados", importados="{n} perfil(is) importado(s).",
        dados_sec="Dados", perigo="Zona de perigo", apagar_tudo="Apagar todos os dados",
        apagar_tudo_sub="Apaga todos os perfis, logins, sessões, fotos enviadas e configurações do Multi Claude. "
                        "Não dá para desfazer.",
        apagar_confirma="Isso não pode ser desfeito. Para confirmar, digite {p}:", palavra="APAGAR",
        direitos="Software livre sob a licença GPL-3.0.", licenca="Licença", codigo="Código-fonte",
        nao_oficial="Projeto independente, sem ligação com a Anthropic."),
    "en": dict(
        bv_titulo="Welcome to Multi Claude", continuar="Continue",
        bv_sub="Choose the app language. You can change it later in ⚙ Settings.",
        importar="Import profiles", importar_sub="Claude profiles found on this computer that are not in Multi Claude yet:",
        nenhum_encontrado="No new profiles found. Use “Browse folder…” to pick one manually.",
        procurar_pasta="Browse folder…", procurar_db="Import perfis.db…",
        pasta_invalida="That folder doesn't look like a Claude profile (config.json and Local State are missing).",
        importar_sel="Import selected", importados="{n} profile(s) imported.",
        dados_sec="Data", perigo="Danger zone", apagar_tudo="Erase all data",
        apagar_tudo_sub="Erases every profile, sign-in, session, uploaded picture and setting of Multi Claude. "
                        "This cannot be undone.",
        apagar_confirma="This cannot be undone. To confirm, type {p}:", palavra="DELETE",
        direitos="Free software under the GPL-3.0 license.", licenca="License", codigo="Source code",
        nao_oficial="Independent project, not affiliated with Anthropic."),
    "es": dict(
        bv_titulo="Bienvenido a Multi Claude", continuar="Continuar",
        bv_sub="Elige el idioma del programa. Puedes cambiarlo después en ⚙ Configuración.",
        importar="Importar perfiles", importar_sub="Perfiles de Claude encontrados en este equipo que aún no están en Multi Claude:",
        nenhum_encontrado="No se encontraron perfiles nuevos. Usa “Buscar carpeta…” para elegir uno manualmente.",
        procurar_pasta="Buscar carpeta…", procurar_db="Importar perfis.db…",
        pasta_invalida="Esa carpeta no parece un perfil de Claude (faltan config.json y Local State).",
        importar_sel="Importar seleccionados", importados="{n} perfil(es) importado(s).",
        dados_sec="Datos", perigo="Zona de peligro", apagar_tudo="Borrar todos los datos",
        apagar_tudo_sub="Borra todos los perfiles, sesiones, historial, fotos subidas y ajustes de Multi Claude. "
                        "No se puede deshacer.",
        apagar_confirma="No se puede deshacer. Para confirmar, escribe {p}:", palavra="BORRAR",
        direitos="Software libre bajo la licencia GPL-3.0.", licenca="Licencia", codigo="Código fuente",
        nao_oficial="Proyecto independiente, sin relación con Anthropic."),
    "fr": dict(
        bv_titulo="Bienvenue dans Multi Claude", continuar="Continuer",
        bv_sub="Choisissez la langue de l'application. Vous pourrez la changer dans ⚙ Paramètres.",
        importar="Importer des profils", importar_sub="Profils Claude trouvés sur cet ordinateur qui ne sont pas encore dans Multi Claude :",
        nenhum_encontrado="Aucun nouveau profil trouvé. Utilisez « Parcourir… » pour en choisir un.",
        procurar_pasta="Parcourir…", procurar_db="Importer perfis.db…",
        pasta_invalida="Ce dossier ne ressemble pas à un profil Claude (config.json et Local State manquants).",
        importar_sel="Importer la sélection", importados="{n} profil(s) importé(s).",
        dados_sec="Données", perigo="Zone de danger", apagar_tudo="Effacer toutes les données",
        apagar_tudo_sub="Efface tous les profils, connexions, sessions, photos ajoutées et réglages de Multi Claude. "
                        "Action irréversible.",
        apagar_confirma="Action irréversible. Pour confirmer, tapez {p} :", palavra="EFFACER",
        direitos="Logiciel libre sous licence GPL-3.0.", licenca="Licence", codigo="Code source",
        nao_oficial="Projet indépendant, sans lien avec Anthropic."),
    "de": dict(
        bv_titulo="Willkommen bei Multi Claude", continuar="Weiter",
        bv_sub="Wähle die Sprache der App. Du kannst sie später unter ⚙ Einstellungen ändern.",
        importar="Profile importieren", importar_sub="Auf diesem Computer gefundene Claude-Profile, die noch nicht in Multi Claude sind:",
        nenhum_encontrado="Keine neuen Profile gefunden. Wähle mit „Ordner suchen…“ eines manuell aus.",
        procurar_pasta="Ordner suchen…", procurar_db="perfis.db importieren…",
        pasta_invalida="Dieser Ordner ist kein Claude-Profil (config.json und Local State fehlen).",
        importar_sel="Auswahl importieren", importados="{n} Profil(e) importiert.",
        dados_sec="Daten", perigo="Gefahrenzone", apagar_tudo="Alle Daten löschen",
        apagar_tudo_sub="Löscht alle Profile, Anmeldungen, Sitzungen, hochgeladenen Bilder und Einstellungen von Multi Claude. "
                        "Kann nicht rückgängig gemacht werden.",
        apagar_confirma="Kann nicht rückgängig gemacht werden. Zum Bestätigen {p} eingeben:", palavra="LÖSCHEN",
        direitos="Freie Software unter der GPL-3.0-Lizenz.", licenca="Lizenz", codigo="Quellcode",
        nao_oficial="Unabhängiges Projekt, nicht mit Anthropic verbunden."),
    "it": dict(
        bv_titulo="Benvenuto in Multi Claude", continuar="Continua",
        bv_sub="Scegli la lingua dell'app. Puoi cambiarla in ⚙ Impostazioni.",
        importar="Importa profili", importar_sub="Profili di Claude trovati su questo computer non ancora in Multi Claude:",
        nenhum_encontrado="Nessun nuovo profilo trovato. Usa “Sfoglia cartella…” per sceglierne uno.",
        procurar_pasta="Sfoglia cartella…", procurar_db="Importa perfis.db…",
        pasta_invalida="Questa cartella non sembra un profilo di Claude (mancano config.json e Local State).",
        importar_sel="Importa selezionati", importados="{n} profilo/i importato/i.",
        dados_sec="Dati", perigo="Zona pericolosa", apagar_tudo="Cancella tutti i dati",
        apagar_tudo_sub="Cancella tutti i profili, accessi, sessioni, immagini caricate e impostazioni di Multi Claude. "
                        "Non si può annullare.",
        apagar_confirma="Non si può annullare. Per confermare, scrivi {p}:", palavra="ELIMINA",
        direitos="Software libero con licenza GPL-3.0.", licenca="Licenza", codigo="Codice sorgente",
        nao_oficial="Progetto indipendente, non affiliato ad Anthropic."),
    "ru": dict(
        bv_titulo="Добро пожаловать в Multi Claude", continuar="Продолжить",
        bv_sub="Выберите язык программы. Его можно изменить в ⚙ Настройках.",
        importar="Импорт профилей", importar_sub="Найденные на этом компьютере профили Claude, которых ещё нет в Multi Claude:",
        nenhum_encontrado="Новых профилей не найдено. Нажмите «Выбрать папку…», чтобы указать вручную.",
        procurar_pasta="Выбрать папку…", procurar_db="Импорт perfis.db…",
        pasta_invalida="Эта папка не похожа на профиль Claude (нет config.json и Local State).",
        importar_sel="Импортировать выбранные", importados="Импортировано профилей: {n}.",
        dados_sec="Данные", perigo="Опасная зона", apagar_tudo="Удалить все данные",
        apagar_tudo_sub="Удаляет все профили, входы, сессии, загруженные фото и настройки Multi Claude. "
                        "Отменить нельзя.",
        apagar_confirma="Отменить нельзя. Для подтверждения введите {p}:", palavra="УДАЛИТЬ",
        direitos="Свободное ПО под лицензией GPL-3.0.", licenca="Лицензия", codigo="Исходный код",
        nao_oficial="Независимый проект, не связан с Anthropic."),
    "ja": dict(
        bv_titulo="Multi Claude へようこそ", continuar="続行",
        bv_sub="アプリの言語を選んでください。あとで ⚙ 設定から変更できます。",
        importar="プロフィールを取り込む", importar_sub="このパソコンで見つかった、まだ Multi Claude にない Claude プロフィール：",
        nenhum_encontrado="新しいプロフィールは見つかりませんでした。「フォルダーを選択…」で手動で選べます。",
        procurar_pasta="フォルダーを選択…", procurar_db="perfis.db を取り込む…",
        pasta_invalida="このフォルダーは Claude のプロフィールではないようです（config.json と Local State がありません）。",
        importar_sel="選択したものを取り込む", importados="{n} 件のプロフィールを取り込みました。",
        dados_sec="データ", perigo="危険ゾーン", apagar_tudo="すべてのデータを消去",
        apagar_tudo_sub="Multi Claude のすべてのプロフィール、ログイン、セッション、追加した画像、設定を消去します。"
                        "元に戻せません。",
        apagar_confirma="元に戻せません。確認のため {p} と入力してください：", palavra="削除",
        direitos="GPL-3.0 ライセンスのフリーソフトウェアです。", licenca="ライセンス", codigo="ソースコード",
        nao_oficial="Anthropic とは無関係の独立したプロジェクトです。"),
    "zh": dict(
        bv_titulo="欢迎使用 Multi Claude", continuar="继续",
        bv_sub="请选择程序语言。之后可在 ⚙ 设置中更改。",
        importar="导入配置", importar_sub="在本机找到、尚未加入 Multi Claude 的 Claude 配置：",
        nenhum_encontrado="未找到新的配置。可点击“选择文件夹…”手动选择。",
        procurar_pasta="选择文件夹…", procurar_db="导入 perfis.db…",
        pasta_invalida="该文件夹不像 Claude 配置（缺少 config.json 和 Local State）。",
        importar_sel="导入所选", importados="已导入 {n} 个配置。",
        dados_sec="数据", perigo="危险区域", apagar_tudo="清除所有数据",
        apagar_tudo_sub="清除 Multi Claude 的所有配置、登录、会话、上传的图片和设置。此操作无法撤销。",
        apagar_confirma="此操作无法撤销。请输入 {p} 以确认：", palavra="删除",
        direitos="基于 GPL-3.0 许可证的自由软件。", licenca="许可证", codigo="源代码",
        nao_oficial="独立项目，与 Anthropic 无关。"),
    "ko": dict(
        bv_titulo="Multi Claude에 오신 것을 환영합니다", continuar="계속",
        bv_sub="프로그램 언어를 선택하세요. 나중에 ⚙ 설정에서 바꿀 수 있습니다.",
        importar="프로필 가져오기", importar_sub="이 컴퓨터에서 찾은, 아직 Multi Claude에 없는 Claude 프로필:",
        nenhum_encontrado="새 프로필을 찾지 못했습니다. “폴더 찾아보기…”로 직접 선택하세요.",
        procurar_pasta="폴더 찾아보기…", procurar_db="perfis.db 가져오기…",
        pasta_invalida="이 폴더는 Claude 프로필이 아닌 것 같습니다 (config.json과 Local State가 없음).",
        importar_sel="선택 항목 가져오기", importados="프로필 {n}개를 가져왔습니다.",
        dados_sec="데이터", perigo="위험 구역", apagar_tudo="모든 데이터 삭제",
        apagar_tudo_sub="Multi Claude의 모든 프로필, 로그인, 세션, 올린 사진과 설정을 지웁니다. 되돌릴 수 없습니다.",
        apagar_confirma="되돌릴 수 없습니다. 확인하려면 {p}을(를) 입력하세요:", palavra="삭제",
        direitos="GPL-3.0 라이선스의 자유 소프트웨어입니다.", licenca="라이선스", codigo="소스 코드",
        nao_oficial="Anthropic과 관련 없는 독립 프로젝트입니다."),
}
for _cod, _textos in _EXTRA.items():
    T[_cod].update(_textos)


def log(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 500_000:
            os.replace(LOG, LOG + ".old")
        with open(LOG, "a", encoding="utf8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {msg}\n")
    except OSError:
        pass


# ---------- banco ----------

@contextlib.contextmanager
def db():
    """Conexão com perfis.db: confirma ao sair e sempre fecha (senão o Windows não deixa apagar o arquivo)."""
    os.makedirs(BASE, exist_ok=True)
    con = sqlite3.connect(DB, timeout=5)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS perfis ("
            "id INTEGER PRIMARY KEY, nome TEXT UNIQUE NOT NULL, pasta TEXT NOT NULL, "
            "criado TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        con.execute("CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT)")
        try:
            con.execute("ALTER TABLE perfis ADD COLUMN foto TEXT")
        except sqlite3.OperationalError:
            pass  # coluna já existe
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def cfg_get(chave):
    with db() as con:
        r = con.execute("SELECT valor FROM config WHERE chave = ?", (chave,)).fetchone()
    return r[0] if r else None


def cfg_set(chave, valor):
    with db() as con:
        if valor is None:
            con.execute("DELETE FROM config WHERE chave = ?", (chave,))
        else:
            con.execute("INSERT OR REPLACE INTO config VALUES (?, ?)", (chave, valor))


def caminho_real(pasta, base=None):
    """Pastas dentro da pasta do programa ficam salvas como relativas (portátil)."""
    return os.path.normpath(pasta if os.path.isabs(pasta) else os.path.join(base or BASE, pasta))


def caminho_salvo(pasta):
    pasta = os.path.abspath(pasta)
    try:
        rel = os.path.relpath(pasta, BASE)
        if not rel.startswith(".."):
            return rel
    except ValueError:  # outro disco
        pass
    return pasta


# ---------- perfis existentes na máquina ----------

def protegidas():
    """Pastas que nunca são tratadas como perfil (dados do Claude principal, pastas do usuário)."""
    loc, roam, casa = os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", ""), os.path.expanduser("~")
    fixas = [os.path.join(roam, "Claude"), os.path.join(loc, "AnthropicClaude"), casa, BASE, DADOS, FOTOS]
    for raiz in (os.path.join(loc, "Claude-Data"), os.path.join(loc, "Packages")):
        try:
            fixas += [os.path.join(raiz, n) for n in os.listdir(raiz) if "claude" in n.lower()]
        except OSError:
            pass
    fixas.append(os.path.join(loc, "Claude-Data"))
    return {normalizar(p) for p in fixas if p}


def eh_perfil_claude(pasta):
    return (os.path.isfile(os.path.join(pasta, "config.json"))
            and os.path.exists(os.path.join(pasta, "Local State"))
            and normalizar(pasta) not in protegidas())


def detectar_perfis(registradas):
    """Pastas de perfil do Claude na máquina que ainda não estão cadastradas."""
    candidatas = []
    for raiz in (DADOS, os.path.join(os.path.expanduser("~"), "ClaudePerfis")):
        try:
            candidatas += [os.path.join(raiz, n) for n in os.listdir(raiz)]
        except OSError:
            pass
    candidatas += list(claudes_abertos_caminhos())
    vistas, achadas = set(registradas), []
    for c in candidatas:
        n = normalizar(c)
        if n in vistas or not os.path.isdir(c) or not eh_perfil_claude(c):
            continue
        vistas.add(n)
        achadas.append(c)
    return achadas


def pasta_segura_para_apagar(pasta):
    n = normalizar(pasta)
    if n in protegidas() or len(n) < 8:
        return False
    return n.startswith(normalizar(DADOS) + os.sep) or eh_perfil_claude(pasta)


# ---------- fotos de perfil ----------

def preparar_fotos():
    """Cria profile_pictures e, no .exe, copia as fotos padrão embutidas que faltarem."""
    os.makedirs(FOTOS, exist_ok=True)
    embutidas = os.path.join(RECURSOS, "profile_pictures")
    if os.path.normcase(embutidas) != os.path.normcase(FOTOS) and os.path.isdir(embutidas):
        for nome in os.listdir(embutidas):
            destino = os.path.join(FOTOS, nome)
            if not os.path.exists(destino):
                shutil.copy2(os.path.join(embutidas, nome), destino)


def listar_fotos():
    """Todas as imagens da pasta profile_pictures (as do app primeiro, as do usuário no fim)."""
    try:
        nomes = [n for n in os.listdir(FOTOS) if n.lower().endswith(EXT_IMAGEM)]
    except OSError:
        return []
    return sorted(nomes, key=lambda n: (n.startswith("usuario_"), n.lower()))


def importar_foto(caminho):
    """Copia uma imagem escolhida pelo usuário para profile_pictures (recortada em quadrado)."""
    img = Image.open(caminho)
    img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
    lado = min(img.size)
    x, y = (img.width - lado) // 2, (img.height - lado) // 2
    img = img.crop((x, y, x + lado, y + lado)).resize((512, 512), Image.LANCZOS)
    base = re.sub(r"[^\w-]+", "_", os.path.splitext(os.path.basename(caminho))[0]).strip("_")[:40] or "foto"
    nome = f"usuario_{base}_{int(time.time())}.png"
    img.save(os.path.join(FOTOS, nome))
    return nome


_cache_img = {}


def avatar(foto, tam, fundo):
    """PhotoImage redondo da foto (ou None se não der). Fica em cache."""
    if not Image or not foto:
        return None
    caminho = os.path.join(FOTOS, foto)
    try:
        chave = (caminho, os.path.getmtime(caminho), tam, fundo)
    except OSError:
        return None
    if chave in _cache_img:
        return _cache_img[chave]
    try:
        img = Image.open(caminho)
        img.seek(0)
        img = img.convert("RGBA")
        lado = min(img.size)
        x, y = (img.width - lado) // 2, (img.height - lado) // 2
        f = 4  # supersampling para borda suave
        img = img.crop((x, y, x + lado, y + lado)).resize((tam * f, tam * f), Image.LANCZOS)
        mask = Image.new("L", (tam * f, tam * f), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, tam * f - 1, tam * f - 1), fill=255)
        out = Image.new("RGBA", (tam * f, tam * f), fundo)
        out.paste(img, (0, 0), Image.composite(img.split()[3], Image.new("L", mask.size, 0), mask))
        out = out.resize((tam, tam), Image.LANCZOS)
        foto_tk = ImageTk.PhotoImage(out)
    except Exception as e:
        log(f"foto inválida {foto}: {e}")
        return None
    _cache_img[chave] = foto_tk
    return foto_tk


def desenhar_avatar(canvas, nome, foto, tam, fundo, indice):
    canvas.delete("all")
    img = avatar(foto, tam, fundo)
    if img:
        canvas.create_image(tam // 2, tam // 2, image=img)
        canvas.imagem = img  # mantém referência
    else:
        canvas.create_oval(1, 1, tam - 1, tam - 1, fill=AVATARES[indice % len(AVATARES)], width=0)
        canvas.create_text(tam // 2, tam // 2, text=(nome.strip()[:1] or "?").upper(), fill="#ffffff",
                           font=(FONTE, int(tam * 0.36), "bold"))


# ---------- Claude ----------

def achar_claude():
    alias = os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "WindowsApps", "claude-desktop.exe")
    if os.path.exists(alias):
        return alias
    p = os.path.join(os.environ["LOCALAPPDATA"], "AnthropicClaude", "claude.exe")
    if os.path.exists(p):
        return p
    try:
        loc = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", "(Get-AppxPackage Claude).InstallLocation"],
            text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        ).strip()
        exe = os.path.join(loc, "app", "claude.exe")
        if os.path.exists(exe):
            return exe
    except Exception:
        pass
    return None


def abrir_claude(claude, pasta, url=None):
    args = [claude]
    if pasta:
        os.makedirs(pasta, exist_ok=True)
        args.append(f"--user-data-dir={pasta}")
    if url:
        args.append(url)
    subprocess.Popen(args)


def esta_logado(pasta):
    """Lê a última transição de login no log do Claude do perfil."""
    try:
        with open(os.path.join(pasta, "logs", "main.log"), "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 2_000_000))
            texto = f.read().decode("utf8", "replace")
    except OSError:
        return False
    m = re.findall(r"Login-state transition \(loggedOut: \w+ → (\w+)", texto)
    if m:
        return m[-1] == "false"
    try:
        with open(os.path.join(pasta, "config.json"), encoding="utf8") as f:
            return bool(json.load(f).get("lastKnownAccountUuid"))
    except (OSError, ValueError):
        return False


def deslogar(pasta):
    """Apaga cookies e tokens do perfil (o Claude dele precisa estar fechado)."""
    for rel in (r"Network\Cookies", r"Network\Cookies-journal"):
        try:
            os.remove(os.path.join(pasta, rel))
        except OSError:
            pass
    cfg = os.path.join(pasta, "config.json")
    try:
        with open(cfg, encoding="utf8") as f:
            d = json.load(f)
        for k in [k for k in d if k.startswith("oauth:") or k == "lastKnownAccountUuid"]:
            del d[k]
        with open(cfg, "w", encoding="utf8") as f:
            json.dump(d, f, indent=2)
    except (OSError, ValueError):
        pass
    # Marca no log do perfil, para o status ficar "sem login" até o próximo login.
    try:
        with open(os.path.join(pasta, "logs", "main.log"), "a", encoding="utf8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [info] [multi-claude] "
                    "Login-state transition (loggedOut: false → true)\n")
    except OSError:
        pass


def devolver_registros():
    """Versões antigas assumiam o claude:// e o navegador padrão; devolve o original."""
    try:
        orig = cfg_get("handler_original")
        cmd = r"Software\Classes\claude\shell\open\command"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cmd) as k:
            atual = winreg.QueryValueEx(k, "")[0]
        if orig and "--link" in atual:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, orig)
    except OSError:
        pass
    progid = cfg_get("nav_progid")
    if progid:
        base = rf"Software\Classes\{progid}"
        hkcu = cfg_get("nav_hkcu")
        try:
            if hkcu:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, hkcu)
            else:
                for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + sub)
                    except OSError:
                        break
            for c in ("nav_progid", "nav_hkcu"):
                cfg_set(c, None)
        except OSError:
            pass


# ----- processos -----

class _PE32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


class _UStr(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort), ("Buffer", ctypes.c_void_p)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
_k32.OpenProcess.restype = wt.HANDLE
_ntdll = ctypes.WinDLL("ntdll")


def pids_por_nome(nome):
    snap = _k32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    pids = set()
    if not snap or snap == wt.HANDLE(-1).value:
        return pids
    try:
        e = _PE32()
        e.dwSize = ctypes.sizeof(e)
        ok = _k32.Process32FirstW(wt.HANDLE(snap), ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() == nome:
                pids.add(e.th32ProcessID)
            ok = _k32.Process32NextW(wt.HANDLE(snap), ctypes.byref(e))
    finally:
        _k32.CloseHandle(wt.HANDLE(snap))
    return pids


def linha_de_comando(pid):
    h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_string_buffer(65536)
        ret = wt.ULONG()
        # 60 = ProcessCommandLineInformation (Windows 8.1+)
        if _ntdll.NtQueryInformationProcess(wt.HANDLE(h), 60, buf, len(buf), ctypes.byref(ret)) != 0:
            return ""
        us = _UStr.from_buffer(buf)
        return ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer else ""
    finally:
        _k32.CloseHandle(wt.HANDLE(h))


def encerrar_processo(pid):
    h = _k32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
    if not h:
        return False
    try:
        return bool(_k32.TerminateProcess(wt.HANDLE(h), 0))
    finally:
        _k32.CloseHandle(wt.HANDLE(h))


def normalizar(pasta):
    return os.path.normcase(os.path.normpath(pasta))


def _claudes_com_pasta():
    for pid in pids_por_nome("claude.exe"):
        cmd = linha_de_comando(pid)
        if "--type=" in cmd:
            continue
        m = re.search(r'--user-data-dir="?([^"]+?)"?(?:\s|$)', cmd)
        if m:
            yield pid, m.group(1)


def claudes_abertos():
    """{pasta do perfil normalizada: pid do processo principal} dos Claude abertos com --user-data-dir."""
    return {normalizar(pasta): pid for pid, pasta in _claudes_com_pasta()}


def claudes_abertos_caminhos():
    return {pasta for _, pasta in _claudes_com_pasta()}


def fechar_claude(pasta):
    pid = claudes_abertos().get(normalizar(pasta))
    if pid:
        # Fecha a árvore toda (renderer, GPU etc. junto com o principal).
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(30):
            if normalizar(pasta) not in claudes_abertos():
                break
            time.sleep(0.1)
        log(f"Claude do perfil fechado ({pasta})")


class VigiaProcessos:
    """Procura, em Claude.exe novos, um link de login claude:// e o entrega via `aviso`.

    Quando o navegador abre claude://..., o Windows inicia um Claude.exe novo com o
    link na linha de comando; ele vive por um instante, repassa ao Claude principal
    e fecha. Lemos a linha de comando dele e o encerramos antes que repasse.
    """

    def __init__(self, aviso, nome="claude.exe"):
        self.aviso, self.nome, self.parar = aviso, nome, False
        threading.Thread(target=self._rodar, daemon=True).start()

    def _rodar(self):
        vistos = pids_por_nome(self.nome)
        log(f"vigia de processos ligado ({len(vistos)} {self.nome} já abertos)")
        while not self.parar:
            atuais = pids_por_nome(self.nome)
            for pid in atuais - vistos:
                cmd = linha_de_comando(pid)
                for url in re.findall(r"claude://[^\"\s]+", cmd):
                    log(f"processo {pid} abriu {url[:40]}")
                    if LINK_LOGIN.match(url):
                        self.parar = True
                        log(f"processo {pid} encerrado: {encerrar_processo(pid)}")
                        self.aviso(url)
                        return
            vistos = atuais
            time.sleep(0.01)


# ---------- bandeiras ----------

def desenhar_bandeira(c, cod, w=24, h=16):
    def faixas_h(*cores):
        for i, cor in enumerate(cores):
            c.create_rectangle(0, i * h / len(cores), w, (i + 1) * h / len(cores), fill=cor, width=0)

    def faixas_v(*cores):
        for i, cor in enumerate(cores):
            c.create_rectangle(i * w / len(cores), 0, (i + 1) * w / len(cores), h, fill=cor, width=0)

    if cod == "pt":  # Brasil
        c.create_rectangle(0, 0, w, h, fill="#009c3b", width=0)
        c.create_polygon(w / 2, 2, w - 2, h / 2, w / 2, h - 2, 2, h / 2, fill="#ffdf00", width=0)
        c.create_oval(w / 2 - 4, h / 2 - 4, w / 2 + 4, h / 2 + 4, fill="#002776", width=0)
    elif cod == "en":  # EUA
        for i in range(13):
            c.create_rectangle(0, i * h / 13, w, (i + 1) * h / 13,
                               fill="#b22234" if i % 2 == 0 else "#ffffff", width=0)
        c.create_rectangle(0, 0, w * 0.45, h * 7 / 13, fill="#3c3b6e", width=0)
    elif cod == "es":
        c.create_rectangle(0, 0, w, h, fill="#aa151b", width=0)
        c.create_rectangle(0, h / 4, w, h * 3 / 4, fill="#f1bf00", width=0)
    elif cod == "fr":
        faixas_v("#0055a4", "#ffffff", "#ef4135")
    elif cod == "de":
        faixas_h("#000000", "#dd0000", "#ffce00")
    elif cod == "it":
        faixas_v("#009246", "#ffffff", "#ce2b37")
    elif cod == "ru":
        faixas_h("#ffffff", "#0039a6", "#d52b1e")
    elif cod == "ja":
        c.create_rectangle(0, 0, w, h, fill="#ffffff", width=0)
        c.create_oval(w / 2 - 5, h / 2 - 5, w / 2 + 5, h / 2 + 5, fill="#bc002d", width=0)
    elif cod == "zh":
        c.create_rectangle(0, 0, w, h, fill="#de2910", width=0)
        c.create_text(6, 6, text="★", fill="#ffde00", font=(FONTE, 7))
    elif cod == "ko":
        c.create_rectangle(0, 0, w, h, fill="#ffffff", width=0)
        x, y, r = w / 2, h / 2, 4.5
        c.create_arc(x - r, y - r, x + r, y + r, start=0, extent=180, fill="#cd2e3a", width=0)
        c.create_arc(x - r, y - r, x + r, y + r, start=180, extent=180, fill="#0047a0", width=0)
        for x0 in (2, w - 5):
            for y0 in (2, h - 5):
                c.create_rectangle(x0, y0, x0 + 3, y0 + 3, fill="#000000", width=0)
    c.create_rectangle(0, 0, w - 1, h - 1, outline=C.get("BORDA", "#888888"))


# ---------- componentes ----------

class Botao(tk.Label):
    """Botão plano com hover. tipo: 'primario', 'normal' ou 'fantasma'."""

    def __init__(self, master, texto, cmd, tipo="normal", tamanho=10, **kw):
        cores = {"primario": (C["ACCENT"], C["ACCENT_HOVER"], "#ffffff"),
                 "normal": (C["BTN"], C["BTN_HOVER"], C["TEXTO"]),
                 "fantasma": (master["bg"], C["BTN"], C["TEXTO"])}[tipo]
        self.cor, self.hover = cores[0], cores[1]
        kw.setdefault("padx", 14)
        kw.setdefault("pady", 7)
        super().__init__(master, text=texto, bg=self.cor, fg=cores[2], font=(FONTE, tamanho, "bold"),
                         cursor="hand2", **kw)
        self.bind("<Button-1>", lambda e: cmd())
        self.bind("<Enter>", lambda e: self.config(bg=self.hover))
        self.bind("<Leave>", lambda e: self.config(bg=self.cor))


class Rolavel(tk.Frame):
    """Frame com rolagem vertical (roda do mouse) que ajusta a largura do conteúdo."""

    def __init__(self, master, bg):
        super().__init__(master, bg=bg)
        self.tela = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.tela.pack(fill="both", expand=True)
        self.dentro = tk.Frame(self.tela, bg=bg)
        self._janela = self.tela.create_window(0, 0, window=self.dentro, anchor="nw")
        self.dentro.bind("<Configure>", lambda e: self.tela.configure(scrollregion=self.tela.bbox("all")))
        self.tela.bind("<Configure>", lambda e: self.tela.itemconfigure(self._janela, width=e.width))
        self.bind_all("<MouseWheel>", self._roda, add="+")

    def _roda(self, e):
        try:
            if str(e.widget).startswith(str(self)) and self.dentro.winfo_height() > self.tela.winfo_height():
                self.tela.yview_scroll(int(-e.delta / 120), "units")
        except (tk.TclError, AttributeError):
            pass


class Janela(tk.Toplevel):
    """Diálogo modal no tema do app."""

    def __init__(self, app, titulo, largura=420, altura=None):
        super().__init__(app)
        self.app = app
        self.withdraw()
        self.title(titulo)
        self.configure(bg=C["PAINEL"])
        self.transient(app)
        self.resizable(True, True)
        por_icone(self)
        self.bind("<Escape>", lambda e: self.destroy())
        self._tam = (largura, altura)

    def mostrar(self):
        self.update_idletasks()
        w, h = self._tam
        w = max(w, self.winfo_reqwidth())
        h = h or self.winfo_reqheight()
        x = self.app.winfo_rootx() + (self.app.winfo_width() - w) // 2
        y = self.app.winfo_rooty() + (self.app.winfo_height() - h) // 3
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.minsize(min(w, 340), min(h, 200))
        barra_titulo(self)
        self.deiconify()
        self.grab_set()
        self.focus_force()


def dialogo(app, titulo, msg, entrada=None, botoes=None):
    """Mostra uma mensagem; com `entrada` (texto inicial) pede um texto. Devolve o valor do botão/texto."""
    j = Janela(app, titulo)
    res = {"v": None}
    corpo = tk.Frame(j, bg=C["PAINEL"])
    corpo.pack(fill="both", expand=True, padx=22, pady=(20, 8))
    tk.Label(corpo, text=msg, bg=C["PAINEL"], fg=C["TEXTO"], font=(FONTE, 10), justify="left",
             wraplength=370, anchor="w").pack(fill="x")
    campo = None
    if entrada is not None:
        borda = tk.Frame(corpo, bg=C["BORDA"])
        borda.pack(fill="x", pady=(12, 0))
        campo = tk.Entry(borda, font=(FONTE, 11), bg=C["CARD"], fg=C["TEXTO"], insertbackground=C["TEXTO"],
                         relief="flat", highlightthickness=0)
        campo.pack(fill="x", padx=1, pady=1, ipady=6, ipadx=6)
        campo.insert(0, entrada)
        campo.select_range(0, "end")
        campo.focus_set()
    rodape = tk.Frame(j, bg=C["PAINEL"])
    rodape.pack(fill="x", padx=22, pady=(8, 18))
    botoes = botoes or [(app.t("ok"), True, "primario")]

    def escolher(v):
        res["v"] = (campo.get().strip() if v is True and campo is not None else v)
        j.destroy()

    for texto, valor, tipo in reversed(botoes):
        Botao(rodape, texto, lambda v=valor: escolher(v), tipo=tipo).pack(side="right", padx=(8, 0))
    j.bind("<Return>", lambda e: escolher(botoes[0][1]))
    j.mostrar()
    j.wait_window()
    return res["v"]


# ---------- app ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        por_icone(self)
        self.claude = achar_claude()
        self.login_inicio = None
        self.login_perfil = None
        self.ultimo_clip = ""
        self.vigia = None
        self.fila = queue.Queue()
        self.estado = {}  # pasta -> (logado, aberto)
        self.layout = None  # (colunas, compacto) do último desenho
        self.primeira = cfg_get("idioma") is None
        self.lang = cfg_get("idioma") or idioma_do_windows()
        if self.lang not in T:
            self.lang = "en"
        self.tema = cfg_get("tema") or "sistema"
        self.tema_efetivo = aplicar_tema(self.tema)

        geo = cfg_get("geometria")
        self.geometry(geo if geo else "640x680")
        self.minsize(440, 480)

        # Sobrou modo login de uma execução anterior? Limpa.
        for c in ("login_pasta", "login_ok", "login_url"):
            cfg_set(c, None)
        devolver_registros()
        preparar_fotos()

        self.montar()
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.after(500, self.vigiar_login)
        self.after(200, self.atualizar_estado)
        if self.primeira:
            self.after(300, self.boas_vindas)

    def t(self, chave, **kw):
        s = T[self.lang].get(chave, T["en"][chave])
        return s.format(**kw) if kw else s

    # ----- montagem -----
    def montar(self):
        for w in self.winfo_children():
            w.destroy()
        self.configure(bg=C["BG"])
        barra_titulo(self)
        self.layout = None

        topo = tk.Frame(self, bg=C["BG"])
        topo.pack(fill="x", padx=22, pady=(18, 0))
        logo = tk.Canvas(topo, width=40, height=40, bg=C["BG"], highlightthickness=0)
        logo.pack(side="left", padx=(0, 12))
        img = None
        for arq in (ICONE_PNG, ICONE):
            if Image and os.path.exists(arq):
                try:
                    img = ImageTk.PhotoImage(Image.open(arq).convert("RGBA").resize((40, 40), Image.LANCZOS))
                    break
                except Exception:
                    img = None
        if img:
            logo.create_image(20, 20, image=img)
            logo.imagem = img
        else:
            logo.create_text(20, 20, text="✳", fill=C["ACCENT"], font=(FONTE, 22, "bold"))
        # Os botões entram primeiro no pack para nunca serem cortados quando a janela estreita.
        acoes = tk.Frame(topo, bg=C["BG"])
        acoes.pack(side="right")
        Botao(acoes, "⚙", self.configuracoes, tipo="fantasma", tamanho=13, padx=9, pady=2).pack(side="left", padx=(0, 6))
        self.btn_novo = Botao(acoes, "+  " + self.t("novo"), self.novo, tipo="primario")
        self.btn_novo.pack(side="left")
        textos = tk.Frame(topo, bg=C["BG"])
        textos.pack(side="left", fill="x", expand=True)
        tk.Label(textos, text=APP, bg=C["BG"], fg=C["TEXTO"], font=(FONTE, 18, "bold"), anchor="w").pack(fill="x")
        self.lbl_sub = tk.Label(textos, text=self.t("sub"), bg=C["BG"], fg=C["SUB"], font=(FONTE, 9),
                                anchor="w", justify="left")
        self.lbl_sub.pack(fill="x")
        textos.bind("<Configure>", lambda e: self.lbl_sub.config(wraplength=max(120, e.width)))
        topo.bind("<Configure>", lambda e: self.btn_novo.config(
            text="+" if e.width < 520 else "+  " + self.t("novo")))

        if not self.claude:
            tk.Label(self, text="⚠  " + self.t("ausente"), bg=C["BG"], fg=C["VERMELHO"],
                     font=(FONTE, 9, "bold"), anchor="w").pack(fill="x", padx=24, pady=(10, 0))

        # Barra de status do login
        self.status = tk.Frame(self, bg=C["PAINEL"], highlightthickness=1, highlightbackground=C["ACCENT"])
        self.status_txt = tk.Label(self.status, bg=C["PAINEL"], fg=C["TEXTO"], font=(FONTE, 10),
                                   justify="left", anchor="w")
        self.status_txt.pack(side="left", fill="x", expand=True, padx=14, pady=10)
        self.status_btns = tk.Frame(self.status, bg=C["PAINEL"])
        Botao(self.status_btns, self.t("colar"), self.colar_link, tipo="primario", tamanho=9).pack(fill="x", pady=2)
        Botao(self.status_btns, self.t("cancelar"), self.cancelar_login, tamanho=9).pack(fill="x", pady=2)
        self.status.bind("<Configure>", lambda e: self.status_txt.config(wraplength=max(200, e.width - 170)))

        # Rodapé com copyright
        rodape = tk.Frame(self, bg=C["BG"])
        rodape.pack(side="bottom", fill="x", padx=22, pady=(0, 10))
        tk.Label(rodape, text=f"{APP} v{VERSAO}  ·  {COPYRIGHT}", bg=C["BG"], fg=C["SUB"],
                 font=(FONTE, 8)).pack(side="left")
        link = tk.Label(rodape, text="github.com/RichardKPL", bg=C["BG"], fg=C["ACCENT"], font=(FONTE, 8, "underline"),
                        cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: webbrowser.open(GITHUB))

        self.corpo = Rolavel(self, C["BG"])
        self.corpo.pack(fill="both", expand=True, padx=(22, 16), pady=14)
        self.area = self.corpo.dentro
        self.corpo.tela.bind("<Configure>", self._ao_redimensionar, add="+")

        self.recarregar()
        if self.login_inicio and self.login_perfil:
            self.mostrar_status(self.t("aguardando", n=self.login_perfil[1]), True)

    def _layout_para(self, largura):
        colunas = 2 if largura >= 860 else 1
        compacto = largura / colunas < 470
        return colunas, compacto

    def _ao_redimensionar(self, e):
        if self._layout_para(e.width) != self.layout:
            self.after_idle(self.recarregar)

    # ----- configurações -----
    def configuracoes(self):
        j = Janela(self, self.t("config"), largura=460, altura=560)
        rol = Rolavel(j, C["PAINEL"])
        rol.pack(fill="both", expand=True)
        corpo = tk.Frame(rol.dentro, bg=C["PAINEL"])
        corpo.pack(fill="both", expand=True, padx=22, pady=18)

        def secao(txt):
            tk.Label(corpo, text=txt.upper(), bg=C["PAINEL"], fg=C["SUB"], font=(FONTE, 8, "bold"),
                     anchor="w").pack(fill="x", pady=(14, 6))

        secao(self.t("aparencia"))
        seg = tk.Frame(corpo, bg=C["BTN"])
        seg.pack(fill="x")
        for cod, icone in (("claro", "☀"), ("escuro", "☾"), ("sistema", "◐")):
            ativo = cod == self.tema
            b = tk.Label(seg, text=f"{icone}  {self.t(cod)}", bg=C["ACCENT"] if ativo else C["BTN"],
                         fg="#ffffff" if ativo else C["TEXTO"], font=(FONTE, 10, "bold"), pady=8, cursor="hand2")
            b.pack(side="left", fill="x", expand=True, padx=2, pady=2)
            b.bind("<Button-1>", lambda e, cod=cod: (j.destroy(), self.mudar_tema(cod)))

        secao(self.t("idioma"))
        grade = tk.Frame(corpo, bg=C["PAINEL"])
        grade.pack(fill="x")
        for col in (0, 1):
            grade.columnconfigure(col, weight=1, uniform="i")
        for i, (cod, nome) in enumerate(IDIOMAS):
            ativo = cod == self.lang
            cor = C["ACCENT"] if ativo else C["CARD"]
            linha = tk.Frame(grade, bg=cor, cursor="hand2", highlightthickness=1,
                             highlightbackground=C["ACCENT"] if ativo else C["BORDA"])
            linha.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
            cv = tk.Canvas(linha, width=24, height=16, bg=cor, highlightthickness=0, cursor="hand2")
            desenhar_bandeira(cv, cod)
            cv.pack(side="left", padx=(10, 8), pady=8)
            lb = tk.Label(linha, text=nome, bg=cor, fg="#ffffff" if ativo else C["TEXTO"], font=(FONTE, 10),
                          anchor="w", cursor="hand2")
            lb.pack(side="left", fill="x", expand=True)
            for w in (linha, cv, lb):
                w.bind("<Button-1>", lambda e, cod=cod: (j.destroy(), self.mudar_idioma(cod)))

        secao(self.t("sobre"))
        sobre = tk.Frame(corpo, bg=C["CARD"], highlightthickness=1, highlightbackground=C["BORDA"])
        sobre.pack(fill="x")
        tk.Label(sobre, text=APP, bg=C["CARD"], fg=C["TEXTO"], font=(FONTE, 12, "bold"),
                 anchor="w").pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(sobre, text=f"{self.t('versao')} {VERSAO}", bg=C["CARD"], fg=C["SUB"], font=(FONTE, 9),
                 anchor="w").pack(fill="x", padx=14)
        tk.Label(sobre, text=f"{COPYRIGHT}. {self.t('direitos')}", bg=C["CARD"], fg=C["SUB"], font=(FONTE, 9),
                 anchor="w").pack(fill="x", padx=14, pady=(6, 0))
        tk.Label(sobre, text=self.t("nao_oficial"), bg=C["CARD"], fg=C["SUB"], font=(FONTE, 9),
                 anchor="w").pack(fill="x", padx=14)
        links = tk.Frame(sobre, bg=C["CARD"])
        links.pack(fill="x", padx=14, pady=(6, 12))
        for texto, url in ((self.t("codigo"), REPO), (self.t("licenca") + " GPL-3.0", REPO + "/blob/main/LICENSE"),
                           ("github.com/RichardKPL", GITHUB)):
            lk = tk.Label(links, text=texto, bg=C["CARD"], fg=C["ACCENT"], font=(FONTE, 9, "underline"),
                          cursor="hand2")
            lk.pack(side="left", padx=(0, 14))
            lk.bind("<Button-1>", lambda e, url=url: webbrowser.open(url))

        secao(self.t("dados_sec"))
        Botao(corpo, "⇩  " + self.t("importar"), lambda: (j.destroy(), self.importar())).pack(anchor="w")

        secao(self.t("perigo"))
        perigo = tk.Frame(corpo, bg=C["CARD"], highlightthickness=1, highlightbackground=C["VERMELHO"])
        perigo.pack(fill="x", pady=(0, 6))
        tk.Label(perigo, text=self.t("apagar_tudo"), bg=C["CARD"], fg=C["VERMELHO"], font=(FONTE, 11, "bold"),
                 anchor="w").pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(perigo, text=self.t("apagar_tudo_sub"), bg=C["CARD"], fg=C["SUB"], font=(FONTE, 9),
                 anchor="w", justify="left", wraplength=360).pack(fill="x", padx=14, pady=(2, 8))
        b = Botao(perigo, self.t("apagar_tudo"), lambda: (j.destroy(), self.apagar_tudo()))
        b.cor = b.hover = C["VERMELHO"]
        b.config(bg=C["VERMELHO"], fg="#ffffff")
        b.pack(anchor="w", padx=14, pady=(0, 14))
        j.mostrar()

    # ----- primeira abertura -----
    def boas_vindas(self):
        j = Janela(self, APP, largura=500, altura=520)
        j.protocol("WM_DELETE_WINDOW", lambda: concluir())
        corpo = tk.Frame(j, bg=C["PAINEL"])
        corpo.pack(fill="both", expand=True, padx=26, pady=22)
        logo = tk.Canvas(corpo, width=64, height=64, bg=C["PAINEL"], highlightthickness=0)
        logo.pack()
        try:
            img = ImageTk.PhotoImage(Image.open(ICONE_PNG).convert("RGBA").resize((64, 64), Image.LANCZOS))
            logo.create_image(32, 32, image=img)
            logo.imagem = img
        except Exception:
            logo.create_text(32, 32, text="✳", fill=C["ACCENT"], font=(FONTE, 30, "bold"))
        titulo = tk.Label(corpo, bg=C["PAINEL"], fg=C["TEXTO"], font=(FONTE, 16, "bold"))
        titulo.pack(pady=(10, 2))
        sub = tk.Label(corpo, bg=C["PAINEL"], fg=C["SUB"], font=(FONTE, 10), wraplength=430, justify="center")
        sub.pack(pady=(0, 14))
        grade = tk.Frame(corpo, bg=C["PAINEL"])
        grade.pack(fill="x")
        for col in (0, 1):
            grade.columnconfigure(col, weight=1, uniform="i")
        botao = Botao(corpo, "", lambda: concluir(), tipo="primario")
        botao.pack(fill="x", pady=(18, 0))

        def desenhar():
            titulo.config(text=self.t("bv_titulo"))
            sub.config(text=self.t("bv_sub"))
            botao.config(text=self.t("continuar") + "  →")
            for w in grade.winfo_children():
                w.destroy()
            for i, (cod, nome) in enumerate(IDIOMAS):
                ativo = cod == self.lang
                cor = C["ACCENT"] if ativo else C["CARD"]
                linha = tk.Frame(grade, bg=cor, cursor="hand2", highlightthickness=1,
                                 highlightbackground=C["ACCENT"] if ativo else C["BORDA"])
                linha.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
                cv = tk.Canvas(linha, width=24, height=16, bg=cor, highlightthickness=0, cursor="hand2")
                desenhar_bandeira(cv, cod)
                cv.pack(side="left", padx=(10, 8), pady=8)
                lb = tk.Label(linha, text=nome, bg=cor, fg="#ffffff" if ativo else C["TEXTO"],
                              font=(FONTE, 10), anchor="w", cursor="hand2")
                lb.pack(side="left", fill="x", expand=True)
                for w in (linha, cv, lb):
                    w.bind("<Button-1>", lambda e, cod=cod: escolher(cod))

        def escolher(cod):
            self.lang = cod
            desenhar()

        def concluir():
            cfg_set("idioma", self.lang)
            self.primeira = False
            j.destroy()
            self.montar()
            # Já existem perfis do Claude nesta máquina? Oferece importar.
            if detectar_perfis({normalizar(p[2]) for p in self.perfis()}):
                self.importar()

        desenhar()
        j.unbind("<Escape>")
        j.mostrar()

    # ----- importar perfis -----
    def importar(self):
        j = Janela(self, self.t("importar"), largura=560, altura=500)
        tk.Label(j, text=self.t("importar_sub"), bg=C["PAINEL"], fg=C["TEXTO"], font=(FONTE, 10),
                 anchor="w", justify="left", wraplength=500).pack(fill="x", padx=20, pady=(18, 8))
        rodape = tk.Frame(j, bg=C["PAINEL"])
        rodape.pack(side="bottom", fill="x", padx=20, pady=14)
        rol = Rolavel(j, C["PAINEL"])
        rol.pack(fill="both", expand=True, padx=20)
        marcados = {}

        def listar():
            for w in rol.dentro.winfo_children():
                w.destroy()
            achadas = detectar_perfis({normalizar(p[2]) for p in self.perfis()}) + [
                c for c in marcados if normalizar(c) not in {normalizar(p[2]) for p in self.perfis()}]
            vistas = set()
            for pasta in achadas:
                if normalizar(pasta) in vistas:
                    continue
                vistas.add(normalizar(pasta))
                marcados.setdefault(pasta, True)
                linha = tk.Frame(rol.dentro, bg=C["CARD"], highlightthickness=1, highlightbackground=C["BORDA"],
                                 cursor="hand2")
                linha.pack(fill="x", pady=3)
                caixa = tk.Label(linha, bg=C["CARD"], fg=C["ACCENT"], font=(FONTE, 14), cursor="hand2")
                caixa.pack(side="left", padx=(12, 8), pady=8)
                # O status entra antes do texto no pack para não ser cortado por caminhos longos.
                self._chip(linha, self.t("conectado" if esta_logado(pasta) else "desconectado"),
                           C["VERDE"] if esta_logado(pasta) else C["SUB"]).pack(side="right", padx=12)
                textos = tk.Frame(linha, bg=C["CARD"])
                textos.pack(side="left", fill="x", expand=True, pady=6)
                tk.Label(textos, text=os.path.basename(pasta.rstrip("\\/")), bg=C["CARD"], fg=C["TEXTO"],
                         font=(FONTE, 10, "bold"), anchor="w").pack(fill="x")
                tk.Label(textos, text=pasta, bg=C["CARD"], fg=C["SUB"], font=(FONTE, 8), anchor="w").pack(fill="x")

                def alternar(e=None, pasta=pasta, caixa=caixa):
                    marcados[pasta] = not marcados[pasta]
                    caixa.config(text="☑" if marcados[pasta] else "☐")
                caixa.config(text="☑" if marcados[pasta] else "☐")
                for w in (linha, caixa, textos, *textos.winfo_children()):
                    w.bind("<Button-1>", alternar)
            if not vistas:
                tk.Label(rol.dentro, text=self.t("nenhum_encontrado"), bg=C["PAINEL"], fg=C["SUB"],
                         font=(FONTE, 10), wraplength=480, justify="left").pack(fill="x", pady=20)

        def procurar():
            pasta = filedialog.askdirectory(parent=j, title=self.t("procurar_pasta"))
            if not pasta:
                return
            pasta = os.path.normpath(pasta)
            if not eh_perfil_claude(pasta):
                dialogo(self, self.t("erro"), self.t("pasta_invalida"))
                return
            marcados[pasta] = True
            listar()

        def importar_db():
            arq = filedialog.askopenfilename(parent=j, title=self.t("procurar_db"),
                                             filetypes=[("perfis.db", "*.db"), ("*", "*.*")])
            if not arq:
                return
            n = 0
            try:
                origem = sqlite3.connect(f"file:{arq}?mode=ro", uri=True)
                cols = [c[1] for c in origem.execute("PRAGMA table_info(perfis)")]
                linhas = origem.execute("SELECT nome, pasta" + (", foto" if "foto" in cols else ", NULL")
                                        + " FROM perfis").fetchall()
                origem.close()
            except sqlite3.Error as e:
                dialogo(self, self.t("erro"), str(e))
                return
            registradas = {normalizar(p[2]) for p in self.perfis()}
            with db() as con:
                for nome, pasta, foto in linhas:
                    pasta = caminho_real(pasta, os.path.dirname(arq))
                    if normalizar(pasta) in registradas or not eh_perfil_claude(pasta):
                        continue
                    if foto and not os.path.exists(os.path.join(FOTOS, foto)):
                        foto = None
                    self._inserir(con, self.nome_livre(con, nome), pasta, foto)
                    registradas.add(normalizar(pasta))
                    n += 1
            j.destroy()
            self.forcar_estado()
            dialogo(self, self.t("importar"), self.t("importados", n=n))

        def confirmar():
            escolhidas = [p for p, v in marcados.items() if v]
            registradas = {normalizar(p[2]) for p in self.perfis()}
            n = 0
            with db() as con:
                for pasta in escolhidas:
                    if normalizar(pasta) in registradas:
                        continue
                    self._inserir(con, self.nome_livre(con, os.path.basename(pasta.rstrip("\\/"))), pasta)
                    n += 1
            log(f"{n} perfil(is) importado(s)")
            j.destroy()
            self.forcar_estado()
            if n:
                dialogo(self, self.t("importar"), self.t("importados", n=n))

        Botao(rodape, self.t("importar_sel"), confirmar, tipo="primario").pack(side="right")
        Botao(rodape, self.t("procurar_pasta"), procurar).pack(side="left")
        Botao(rodape, self.t("procurar_db"), importar_db, tipo="fantasma").pack(side="left", padx=6)
        listar()
        j.mostrar()

    # ----- zona de perigo -----
    def apagar_tudo(self):
        palavra = self.t("palavra")
        resp = dialogo(self, self.t("apagar_tudo"), self.t("apagar_confirma", p=palavra), entrada="",
                       botoes=[(self.t("apagar_tudo"), True, "primario"), (self.t("cancelar"), None, "normal")])
        if (resp or "").strip().upper() != palavra.upper():
            return
        self.cancelar_login()
        for _, nome, pasta, _ in self.perfis():
            fechar_claude(pasta)
            if pasta_segura_para_apagar(pasta):
                shutil.rmtree(pasta, ignore_errors=True)
            else:
                log(f"pasta não apagada por segurança: {pasta}")
        shutil.rmtree(DADOS, ignore_errors=True)
        for nome in listar_fotos():
            if nome.startswith("usuario_"):
                try:
                    os.remove(os.path.join(FOTOS, nome))
                except OSError:
                    pass
        for arq in (DB, LOG, LOG + ".old"):
            try:
                os.remove(arq)
            except OSError:
                pass
        reiniciar(self)

    def mudar_idioma(self, cod):
        self.lang = cod
        cfg_set("idioma", cod)
        self.montar()

    def mudar_tema(self, cod):
        self.tema = cod
        cfg_set("tema", cod)
        self.tema_efetivo = aplicar_tema(cod)
        _cache_img.clear()
        self.montar()

    # ----- perfis -----
    def _inserir(self, con, nome, pasta=None, foto=None):
        """Cadastra um perfil; sem `pasta`, cria uma nova em dados/ (portátil). Devolve o id."""
        if pasta is None:
            slug = re.sub(r"[^\w-]+", "_", nome).strip("_") or "perfil"
            pasta = os.path.join(DADOS, slug)
            usadas = {normalizar(caminho_real(r[0])) for r in con.execute("SELECT pasta FROM perfis")}
            while normalizar(pasta) in usadas or os.path.exists(pasta):
                pasta += "_"
        cur = con.execute("INSERT INTO perfis (nome, pasta, foto) VALUES (?, ?, ?)",
                          (nome, caminho_salvo(pasta), foto))
        return cur.lastrowid

    def nome_livre(self, con, nome):
        base, n = nome, 2
        while con.execute("SELECT 1 FROM perfis WHERE nome = ?", (nome,)).fetchone():
            nome, n = f"{base} ({n})", n + 1
        return nome

    def perfis(self):
        with db() as con:
            linhas = con.execute("SELECT id, nome, pasta, foto FROM perfis ORDER BY id").fetchall()
        return [(i, n, caminho_real(p), f) for i, n, p, f in linhas]

    def calcular_estado(self):
        abertos = claudes_abertos()
        return {p[2]: (esta_logado(p[2]), normalizar(p[2]) in abertos) for p in self.perfis()}

    def atualizar_estado(self):
        try:
            if self.tema == "sistema" and tema_sistema() != self.tema_efetivo:
                self.mudar_tema("sistema")
            novo = self.calcular_estado()
            if novo != self.estado:
                self.estado = novo
                self.recarregar()
        except Exception as e:
            log(f"erro ao atualizar estado: {e}")
        self.after(2000, self.atualizar_estado)

    def recarregar(self):
        for w in self.area.winfo_children():
            w.destroy()
        largura = self.corpo.tela.winfo_width()
        self.layout = self._layout_para(largura if largura > 1 else 600)
        colunas, compacto = self.layout
        for col in range(2):
            self.area.columnconfigure(col, weight=1 if col < colunas else 0, uniform="c" if col < colunas else "")
        perfis = self.perfis()
        if not perfis:
            vazio = tk.Frame(self.area, bg=C["BG"])
            vazio.grid(row=0, column=0, columnspan=colunas, pady=60)
            tk.Label(vazio, text="✳", bg=C["BG"], fg=C["ACCENT"], font=(FONTE, 40)).pack()
            tk.Label(vazio, text=self.t("nenhum"), bg=C["BG"], fg=C["TEXTO"], font=(FONTE, 13, "bold")).pack()
            tk.Label(vazio, text=self.t("nenhum_sub"), bg=C["BG"], fg=C["SUB"], font=(FONTE, 10)).pack(pady=(2, 14))
            Botao(vazio, "+  " + self.t("novo"), self.novo, tipo="primario").pack(fill="x")
            Botao(vazio, "⇩  " + self.t("importar"), self.importar, tipo="fantasma").pack(fill="x", pady=(6, 0))
        for i, p in enumerate(perfis):
            card = self._card(p, i, compacto)
            col = i % colunas
            card.grid(row=i // colunas, column=col, sticky="nsew", pady=6,
                      padx=(0, 6) if colunas == 2 and col == 0 else (6, 0) if colunas == 2 else 0)

    def _chip(self, master, texto, cor):
        f = tk.Frame(master, bg=C["CHIP"])
        tk.Label(f, text="●", bg=C["CHIP"], fg=cor, font=(FONTE, 8)).pack(side="left", padx=(8, 4), pady=2)
        tk.Label(f, text=texto, bg=C["CHIP"], fg=C["TEXTO"], font=(FONTE, 9)).pack(side="left", padx=(0, 9), pady=2)
        return f

    def _card(self, p, i, compacto):
        _, nome, pasta, foto = p
        logado, aberto = self.estado.get(pasta, (False, False))
        esperando = bool(self.login_inicio and self.login_perfil and self.login_perfil[2] == pasta)

        c = tk.Frame(self.area, bg=C["CARD"], highlightthickness=1,
                     highlightbackground=C["ACCENT"] if esperando else C["BORDA"])
        c.columnconfigure(1, weight=1)

        av = tk.Canvas(c, width=52, height=52, bg=C["CARD"], highlightthickness=0, cursor="hand2")
        desenhar_avatar(av, nome, foto, 52, C["CARD"], i)
        av.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=14)
        av.bind("<Button-1>", lambda e: self.escolher_foto(p))

        titulo = tk.Label(c, text=nome, bg=C["CARD"], fg=C["TEXTO"], font=(FONTE, 12, "bold"),
                          cursor="xterm", anchor="w")
        titulo.grid(row=0, column=1, sticky="sw", pady=(14, 0))
        titulo.bind("<Double-Button-1>", lambda e: self.renomear(p))
        chips = tk.Frame(c, bg=C["CARD"])
        chips.grid(row=1, column=1, sticky="nw", pady=(4, 14))
        if esperando:
            self._chip(chips, self.t("aguard"), C["AMARELO"]).pack(side="left")
        else:
            self._chip(chips, self.t("conectado" if logado else "desconectado"),
                       C["VERDE"] if logado else C["SUB"]).pack(side="left", padx=(0, 6))
            self._chip(chips, self.t("aberto" if aberto else "fechado"),
                       C["VERDE"] if aberto else C["SUB"]).pack(side="left")

        botoes = tk.Frame(c, bg=C["CARD"])
        if compacto:
            botoes.grid(row=2, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 14))
        else:
            botoes.grid(row=0, column=2, rowspan=2, padx=(8, 14))
        mais = Botao(botoes, "⋯", lambda: self.menu(p, mais, logado), tipo="fantasma", tamanho=12, padx=10, pady=3)
        mais.pack(side="right")
        acoes = []
        if not logado:
            acoes.append((self.t("entrar"), lambda: self.login(p), "primario"))
            if aberto:
                acoes.append((self.t("fechar"), lambda: self.fechar_perfil(p), "normal"))
        elif aberto:
            acoes.append((self.t("fechar"), lambda: self.fechar_perfil(p), "normal"))
        else:
            acoes.append((self.t("abrir"), lambda: self.abrir(p), "primario"))
        for texto, cmd, tipo in acoes:
            Botao(botoes, texto, cmd, tipo=tipo).pack(side="left" if compacto else "right",
                                                       padx=(0, 6) if compacto else (0, 6))
        return c

    def menu(self, p, widget, logado):
        m = tk.Menu(self, tearoff=0, bg=C["MENU"], fg=C["TEXTO"], activebackground=C["ACCENT"],
                    activeforeground="#ffffff", font=(FONTE, 10), bd=0, relief="flat")
        m.add_command(label="  " + self.t("foto"), command=lambda: self.escolher_foto(p))
        m.add_command(label="  " + self.t("renomear"), command=lambda: self.renomear(p))
        m.add_command(label="  " + self.t("pasta"), command=lambda: self.pasta(p))
        if logado:
            m.add_command(label="  " + self.t("sair"), command=lambda: self.sair(p))
        m.add_separator()
        m.add_command(label="  " + self.t("excluir"), command=lambda: self.excluir(p), foreground=C["VERMELHO"])
        m.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())

    def precisa_claude(self):
        if not self.claude:
            dialogo(self, self.t("erro"), self.t("ausente"))
        return bool(self.claude)

    def abrir(self, p):
        if self.precisa_claude():
            try:
                abrir_claude(self.claude, p[2])
            except Exception as e:
                dialogo(self, self.t("erro"), str(e))
            self.after(1500, self.forcar_estado)

    def fechar_perfil(self, p):
        fechar_claude(p[2])
        self.forcar_estado()

    def forcar_estado(self):
        self.estado = self.calcular_estado()
        self.recarregar()

    def confirmar(self, titulo, msg, perigo=False):
        return dialogo(self, titulo, msg, botoes=[(self.t("sim"), True, "primario"),
                                                  (self.t("nao"), False, "normal")]) is True

    def sair(self, p):
        if not self.confirmar(self.t("sair"), self.t("sair_q", n=p[1])):
            return
        fechar_claude(p[2])
        deslogar(p[2])
        log(f"deslogado: {p[1]}")
        self.forcar_estado()
        self.mostrar_status(self.t("saiu", n=p[1]), False)
        self.after(5000, self.esconder_status)

    # ----- fotos -----
    def escolher_foto(self, p):
        j = Janela(self, self.t("fotos_titulo", n=p[1]), largura=520, altura=520)
        tk.Label(j, text=self.t("fotos_dica"), bg=C["PAINEL"], fg=C["SUB"], font=(FONTE, 9),
                 anchor="w", justify="left", wraplength=460).pack(fill="x", padx=20, pady=(16, 6))
        rodape = tk.Frame(j, bg=C["PAINEL"])
        rodape.pack(side="bottom", fill="x", padx=20, pady=14)
        rol = Rolavel(j, C["PAINEL"])
        rol.pack(fill="both", expand=True, padx=14)
        grade = rol.dentro
        estado = {"colunas": 0}

        def definir(foto):
            with db() as con:
                con.execute("UPDATE perfis SET foto = ? WHERE id = ?", (foto, p[0]))
            j.destroy()
            self.recarregar()

        def desenhar(largura):
            colunas = max(3, (largura - 8) // 96)
            if colunas == estado["colunas"]:
                return
            estado["colunas"] = colunas
            for w in grade.winfo_children():
                w.destroy()
            for col in range(colunas):
                grade.columnconfigure(col, weight=1)
            for k, nome in enumerate(listar_fotos()):
                ativo = nome == p[3]
                cv = tk.Canvas(grade, width=80, height=80, bg=C["PAINEL"], cursor="hand2",
                               highlightthickness=3, highlightbackground=C["ACCENT"] if ativo else C["PAINEL"])
                img = avatar(nome, 76, C["PAINEL"])
                if not img:
                    cv.destroy()
                    continue
                cv.create_image(40, 40, image=img)
                cv.imagem = img
                cv.grid(row=k // colunas, column=k % colunas, padx=4, pady=4)
                cv.bind("<Button-1>", lambda e, nome=nome: definir(nome))

        rol.tela.bind("<Configure>", lambda e: desenhar(e.width), add="+")

        def adicionar():
            arq = filedialog.askopenfilename(parent=j, title=self.t("adicionar_img"), filetypes=[
                (self.t("imagens"), " ".join("*" + e for e in EXT_IMAGEM)), ("*", "*.*")])
            if not arq:
                return
            try:
                definir(importar_foto(arq))
            except Exception as e:
                log(f"erro ao importar foto: {e}")
                dialogo(self, self.t("erro"), self.t("img_erro"))

        if Image:
            Botao(rodape, "+  " + self.t("adicionar_img"), adicionar, tipo="primario").pack(side="left")
        Botao(rodape, self.t("abrir_fotos"), lambda: os.startfile(FOTOS)).pack(side="left", padx=6)
        Botao(rodape, self.t("sem_foto"), lambda: definir(None), tipo="fantasma").pack(side="right")
        j.mostrar()

    # ----- login -----
    def login(self, p):
        if not self.precisa_claude():
            return
        try:
            cfg_set("login_pasta", p[2])
            self.parar_vigia()
            self.vigia = VigiaProcessos(self.fila.put)
            abrir_claude(self.claude, p[2])
        except Exception as e:
            dialogo(self, self.t("erro"), str(e))
            return
        self.login_inicio = time.time()
        self.login_perfil = p
        self.ultimo_clip = self.ler_clip()
        log(f"login iniciado para {p[1]} ({p[2]})")
        self.mostrar_status(self.t("aguardando", n=p[1]), True)
        self.recarregar()

    def ler_clip(self):
        try:
            return self.clipboard_get().strip()
        except tk.TclError:
            return ""

    def colar_link(self):
        url = self.ler_clip()
        if not url.startswith("claude://"):
            url = (dialogo(self, self.t("colar"), self.t("colar_pergunta"), entrada="",
                           botoes=[(self.t("ok"), True, "primario"), (self.t("cancelar"), None, "normal")]) or "")
        if url.startswith("claude://"):
            self.ultimo_clip = url
            self.enviar_link(url)
        elif url:
            dialogo(self, self.t("erro"), self.t("invalido"))

    def enviar_link(self, url):
        p = self.login_perfil
        cfg_set("login_pasta", None)
        self.parar_vigia()
        abrir_claude(self.claude, p[2], url)
        log(f"link entregue ao perfil {p[1]}")
        self.login_inicio = None
        self.mostrar_status(self.t("enviado", n=p[1]), False)
        self.after(6000, self.esconder_status)
        self.after(3000, self.forcar_estado)
        self.recarregar()

    def parar_vigia(self):
        if self.vigia:
            self.vigia.parar = True
            self.vigia = None

    def vigiar_login(self):
        if self.login_inicio:
            try:
                capturado = self.fila.get_nowait()
            except queue.Empty:
                capturado = None
            clip = self.ler_clip()
            if capturado:
                self.enviar_link(capturado)
            elif clip != self.ultimo_clip and clip.startswith("claude://"):
                self.ultimo_clip = clip
                self.enviar_link(clip)
            elif time.time() - self.login_inicio > LOGIN_TIMEOUT:
                self.cancelar_login(self.t("esgotado"))
        self.after(300, self.vigiar_login)

    def cancelar_login(self, msg=None):
        self.login_inicio = None
        cfg_set("login_pasta", None)
        self.parar_vigia()
        if msg:
            self.mostrar_status(msg, False)
            self.after(6000, self.esconder_status)
        else:
            self.esconder_status()
        self.recarregar()

    def mostrar_status(self, texto, cancelavel):
        self.status_txt.config(text=texto)
        self.status_btns.pack_forget()
        if cancelavel:
            self.status_btns.pack(side="right", padx=10, pady=8)
        self.status.pack(fill="x", padx=22, pady=(14, 0), before=self.corpo)

    def esconder_status(self):
        if not self.login_inicio:
            self.status.pack_forget()

    # ----- outras ações -----
    def novo(self):
        nome = dialogo(self, self.t("novo"), self.t("novo_pergunta"), entrada="",
                       botoes=[(self.t("ok"), True, "primario"), (self.t("cancelar"), None, "normal")])
        if not nome:
            return
        try:
            with db() as con:
                novo_id = self._inserir(con, nome)
        except sqlite3.IntegrityError:
            dialogo(self, self.t("erro"), self.t("existe"))
            return
        self.forcar_estado()
        # Logo depois de criar, já pede a foto (galeria ou upload).
        perfil = next((p for p in self.perfis() if p[0] == novo_id), None)
        if perfil:
            self.escolher_foto(perfil)

    def renomear(self, p):
        nome = dialogo(self, self.t("renomear"), self.t("renomear_pergunta"), entrada=p[1],
                       botoes=[(self.t("ok"), True, "primario"), (self.t("cancelar"), None, "normal")])
        if not nome:
            return
        try:
            with db() as con:
                con.execute("UPDATE perfis SET nome = ? WHERE id = ?", (nome, p[0]))
        except sqlite3.IntegrityError:
            dialogo(self, self.t("erro"), self.t("existe"))
        self.recarregar()

    def pasta(self, p):
        os.makedirs(p[2], exist_ok=True)
        os.startfile(p[2])

    def excluir(self, p):
        if not self.confirmar(self.t("excluir"), self.t("excluir_q", n=p[1])):
            return
        apagar = self.confirmar(self.t("excluir"), self.t("excluir_dados"))
        fechar_claude(p[2])
        with db() as con:
            con.execute("DELETE FROM perfis WHERE id = ?", (p[0],))
        if apagar:
            shutil.rmtree(p[2], ignore_errors=True)
        self.forcar_estado()

    def fechar(self):
        cfg_set("login_pasta", None)
        if self.state() == "normal":
            cfg_set("geometria", self.geometry())
        self.parar_vigia()
        self.destroy()


_MUTEX = None


def reiniciar(app):
    """Fecha e abre o programa de novo (usado depois de apagar todos os dados)."""
    app.destroy()
    if _MUTEX:
        _k32.CloseHandle(wt.HANDLE(_MUTEX))
    args = [sys.executable] if CONGELADO else [sys.executable, os.path.abspath(__file__)]
    subprocess.Popen(args)
    sys.exit()


def principal():
    global _MUTEX
    if len(sys.argv) >= 3 and sys.argv[1] in ("--link", "--browser"):
        # Registro deixado por versão antiga: devolve e repassa o link ao destino normal.
        devolver_registros()
        os.startfile(sys.argv[2])
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RichardKPL.MultiClaude")
    _k32.CreateMutexW.restype = wt.HANDLE
    # Uma instância por pasta: cópias portáteis em pastas diferentes podem rodar juntas.
    _MUTEX = _k32.CreateMutexW(None, False, "MultiClaude_" + hashlib.md5(normalizar(BASE).encode()).hexdigest()[:16])
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(None, f"{APP} já está aberto.", APP, 0x40)
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # nitidez em telas com escala
    except Exception:
        pass
    log(f"{APP} {VERSAO} aberto")
    app = App()
    app.report_callback_exception = lambda *e: log("ERRO: " + "".join(__import__("traceback").format_exception(*e)))
    app.mainloop()


if __name__ == "__main__":
    principal()
