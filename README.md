# Pricer d'options et de produits structurés

Pricer Python (Flask) construit autour du cours d'options de la S&P Academy. Trois onglets :

1. **Options vanilles** : long/short call et put, valeur intrinsèque et valeur temps, profil de gain, grecs.
2. **Stratégies** : 11 stratégies du chapitre 3 (covered call, protective put, long/short straddle, long/short strangle, bull call spread, bear put spread, collar, risk reversal, forward synthétique).
3. **Produits structurés** : Phoenix, Athéna (Autocall Plain), accumulateur, décumulateur et DRA Daily.

Un bloc **Paramètres de marché à t₀** (spot, volatilité, taux, dividende) alimente les trois onglets. Un bouton bascule la valorisation entre **Black-Scholes** (formule fermée) et **Monte Carlo** quand les deux existent. Tous les produits affichent leurs **grecs** (primaires et principaux secondaires).

Guide du code ajouté : [README_NOUVEAUX_MOTEURS.md](README_NOUVEAUX_MOTEURS.md).

## Lancer sur ton Mac

Un environnement `venv` local est présent dans cette copie. Depuis le dossier du pricer :

```bash
source venv/bin/activate
python main.py
```

Ouvrir http://127.0.0.1:5001. Le port 5001 est distinct du port 5000 de l’ancien projet. Si tu déplaces le dossier ou changes d’ordinateur, recrée l’environnement avec les instructions suivantes : un environnement virtuel n’est pas portable.

## Installer sur un autre ordinateur

Depuis ce dossier :

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Les versions du fichier requirements correspondent à l'environnement utilisé pour les vérifications. Un environnement local venv a depuis été créé, les dépendances installées et les tests exécutés avec cet environnement. Les commandes d'activation ci-dessus conviennent à macOS/Linux.

Ctrl + C arrête le serveur. Après modification Python, arrêter puis relancer le serveur ; après modification HTML, recharger la page.

## Utilisation

Les trois onglets (Options vanilles, Stratégies, Produits structurés) partagent le bloc « Paramètres de marché » en haut de page : spot S₀, source et valeur de la volatilité à t₀, taux r, dividende q, méthode de valorisation (Black-Scholes ou Monte Carlo), nombre de simulations et graine.

| Produit | Black-Scholes | Monte Carlo |
|---|---|---|
| Options, stratégies | oui (formules du cours) | oui |
| DRA Daily | oui (somme de probabilités digitales) | oui |
| Phoenix, Athéna, accumulateur, décumulateur | non (barrières observées aux constats) | oui, seule méthode |

Sans ticker, le spot (100 par défaut) et la volatilité à t₀ se saisissent dans ce bloc : le pricing fonctionne sans Yahoo Finance. Pour charger le marché, chercher puis sélectionner un ticker ; le spot et les volatilités disponibles sont récupérés. Choisir Manuelle, Historique (1 an) ou VIX. Le taux et le dividende restent ceux saisis. Le VIX est celui du S&P 500, pas la volatilité implicite propre au titre. Si le VIX est indisponible, le spot et la volatilité historique peuvent quand même être utilisés.

Le coupon est exprimé **par observation**, pas par an : 4 % avec des constats semestriels signifie 4 % par semestre. Les valeurs du formulaire sont en pourcentage ; le moteur reçoit des décimaux.

- **Phoenix** : coupons périodiques conditionnels, mémoire facultative, rappel activable, step-up, bonus et protection finale selon les paramètres existants.
- **Autocall Plain** : coupons accumulés payés au rappel. Sans rappel anticipé, tous les coupons sont payés à maturité uniquement si le seuil final est atteint, sinon aucun. Cette mécanique est de type Athéna classique. La protection du capital est observée à maturité.

Les règles financières de ces deux produits sont conservées depuis le projet initial. Le nom Plain désigne ici le produit effectivement implémenté ; les paramètres d'un contrat réel doivent toujours être vérifiés séparément.

## Résultats

Le prix est la moyenne des flux actualisés. L'intervalle de confiance décrit l'incertitude Monte Carlo, pas l'erreur du modèle. Les probabilités sont celles du modèle risque-neutre, pas des prévisions du marché. La perte en capital concerne le principal avant prise en compte des coupons. L'écart entre 100 % et la valeur n'est pas une marge commerciale nette.

Le graphique Phoenix représente seulement le remboursement final des scénarios non rappelés, avec le dernier coupon. Il exclut les coupons déjà versés et tout le rattrapage lié au chemin. Le Plain affiche aussi un graphique de remboursement à maturité, sous l'hypothèse d'absence de rappel anticipé. Il inclut tous les coupons accumulés si le seuil final est atteint, sinon aucun coupon. La courbe de gain/perte soustrait le nominal investi ; les montants ne sont pas actualisés.

## Fichiers

- `main.py` : serveur Flask et routes `/`, `/api/search_ticker`, `/api/market/<ticker>`, `/api/phoenix`, `/api/autocall`, `/api/option`, `/api/strategies`, `/api/strategie`, `/api/accumulateur`, `/api/dra`.
- `options_engine.py` : Black-Scholes, Monte Carlo et grecs d'une option.
- `strategies_engine.py` : les 11 stratégies du cours.
- `fixings_engine.py` : accumulateur, décumulateur, DRA Daily.
- `greeks_engine.py` : grecs par différences finies (Phoenix, Athéna, accumulateur, DRA).
- `strutu_engine.py` : moteurs Phoenix et Plain.
- `market_data_engine.py` : données de marché utiles au pricing.
- `volatility_engine.py` : rendements et volatilité historique nécessaires aux paramètres.
- `templates/index.html`, `static/style.css`, `static/app.js` : interface (structure, apparence, logique). `static/logo.svg` est le logo : remplacer ce fichier suffit à le changer ; les couleurs sont les variables en tête de `style.css`.
- `requirements.txt` : bibliothèques nécessaires.
- `tests/` : vérifications des routes et des mécanismes.

Aucun import de `pricer_engine.py` ni de `rates_engine.py` n'est nécessaire. Les données de marché exigent une connexion Internet et dépendent de Yahoo Finance. La saisie manuelle reste disponible.

## Tests

```bash
python -m unittest discover -s tests -v
```

`tests/test_nouveaux_moteurs.py` (37 tests) vérifie des propriétés financières : parité call-put, grecs analytiques contre différences finies, signes du tableau du chapitre 10, formules du cours pour les stratégies, accumulateur à volatilité quasi nulle (valeur calculable à la main), strike zéro coût, égalité Black-Scholes / Monte Carlo du DRA, et toutes les routes.

Les tests automatisés des deux produits d'origine couvrent le Plain déterministe, les coupons, les unités, les erreurs, le report du rappel, le Phoenix, les pertes sur toutes les trajectoires et l'absence des routes supprimées. Les moteurs sont comparés à ceux du projet d'origine avec la même graine pour vérifier l'identité des résultats.

## Présentation harmonisée des résultats

Les deux produits affichent les mêmes huit indicateurs, dans le même ordre et avec deux décimales : prix théorique, valeur monétaire, marge émetteur, probabilité de perte du principal, durée de vie moyenne, probabilité d’arriver à maturité, remboursement moyen du principal en cas de perte, coupons moyens actualisés. Le prix, le graphe et le calendrier décrivent des objets différents ; les notes précisent les hypothèses. Les tests de graphique vérifient les égalités aux barrières et l’absence de perte du principal lorsque le knock-in est désactivé.


## Guides pédagogiques des fichiers

Chaque guide présente le rôle du fichier, les conventions, des exemples et le code des fonctions suivi d’une **Traduction en phrase**.

- [main.py : serveur, routes, paramètres et graphiques](README_MAIN.md)
- [strutu_engine.py : simulation, Phoenix, Plain et statistiques](README_STRUTURES_PEDAGOGIQUE.md)
- [market_data_engine.py : recherche et données Yahoo Finance](README_MARKET_DATA.md)
- [volatility_engine.py : rendements logarithmiques et volatilité historique](README_VOLATILITY.md)

Lire d’abord ce guide général, puis le serveur pour suivre le parcours d’un clic, le moteur pour comprendre le prix et les deux modules de marché pour comprendre les entrées.

## Comment la valeur théorique est calculée

Le moteur simule le sous-jacent sous un modèle risque-neutre à taux, dividende et volatilité constants. Pour chaque trajectoire, il applique les règles du produit et actualise les paiements à leur date avec `exp(-r × t)`. La moyenne de ces flux donne le prix pour un nominal de 1. Le serveur convertit cette valeur en pourcentage et en montant investi. Les probabilités affichées sont des fréquences dans ces simulations, pas des probabilités historiques estimées séparément.

Exemple : `prix=0.95` dans le moteur donne 95 % du nominal et 950 pour un investissement de 1 000. L’écart affiché de 5 % représente 50 du nominal, avant frais, couverture et risque de défaut. Le graphique de remboursement à maturité représente des flux futurs conditionnels, pas cette valeur actualisée.

## Option de rappel anticipé du Plain

La case **Remboursement anticipé possible (autocall)** est cochée par défaut. Décochée, elle masque le premier rappel autorisé et envoie `has_autocall=false`. Le produit reste en vie jusqu’à maturité : aucun rappel, durée égale à T, probabilité de maturité de 100 %. Le seuil reste utile pour le coupon final.

Les coupons ne sont pas acquis aux constats intermédiaires. À maturité, tous les coupons accumulés sont dus si le cours final atteint le seuil ; sinon aucun. La protection conditionnelle du capital reste une option indépendante. Les anciens appels qui omettent `has_autocall` gardent le rappel activé.
