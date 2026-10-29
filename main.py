"""Pricer autonome de produits structurés : serveur Flask."""
from flask import Flask, render_template, request, jsonify
import numpy as np
from market_data_engine import search_tickers, get_spot, get_devise, get_vix, get_vol_historique
from strutu_engine import (analyse_phoenix, payoff_phoenix_maturite,
                           analyse_autocall_plain)
from options_engine import analyser_option
from strategies_engine import analyser_strategie, STRATEGIES, strikes_par_defaut
from fixings_engine import (analyser_accumulateur, analyser_dra, strike_zero_cout,
                            FREQUENCES_CONSTAT, FREQUENCES_PAIEMENT)
import greeks_engine
app = Flask(__name__)
N_SIM_MIN = 1000
N_SIM_MAX = 500000
SIGMA_MAX = 2.0
TAUX_MAX = 0.5
MATURITE_MAX = 30.0
COUPON_MAX = 1.0

def _grid(centres, n_points=121, low=0.4, high=1.6):
    """Construit la grille de prix finaux S_T pour les graphes.

    Je vais de min(centres) x low à max(centres) x high, avec n_points points.
    """
    lo = max(0.01, min(centres) * low)
    hi = max(centres) * high
    return np.linspace(lo, hi, n_points)


def _err(message, code=400):
    """Renvoie une erreur au site (affichée en rouge sous le bouton)."""
    return jsonify({"error": message}), code


@app.get("/api/search_ticker")
def api_search_ticker():
    """Route GET /api/search_ticker?q=... : suggestions de tickers."""
    query = request.args.get("q", "").strip()
    if len(query) < 1:
        return jsonify({"results": []})
    try:
        return jsonify({"results": search_tickers(query)})
    except Exception as e:
        return _err(str(e))


@app.get("/api/market/<ticker>")
def api_market(ticker):
    """Route GET /api/market/<ticker> : spot, devise, VIX et vol historique.

    Si la vol historique n'est pas dispo (ticker récent), je renvoie None et
    le site se rabat sur le VIX.
    """
    try:
        S0 = get_spot(ticker)
        devise = get_devise(ticker)
        try:
            vix = get_vix()
        except Exception:
            vix = None  # Le VIX ne doit pas bloquer le spot ni la volatilité historique.
        # si pas assez d'historique (ticker récent) je mets None, le site prendra le VIX
        try:
            vol_hist = round(get_vol_historique(ticker), 4)
        except Exception:
            vol_hist = None
        return jsonify({
            "S0": round(S0, 4),
            "devise": devise,
            "vix": None if vix is None else round(vix, 4),
            "vol_hist": vol_hist,
        })
    except Exception as e:
        return _err(f"Impossible de récupérer les données pour '{ticker}' : {e}")


@app.get("/")
def index():
    """Route GET / : affiche la page du site."""
    return render_template("index.html")


def _est_fini(x):
    """Vrai si x est un vrai nombre fini.

    J'ai besoin de ce check car NaN passe le test "sigma <= 0"
    (NaN <= 0 donne False).
    """
    return isinstance(x, (int, float)) and not isinstance(x, bool) and np.isfinite(x)


def valider_parametres_phoenix(S0, r, q, sigma, obs_dates, K_auto, B_phoenix, B_pdi,
                                coupon, n_simulations, has_autocall,
                                bonus_threshold, bonus_amount, strike_pct):
    # tout doit être un vrai nombre
    """Vérifie tous les paramètres du Phoenix avant la simulation.

    Mon formulaire bloque déjà les valeurs absurdes, mais on peut le contourner,
    donc je revérifie tout ici : nombres finis, vol et taux réalistes,
    protection <= coupon <= rappel, dates strictement croissantes, coupons
    positifs, nombre de simulations raisonnable.
    Les valeurs arrivent déjà en décimal (0.25 = 25 %).
    Lève une ValueError avec un message clair à la première erreur.
    """
    for nom, valeur in [("Le spot", S0), ("Le taux", r), ("Le dividende", q),
                        ("La volatilité", sigma), ("La barrière de rappel", K_auto),
                        ("La barrière coupon", B_phoenix), ("La barrière de protection", B_pdi),
                        ("Le bonus", bonus_amount), ("Le strike", strike_pct)]:
        if not _est_fini(valeur):
            raise ValueError(f"{nom} doit être un nombre.")

    # marché
    if S0 <= 0:
        raise ValueError("Le spot doit être strictement positif.")
    if sigma <= 0:
        raise ValueError("La volatilité doit être strictement positive.")
    if sigma > SIGMA_MAX:
        raise ValueError(f"Volatilité de {sigma:.0%} irréaliste (max {SIGMA_MAX:.0%}).")
    if abs(r) > TAUX_MAX:
        raise ValueError(f"Taux de {r:.0%} irréaliste (entre -{TAUX_MAX:.0%} et {TAUX_MAX:.0%}).")
    if q < 0 or q > TAUX_MAX:
        raise ValueError(f"Le dividende doit être compris entre 0 et {TAUX_MAX:.0%}.")

    # barrières : protection <= coupon <= rappel
    if strike_pct <= 0:
        raise ValueError("Le strike doit être strictement positif.")
    if min(K_auto, B_phoenix, B_pdi) <= 0:
        raise ValueError("Les barrières doivent être strictement positives.")
    if B_pdi > B_phoenix:
        raise ValueError("La barrière de protection doit être inférieure ou égale "
                         "à la barrière coupon.")
    if has_autocall and B_phoenix > K_auto:
        raise ValueError("La barrière coupon doit être inférieure ou égale "
                         "à la barrière de rappel.")

    # dates : au moins une, positives, dans l'ordre
    if not obs_dates:
        raise ValueError("Il faut au moins une date d'observation.")
    if not all(_est_fini(t) for t in obs_dates):
        raise ValueError("Les dates d'observation doivent être des nombres.")
    if obs_dates[0] <= 0:
        raise ValueError("La première date d'observation doit être après aujourd'hui.")
    for avant, apres in zip(obs_dates, obs_dates[1:]):
        if apres <= avant:
            raise ValueError(f"Les dates d'observation doivent être strictement croissantes "
                             f"(problème entre {avant} et {apres}).")
    if obs_dates[-1] > MATURITE_MAX:
        raise ValueError(f"Maturité de {obs_dates[-1]} ans irréaliste (max {MATURITE_MAX:.0f}).")

    # coupons : un seul montant ou une liste (step-up) avec un coupon par date
    coupons = coupon if isinstance(coupon, list) else [coupon]
    if isinstance(coupon, list) and len(coupon) != len(obs_dates):
        raise ValueError(f"Il faut un coupon par date d'observation "
                         f"({len(obs_dates)} dates, {len(coupon)} coupons).")
    for c in coupons:
        if not _est_fini(c):
            raise ValueError("Les coupons doivent être des nombres.")
        if c < 0:
            raise ValueError("Un coupon ne peut pas être négatif.")
        if c > COUPON_MAX:
            raise ValueError(f"Coupon de {c:.0%} sur une période irréaliste "
                             f"(max {COUPON_MAX:.0%}).")

    # bonus
    if bonus_amount < 0:
        raise ValueError("Le bonus ne peut pas être négatif.")
    if bonus_threshold is not None and (not _est_fini(bonus_threshold) or bonus_threshold <= 0):
        raise ValueError("Le seuil du bonus doit être strictement positif.")

    # simulations
    if not N_SIM_MIN <= n_simulations <= N_SIM_MAX:
        raise ValueError(f"Le nombre de simulations doit être entre {N_SIM_MIN:,} et "
                         f"{N_SIM_MAX:,}.".replace(",", " "))


def _to_bool(valeur, nom):
    """Convertit un true/false venu du JSON en vrai booléen.

    Attention : bool("false") donne True en Python, d'où cette fonction.
    """
    if isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, str) and valeur.strip().lower() in ("true", "1", "oui", "yes"):
        return True
    if isinstance(valeur, str) and valeur.strip().lower() in ("false", "0", "non", "no"):
        return False
    if valeur in (0, 1):
        return bool(valeur)
    raise ValueError(f"{nom} doit valoir true ou false (reçu : {valeur!r}).")


def _optionnel(data, cle, defaut=None):
    """Renvoie la valeur par défaut si le champ est absent ou vide dans le formulaire."""
    valeur = data.get(cle, defaut)
    return defaut if valeur in (None, "") else valeur


def _dates_observation(data):
    """Construit la liste des dates d'observation (en années).

    Deux possibilités : une liste directe (obs_dates), ou la maturité T
    + la fréquence (1, 2, 4 ou 12 obs par an). C'est la deuxième que
    j'utilise sur le site.
    """
    if _optionnel(data, "obs_dates") is not None:
        dates = data["obs_dates"]
        if not isinstance(dates, list):
            raise ValueError("obs_dates doit être une liste, ex : [0.5, 1, 1.5, 2].")
        return [float(t) for t in dates]

    T = float(data["T"])
    frequence = int(data.get("frequence", 1))
    if frequence not in (1, 2, 4, 12):
        raise ValueError("La fréquence doit être 1 (annuelle), 2, 4 ou 12 (mensuelle).")
    # T doit tomber pile sur un nombre entier de périodes
    n_obs = T * frequence
    if T <= 0 or abs(n_obs - round(n_obs)) > 1e-9:
        raise ValueError(f"Avec une fréquence de {frequence}/an, la maturité doit être un "
                         f"multiple de {1 / frequence:g} an (reçu : T = {T}).")
    return [k / frequence for k in range(1, int(round(n_obs)) + 1)]


@app.post("/api/phoenix")
def api_phoenix():
    """Route POST /api/phoenix : prix, stats des scénarios et graphe du Phoenix.

    Barrières, coupons et bonus arrivent en % (70 = 70 %), comme r, q et sigma.
    Je renvoie les montants en devise du nominal, et en % du nominal pour
    les champs qui finissent par _pct.
    """
    try:
        data = request.get_json(force=True)

        # marché
        S0 = float(data["S0"])
        r = float(data["r"]) / 100
        q = float(data.get("q", 0)) / 100
        sigma = float(data["sigma"]) / 100
        nominal = float(data.get("nominal", 1000))
        if not np.isfinite(nominal) or nominal <= 0:
            return _err("Le nominal doit être strictement positif.")

        # produit
        obs_dates = _dates_observation(data)
        K_auto = float(data.get("K_auto", 100)) / 100
        B_phoenix = float(data["B_phoenix"]) / 100
        B_pdi = float(data["B_pdi"]) / 100
        strike_pct = float(data.get("strike_pct", 100)) / 100

        coupon_brut = data["coupon"]
        if isinstance(coupon_brut, list):
            coupon = [float(c) / 100 for c in coupon_brut]   # step-up
        else:
            coupon = float(coupon_brut) / 100                # coupon fixe

        memory = _to_bool(data.get("memory", False), "memory")
        has_autocall = _to_bool(data.get("has_autocall", True), "has_autocall")

        bonus_threshold = _optionnel(data, "bonus_threshold")
        if bonus_threshold is not None:
            bonus_threshold = float(bonus_threshold) / 100
        bonus_amount = float(_optionnel(data, "bonus_amount", 0)) / 100

        n_simulations = int(data.get("n_simulations", 50000))
        seed = _optionnel(data, "seed")
        seed = int(seed) if seed is not None else None

        # je vérifie tout avant de lancer la simu
        valider_parametres_phoenix(S0, r, q, sigma, obs_dates, K_auto, B_phoenix, B_pdi,
                                   coupon, n_simulations, has_autocall,
                                   bonus_threshold, bonus_amount, strike_pct)

        # prix + stats des scénarios
        res = analyse_phoenix(S0, r, q, sigma, obs_dates, K_auto, B_phoenix, B_pdi, coupon,
                              n_simulations, memory=memory, has_autocall=has_autocall,
                              bonus_threshold=bonus_threshold, bonus_amount=bonus_amount,
                              strike_pct=strike_pct, seed=seed)

        # je passe les barrières en prix pour les tracer sur le graphe
        strike_reference = strike_pct * S0
        niveaux = {
            "strike": strike_reference,
            "autocall": K_auto * strike_reference if has_autocall else None,
            "coupon": B_phoenix * strike_reference,
            "protection": B_pdi * strike_reference,
        }
        centres = [S0] + [v for v in niveaux.values() if v is not None]
        ST_grid = _grid(centres, n_points=241, low=0.6, high=1.3)

        # payoff à maturité si pas rappelé
        coupon_final = res["coupon_schedule"][-1]
        payoff = payoff_phoenix_maturite(ST_grid, S0, B_phoenix, B_pdi, coupon_final,
                                         strike_pct, bonus_threshold, bonus_amount)
        payoff_total = payoff["total"] * nominal
        # P&L du client : il a payé le nominal (100 %), pas le prix théorique
        pnl = payoff_total - nominal

        # grecs par différences finies (mêmes tirages) ; sans bloquer le prix en cas d'échec
        grecs = None
        if _to_bool(data.get("avec_grecs", True), "avec_grecs"):
            try:
                grecs = greeks_engine.grecs_phoenix(
                    r, q, sigma, obs_dates, K_auto, B_phoenix, B_pdi, coupon,
                    min(n_simulations, 100000), memory, has_autocall, bonus_threshold,
                    bonus_amount, strike_pct, seed if seed is not None else 42)
            except Exception:
                grecs = None

        # petit raccourci que je me suis fait pour passer en % arrondi
        def pct(x):
            return round(100 * float(x), 4)

        return jsonify({
            "prix": round(res["prix"] * nominal, 4),
            "prix_pct": pct(res["prix"]),
            "ic95_pct": [pct(res["ic95"][0]), pct(res["ic95"][1])],
            "marge_emetteur_pct": pct(res["marge_emetteur"]),
            "duree_de_vie_moyenne": round(res["duree_de_vie_moyenne"], 4),
            "coupons_moyens_actualises_pct": pct(res["coupons_moyens_actualises"]),
            "obs_dates": res["obs_dates"],
            "coupon_schedule_pct": [pct(c) for c in res["coupon_schedule"]],
            "proba_rappel_par_date_pct": [pct(p) for p in res["proba_rappel_par_date"]],
            "proba_maturite_pct": pct(res["proba_maturite"]),
            "proba_perte_capital_pct": pct(res["proba_perte_capital"]),
            "remboursement_moyen_si_perte_pct": (
                None if res["remboursement_moyen_si_perte"] is None
                else pct(res["remboursement_moyen_si_perte"])
            ),
            "niveaux": {k: (None if v is None else round(float(v), 4)) for k, v in niveaux.items()},
            "ST_grid": [round(float(x), 4) for x in ST_grid],
            "payoff": [round(float(x), 4) for x in payoff_total],
            "pnl": [round(float(x), 4) for x in pnl],
            "grecs": grecs,
        })

    except KeyError as e:
        return _err(f"Paramètre manquant : {e}")
    except (TypeError, ValueError) as e:
        # mes messages de vérif, ou un float("abc") venu du formulaire
        return _err(str(e))
    except Exception as e:
        return _err(f"Erreur inattendue : {e}", 500)


@app.post("/api/autocall")
def api_autocall():
    """Entrées du formulaire en %, calculs en décimal, montants en devise du nominal."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _err("Le formulaire doit être un objet JSON.")
    try:
        produit = data.get("produit")
        if produit not in ("autocall_plain",):
            return _err("Produit autocall inconnu.")

        def nombre(cle, defaut=None):
            valeur = data.get(cle, defaut)
            if isinstance(valeur, bool) or valeur in (None, ""):
                raise ValueError(f"Paramètre manquant ou invalide : {cle}.")
            valeur = float(valeur)
            if not np.isfinite(valeur):
                raise ValueError(f"Le paramètre {cle} doit être fini.")
            return valeur

        S0 = nombre("S0")
        r, q, sigma = nombre("r") / 100, nombre("q", 0) / 100, nombre("sigma") / 100
        nominal = nombre("nominal", 1000)
        T, frequence = nombre("T"), nombre("frequence", 2)
        n = nombre("n_simulations", 50000)
        if not 0 < S0 <= 1e9 or not 0 < nominal <= 1e12:
            return _err("Spot et montant investi doivent être positifs et dans les limites autorisées.")
        if not -.5 <= r <= .5 or not 0 <= q <= .5 or not 0 <= sigma <= 2:
            return _err("Taux r : −50 à 50 %, dividende : 0 à 50 %, volatilité : 0 à 200 %.")
        if not 0 < T <= 30 or frequence not in (1, 2, 4, 12):
            return _err("Maturité : 0 à 30 ans ; fréquence : 1, 2, 4 ou 12 observations par an.")
        if not n.is_integer() or not 1000 <= n <= 500000:
            return _err("Le nombre de simulations doit être un entier entre 1 000 et 500 000.")
        dates = _dates_observation({"T": T, "frequence": int(frequence)})
        if int(n) * len(dates) > 6000000:
            return _err("Calcul trop volumineux : réduisez les simulations ou la fréquence (maximum 6 millions de constats simulés).")
        K_auto = nombre("K_auto", 100) / 100
        coupon = nombre("coupon") / 100
        if not 0 < K_auto <= 3 or not 0 <= coupon <= 1:
            return _err("Barrière : 0 à 300 % ; coupon par observation : 0 à 100 %.")
        protection = _to_bool(data.get("protection", True), "protection")
        B_pdi = nombre("B_pdi", 60) / 100 if protection else None
        has_autocall = _to_bool(data.get("has_autocall", True), "has_autocall")
        premiere = None
        if has_autocall:
            premiere = nombre("first_call_months", 0) / 12
        seed = nombre("seed", 42)
        if not seed.is_integer() or not 0 <= seed <= 2**32 - 1:
            return _err("La graine doit être un entier entre 0 et 4 294 967 295.")
        arguments = dict(S0=S0, r=r, q=q, sigma=sigma, obs_dates=dates, K_auto=K_auto,
                         B_pdi=B_pdi, coupon=coupon, n_simulations=int(n), seed=int(seed))
        res = analyse_autocall_plain(**arguments, first_call_date=premiere, has_autocall=has_autocall)
        grecs = None
        if _to_bool(data.get("avec_grecs", True), "avec_grecs"):
            try:
                grecs = greeks_engine.grecs_plain(r, q, sigma, dates, K_auto, B_pdi, coupon,
                                                  min(int(n), 100000), premiere, has_autocall,
                                                  seed=int(seed))
            except Exception:
                grecs = None
        # Remboursement final du Plain, sous l'hypothèse d'absence de rappel.
        niveaux = {"autocall": K_auto * S0 if has_autocall else None, "coupon": K_auto * S0,
                   "protection": None if B_pdi is None else B_pdi * S0}
        centres = [S0] + [v for v in niveaux.values() if v is not None]
        grille = _grid(centres, n_points=241, low=0.6, high=1.3)
        # Deux points de part et d'autre des seuils montrent leurs discontinuités.
        seuils = [v for v in niveaux.values() if v is not None]
        grille = np.unique(np.concatenate([grille, seuils, [np.nextafter(v, 0) for v in seuils]]))
        capital = np.ones_like(grille)
        if B_pdi is not None:
            capital = np.where(grille >= B_pdi * S0, 1.0, grille / S0)
        coupons_finaux = np.where(grille >= K_auto * S0, coupon * len(dates), 0.0)
        remboursement = (capital + coupons_finaux) * nominal
        return jsonify({
            "ST_grid": grille.tolist(), "payoff": remboursement.tolist(),
            "pnl": (remboursement - nominal).tolist(), "niveaux": niveaux,
            "marge_emetteur_pct": round(res["marge_emetteur"] * 100, 4),
            "produit": produit, "has_autocall": has_autocall,
            "prix": round(res["prix"] * nominal, 4),
            "prix_pct": round(res["prix"] * 100, 4),
            "ic95_pct": [round(v * 100, 4) for v in res["ic95"]],
            "erreur_type": round(res["erreur_type"] * nominal, 6),
            "ecart_souscription_pct": round(res["marge_emetteur"] * 100, 4),
            "proba_perte_capital_pct": round(res["proba_perte_capital"] * 100, 4),
            "proba_maturite_pct": round(res["proba_maturite"] * 100, 4),
            "proba_rappel_par_date_pct": [round(v * 100, 4) for v in res["proba_rappel_par_date"]],
            "duree_de_vie_moyenne": round(res["duree_de_vie_moyenne"], 4),
            "coupons_moyens_actualises_pct": round(res["coupons_moyens_actualises"] * 100, 4),
            "nombre_moyen_coupons": round(res["nombre_moyen_coupons"], 4),
            "remboursement_moyen_si_perte_pct": None if res["remboursement_moyen_si_perte"] is None else round(res["remboursement_moyen_si_perte"] * 100, 4),
            "obs_dates": res["obs_dates"], "nominal": nominal, "S0": S0,
            "coupon_pct": coupon * 100, "K_auto_pct": K_auto * 100,
            "B_pdi_pct": None if B_pdi is None else B_pdi * 100,
            "first_call_date": premiere, "n_simulations": int(n), "seed": int(seed),
            "grecs": grecs,
        })
    except (TypeError, ValueError, OverflowError) as e:
        return _err(str(e))
    except Exception:
        return _err("Le calcul autocall a échoué. Vérifiez les paramètres et réessayez.", 500)


# =====================================================================
# Options, stratégies, accumulateur / décumulateur, DRA Daily
# Mêmes conventions que plus haut : entrées en % (r, q, sigma, barrières),
# calculs en décimal, sorties en % avec le suffixe _pct.
# =====================================================================

N_SIM_STEPS_MAX = 30_000_000     # simulations x constats simulés, au maximum
N_SIM_GRECS_FIXINGS = 20_000     # les grecs par différences finies relancent ~14 simulations


def _nombre(data, cle, defaut=None):
    """Lit un nombre fini dans le JSON (erreur claire sinon)."""
    valeur = data.get(cle, defaut)
    if isinstance(valeur, bool) or valeur in (None, ""):
        raise ValueError(f"Paramètre manquant ou invalide : {cle}.")
    valeur = float(valeur)
    if not np.isfinite(valeur):
        raise ValueError(f"Le paramètre {cle} doit être un nombre fini.")
    return valeur


def _json_dict():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Le formulaire doit être un objet JSON.")
    return data


def _marche(data):
    """Lit et vérifie spot, taux, dividende et volatilité à t0 (r, q, sigma reçus en %)."""
    S0 = _nombre(data, "S0")
    r, q, sigma = _nombre(data, "r") / 100, _nombre(data, "q", 0) / 100, _nombre(data, "sigma") / 100
    if not 0 < S0 <= 1e9:
        raise ValueError("Le spot doit être strictement positif.")
    if sigma <= 0 or sigma > SIGMA_MAX:
        raise ValueError(f"La volatilité doit être comprise entre 0 (exclu) et {SIGMA_MAX:.0%}.")
    if abs(r) > TAUX_MAX:
        raise ValueError(f"Taux de {r:.0%} irréaliste (entre -{TAUX_MAX:.0%} et {TAUX_MAX:.0%}).")
    if not 0 <= q <= TAUX_MAX:
        raise ValueError(f"Le dividende doit être compris entre 0 et {TAUX_MAX:.0%}.")
    return S0, r, q, sigma


def _maturite(data, cle="T"):
    T = _nombre(data, cle)
    if not 0 < T <= MATURITE_MAX:
        raise ValueError(f"La maturité doit être comprise entre 0 (exclu) et {MATURITE_MAX:.0f} ans.")
    return T


def _simulations(data, pas_par_simulation=1):
    n = _nombre(data, "n_simulations", 50000)
    if not n.is_integer() or not N_SIM_MIN <= n <= N_SIM_MAX:
        raise ValueError(f"Le nombre de simulations doit être un entier entre {N_SIM_MIN:,} et "
                         f"{N_SIM_MAX:,}.".replace(",", " "))
    if n * pas_par_simulation > N_SIM_STEPS_MAX:
        raise ValueError("Calcul trop volumineux : réduisez le nombre de simulations ou la fréquence "
                         "des constats.")
    seed = _nombre(data, "seed", 42)
    if not seed.is_integer() or not 0 <= seed <= 2 ** 32 - 1:
        raise ValueError("La graine doit être un entier entre 0 et 4 294 967 295.")
    return int(n), int(seed)


def _methode(data):
    methode = data.get("methode", "bs")
    if methode not in ("bs", "mc"):
        raise ValueError("La méthode doit être 'bs' (Black-Scholes) ou 'mc' (Monte Carlo).")
    return methode


def _pct(x):
    return None if x is None else round(100 * float(x), 4)


def _erreurs(exc_valeur):
    """Gestion commune des erreurs des nouvelles routes."""
    return _err(str(exc_valeur))


@app.post("/api/option")
def api_option():
    """Option classique : long/short call/put, prix et grecs en Black-Scholes ou Monte Carlo."""
    try:
        data = _json_dict()
        S0, r, q, sigma = _marche(data)
        K, T = _nombre(data, "K"), _maturite(data)
        methode = _methode(data)
        n, seed = _simulations(data)
        res = analyser_option(data.get("type"), data.get("position"), S0, K, T, r, q, sigma,
                              methode, n, seed)
        res["parametres"] = {"S0": S0, "K": K, "T": T, "r_pct": r * 100, "q_pct": q * 100,
                             "sigma_pct": sigma * 100}
        return jsonify(res)
    except (TypeError, ValueError, OverflowError) as e:
        return _erreurs(e)
    except Exception:
        return _err("Le calcul de l'option a échoué. Vérifiez les paramètres et réessayez.", 500)


@app.get("/api/strategies")
def api_strategies():
    """Catalogue des stratégies du cours (nom, construction, vue de marché, paramètres à saisir)."""
    return jsonify({"strategies": [{"cle": cle, **info} for cle, info in STRATEGIES.items()]})


@app.post("/api/strategie")
def api_strategie():
    """Stratégie d'options du cours : coût net, grecs agrégés, profil de gain, points morts."""
    try:
        data = _json_dict()
        nom = data.get("strategie")
        if nom not in STRATEGIES:
            raise ValueError("Stratégie inconnue.")
        S0, r, q, sigma = _marche(data)
        methode = _methode(data)
        n, seed = _simulations(data)
        params = {"T": _maturite(data), "sens": data.get("sens", "haussier")}
        defauts = strikes_par_defaut(nom, S0)
        for cle in STRATEGIES[nom]["parametres"]:
            params[cle] = _nombre(data, cle, defauts[cle])
        res = analyser_strategie(nom, S0, params, r, q, sigma, methode, n, seed)
        res["parametres"] = {"S0": S0, **{k: v for k, v in params.items()}, "r_pct": r * 100,
                             "q_pct": q * 100, "sigma_pct": sigma * 100}
        return jsonify(res)
    except (TypeError, ValueError, OverflowError) as e:
        return _erreurs(e)
    except Exception:
        return _err("Le calcul de la stratégie a échoué. Vérifiez les paramètres et réessayez.", 500)


@app.post("/api/accumulateur")
def api_accumulateur():
    """Accumulateur ou décumulateur classique (Monte Carlo) avec grecs et strike zéro coût optionnel."""
    try:
        data = _json_dict()
        sens = data.get("sens", "accumulateur")
        S0, r, q, sigma = _marche(data)
        T = _maturite(data)
        frequence = data.get("frequence", "quotidien")
        if frequence not in FREQUENCES_CONSTAT:
            raise ValueError("La fréquence doit être 'quotidien', 'hebdomadaire' ou 'mensuel'.")
        n_fix = max(1, round(T * FREQUENCES_CONSTAT[frequence]))
        n, seed = _simulations(data, pas_par_simulation=n_fix)
        accu = sens == "accumulateur"
        strike_pct = _nombre(data, "strike_pct", 90 if accu else 110) / 100
        ko_pct = _nombre(data, "ko_pct", 105 if accu else 95) / 100
        levier = _nombre(data, "levier", 2)
        quantite = _nombre(data, "quantite", 1)
        n_garanti = int(_nombre(data, "n_garanti", 0))
        livraison_au_ko = _to_bool(data.get("livraison_au_ko", False), "livraison_au_ko")
        arguments = dict(sens=sens, S0=S0, r=r, q=q, sigma=sigma, T=T, strike_pct=strike_pct,
                         ko_pct=ko_pct, levier=levier, quantite=quantite, frequence=frequence,
                         n_garanti=n_garanti, livraison_au_ko=livraison_au_ko, seed=seed)
        res = analyser_accumulateur(**arguments, n_simulations=n)
        n_grecs = min(n, N_SIM_GRECS_FIXINGS)

        grecs = None
        if _to_bool(data.get("avec_grecs", True), "avec_grecs"):
            try:
                grecs = greeks_engine.grecs_accumulateur(**arguments, n_simulations=n_grecs)
            except Exception:
                grecs = None

        strike_zc = None
        if _to_bool(data.get("zero_cout", False), "zero_cout"):
            strike_zc = strike_zero_cout(sens, S0, r, q, sigma, T, ko_pct, levier, quantite, frequence,
                                         n_garanti, livraison_au_ko, n_grecs, seed)

        res.update({
            "valeur_pct_notionnel": _pct(res["valeur_pct_notionnel"]),
            "proba_ko_pct": _pct(res["proba_ko"]),
            "proba_ko_cumulee_pct": [_pct(p) for p in res["proba_ko_cumulee"]],
            "proba_levier_pct": _pct(res["proba_levier"]),
            "strike_pct": strike_pct * 100, "ko_pct": ko_pct * 100,
            "strike_zero_cout_pct": _pct(strike_zc),
            "grecs": grecs,
            "parametres": {"S0": S0, "T": T, "r_pct": r * 100, "q_pct": q * 100,
                           "sigma_pct": sigma * 100, "levier": levier, "quantite": quantite,
                           "n_garanti": n_garanti, "livraison_au_ko": livraison_au_ko, "seed": seed},
        })
        return jsonify(res)
    except (TypeError, ValueError, OverflowError) as e:
        return _erreurs(e)
    except Exception:
        return _err("Le calcul de l'accumulateur a échoué. Vérifiez les paramètres et réessayez.", 500)


@app.post("/api/dra")
def api_dra():
    """DRA Daily : coupon proportionnel aux jours passés dans la fourchette, capital garanti."""
    try:
        data = _json_dict()
        S0, r, q, sigma = _marche(data)
        T = _maturite(data)
        methode = _methode(data)
        nominal = _nombre(data, "nominal", 1000)
        if not 0 < nominal <= 1e12:
            raise ValueError("Le nominal doit être strictement positif.")
        frequence_paiement = data.get("frequence_paiement", "trimestriel")
        if frequence_paiement not in FREQUENCES_PAIEMENT:
            raise ValueError("La fréquence de paiement doit être 'mensuel', 'trimestriel', "
                             "'semestriel' ou 'annuel'.")
        n, seed = _simulations(data, pas_par_simulation=max(1, round(T * 252)) if methode == "mc" else 1)
        bas = _nombre(data, "borne_basse_pct", 90) / 100
        haut = _nombre(data, "borne_haute_pct", 110) / 100
        coupon = _nombre(data, "coupon_annuel", 8) / 100
        if coupon > COUPON_MAX:
            raise ValueError(f"Coupon annuel de {coupon:.0%} irréaliste (max {COUPON_MAX:.0%}).")
        arguments = dict(S0=S0, r=r, q=q, sigma=sigma, T=T, borne_basse_pct=bas, borne_haute_pct=haut,
                         coupon_annuel=coupon, frequence_paiement=frequence_paiement, seed=seed)
        res = analyser_dra(methode, **arguments, n_simulations=n)

        grecs = None
        if _to_bool(data.get("avec_grecs", True), "avec_grecs"):
            try:
                grecs = greeks_engine.grecs_dra(methode, r, q, sigma, T, bas, haut, coupon,
                                                frequence_paiement,
                                                min(n, N_SIM_GRECS_FIXINGS), seed)
            except Exception:
                grecs = None

        res.update({
            "prix_pct": _pct(res["prix"]), "prix": round(res["prix"] * nominal, 4),
            "ic95_pct": None if res["ic95"] is None else [_pct(v) for v in res["ic95"]],
            "marge_emetteur_pct": _pct(res["marge_emetteur"]),
            "valeur_capital_pct": _pct(res["valeur_capital"]),
            "valeur_coupons_pct": _pct(res["valeur_coupons"]),
            "presence_moyenne_pct": _pct(res["presence_moyenne"]),
            "coupon_annualise_espere_pct": _pct(res["coupon_annualise_espere"]),
            "presence_par_periode_pct": [_pct(v) for v in res["presence_par_periode"]],
            "coupons_espere_par_periode_pct": [_pct(v) for v in res["coupons_espere_par_periode"]],
            "proba_coupon_nul_pct": _pct(res["proba_coupon_nul"]),
            "coupon_annuel_pct": coupon * 100, "nominal": nominal,
            "grecs": grecs,
            "parametres": {"S0": S0, "T": T, "r_pct": r * 100, "q_pct": q * 100,
                           "sigma_pct": sigma * 100, "seed": seed},
        })
        return jsonify(res)
    except (TypeError, ValueError, OverflowError) as e:
        return _erreurs(e)
    except Exception:
        return _err("Le calcul du DRA a échoué. Vérifiez les paramètres et réessayez.", 500)


if __name__ == "__main__":
    import os
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5001")), debug=False)
