"""Le message qu'un run envoie : ce qu'il dit, et dans quel ordre.

Par où il part est l'affaire des Canaux (canaux.py) ; combien de morceaux il
fait, celle de leurs limites. Ici on décide seulement de ce qui est écrit, et
de ce que le résumé annonce — c'est lui qui décide si la notification est
ouverte, donc il ne doit pas gonfler d'annonces dont on doute (ADR 0004).
"""
import bons_plans
import canaux


def _blocs(label, df):
    lignes = []
    for _, r in df.iterrows():
        # Un secteur trop peu représenté donne une estimation fragile : le
        # bon plan part quand même, mais avec son doute.
        doute = "" if r.get("Fiable", True) else "\n⚠️ estimation peu fiable"
        lignes.append(f"{label} — {r['Secteur']} {int(r['Surface'])}m² "
                      f"{int(r['Prix'])}€ ({r['Decote']:.0f}%){doute}\n{r['Lien']}")
    return lignes


def _construire(nouveaux, baisses):
    new_marche, new_hors = bons_plans.scinder(nouveaux)
    bai_marche, bai_hors = bons_plans.scinder(baisses)
    n_new, n_bai = len(new_marche), len(bai_marche)
    n_hors = len(new_hors) + len(bai_hors)

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
    canaux.envoyer(canal, resume, detail)
