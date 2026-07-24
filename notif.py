"""Notifications multi-canal : terminal, macOS, Telegram, Email, Discord.

Les identifiants des canaux distants sont demandés une fois de façon
interactive puis sauvegardés (config.py / .config.json). On peut aussi les
fournir par variable d'environnement (prioritaire).
"""
import ssl
import json
import shutil
import getpass
import smtplib
import subprocess
import urllib.parse
import urllib.request
from email.message import EmailMessage

import config

CANAUX = {
    "1": ("terminal", "Terminal seulement"),
    "2": ("macos", "Notification macOS"),
    "3": ("telegram", "Telegram"),
    "4": ("email", "Email"),
    "5": ("discord", "Discord"),
}

# Champs à demander par canal : (clé, label, secret ?, optionnel ?)
_CHAMPS = {
    "telegram": [
        ("TELEGRAM_TOKEN", "Token du bot Telegram (via @BotFather)", True, False),
        ("TELEGRAM_CHAT_ID", "Chat ID Telegram", False, False),
    ],
    "email": [
        ("EMAIL_FROM", "Ton email expéditeur", False, False),
        ("EMAIL_PASSWORD", "Mot de passe d'application", True, False),
        ("EMAIL_TO", "Email destinataire (Entrée = le même)", False, True),
    ],
    "discord": [
        ("DISCORD_WEBHOOK", "URL du webhook Discord", False, False),
    ],
}


def assurer_config(canal):
    """Demande interactivement les identifiants manquants du canal et les sauve."""
    champs = _CHAMPS.get(canal)
    if not champs:
        return True
    cfg = config.charger()
    ok = True
    for cle, label, secret, optionnel in champs:
        if config.get(cle):
            continue
        prompt = f"  {label} : "
        val = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        if val:
            cfg[cle] = val
        elif not optionnel:
            print(f"  (vide → canal '{canal}' inactif, deals seulement au terminal + CSV)")
            ok = False
    config.sauver(cfg)
    return ok


# ── canaux ───────────────────────────────────────────────────
def _notif_macos(titre, message):
    if not shutil.which("osascript"):
        return
    t, m = titre.replace('"', "'"), message.replace('"', "'")
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{m}" with title "{t}"'], check=False)
    except Exception:
        pass

def _notif_telegram(message):
    token, chat = config.get("TELEGRAM_TOKEN"), config.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": message,
                                   "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
    except Exception as e:
        print(f"  ! Telegram échec : {e}")

def _notif_email(sujet, corps):
    exp, pwd = config.get("EMAIL_FROM"), config.get("EMAIL_PASSWORD")
    if not exp or not pwd:
        return
    dest = config.get("EMAIL_TO") or exp
    host = config.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(config.get("SMTP_PORT") or 587)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = exp, dest, sujet
    msg.set_content(corps)
    try:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(exp, pwd)
            s.send_message(msg)
    except Exception as e:
        print(f"  ! Email échec : {e}")

def _notif_discord(corps):
    wh = config.get("DISCORD_WEBHOOK")
    if not wh:
        return
    data = json.dumps({"content": corps[:1900]}).encode()
    # Discord renvoie 403 si le User-Agent est celui par défaut de urllib.
    req = urllib.request.Request(wh, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "rent-estimator/0.1 (+https://github.com)",
    })
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"  ! Discord échec : {e}")


# ── message ──────────────────────────────────────────────────
def _construire(nouveaux, baisses):
    n_new = 0 if nouveaux is None else len(nouveaux)
    n_bai = 0 if baisses is None else len(baisses)
    parts = []
    if n_new:
        parts.append(f"{n_new} nouveau(x) bon(s) plan(s)")
    if n_bai:
        parts.append(f"{n_bai} baisse(s) de prix")
    resume = " · ".join(parts)

    lignes = [f"🏠 Rent Estimator — {resume}\n"]
    for label, df in (("🆕 Nouveau", nouveaux), ("📉 Baisse", baisses)):
        if df is None:
            continue
        for _, r in df.iterrows():
            lignes.append(f"{label} — {r['Commune']} {int(r['Surface'])}m² "
                          f"{int(r['Prix'])}€ ({r['Decote']:.0f}%)\n{r['Lien']}")
    return resume, "\n\n".join(lignes)


def notifier_deals(nouveaux, baisses, canal="terminal"):
    """Envoie la notif sur le canal choisi. Le terminal affiche déjà les deals."""
    n_new = 0 if nouveaux is None else len(nouveaux)
    n_bai = 0 if baisses is None else len(baisses)
    if n_new == 0 and n_bai == 0:
        return
    resume, detail = _construire(nouveaux, baisses)

    if canal == "macos":
        _notif_macos("Rent Estimator", resume)
    elif canal == "telegram":
        _notif_telegram(detail)
    elif canal == "email":
        _notif_email(f"Rent Estimator — {resume}", detail)
    elif canal == "discord":
        _notif_discord(detail)
    # "terminal" / autre : rien de plus (déjà affiché dans le terminal)
