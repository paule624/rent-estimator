"""Notifications : macOS native (zéro config) + Telegram optionnel.

Telegram s'active si les variables d'environnement TELEGRAM_TOKEN et
TELEGRAM_CHAT_ID sont définies ; sinon on l'ignore silencieusement.
"""
import os
import json
import shutil
import subprocess
import urllib.parse
import urllib.request


def _notif_macos(titre, message):
    if not shutil.which("osascript"):
        return
    texte = message.replace('"', "'")
    titre = titre.replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{texte}" with title "{titre}"'],
            check=False,
        )
    except Exception:
        pass


def _notif_telegram(message):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": message, "disable_web_page_preview": "true",
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
    except Exception:
        pass


def notifier_deals(nouveaux, baisses):
    """Notifie s'il y a de nouvelles annonces ou des baisses de prix."""
    n_new = 0 if nouveaux is None else len(nouveaux)
    n_baisse = 0 if baisses is None else len(baisses)
    if n_new == 0 and n_baisse == 0:
        return

    titre = "Rent Estimator"
    resume = []
    if n_new:
        resume.append(f"{n_new} nouveau(x) bon(s) plan(s)")
    if n_baisse:
        resume.append(f"{n_baisse} baisse(s) de prix")
    resume = " · ".join(resume)

    _notif_macos(titre, resume)

    # Telegram : message détaillé avec les liens
    lignes = [f"🏠 {titre} — {resume}\n"]
    for label, df in (("🆕 Nouveau", nouveaux), ("📉 Baisse", baisses)):
        if df is None:
            continue
        for _, r in df.iterrows():
            lignes.append(
                f"{label} — {r['Commune']} {int(r['Surface'])}m² "
                f"{int(r['Prix'])}€ ({r['Decote']:.0f}%)\n{r['Lien']}"
            )
    _notif_telegram("\n\n".join(lignes))
