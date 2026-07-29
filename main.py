import argparse

import questionary

from model import MIN_ANNONCES_PAR_SECTEUR
import bons_plans
import canaux
import config
import notif
import recherche



def entier_ou_none(txt):
    """Valeur saisie, ou None si le champ est laissé vide — un champ vide vaut
    "pas de contrainte", pas une valeur par défaut cachée.

    `isdigit` accepte les seuls entiers positifs ; "10.5" ou "-5" tomberaient
    donc sur None. Ce n'est pas un trou : `valider_entier_optionnel` les rejette
    en amont dans les prompts. Ne pas appeler cette fonction sans ce garde-fou."""
    t = str(txt).strip() if txt is not None else ""
    return int(t) if t.isdigit() else None


def valider_entier_optionnel(txt):
    """Validateur questionary : accepte un entier positif ou rien du tout.
    Sans lui, une faute de frappe passerait pour "aucune contrainte"."""
    t = str(txt).strip() if txt is not None else ""
    return True if t == "" or t.isdigit() else "Entre un nombre, ou laisse vide"


# Deux issues d'un prompt, distinctes d'une vraie valeur (y compris None = "pas
# de contrainte") : tout abandonner, ou valider le récapitulatif.
ABANDON = object()
VALIDER = object()

# L'ordre des questions du flux « nouvelle recherche ». Sert aussi de colonne au
# récapitulatif : une seule liste, pas deux qui divergeraient.
_CHAMPS = ["ville", "km", "prix_max", "surface_min", "canal"]

_NUM_LABELS = {
    "km": ("Rayon (km) · vide = la commune seule", "ex : 10"),
    "prix_max": ("Budget max (€/mois) · vide = sans plafond", "ex : 700"),
    "surface_min": ("Surface mini (m²) · vide = sans minimum", "ex : 33"),
}


def _canal_choices():
    return [questionary.Choice(c.libelle, value=nom) for nom, c in canaux.CANAUX.items()]


def _profil_label(nom, p):
    rayon = f"{p['km']}km" if p.get("km") else "commune seule"
    budget = f"≤{p['prix_max']}€" if p.get("prix_max") else "sans plafond"
    return f"{nom} · {rayon} · {budget} · {p['canal']}"


def profil_vers_recherche(p, nom=None):
    """Un Profil sauvegardé est une Recherche nommée plus son Canal."""
    return recherche.Recherche(
        ville=p["ville"], km=p["km"], prix_max=p["prix_max"],
        surface_min=p["surface_min"], canal=p["canal"], nom=nom)


# ── flux « nouvelle recherche » ──────────────────────────────
# On corrige une saisie au récapitulatif éditable de fin, pas en cours de route.
# Chaque prompt vit dans sa propre fonction pour isoler questionary — la logique
# du récap se teste alors sans lui.
def _prompt_ville(courant):
    """Ville : obligatoire. Un champ vide → on redemande plutôt que d'avancer
    sans ville."""
    while True:
        v = questionary.text("Ville", placeholder="ex : Vannes, Paris, Lyon",
                             default=courant or "").ask()
        if v is None:          # Ctrl-C
            return ABANDON
        v = v.strip()
        if v:
            return v


def _prompt_entier(champ, courant):
    """Prompt numérique : vide = None, exemple grisé. La valeur courante préremplit
    le champ pour la corriger au récap sans tout retaper."""
    message, exemple = _NUM_LABELS[champ]
    defaut = "" if courant is None else str(courant)
    txt = questionary.text(message, placeholder=exemple, default=defaut,
                           validate=valider_entier_optionnel).ask()
    if txt is None:            # Ctrl-C
        return ABANDON
    return entier_ou_none(txt)


def _prompt_canal(courant):
    sel = questionary.select("Où recevoir les bons plans ?",
                             choices=_canal_choices(), default=courant).ask()
    return ABANDON if sel is None else sel


def _demander_champ(champ, courant):
    """Aiguille vers le bon prompt selon le champ. Seul point que les tests
    remplacent pour piloter tout le flux."""
    if champ == "ville":
        return _prompt_ville(courant)
    if champ == "canal":
        return _prompt_canal(courant)
    return _prompt_entier(champ, courant)


def _collecter_champs():
    """Pose les questions dans l'ordre. Rend le dict des valeurs, ou None si
    abandon."""
    v = {}
    for champ in _CHAMPS:
        res = _demander_champ(champ, None)
        if res is ABANDON:
            return None
        v[champ] = res
    if v["km"] is None:
        v["km"] = 0            # la commune seule, sans élargissement
    return v


def _resume_champ(champ, val):
    """Ligne du récap pour un champ, un vide dit en clair (« sans plafond »).

    Un if/elif, pas un dict littéral : celui-ci évaluerait `CANAUX[val]` pour
    tous les champs à la fois, et plantait sur la ville (val = un nom de ville,
    pas de canal)."""
    if champ == "ville":
        return f"ville : {val}"
    if champ == "km":
        return f"rayon : {f'{val}km' if val else 'commune seule'}"
    if champ == "prix_max":
        return f"budget max : {f'≤{val}€' if val else 'sans plafond'}"
    if champ == "surface_min":
        return f"surface mini : {f'≥{val}m²' if val else 'sans minimum'}"
    return f"canal : {canaux.CANAUX[val].libelle}"


def _choisir_champ_a_corriger(v, label_valider="✓ Lancer la recherche"):
    """Menu du récap : rend le champ à re-poser, VALIDER pour valider, None si
    Ctrl-C. Isolé pour que _reviser se teste sans questionary.

    `label_valider` distingue le flux : « Lancer la recherche » à la création,
    « Enregistrer » quand on édite un profil déjà sauvé."""
    choix = [questionary.Choice(label_valider, value=VALIDER)]
    choix += [questionary.Choice(f"Modifier {_resume_champ(c, v[c])}", value=c)
              for c in _CHAMPS]
    return questionary.select("Récapitulatif — corriger un champ ?", choices=choix).ask()


def _reviser(v, label_valider="✓ Lancer la recherche"):
    """Récap éditable : re-pose un champ à la demande jusqu'à validation. Rend le
    dict validé, ou None si abandon."""
    while True:
        sel = _choisir_champ_a_corriger(v, label_valider)
        if sel is None:        # Ctrl-C
            return None
        if sel is VALIDER:
            return v
        res = _demander_champ(sel, v[sel])
        if res is ABANDON:
            return None
        if sel == "km" and res is None:
            res = 0
        v[sel] = res


def nouvelle_recherche():
    v = _collecter_champs()
    if v is None:
        return None
    v = _reviser(v)
    if v is None:
        return None
    # Le canal n'est assuré qu'une fois figé : inutile de configurer un webhook
    # qu'une correction au récap remplacerait.
    canaux.assurer_config(v["canal"])

    profil = {c: v[c] for c in _CHAMPS}
    if questionary.confirm("Sauver cette recherche comme profil ?", default=True).ask():
        _sauver_profil_interactif(profil)
    return profil


def _sauver_profil_interactif(profil):
    profils = config.charger_profils()
    nom = questionary.text("Nom du profil", default=profil["ville"]).ask()
    if not nom:
        return
    if nom in profils and not questionary.confirm(f"'{nom}' existe déjà. Écraser ?",
                                                  default=False).ask():
        nom = questionary.text("Nouveau nom").ask()
        if not nom:
            return
    config.sauver_profil(nom, profil)
    print(f"  ✓ Profil '{nom}' sauvé.")


def _modifier_profil(nom):
    """Édite un profil sauvé via le même récap que la création, puis le
    réenregistre sous le même nom."""
    v = {c: config.get_profil(nom)[c] for c in _CHAMPS}
    v = _reviser(v, label_valider="✓ Enregistrer")
    if v is None:
        return
    # Un canal changé peut exiger un webhook : on l'assure une fois figé.
    canaux.assurer_config(v["canal"])
    config.sauver_profil(nom, {c: v[c] for c in _CHAMPS})
    print(f"  ✓ Profil '{nom}' modifié.")


def _supprimer_profil_interactif(profils):
    nom = questionary.select(
        "Supprimer quel profil ?",
        choices=list(profils) + [questionary.Choice("← annuler", value=None)],
    ).ask()
    if nom and questionary.confirm(f"Supprimer '{nom}' ?", default=False).ask():
        config.supprimer_profil(nom)
        print(f"  ✓ Profil '{nom}' supprimé.")


# ── menu principal ───────────────────────────────────────────
def menu_interactif():
    """Boucle du menu profils. Renvoie un dict profil, ou None si abandon."""
    while True:
        profils = config.charger_profils()
        if not profils:
            return nouvelle_recherche()

        dernier = config.get_dernier_profil()
        choix, defaut = [], None
        for nom, p in profils.items():
            c = questionary.Choice(_profil_label(nom, p), value=("profil", nom))
            choix.append(c)
            if nom == dernier:
                defaut = c
        choix.append(questionary.Choice("🆕 Nouvelle recherche", value=("nouveau", None)))
        choix.append(questionary.Choice("🗑 Supprimer un profil", value=("supprimer", None)))

        sel = questionary.select("Profil ?", choices=choix, default=defaut).ask()
        if sel is None:
            return None
        action, nom = sel
        if action == "profil":
            sous = questionary.select(
                _profil_label(nom, profils[nom]),
                choices=[
                    questionary.Choice("▶ Lancer la recherche", value="lancer"),
                    questionary.Choice("✏️  Modifier", value="modifier"),
                    questionary.Choice("← retour", value=None),
                ],
            ).ask()
            if sous == "lancer":
                config.set_dernier_profil(nom)
                return config.get_profil(nom)
            if sous == "modifier":
                _modifier_profil(nom)
            # retour / Ctrl-C → reboucle sur le menu
            continue
        if action == "nouveau":
            return nouvelle_recherche()
        if action == "supprimer":
            _supprimer_profil_interactif(profils)
            # retour au menu (boucle)


def _nom_recherche(profil):
    """Le nom du compartiment : celui du Profil qui rejoue la Recherche, ou la
    ville si elle n'a pas été sauvée.

    Se fier au dernier profil ouvert faisait atterrir une recherche non sauvée
    dans le dossier d'une autre ville, historiques mélangés compris."""
    dernier = config.get_dernier_profil()
    if dernier and config.get_profil(dernier) == profil:
        return dernier
    return profil["ville"]


def _parser():
    """Les canaux acceptés se lisent dans le registre : une liste recopiée ici
    finissait par diverger du menu, qui offrait alors un canal que la ligne de
    commande refusait."""
    p = argparse.ArgumentParser(description="Détecteur de locations sous-cotées (France).")
    p.add_argument("--ville")
    p.add_argument("--km", type=int)
    p.add_argument("--max", type=int, dest="prix_max")
    p.add_argument("--surface-min", type=int, dest="surface_min")
    p.add_argument("--notif", choices=list(canaux.CANAUX))
    p.add_argument("--profil", help="Rejoue un profil sauvegardé sans menu (pour cron)")
    return p


def recolte_parametres():
    """Renvoie (Recherche, interactif) ou None si abandon.
    `interactif` = True si on est passé par le menu (→ demander confirmation
    avant Chrome)."""
    a = _parser().parse_args()

    # Non-interactif : rejouer un profil (cron)
    if a.profil:
        prof = config.get_profil(a.profil)
        if not prof:
            print(f"Profil '{a.profil}' introuvable. Existants : {list(config.charger_profils())}")
            return None
        config.set_dernier_profil(a.profil)
        return profil_vers_recherche(prof, nom=a.profil), False

    # Non-interactif : flags explicites. Un flag omis vaut "pas de contrainte",
    # comme un champ laissé vide dans le menu — une même règle pour les deux
    # modes. `is not None` et pas `or` : --km 0 est un choix, pas un vide.
    if a.ville is not None:
        canal = a.notif or "terminal"
        canaux.assurer_config(canal)
        return recherche.Recherche(
            ville=a.ville, km=a.km if a.km is not None else 0, prix_max=a.prix_max,
            surface_min=a.surface_min, canal=canal), False

    # Interactif : menu profils
    print("=== Rent Estimator — Détecteur de bons plans location ===\n")
    profil = menu_interactif()
    if profil is None:
        return None
    print()
    return profil_vers_recherche(profil, nom=_nom_recherche(profil)), True


def _afficher_lignes(df):
    for _, r in df.iterrows():
        print(f"\n  {r['Secteur']} — {int(r['Surface'])}m², {int(r['Pieces'])} pièces — "
              f"{int(r['Prix'])}€/mois")
        print(f"    Décote : {r['Decote']:.0f}%  (estimé ~{int(r['Estimation'])}€)  "
              f"[{r['Source']}]")
        if not r.get("Fiable", True):
            print(f"    ⚠️  Estimation peu fiable : moins de "
                  f"{MIN_ANNONCES_PAR_SECTEUR} annonces dans ce secteur.")
        print(f"    {r['Lien']}")


def afficher_deals(deals):
    print("\n" + "=" * 60)
    if deals is None or len(deals) == 0:
        print("  Aucun bon plan trouvé avec ces critères.")
        print("  Essaie d'élargir : budget +, surface -, ou rayon +.")
        print("=" * 60)
        return
    marche, a_verifier = bons_plans.scinder(deals)

    print(f"  {len(marche)} BON(S) PLAN(S) — triés par décote")
    print("=" * 60)
    _afficher_lignes(marche)
    # Prix hors du marché observé : forte décote, faible crédibilité. Séparés
    # pour ne pas occuper la tête de liste (cf docs/adr/0004).
    if len(a_verifier):
        print("\n" + "=" * 60)
        print(f"  {len(a_verifier)} À VÉRIFIER — prix hors du marché observé")
        print("=" * 60)
        _afficher_lignes(a_verifier)
    print("\n" + "=" * 60)


def main():
    params = recolte_parametres()
    if params is None:
        print("Abandon.")
        return
    cherchee, interactif = params

    if interactif:
        print(f"\n▶ Recherche : {cherchee.resume()} · notif {cherchee.canal}")
        print("  Une fenêtre Chrome va s'ouvrir automatiquement (elle se ferme seule à la fin).")
        if not questionary.confirm("Commencer ?", default=True).ask():
            print("Annulé.")
            return

    resultat = recherche.executer(cherchee)
    if resultat is None:
        return

    afficher_deals(resultat.deals)

    if len(resultat.nouveaux) or len(resultat.baisses):
        print(f"\n🔔 {len(resultat.nouveaux)} nouveau(x) · {len(resultat.baisses)} "
              f"baisse(s) depuis le dernier run")
        notif.notifier_deals(resultat.nouveaux, resultat.baisses, canal=cherchee.canal)

    print(f"\n→ Détail complet + liens : {resultat.chemin}")


if __name__ == "__main__":
    main()
