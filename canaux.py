"""Les Canaux : par où les bons plans sortent à la fin d'un run (CONTEXT.md).

Un Canal se déclare **une fois**, ici. Le menu, l'analyseur de ligne de commande
et l'envoi le lisent tous depuis ce registre : avant, en ajouter un demandait de
toucher cinq endroits, dont une liste recopiée en dur dans `--notif` — le menu
l'offrait, la ligne de commande le refusait.

Les identifiants (token, webhook) sont **globaux**, pas stockés par Profil : un
même webhook Discord sert tous les profils (cf CONTEXT.md, ambiguïté relevée).
"""
import os
import ssl
import json
import getpass
import shutil
import smtplib
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Callable

import config

# Discord refuse au-delà de 2000 caractères, Telegram au-delà de 4096. On reste
# en dessous : le corps part tel quel s'il tient, sinon en plusieurs messages.
LIMITE_DISCORD = 1900
LIMITE_TELEGRAM = 4000
# Un premier run compare à un historique vide : toutes les annonces sont neuves.
# Sans plafond, une recherche sur Paris déverserait des centaines de messages.
MAX_MESSAGES = 5


def _ou_trouver_la_suite():
    """Où lire les bons plans qui n'ont pas tenu dans la notification.

    Se lit à l'usage, jamais à l'import : chaque Recherche a son sous-dossier,
    connu seulement au lancement du run. Un chemin figé envoyait l'utilisateur
    sur un fichier qui n'existe plus depuis le cloisonnement."""
    chemin = config.chemin_deals()
    relatif = os.path.relpath(chemin, config.RACINE)
    return f"voir {chemin if relatif.startswith('..') else relatif}"


def decouper(corps, limite, max_messages=MAX_MESSAGES):
    """Répartit `corps` en messages tenant sous `limite`.

    La découpe suit les frontières de blocs (deux sauts de ligne), jamais
    l'intérieur d'un bloc : un lien tranché en deux donnerait une URL morte,
    ce qui est pire que de ne rien envoyer. Ce qui dépasse le plafond de
    messages est annoncé — jamais effacé en silence.
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
        suffixe = f"\n\n… et {restants} autre(s), {_ou_trouver_la_suite()}"
        corps = "\n\n".join(blocs)
        if len(corps) + len(suffixe) <= limite:
            messages[-1] = corps + suffixe
            return messages
        blocs.pop()
        restants += 1
    # Même vide, le dernier message doit dire ce qui manque.
    messages[-1] = f"… et {restants} autre(s), {_ou_trouver_la_suite()}"[:limite]
    return messages


@dataclass(frozen=True)
class Champ:
    """Un identifiant à demander une fois puis à garder (.config.json)."""
    cle: str
    label: str
    secret: bool = False
    optionnel: bool = False


@dataclass(frozen=True)
class Canal:
    libelle: str                    # ce que le menu affiche
    envoyer: Callable                # (resume, detail) -> None
    champs: tuple = field(default_factory=tuple)


# ── transports ───────────────────────────────────────────────
def _envoyer_terminal(resume, detail):
    """Les bons plans sont déjà à l'écran : le terminal n'a rien à envoyer."""


def _envoyer_macos(resume, detail):
    if not shutil.which("osascript"):
        return
    t, m = "Rent Estimator", resume.replace('"', "'")
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{m}" with title "{t}"'], check=False)
    except Exception:
        pass


def _envoyer_telegram(resume, detail):
    token, chat = config.get("TELEGRAM_TOKEN"), config.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for morceau in decouper(detail, LIMITE_TELEGRAM):
        data = urllib.parse.urlencode({"chat_id": chat, "text": morceau,
                                       "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
        except Exception as e:
            print(f"  ! Telegram échec : {e}")
            return


def _envoyer_email(resume, detail):
    exp, pwd = config.get("EMAIL_FROM"), config.get("EMAIL_PASSWORD")
    if not exp or not pwd:
        return
    dest = config.get("EMAIL_TO") or exp
    host = config.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(config.get("SMTP_PORT") or 587)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = exp, dest, f"Rent Estimator — {resume}"
    msg.set_content(detail)
    try:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(exp, pwd)
            s.send_message(msg)
    except Exception as e:
        print(f"  ! Email échec : {e}")


def _envoyer_discord(resume, detail):
    wh = config.get("DISCORD_WEBHOOK")
    if not wh:
        return
    for morceau in decouper(detail, LIMITE_DISCORD):
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


# ── registre ─────────────────────────────────────────────────
CANAUX = {
    "terminal": Canal("Terminal seulement", _envoyer_terminal),
    "macos": Canal("Notification macOS", _envoyer_macos),
    "telegram": Canal("Telegram", _envoyer_telegram, (
        Champ("TELEGRAM_TOKEN", "Token du bot Telegram (via @BotFather)", secret=True),
        Champ("TELEGRAM_CHAT_ID", "Chat ID Telegram"),
    )),
    "email": Canal("Email", _envoyer_email, (
        Champ("EMAIL_FROM", "Ton email expéditeur"),
        Champ("EMAIL_PASSWORD", "Mot de passe d'application", secret=True),
        Champ("EMAIL_TO", "Email destinataire (Entrée = le même)", optionnel=True),
    )),
    "discord": Canal("Discord", _envoyer_discord, (
        Champ("DISCORD_WEBHOOK", "URL du webhook Discord"),
    )),
}


def assurer_config(canal):
    """Demande interactivement les identifiants manquants du canal et les sauve."""
    declare = CANAUX.get(canal)
    if not declare or not declare.champs:
        return True
    cfg = config.charger()
    ok = True
    for champ in declare.champs:
        if config.get(champ.cle):
            continue
        prompt = f"  {champ.label} : "
        val = (getpass.getpass(prompt) if champ.secret else input(prompt)).strip()
        if val:
            cfg[champ.cle] = val
        elif not champ.optionnel:
            print(f"  (vide → canal '{canal}' inactif, deals seulement au terminal + CSV)")
            ok = False
    config.sauver(cfg)
    return ok


def envoyer(canal, resume, detail):
    """Remet le message au canal demandé. Un canal inconnu ne fait rien plutôt
    que de faire échouer un run dont les bons plans sont déjà à l'écran."""
    declare = CANAUX.get(canal)
    if declare:
        declare.envoyer(resume, detail)
