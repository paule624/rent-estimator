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


# ── découpage ────────────────────────────────────────────────
# Discord refuse au-delà de 2000 caractères, Telegram au-delà de 4096. On reste
# en dessous : le corps part tel quel s'il tient, sinon en plusieurs messages.
LIMITE_DISCORD = 1900
LIMITE_TELEGRAM = 4000
# Un premier run compare à un historique vide : toutes les annonces sont neuves.
# Sans plafond, une recherche sur Paris déverserait des centaines de messages.
MAX_MESSAGES = 5
OU_TROUVER_LA_SUITE = "voir output/Appartement_interessant.csv"


def _decouper(corps, limite, max_messages=MAX_MESSAGES):
    """Répartit `corps` en messages tenant sous `limite`.

    La découpe suit les frontières de blocs (deux sauts de ligne), jamais
    l'intérieur d'un bloc : un lien tranché en deux donnerait une URL morte,
    ce qui est pire que de ne rien envoyer. Ce qui dépasse le plafond de
    messages est annoncé — jamais effacé en silence, ce que faisait l'ancien
    `corps[:1900]`.
    """
    if not corps:
        return []

    blocs, messages, courant = corps.split("\n\n"), [], ""
    for i, bloc in enumerate(blocs):
        candidat = f"{courant}\n\n{bloc}" if courant else bloc
        if len(candidat) <= limite:
            courant = candidat
            continue
        if courant:
            messages.append(courant)
        # Un bloc seul plus long que la limite ne rentrera dans aucun message :
        # on le tronque plutôt que de boucler sans fin.
        courant = bloc if len(bloc) <= limite else bloc[:limite - 1] + "…"
        if len(messages) == max_messages:
            restants = len(blocs) - i
            return _annoncer_le_reste(messages, restants, limite)
    if courant:
        messages.append(courant)
    return messages


def _annoncer_le_reste(messages, restants, limite):
    """Ajoute au dernier message le compte de ce qui n'a pas été envoyé.

    Faire de la place en tranchant des caractères couperait un bloc en deux —
    le défaut même qu'on corrige. On retire donc des blocs entiers du dernier
    message, chacun venant grossir le compte annoncé.
    """
    blocs = messages[-1].split("\n\n")
    while blocs:
        suffixe = f"\n\n… et {restants} autre(s), {OU_TROUVER_LA_SUITE}"
        corps = "\n\n".join(blocs)
        if len(corps) + len(suffixe) <= limite:
            messages[-1] = corps + suffixe
            return messages
        blocs.pop()
        restants += 1
    # Même vide, le dernier message doit dire ce qui manque.
    messages[-1] = f"… et {restants} autre(s), {OU_TROUVER_LA_SUITE}"[:limite]
    return messages


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
    for morceau in _decouper(message, LIMITE_TELEGRAM):
        data = urllib.parse.urlencode({"chat_id": chat, "text": morceau,
                                       "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
        except Exception as e:
            print(f"  ! Telegram échec : {e}")
            return

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
    for morceau in _decouper(corps, LIMITE_DISCORD):
        data = json.dumps({"content": morceau}).encode()
        # Discord renvoie 403 si le User-Agent est celui par défaut de urllib.
        req = urllib.request.Request(wh, data=data, headers={
            "Content-Type": "application/json",
            "User-Agent": "rent-estimator/0.1 (+https://github.com)",
        })
        try:
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print(f"  ! Discord échec : {e}")
            return


# ── message ──────────────────────────────────────────────────
def _scinder(df):
    """Sépare le marché observé de ce qui reste à vérifier (cf ADR 0004)."""
    if df is None or len(df) == 0 or "HorsMarche" not in df.columns:
        return df, None
    hors = df["HorsMarche"].astype(bool)
    return df[~hors], (df[hors] if hors.any() else None)


def _blocs(label, df):
    if df is None:
        return []
    lignes = []
    for _, r in df.iterrows():
        # Un secteur trop peu représenté donne une estimation fragile : le
        # bon plan part quand même, mais avec son doute.
        doute = "" if r.get("Fiable", True) else "\n⚠️ estimation peu fiable"
        lignes.append(f"{label} — {r['Secteur']} {int(r['Surface'])}m² "
                      f"{int(r['Prix'])}€ ({r['Decote']:.0f}%){doute}\n{r['Lien']}")
    return lignes


def _construire(nouveaux, baisses):
    new_marche, new_hors = _scinder(nouveaux)
    bai_marche, bai_hors = _scinder(baisses)
    n_new = 0 if new_marche is None else len(new_marche)
    n_bai = 0 if bai_marche is None else len(bai_marche)
    n_hors = sum(0 if d is None else len(d) for d in (new_hors, bai_hors))

    parts = []
    if n_new:
        parts.append(f"{n_new} nouveau(x) bon(s) plan(s)")
    if n_bai:
        parts.append(f"{n_bai} baisse(s) de prix")
    # Compté à part : le résumé sert de titre, il ne doit pas gonfler d'annonces
    # dont on doute.
    if n_hors:
        parts.append(f"{n_hors} à vérifier")
    resume = " · ".join(parts)

    lignes = [f"🏠 Rent Estimator — {resume}\n"]
    for label, df in (("🆕 Nouveau", new_marche), ("📉 Baisse", bai_marche)):
        lignes += _blocs(label, df)
    # En fin de message : leur décote est la plus forte sans être la plus
    # crédible, et la notification est plafonnée à quelques messages.
    if n_hors:
        lignes.append("⚠️ Hors marché — prix hors du marché observé, à vérifier")
        for label, df in (("🆕 Nouveau", new_hors), ("📉 Baisse", bai_hors)):
            lignes += _blocs(label, df)
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
