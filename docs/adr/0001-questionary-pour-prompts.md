# Utiliser questionary pour les prompts interactifs

Le CLI passe des prompts `input()` bruts à une vraie interface interactive
(menus à flèches, sélection, valeurs par défaut) via **questionary**.

## Contexte

La philosophie par défaut du projet est de minimiser les dépendances
externes. Or une sélection au clavier (flèches + Enter, façon
`create-next-app`) est impossible avec `input()` seul : il faut passer le
terminal en "raw mode", ce que fait `prompt_toolkit` (dont dépend questionary).

## Décision

On ajoute `questionary` malgré la règle "min de deps", parce que :
- le gain UX est central pour l'usage quotidien (menu de profils, choix du canal) ;
- la lib est pure Python, stable, et vérifiée compatible Python 3.14 ;
- la dépendance reste réversible (retour à `input()` possible sans changer la logique).

## Conséquences

- Les prompts nécessitent un vrai terminal (tty). L'usage non-interactif
  (cron) passe par `--profil <nom>` ou les flags `--ville/--km/...`, qui
  n'appellent jamais questionary.
