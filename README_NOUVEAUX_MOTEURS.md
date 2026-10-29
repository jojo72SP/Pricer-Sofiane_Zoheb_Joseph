# Guide des nouveaux moteurs

Ce guide explique le code ajouté : options, stratégies, accumulateur, décumulateur, DRA Daily, grecs et interface. Il suit le même esprit que les guides des fichiers existants. Ordre de lecture conseillé : parcours d'un clic, `options_engine.py`, `strategies_engine.py`, `greeks_engine.py`, `fixings_engine.py`, puis l'interface.

## 1. Parcours d'un clic

Exemple : un clic sur **Calculer** dans l'onglet Options.

1. `static/app.js` lit le bloc « Paramètres de marché » (`lireMarche`) et le formulaire de l'onglet, puis envoie un JSON à `/api/option`.
2. `main.py` (`api_option`) vérifie les valeurs (spot positif, volatilité entre 0 et 200 %, taux, dividende, maturité), convertit les pourcentages en décimaux et appelle `options_engine.analyser_option`.
3. Le moteur renvoie prime, grecs, profil de gain, points morts. Flask renvoie le tout en JSON.
4. `app.js` construit les indicateurs, le graphique SVG et le tableau des grecs.

Les autres onglets suivent le même chemin avec leur propre route et leur propre moteur.

## 2. Conventions

- Dans les moteurs : r, q, σ en **décimal** (0,25 = 25 %), durées en **années**, barrières des structurés en **fraction du spot initial**.
- Dans l'interface et dans le JSON reçu par Flask : les mêmes valeurs en **pourcentage**. Les sorties de pourcentage portent le suffixe `_pct`.
- Dividende `q` continu, comme au chapitre 4 du cours.

## 3. `options_engine.py` : une option

**Black-Scholes (chapitre 7).** Avec `d1 = [ln(S/K) + (r − q + σ²/2)·T] / (σ√T)` et `d2 = d1 − σ√T` :

- call = `S·e^(−qT)·N(d1) − K·e^(−rT)·N(d2)`
- put = `K·e^(−rT)·N(−d2) − S·e^(−qT)·N(−d1)`

**Monte Carlo (chapitre 11).** On tire des chocs normaux `Z`, on simule `S_T = S·exp[(r − q − σ²/2)·T + σ√T·Z]`, on calcule le payoff et on actualise. Deux choix techniques :

- **Variables antithétiques** : chaque `Z` sert deux trajectoires (`Z` et `−Z`), ce qui réduit la variance (cours 11.4.a).
- **Mêmes tirages pour tous les calculs** : les grecs Monte Carlo sont des différences entre deux prix. Avec les mêmes tirages, l'écart vient du paramètre qu'on a bougé, pas du hasard.

**Grecs.** `bs_grecs` donne les formules analytiques des chapitres 8 et 9 (delta, gamma, vega, theta, rho, vanna, vomma, charm, color, speed, zomma, ultima, lambda). `mc_grecs` les calcule par différences finies. En Monte Carlo, color, speed, zomma et ultima (dérivées d'ordre 3) sont trop bruités : ils restent à `None`, et l'interface affiche « B&S uniquement ».

**Unités de lecture** (`grecs_affichage`) : vega, vanna, vomma, zomma, ultima pour +1 point de volatilité ; theta, charm, color par jour ; rho pour +1 point de taux. Les valeurs brutes sont par unité de σ, par an, par unité de taux.

**Profil de gain.** `analyser_option` renvoie le profit à l'échéance **prime incluse, sans actualisation**, comme au chapitre 2.5 du cours, avec points morts et gain/perte maximaux (« illimité » quand la pente reste non nulle à droite).

## 4. `strategies_engine.py` : les stratégies

Une stratégie est une liste de **jambes** (option ou action) avec un signe (+1 long, −1 short). Le dictionnaire `STRATEGIES` contient le texte du cours (construction, vue de marché, intérêt). `construire_jambes` transforme les paramètres (K, K1, K2, T) en jambes.

Exemple, covered call = jambe action (+1) + jambe call (−1, strike K). Pour chaque jambe on calcule le prix et les grecs, puis :

- **coût net** = somme des prix signés (positif = débit, négatif = crédit) ;
- **grecs de la stratégie** = somme des grecs signés des jambes (lambda est recalculé sur la stratégie entière, car il n'est pas additif) ;
- **profit à l'échéance** = somme des gains des jambes − coût net.

En Monte Carlo, toutes les jambes partagent les mêmes tirages : l'erreur type affichée est celle de la **stratégie entière**, pas d'une jambe.

Les stratégies sont vérifiées contre les formules du cours dans `tests/` (par exemple covered call : point mort `S0 − C`, gain max `(K − S0) + C`).

## 5. `greeks_engine.py` : les grecs par différences finies

Pour les produits sans formule fermée, `grecs_diff_finies(f, S, σ, r, dt)` fait varier une fonction de valeur `f(S, σ, r, tau)` autour du point de départ (`tau` = temps écoulé) :

- delta = `[f(S+h) − f(S−h)] / 2h`, gamma = `[f(S+h) − 2f(S) + f(S−h)] / h²`, vega par différence en σ, rho par différence en r ;
- theta = `[f(tau=dt) − f(0)] / dt` ; vanna, vomma, charm sont des dérivées croisées ;
- avec `ordre3=True` (formule fermée seulement) : color, speed, zomma, ultima.

Le moteur est validé sur le call Black-Scholes : il retrouve les 13 grecs analytiques.

**Deux astuces à comprendre.**

1. *Spot de référence 100.* Pour Phoenix, Athéna et DRA, le prix en % du nominal ne dépend que de `S / S_initial`. On calcule donc les grecs avec un spot de 100 : le delta se lit « en points de nominal pour +1 % de spot ».
2. *Strike initial fixe.* Quand on fait bouger le spot, le strike initial ne bouge pas. On l'obtient en ajustant `strike_pct` (ou les bornes du DRA) en sens inverse. Sans cela, les barrières suivraient le spot et le delta serait nul. C'est la raison de l'ajout du paramètre `strike_pct` à l'Athéna (valeur par défaut 1,0 : aucun résultat existant ne change, vérifié à l'identique avec la même graine).

## 6. `fixings_engine.py` : accumulateur, décumulateur, DRA Daily

### Accumulateur / décumulateur (Monte Carlo uniquement)

À chaque constat `i`, avec `d = +1` (accumulateur) ou `−1` (décumulateur) :

- écart par action = `d·(S_i − K)` ;
- **zone adverse** (écart < 0) : quantité multipliée par le **levier** (souvent ×2) ;
- **KO** si `d·(S_i − H) ≥ 0` (H = barrière) : le contrat s'arrête ;
- gain actualisé du jour = quantité × multiple × écart × `e^(−r·t_i)`.

La valeur du contrat est la moyenne de la somme des gains actualisés, **du point de vue de l'investisseur**. Une valeur négative signifie que le contrat coûte à l'investisseur : l'émetteur se rémunère par le levier et le KO.

**Strike zéro coût** (`strike_zero_cout`) : dichotomie sur le strike pour que la valeur soit nulle. Les mêmes tirages à chaque essai rendent la valeur régulière en fonction du strike. Ordre de grandeur obtenu : environ 85 % du spot pour un accumulateur (KO à 105 %), environ 118 % pour un décumulateur (KO à 95 %).

**Conventions choisies** (à valider avec ton enseignant si le produit de référence diffère) :

- le jour où le KO est touché, **rien n'est livré** (option « livraison le jour du KO » pour l'inverse) ;
- gain réglé à la date du constat ;
- option « constats garantis » : KO désactivé sur les premiers constats.

### DRA Daily

Capital remboursé à 100 % à maturité. Chaque jour d'observation (252 par an) où `L ≤ S ≤ U`, le produit accumule `coupon_annuel / 252`. Le coupon de la période `j` est `coupon_annuel × (jours dans la fourchette) / 252`, payé à la fin de la période.

- **Black-Scholes** : la probabilité d'être dans la fourchette le jour `t` vaut `N(d2(L)) − N(d2(U))`, avec `d2(K) = [ln(S0/K) + (r − q − σ²/2)·t] / (σ√t)`. C'est le prix d'une option digitale. Le prix est la somme des coupons espérés actualisés plus le capital actualisé : **pas de simulation**.
- **Monte Carlo** : simulation jour par jour, comptage des jours dans la fourchette. Les deux méthodes donnent le même prix (test à 4 écarts types).

Cas limites vérifiés : fourchette immense → présence de 100 % ; fourchette quasi nulle → prix égal à la valeur actualisée du capital seul.

## 7. L'interface

- `templates/index.html` : la structure (en-tête, bloc t₀, trois onglets, formulaires).
- `static/style.css` : l'apparence. Les couleurs sont les variables en tête de fichier (`--ink`, `--gold`, …).
- `static/app.js` : la logique, découpée en six sections numérotées en tête de fichier. `renderChart` dessine les graphiques en SVG (graduations rondes, aires gain/perte). `greeksCard` affiche le tableau des grecs.
- `static/logo.svg` : logo générique à remplacer par le logo officiel (même nom de fichier).

Pour ajouter un produit : une route et un moteur côté Python, un `<form data-product="...">` dans `index.html`, une option dans la liste des produits, un bloc de soumission dans `app.js`.

Après modification d'un fichier Python **ou de `index.html`**, relancer le serveur : Flask met le gabarit HTML en cache.

## 8. Hypothèses et limites à connaître

- **Volatilité constante** pour toutes les jambes et toutes les dates : pas de smile ni de skew. Le côté « pari sur le skew » du risk reversal n'apparaît donc pas dans les prix.
- Taux et dividende constants, pas de risque de défaut de l'émetteur, pas de dividendes discrets.
- **Monte Carlo** : toute valeur s'accompagne d'une erreur statistique. Le **gamma** des produits à barrières est bruité d'une graine à l'autre ; augmenter le nombre de simulations le stabilise.
- **Theta des produits à constats** : mesuré avec un constat ou un jour de moins, hors flux déjà tombés.
- Les stratégies sont tracées à l'échéance, primes non actualisées (comme dans le cours).
- Les paramètres d'un contrat réel (convention de KO, de règlement, de calendrier) doivent être vérifiés séparément : ce pricer est pédagogique.
