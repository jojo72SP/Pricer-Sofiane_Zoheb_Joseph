"""Stratégies d'options du chapitre 3 du cours S&P Academy.

Une stratégie est une liste de « jambes » (option ou action) : on valorise
chaque jambe avec options_engine, on additionne prix et grecs, et on trace le
profit à l'échéance (primes non actualisées, comme dans le cours).

Les deux méthodes sont disponibles :
- "bs" : prix et grecs en formule fermée ;
- "mc" : mêmes tirages pour toutes les jambes, donc l'erreur type est celle de
  la stratégie entière (les jambes sont corrélées, leurs bruits se compensent).
"""
import math

import numpy as np

import options_engine as oe

# Description des stratégies : texte repris du cours (chapitre 3).
STRATEGIES = {
    "covered_call": {
        "nom": "Covered Call", "section": "3.1",
        "construction": "Long 1 action + Short 1 call (même T, K)",
        "vue": "Neutre à légèrement haussière",
        "interet": "Générer un revenu (la prime) sur une action détenue, en plafonnant la performance au-dessus de K.",
        "parametres": ["K"],
    },
    "protective_put": {
        "nom": "Protective Put", "section": "3.2",
        "construction": "Long 1 action + Long 1 put (même T, K)",
        "vue": "Haussière prudente",
        "interet": "Assurer une position action contre une forte baisse ; perte bornée.",
        "parametres": ["K"],
    },
    "long_straddle": {
        "nom": "Long Straddle", "section": "3.3",
        "construction": "Long 1 call + Long 1 put (même T, même K, ATM)",
        "vue": "Mouvement fort, dans un sens ou dans l'autre",
        "interet": "Pari pur sur la volatilité : delta proche de 0 au départ, forte convexité.",
        "parametres": ["K"],
    },
    "short_straddle": {
        "nom": "Short Straddle", "section": "3.11",
        "construction": "Short 1 call + Short 1 put (même T, même K)",
        "vue": "Marché calme (volatilité réalisée < implicite)",
        "interet": "Encaisser les deux primes ; gagne si la réalisée reste sous l'implicite, mais risque extrême (convexité négative).",
        "parametres": ["K"],
    },
    "long_strangle": {
        "nom": "Long Strangle", "section": "3.4",
        "construction": "Long 1 put K1 + Long 1 call K2 (K1 < K2, OTM)",
        "vue": "Mouvement très fort",
        "interet": "Même logique que le straddle, prime plus faible, mais il faut un mouvement plus grand pour gagner.",
        "parametres": ["K1", "K2"],
    },
    "short_strangle": {
        "nom": "Short Strangle", "section": "3.4 (inverse)",
        "construction": "Short 1 put K1 + Short 1 call K2 (K1 < K2, OTM)",
        "vue": "Marché calme dans une fourchette",
        "interet": "Vente de volatilité avec des bornes plus larges que le short straddle ; risque non borné.",
        "parametres": ["K1", "K2"],
    },
    "bull_call_spread": {
        "nom": "Bull Call Spread", "section": "3.5 (a)",
        "construction": "Long 1 call K1 + Short 1 call K2 (K1 < K2)",
        "vue": "Haussière bornée",
        "interet": "Pari haussier à prime réduite ; gain plafonné.",
        "parametres": ["K1", "K2"],
    },
    "bear_put_spread": {
        "nom": "Bear Put Spread", "section": "3.5 (b)",
        "construction": "Long 1 put K2 + Short 1 put K1 (K1 < K2)",
        "vue": "Baissière bornée",
        "interet": "Pari baissier à prime réduite ; gain plafonné.",
        "parametres": ["K1", "K2"],
    },
    "collar": {
        "nom": "Collar", "section": "3.6",
        "construction": "Long 1 action + Long 1 put K1 + Short 1 call K2 (K1 < K2)",
        "vue": "Neutre à haussière prudente",
        "interet": "Perte bornée sous K1 grâce au put, financée en tout ou partie par la vente du call ; gain plafonné au-dessus de K2.",
        "parametres": ["K1", "K2"],
    },
    "calendar": {
        "nom": "Calendar (time spread)", "section": "3.7",
        "construction": "Long option à maturité longue T2 + Short option à maturité courte T (même K, même type)",
        "vue": "Marché dans une fourchette autour de K, ou remontée de la volatilité lointaine",
        "interet": "Jouer la structure par terme : l'option courte perd sa valeur temps plus vite que la longue.",
        "parametres": ["K", "T2"],
    },
    "risk_reversal": {
        "nom": "Risk Reversal", "section": "3.8",
        "construction": "Version haussière : Long 1 call K2 + Short 1 put K1 (OTM). Version baissière : l'inverse.",
        "vue": "Directionnelle, avec lecture du skew",
        "interet": "Exposition directionnelle avec un vega net proche de 0 ; forward « adouci ».",
        "parametres": ["K1", "K2"],
    },
    "forward_synthetique": {
        "nom": "Forward synthétique", "section": "3.9",
        "construction": "Long 1 call K + Short 1 put K (même T)",
        "vue": "Directionnelle pure (delta proche de 1)",
        "interet": "Répliquer un forward long sans passer par le marché à terme ; coût initial donné par la parité call-put.",
        "parametres": ["K"],
    },
}


def _jambe(instrument, signe, K=None, T=None, libelle=""):
    return {"instrument": instrument, "signe": signe, "K": K, "T": T, "libelle": libelle}


def construire_jambes(nom, p):
    """Liste des jambes d'une stratégie à partir de ses paramètres (K, K1, K2, T, T2, sens, option)."""
    T = p["T"]
    if nom == "covered_call":
        return [_jambe("action", +1, libelle="Long action"),
                _jambe("call", -1, p["K"], T, "Short call")]
    if nom == "protective_put":
        return [_jambe("action", +1, libelle="Long action"),
                _jambe("put", +1, p["K"], T, "Long put")]
    if nom == "long_straddle":
        return [_jambe("call", +1, p["K"], T, "Long call"), _jambe("put", +1, p["K"], T, "Long put")]
    if nom == "short_straddle":
        return [_jambe("call", -1, p["K"], T, "Short call"), _jambe("put", -1, p["K"], T, "Short put")]
    if nom == "long_strangle":
        return [_jambe("put", +1, p["K1"], T, "Long put"), _jambe("call", +1, p["K2"], T, "Long call")]
    if nom == "short_strangle":
        return [_jambe("put", -1, p["K1"], T, "Short put"), _jambe("call", -1, p["K2"], T, "Short call")]
    if nom == "bull_call_spread":
        return [_jambe("call", +1, p["K1"], T, "Long call"), _jambe("call", -1, p["K2"], T, "Short call")]
    if nom == "bear_put_spread":
        return [_jambe("put", +1, p["K2"], T, "Long put"), _jambe("put", -1, p["K1"], T, "Short put")]
    if nom == "collar":
        return [_jambe("action", +1, libelle="Long action"),
                _jambe("put", +1, p["K1"], T, "Long put"), _jambe("call", -1, p["K2"], T, "Short call")]
    if nom == "calendar":
        kind = p.get("option", "call")
        return [_jambe(kind, +1, p["K"], p["T2"], f"Long {kind} (longue maturité)"),
                _jambe(kind, -1, p["K"], T, f"Short {kind} (courte maturité)")]
    if nom == "risk_reversal":
        if p.get("sens", "haussier") == "haussier":
            return [_jambe("call", +1, p["K2"], T, "Long call OTM"), _jambe("put", -1, p["K1"], T, "Short put OTM")]
        return [_jambe("put", +1, p["K1"], T, "Long put OTM"), _jambe("call", -1, p["K2"], T, "Short call OTM")]
    if nom == "forward_synthetique":
        return [_jambe("call", +1, p["K"], T, "Long call"), _jambe("put", -1, p["K"], T, "Short put")]
    raise ValueError(f"Stratégie inconnue : {nom}")


def _verifier(nom, p, S):
    if nom not in STRATEGIES:
        raise ValueError(f"Stratégie inconnue : {nom}")
    for cle in STRATEGIES[nom]["parametres"]:
        v = p.get(cle)
        if v is None or isinstance(v, bool) or not np.isfinite(v) or v <= 0:
            raise ValueError(f"Le paramètre {cle} est obligatoire et doit être strictement positif.")
    if {"K1", "K2"} <= set(STRATEGIES[nom]["parametres"]) and not p["K1"] < p["K2"]:
        raise ValueError("Il faut K1 < K2.")
    if nom == "calendar":
        if not p["T2"] > p["T"]:
            raise ValueError("La maturité longue T2 doit être strictement supérieure à la maturité courte T.")
        if p.get("option", "call") not in oe.KINDS:
            raise ValueError("L'option du calendar doit être 'call' ou 'put'.")
    if nom == "risk_reversal" and p.get("sens", "haussier") not in ("haussier", "baissier"):
        raise ValueError("Le sens du risk reversal doit être 'haussier' ou 'baissier'.")


def strikes_par_defaut(nom, S):
    """Strikes proposés si l'utilisateur n'en donne pas (ATM, ±10 %, etc.)."""
    arrondi = lambda x: round(float(x), 2)
    return {
        "K": arrondi(S),
        "K1": arrondi(S * (0.90 if nom in ("long_strangle", "short_strangle", "collar", "risk_reversal",
                                           "bear_put_spread") else 1.0)),
        "K2": arrondi(S * 1.10),
    }


def _grecs_action():
    g = {cle: 0.0 for cle, _, _, _ in oe.GRECS_INFO}
    g["delta"] = 1.0
    return g


def _pnl_jambe(j, ST, S, r, q, sigma, T_ref):
    """(gain brut à T_ref, coût d'entrée) d'une jambe, par unité longue."""
    if j["instrument"] == "action":
        return ST, S
    kind, K = j["instrument"], j["K"]
    if j["T"] > T_ref + 1e-12:   # option encore vivante à T_ref (calendar) : valeur Black-Scholes restante
        return oe.bs_price_array(kind, ST, K, j["T"] - T_ref, r, q, sigma), None
    return (np.maximum(ST - K, 0.0) if kind == "call" else np.maximum(K - ST, 0.0)), None


def analyser_strategie(nom, S, params, r, q, sigma, method="bs", n_simulations=100000, seed=42):
    """Prix, grecs agrégés et profil de gain d'une stratégie du cours.

    params : dict avec T (maturité en années) et, selon la stratégie, K, K1, K2,
    T2 (calendar), option ('call'/'put', calendar), sens (risk reversal).
    """
    if method not in oe.METHODS:
        raise ValueError("La méthode doit être 'bs' ou 'mc'.")
    _verifier(nom, params, S)
    oe.verifier_option(S, S, params["T"], r, q, sigma)
    if nom == "calendar":
        oe.verifier_option(S, S, params["T2"], r, q, sigma)

    jambes = construire_jambes(nom, params)
    Z = oe.tirages_normaux(n_simulations, seed) if method == "mc" else None

    valeurs_paires = np.zeros(1 if Z is None else Z.size)   # valeur de la stratégie, par paire (MC)
    grecs_jambes, detail, cout = [], [], 0.0
    for j in jambes:
        if j["instrument"] == "action":
            prix_u, grecs_u = S, _grecs_action()
            if Z is not None:
                valeurs_paires = valeurs_paires + j["signe"] * S
        else:
            kind, K, Tj = j["instrument"], j["K"], j["T"]
            if method == "bs":
                prix_u = oe.bs_price(kind, S, K, Tj, r, q, sigma)
                grecs_u = oe.bs_grecs(kind, S, K, Tj, r, q, sigma)
            else:
                prix_u, _ = oe.mc_prix(kind, S, K, Tj, r, q, sigma, Z)
                grecs_u = oe.mc_grecs(kind, S, K, Tj, r, q, sigma, Z)
                valeurs_paires = valeurs_paires + j["signe"] * oe.mc_valeurs(kind, S, K, Tj, r, q, sigma, Z)
        cout += j["signe"] * prix_u
        grecs_jambes.append(oe.multiplier_grecs(grecs_u, j["signe"]))
        detail.append({"libelle": j["libelle"], "instrument": j["instrument"],
                       "position": "long" if j["signe"] > 0 else "short",
                       "K": j["K"], "T": j["T"], "prix_unitaire": float(prix_u)})

    if method == "mc":
        cout = float(np.mean(valeurs_paires))
        erreur = float(np.std(valeurs_paires, ddof=1) / math.sqrt(valeurs_paires.size))
    else:
        erreur = None

    brut = oe.additionner_grecs(grecs_jambes)
    # Lambda n'est pas additif : on le recalcule sur la stratégie entière.
    brut["lambda"] = brut["delta"] * S / cout if abs(cout) > 1e-9 else None

    # Profit à l'échéance de la jambe courte (T) ; les jambes plus longues restent valorisées.
    T_ref = params["T"]
    niveaux = [j["K"] for j in jambes if j["K"]]
    grille = oe.grille_spot(S, niveaux)
    gain = np.zeros_like(grille)
    gain_zero = 0.0
    for j in jambes:
        g, _ = _pnl_jambe(j, grille, S, r, q, sigma, T_ref)
        g0, _ = _pnl_jambe(j, np.array([0.0]), S, r, q, sigma, T_ref)
        gain = gain + j["signe"] * g
        gain_zero += j["signe"] * float(np.atleast_1d(g0)[0])
    pnl = gain - cout
    pnl_zero = gain_zero - cout

    # Pente à l'infini : action et call valent +1 chacun, put 0.
    pente_haute = sum(j["signe"] * (1 if j["instrument"] in ("action", "call") else 0) for j in jambes)
    if nom == "calendar":
        pente_haute = 0
    tout = np.append(pnl, pnl_zero)
    extremes = {"gain_illimite": bool(pente_haute > 0), "perte_illimitee": bool(pente_haute < 0),
                "gain_max": None if pente_haute > 0 else float(tout.max()),
                "perte_max": None if pente_haute < 0 else float(tout.min())}

    info = STRATEGIES[nom]
    return {
        "methode": method, "strategie": nom, "nom": info["nom"], "section": info["section"],
        "construction": info["construction"], "vue": info["vue"], "interet": info["interet"],
        "jambes": detail,
        "cout_net": float(cout), "nature": "débit" if cout > 0 else ("crédit" if cout < 0 else "nul"),
        "erreur_type": erreur,
        "ic95": None if erreur is None else (cout - 1.96 * erreur, cout + 1.96 * erreur),
        "grecs": oe.grecs_liste(oe.grecs_affichage(brut), method),
        "ST_grid": grille.tolist(), "pnl": pnl.tolist(),
        "breakevens": oe.trouver_breakevens(grille, pnl), "extremes": extremes,
        "n_simulations": None if Z is None else int(2 * Z.size),
    }
