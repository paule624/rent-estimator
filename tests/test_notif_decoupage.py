"""Découpage des notifications : rien ne doit disparaître en silence.

Discord coupe à 2000 caractères, Telegram refuse au-delà de 4096. Un run qui
trouve 28 bons plans dépasse les deux. Avant, Discord perdait la fin et
Telegram perdait le message entier — dans les deux cas sans que personne ne
l'apprenne, la notification arrivant à 8h du matin dans un terminal fermé.
"""
import canaux


def _bloc(i):
    """Un bloc ressemblant à un vrai : deux lignes, dont un lien."""
    return f"🆕 Nouveau — Vannes {30 + i}m² {600 + i}€ (-20%)\nhttps://exemple.fr/annonce/{i}"


def _message(nb_blocs):
    return "\n\n".join(["🏠 Rent Estimator — résumé\n"] + [_bloc(i) for i in range(nb_blocs)])


def test_message_court_part_en_un_seul_morceau():
    texte = _message(3)
    assert canaux.decouper(texte, limite=1900) == [texte]


def test_message_long_est_reparti_sous_la_limite():
    morceaux = canaux.decouper(_message(60), limite=1900)
    assert len(morceaux) > 1
    for m in morceaux:
        assert len(m) <= 1900


def test_aucun_bloc_n_est_coupe_en_deux():
    """Un lien tranché au milieu donnerait une URL morte : pire que rien."""
    morceaux = canaux.decouper(_message(60), limite=1900)
    recolle = "\n\n".join(morceaux)
    for i in range(60):
        assert _bloc(i) in recolle or "et " in morceaux[-1]


def test_ce_qui_ne_tient_pas_est_compte_pas_effacé():
    """Au-delà du plafond de messages, on annonce le reste au lieu de le jeter."""
    morceaux = canaux.decouper(_message(400), limite=1900, max_messages=3)
    assert len(morceaux) == 3
    assert "autre(s)" in morceaux[-1]
    assert "Appartement_interessant.csv" in morceaux[-1]
    assert len(morceaux[-1]) <= 1900
    # Le compte annoncé couvre tout ce qui n'est pas parti.
    envoyes = sum(m.count("https://exemple.fr/annonce/") for m in morceaux)
    annonces = int(morceaux[-1].split("… et ")[1].split(" autre(s)")[0])
    assert envoyes + annonces == 400


def test_le_suffixe_ne_coupe_jamais_un_bloc_en_deux():
    """Faire de la place pour le suffixe doit retirer des blocs entiers."""
    morceaux = canaux.decouper(_message(400), limite=1900, max_messages=3)
    corps = morceaux[-1].split("\n\n… et ")[0]
    for bloc in corps.split("\n\n"):
        assert bloc.startswith("🏠") or bloc in [_bloc(i) for i in range(400)]


def test_un_bloc_plus_long_que_la_limite_est_tronque_mais_envoyé():
    """Cas dégénéré : mieux vaut un bloc tronqué qu'une boucle infinie."""
    morceaux = canaux.decouper("x" * 5000, limite=100)
    assert morceaux
    assert all(len(m) <= 100 for m in morceaux)


def test_message_vide_ne_produit_rien():
    assert canaux.decouper("", limite=1900) == []


def test_discord_envoie_autant_de_requetes_que_de_morceaux(monkeypatch):
    envoyes = []
    monkeypatch.setattr(canaux.config, "get", lambda k: "https://discord.test/webhook")
    monkeypatch.setattr(canaux.urllib.request, "urlopen",
                        lambda req, timeout=None: envoyes.append(req.data) or _Reponse())
    canaux.envoyer("discord", "résumé", _message(60))
    assert len(envoyes) > 1


def test_telegram_envoie_autant_de_requetes_que_de_morceaux(monkeypatch):
    envoyes = []
    monkeypatch.setattr(canaux.config, "get", lambda k: "valeur")
    monkeypatch.setattr(canaux.urllib.request, "urlopen",
                        lambda req, timeout=None: envoyes.append(req.data) or _Reponse())
    canaux.envoyer("telegram", "résumé", _message(200))
    assert len(envoyes) > 1


class _Reponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
