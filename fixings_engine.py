"""Produits à constats réguliers : accumulateur, décumulateur, DRA Daily.

Conventions (les mêmes que strutu_engine) : r, q, sigma en décimal, barrières
en fraction du spot initial (0,90 = 90 % de S0), durées en années.

- Accumulateur / décumulateur : Monte Carlo uniquement. La barrière KO est
  surveillée à chaque constat, il n'y a pas de formule fermée.
- DRA Daily : deux méthodes. "bs" = somme de probabilités digitales (formule
  fermée), "mc" = simulation jour par jour. Les deux doivent donner le même prix.
"""
import math

import numpy as np

import options_engine as oe

FREQUENCES_CONSTAT = {"quotidien": 252, "hebdomadaire": 52, "mensuel": 12}
FREQUENCES_PAIEMENT = {"mensuel": 12, "trimestriel": 4, "semestriel": 2, "annuel": 1}
SENS = {"accumulateur": +1, "decumulateur": -1}


def _verifier_marche(S0, r, q, sigma, T):
    for nom, v in (("Le spot", S0), ("Le taux", r), ("Le dividende", q),
                   ("La volatilité", sigma), ("La maturité", T)):
        if isinstance(v, bool) or not np.isscalar(v) or not np.isfinite(v):
            raise ValueError(f"{nom} doit être un nombre fini.")
    if S0 <= 0:
        raise ValueError("Le spot doit être strictement positif.")
    if sigma <= 0:
        raise ValueError("La volatilité doit être strictement positive.")
    if T <= 0:
        raise ValueError("La maturité doit être strictement positive.")


def _verifier_simulations(n_simulations):
    if isinstance(n_simulations, (bool, np.bool_)) or not isinstance(n_simulations, (int, np.integer)) \
            or n_simulations < 2:
        raise ValueError("Il faut un nombre entier de simulations supérieur ou égal à 2.")


# =====================================================================
# ACCUMULATEUR / DÉCUMULATEUR
# =====================================================================
# Accumulateur : à chaque constat, l'investisseur ACHÈTE `quantite` actions au
# strike K (décoté, K < S0). Son gain du jour = quantite * (S - K).
#   - si S >= H (barrière KO, au-dessus de S0) : le contrat s'arrête ;
#   - si S < K : il achète `levier` fois la quantité (souvent x2), donc il perd plus.
# Décumulateur : le miroir. Il VEND au strike K (majoré, K > S0), gain du jour
#   = quantite * (K - S) ; le contrat s'arrête si S <= H (barrière basse) ;
#   si S > K il vend `levier` fois la quantité.
# On écrit tout avec d = +1 (accumulateur) ou -1 (décumulateur) :
#   écart = d * (S - K)      -> gain par action (négatif = zone de levier)
#   KO si d * (S - H) >= 0

def verifier_accumulateur(sens, S0, r, q, sigma, T, strike_pct, ko_pct, levier, quantite,
                          frequence, n_garanti, n_simulations):
    if sens not in SENS:
        raise ValueError("Le sens doit être 'accumulateur' ou 'decumulateur'.")
    _verifier_marche(S0, r, q, sigma, T)
    _verifier_simulations(n_simulations)
    for nom, v in (("Le strike", strike_pct), ("La barrière KO", ko_pct),
                   ("Le levier", levier), ("La quantité", quantite)):
        if isinstance(v, bool) or not np.isscalar(v) or not np.isfinite(v) or v <= 0:
            raise ValueError(f"{nom} doit être un nombre strictement positif.")
    if levier < 1:
        raise ValueError("Le levier doit être supérieur ou égal à 1 (1 = pas de levier).")
    if frequence not in FREQUENCES_CONSTAT:
        raise ValueError("La fréquence des constats doit être 'quotidien', 'hebdomadaire' ou 'mensuel'.")
    d = SENS[sens]
    if d == 1 and not (strike_pct < ko_pct and ko_pct > 1.0):
        raise ValueError("Accumulateur : il faut strike < barrière KO, et barrière KO au-dessus du spot (> 100 %).")
    if d == -1 and not (strike_pct > ko_pct and ko_pct < 1.0):
        raise ValueError("Décumulateur : il faut strike > barrière KO, et barrière KO sous le spot (< 100 %).")
    n_fix = max(1, int(round(T * FREQUENCES_CONSTAT[frequence])))
    if isinstance(n_garanti, bool) or not float(n_garanti).is_integer() or not 0 <= n_garanti < n_fix:
        raise ValueError(f"Le nombre de constats garantis doit être un entier entre 0 et {n_fix - 1}.")
    return d, n_fix


def _simuler_accumulateur(d, S0, r, q, sigma, n_fix, freq, strike_pct, ko_pct, levier, quantite,
                          n_garanti, livraison_au_ko, n_simulations, seed):
    """Suit chaque scénario constat après constat. Renvoie un dict de tableaux (un élément par scénario)."""
    rng = np.random.default_rng(seed)
    dt = 1.0 / freq
    derive = (r - q - 0.5 * sigma ** 2) * dt
    diffusion = sigma * math.sqrt(dt)
    K, H = strike_pct * S0, ko_pct * S0

    S = np.full(n_simulations, float(S0))
    vivant = np.ones(n_simulations, dtype=bool)
    valeur = np.zeros(n_simulations)            # gains actualisés
    unites = np.zeros(n_simulations)            # actions réellement échangées
    constats_livres = np.zeros(n_simulations)
    levier_touche = np.zeros(n_simulations, dtype=bool)
    duree = np.full(n_simulations, n_fix * dt)
    ko_au_constat = np.full(n_simulations, -1)

    for i in range(1, n_fix + 1):
        S = S * np.exp(derive + diffusion * rng.standard_normal(n_simulations))
        t = i * dt
        # Le KO n'est testé qu'après la période garantie.
        ko = vivant & (d * (S - H) >= 0) if i > n_garanti else np.zeros(n_simulations, dtype=bool)
        livre = vivant & (~ko | livraison_au_ko)
        ecart = d * (S - K)
        en_levier = ecart < 0
        multiple = np.where(en_levier, levier, 1.0)
        valeur += np.where(livre, quantite * multiple * ecart, 0.0) * math.exp(-r * t)
        unites += np.where(livre, quantite * multiple, 0.0)
        constats_livres += livre
        levier_touche |= livre & en_levier
        duree[ko] = t
        ko_au_constat[ko] = i - 1
        vivant &= ~ko
    return {"valeur": valeur, "unites": unites, "constats_livres": constats_livres,
            "levier_touche": levier_touche, "duree": duree, "ko_au_constat": ko_au_constat}


def valeur_accumulateur(sens, S0, r, q, sigma, T, strike_pct, ko_pct, levier=2.0, quantite=1.0,
                        frequence="quotidien", n_garanti=0, livraison_au_ko=False,
                        n_simulations=50000, seed=42):
    """Valeur (un float, en monnaie) du contrat pour l'investisseur. Sert au solveur et aux grecs."""
    d, n_fix = verifier_accumulateur(sens, S0, r, q, sigma, T, strike_pct, ko_pct, levier, quantite,
                                     frequence, n_garanti, n_simulations)
    res = _simuler_accumulateur(d, S0, r, q, sigma, n_fix, FREQUENCES_CONSTAT[frequence], strike_pct,
                                ko_pct, levier, quantite, n_garanti, livraison_au_ko, n_simulations, seed)
    return float(np.mean(res["valeur"]))


def strike_zero_cout(sens, S0, r, q, sigma, T, ko_pct, levier=2.0, quantite=1.0, frequence="quotidien",
                     n_garanti=0, livraison_au_ko=False, n_simulations=20000, seed=42, iterations=24):
    """Strike (en % de S0) pour lequel le contrat vaut 0 à la signature (« zéro coût »).

    Dichotomie sur le strike, avec les mêmes tirages à chaque essai : la valeur
    est alors une fonction régulière du strike. Accumulateur : la valeur baisse
    quand le strike monte. Décumulateur : la valeur monte avec le strike.
    """
    d = SENS.get(sens)
    if d is None:
        raise ValueError("Le sens doit être 'accumulateur' ou 'decumulateur'.")
    # v est croissante en strike dans les deux cas : v = -d * valeur.
    v = lambda k: -d * valeur_accumulateur(sens, S0, r, q, sigma, T, k, ko_pct, levier, quantite,
                                           frequence, n_garanti, livraison_au_ko, n_simulations, seed)
    bas, haut = (0.2, ko_pct - 1e-6) if d == 1 else (ko_pct + 1e-6, 4.0)
    v_bas, v_haut = v(bas), v(haut)
    if v_bas > 0 or v_haut < 0:
        raise ValueError("Aucun strike zéro coût dans l'intervalle exploré avec ces paramètres.")
    for _ in range(iterations):
        milieu = 0.5 * (bas + haut)
        if v(milieu) < 0:
            bas = milieu
        else:
            haut = milieu
    return 0.5 * (bas + haut)


def analyser_accumulateur(sens, S0, r, q, sigma, T, strike_pct, ko_pct, levier=2.0, quantite=1.0,
                          frequence="quotidien", n_garanti=0, livraison_au_ko=False,
                          n_simulations=50000, seed=42):
    """Valorise un accumulateur ou un décumulateur classique (Monte Carlo).

    Le résultat est la valeur du contrat POUR L'INVESTISSEUR, en monnaie : somme
    actualisée des gains par action échangée. Un contrat « zéro coût » vaut 0.
    """
    d, n_fix = verifier_accumulateur(sens, S0, r, q, sigma, T, strike_pct, ko_pct, levier, quantite,
                                     frequence, n_garanti, n_simulations)
    freq = FREQUENCES_CONSTAT[frequence]
    res = _simuler_accumulateur(d, S0, r, q, sigma, n_fix, freq, strike_pct, ko_pct, levier, quantite,
                                n_garanti, livraison_au_ko, n_simulations, seed)
    valeur = float(np.mean(res["valeur"]))
    erreur = float(np.std(res["valeur"], ddof=1) / math.sqrt(n_simulations))
    notionnel = S0 * quantite * n_fix        # exposition maximale sans levier ni KO
    ko = res["ko_au_constat"]
    K, H = strike_pct * S0, ko_pct * S0

    # Gain par action selon le cours au constat (pour le graphique de payoff).
    grille = np.linspace(0.5 * S0, 1.5 * S0, 241)
    ecart = d * (grille - K)
    gain_constat = quantite * np.where(ecart < 0, levier, 1.0) * ecart
    gain_constat = np.where(d * (grille - H) >= 0, 0.0, gain_constat)   # KO : rien n'est livré

    return {
        "produit": sens, "methode": "mc",
        "valeur": valeur, "erreur_type": erreur,
        "ic95": (valeur - 1.96 * erreur, valeur + 1.96 * erreur),
        "valeur_pct_notionnel": valeur / notionnel,
        "strike": K, "barriere_ko": H, "n_constats": n_fix, "frequence": frequence,
        "proba_ko": float(np.mean(ko >= 0)),
        "proba_ko_cumulee": [float(np.mean((ko >= 0) & (ko <= k))) for k in range(n_fix)],
        "duree_de_vie_moyenne": float(np.mean(res["duree"])),
        "unites_moyennes": float(np.mean(res["unites"])),
        "unites_max_sans_ko": float(quantite * n_fix),
        "proba_levier": float(np.mean(res["levier_touche"])),
        "S_grid": grille.tolist(), "gain_par_constat": gain_constat.tolist(),
        "n_simulations": int(n_simulations),
    }


# =====================================================================
# DRA DAILY (Daily Range Accrual)
# =====================================================================
# Le capital est remboursé à 100 % à maturité. Chaque jour d'observation où le
# sous-jacent est dans la fourchette [L, U], le produit « accumule » 1/252 du
# coupon annuel. Les coupons accumulés sont payés à la fin de chaque période.
#   coupon de la période j = coupon_annuel * (jours dans la fourchette) / 252

def verifier_dra(S0, r, q, sigma, T, borne_basse_pct, borne_haute_pct, coupon_annuel, frequence_paiement):
    _verifier_marche(S0, r, q, sigma, T)
    for nom, v in (("La borne basse", borne_basse_pct), ("La borne haute", borne_haute_pct),
                   ("Le coupon annuel", coupon_annuel)):
        if isinstance(v, bool) or not np.isscalar(v) or not np.isfinite(v):
            raise ValueError(f"{nom} doit être un nombre fini.")
    if borne_basse_pct <= 0 or not borne_basse_pct < borne_haute_pct:
        raise ValueError("Il faut 0 < borne basse < borne haute.")
    if coupon_annuel < 0:
        raise ValueError("Le coupon annuel doit être positif ou nul.")
    if frequence_paiement not in FREQUENCES_PAIEMENT:
        raise ValueError("La fréquence de paiement doit être 'mensuel', 'trimestriel', 'semestriel' ou 'annuel'.")


def calendrier_dra(T, frequence_paiement, freq_obs=252):
    """Nombre de jours d'observation et bornes (en indices de jours) de chaque période de paiement."""
    n_obs = max(1, int(round(T * freq_obs)))
    n_periodes = max(1, min(n_obs, int(round(T * FREQUENCES_PAIEMENT[frequence_paiement]))))
    bornes = np.round(np.linspace(0, n_obs, n_periodes + 1)).astype(int)
    return n_obs, n_periodes, bornes


def _jours_attendus_bs(S0, L, U, r, q, sigma, n_obs, freq_obs):
    """Probabilité risque-neutre d'être dans [L, U] chaque jour (formule fermée).

    P(L <= S_t <= U) = N(d2(L)) - N(d2(U)) avec
    d2(K) = [ln(S0/K) + (r - q - sigma^2/2) t] / (sigma sqrt t).
    C'est le prix d'une option digitale, sans actualisation.
    """
    t = np.arange(1, n_obs + 1) / freq_obs
    vol = sigma * np.sqrt(t)
    d2 = lambda K: (np.log(S0 / K) + (r - q - 0.5 * sigma ** 2) * t) / vol
    return oe.norm_cdf(d2(L)) - oe.norm_cdf(d2(U))


def _valeur_dra_bs(S0, r, q, sigma, T, bas, haut, coupon_annuel, frequence_paiement):
    freq_obs = 252
    n_obs, n_per, bornes = calendrier_dra(T, frequence_paiement, freq_obs)
    p = _jours_attendus_bs(S0, bas * S0, haut * S0, r, q, sigma, n_obs, freq_obs)
    jours_par_periode = np.array([p[bornes[j]:bornes[j + 1]].sum() for j in range(n_per)])
    t_paiement = bornes[1:] / freq_obs
    coupons = coupon_annuel * jours_par_periode / freq_obs
    valeur = float(np.sum(coupons * np.exp(-r * t_paiement)) + math.exp(-r * n_obs / freq_obs))
    return valeur, jours_par_periode, bornes, coupons, t_paiement


def _flux_dra_mc(S0, r, q, sigma, T, bas, haut, coupon_annuel, frequence_paiement, n_simulations, seed):
    freq_obs = 252
    n_obs, n_per, bornes = calendrier_dra(T, frequence_paiement, freq_obs)
    rng = np.random.default_rng(seed)
    dt = 1.0 / freq_obs
    derive = (r - q - 0.5 * sigma ** 2) * dt
    diffusion = sigma * math.sqrt(dt)
    L, U = bas * S0, haut * S0
    S = np.full(n_simulations, float(S0))
    jours = np.zeros((n_simulations, n_per))     # jours dans la fourchette, par période
    periode = 0
    for i in range(1, n_obs + 1):
        S = S * np.exp(derive + diffusion * rng.standard_normal(n_simulations))
        while i > bornes[periode + 1]:
            periode += 1
        jours[:, periode] += (S >= L) & (S <= U)
    t_paiement = bornes[1:] / freq_obs
    coupons = coupon_annuel * jours / freq_obs
    flux = coupons @ np.exp(-r * t_paiement) + math.exp(-r * n_obs / freq_obs)
    return flux, jours, bornes, t_paiement


def valeur_dra(methode, S0, r, q, sigma, T, borne_basse_pct, borne_haute_pct, coupon_annuel,
               frequence_paiement="trimestriel", n_simulations=50000, seed=42):
    """Valeur du DRA (fraction du nominal). Sert aux grecs."""
    verifier_dra(S0, r, q, sigma, T, borne_basse_pct, borne_haute_pct, coupon_annuel, frequence_paiement)
    if methode == "bs":
        return _valeur_dra_bs(S0, r, q, sigma, T, borne_basse_pct, borne_haute_pct,
                              coupon_annuel, frequence_paiement)[0]
    _verifier_simulations(n_simulations)
    flux = _flux_dra_mc(S0, r, q, sigma, T, borne_basse_pct, borne_haute_pct, coupon_annuel,
                        frequence_paiement, n_simulations, seed)[0]
    return float(np.mean(flux))


def analyser_dra(methode, S0, r, q, sigma, T, borne_basse_pct, borne_haute_pct, coupon_annuel,
                 frequence_paiement="trimestriel", n_simulations=50000, seed=42):
    """Valorise un DRA Daily (capital garanti à maturité, coupon proportionnel aux jours dans la fourchette)."""
    if methode not in oe.METHODS:
        raise ValueError("La méthode doit être 'bs' ou 'mc'.")
    verifier_dra(S0, r, q, sigma, T, borne_basse_pct, borne_haute_pct, coupon_annuel, frequence_paiement)
    freq_obs = 252
    if methode == "bs":
        prix, jours_attendus, bornes, coupons, t_paiement = _valeur_dra_bs(
            S0, r, q, sigma, T, borne_basse_pct, borne_haute_pct, coupon_annuel, frequence_paiement)
        erreur = None
        proba_coupon_nul = None
        n_sim_utilisees = None
    else:
        _verifier_simulations(n_simulations)
        flux, jours, bornes, t_paiement = _flux_dra_mc(
            S0, r, q, sigma, T, borne_basse_pct, borne_haute_pct, coupon_annuel,
            frequence_paiement, n_simulations, seed)
        prix = float(np.mean(flux))
        erreur = float(np.std(flux, ddof=1) / math.sqrt(n_simulations))
        jours_attendus = jours.mean(axis=0)
        coupons = coupon_annuel * jours_attendus / freq_obs
        proba_coupon_nul = float(np.mean(jours.sum(axis=1) == 0))
        n_sim_utilisees = int(n_simulations)

    n_obs = int(bornes[-1])
    jours_par_periode = np.diff(bornes)
    presence_par_periode = jours_attendus / jours_par_periode           # part du temps passée dans la fourchette
    presence_moyenne = float(jours_attendus.sum() / n_obs)
    valeur_capital = math.exp(-r * n_obs / freq_obs)
    valeur_coupons = prix - valeur_capital

    # Profil d'un jour d'observation : coupon quotidien selon le cours.
    grille = np.linspace(0.5 * S0, 1.5 * S0, 241)
    coupon_jour = np.where((grille >= borne_basse_pct * S0) & (grille <= borne_haute_pct * S0),
                           coupon_annuel / freq_obs, 0.0)

    return {
        "produit": "dra_daily", "methode": methode,
        "prix": float(prix), "erreur_type": erreur,
        "ic95": None if erreur is None else (prix - 1.96 * erreur, prix + 1.96 * erreur),
        "marge_emetteur": 1.0 - float(prix),
        "valeur_capital": float(valeur_capital), "valeur_coupons": float(valeur_coupons),
        "presence_moyenne": presence_moyenne,
        "coupon_annualise_espere": float(coupon_annuel * presence_moyenne),
        "presence_par_periode": presence_par_periode.tolist(),
        "coupons_espere_par_periode": np.asarray(coupons).tolist(),
        "dates_paiement": np.asarray(t_paiement).tolist(),
        "proba_coupon_nul": proba_coupon_nul,
        "borne_basse": borne_basse_pct * S0, "borne_haute": borne_haute_pct * S0,
        "n_observations": n_obs, "n_periodes": int(len(jours_par_periode)),
        "S_grid": grille.tolist(), "coupon_par_jour": coupon_jour.tolist(),
        "n_simulations": n_sim_utilisees,
    }
