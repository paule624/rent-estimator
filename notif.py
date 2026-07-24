"""Notifications multi-canal : terminal, macOS, Telegram, Email, Discord.

Les canaux distants utilisent des variables d'environnement (pas de secret
dans le code) :
- Telegram : TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
- Email    : EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO (optionnel), SMTP_HOST/PORT (optionnel)
- Discord  : DISCORD_WEBHOOK
"""
import os
import ssl
import json
import shutil
import smtplib
import subprocess
import urllib.parse
import urllib.request
from email.message import EmailMessage

CANAUX = {
    "1": ("terminal", "Terminal seulement"),
    "2": ("macos", "Notification macOS"),
    "3": ("telegram", "Telegram"),
    "4": ("email", "Email"),
    "5": ("discord", "Discord"),
}

# Variables d'env requises par canal (pour la vérification au démarrage)
_REQUIS = {
    "telegram": ["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"],
    "email": ["EMAIL_FROM", "EMAIL_PASSWORD"],
    "discord": ["DISCORD_WEBHOOK"],
}
_AIDE = {
    "telegram": "export TELEGRAM_TOKEN=... ; export TELEGRAM_CHAT_ID=...",
    "email": "export EMAIL_FROM=... ; export EMAIL_PASSWORD=... (mot de passe d'application)",
    "discord": "export DISCORD_WEBHOOK=https://discord.com/api/webhooks/...",
}


def verifier_canal(canal):
    """Prévient au démarrage si le canal choisi n'est pas configuré."""
    manquants = [v for v in _REQUIS.get(canal, []) if not os.environ.get(v)]
    if manquants:
        print(f"⚠️  Canal '{canal}' non configuré (manque : {', '.join(manquants)}).")
        print(f"    Configure-le avant : {_AIDE[canal]}")
        print("    Sinon la notif sera ignorée (les deals restent dans le terminal + CSV).\n")
        return False
    return True


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
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
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
    exp, pwd = os.environ.get("EMAIL_FROM"), os.environ.get("EMAIL_PASSWORD")
    if not exp or not pwd:
        return
    dest = os.environ.get("EMAIL_TO", exp)
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
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
    wh = os.environ.get("DISCORD_WEBHOOK")
    if not wh:
        return
    data = json.dumps({"content": corps[:1900]}).encode()
    req = urllib.request.Request(wh, data=data, headers={"Content-Type": "application/json"})
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
