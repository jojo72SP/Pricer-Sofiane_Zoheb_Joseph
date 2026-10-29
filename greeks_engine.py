"""Grecs par différences finies pour les produits sans formule fermée
(Phoenix, Athéna, accumulateur, décumulateur, DRA Daily).

Principe : on reçoit une fonction de valorisation f(S, sigma, r, tau) et on
la fait varier autour du point de départ. Pour les produits Monte Carlo,
f utilise toujours la MÊME graine : les écarts mesurés viennent alors du
paramètre qu'on a bougé, pas du hasard (nombres aléatoires communs).

Convention des grecs : identique à options_engine (clés de GRECS_INFO) afin de
réutiliser grecs_affichage / grecs_liste et d'avoir les mêmes unités de lecture.
tau est le TEMPS ÉCOULÉ (en années) : theta = variation de valeur quand le
temps passe, charm = variation du delta quand le temps passe.
"""
import numpy as np

import options_engine as oe


def grecs_diff_finies(f, S, sigma, r, dt, ordre3=False, h_spot=0.01, h_vol=0.005, h_taux=0.0005):
    """Grecs bruts de f autour de (S, sigma, r), tau = 0.

    f(S=, sigma=, r=, tau=) renvoie la valeur du produit (un float).
    ordre3=True active color, speed, zomma, ultima : il faut une fonction f
    déterministe (formule fermée), sinon le bruit Monte Carlo les noie.
    Sans ordre3, ces quatre grecs valent None.
    Renvoie un dict aux clés de options_engine.GRECS_INFO, en unités brutes
    (vega par unité de volatilité, theta par an, rho par unité de taux...).
    """
    hS = h_spot * S
    hv = min(h_vol, sigma / 3.0)      # on ne descend jamais sous une vol nulle
    hr = h_taux
    cache = {}

    def v(i=0, j=0, k=0, l=0):
        """Valeur en S + i*hS, sigma + j*hv, r + k*hr, après l*dt de temps écoulé."""
        cle = (i, j, k, l)
        if cle not in cache:
            cache[cle] = float(f(S=S + i * hS, sigma=sigma + j * hv, r=r + k * hr, tau=l * dt))
        return cache[cle]

    base = v()
    delta = (v(1) - v(-1)) / (2 * hS)
    gamma = (v(1) - 2 * base + v(-1)) / (hS * hS)
    vega = (v(0, 1) - v(0, -1)) / (2 * hv)
    vomma = (v(0, 1) - 2 * base + v(0, -1)) / (hv * hv)
    rho = (v(0, 0, 1) - v(0, 0, -1)) / (2 * hr)
    theta = (v(0, 0, 0, 1) - base) / dt

    # Dérivées croisées : on dérive le delta par rapport à sigma, puis au temps.
    delta_sigma = lambda j: (v(1, j) - v(-1, j)) / (2 * hS)
    vanna = (delta_sigma(1) - delta_sigma(-1)) / (2 * hv)
    delta_tau = (v(1, 0, 0, 1) - v(-1, 0, 0, 1)) / (2 * hS)
    charm = (delta_tau - delta) / dt
    elasticite = delta * S / base if abs(base) > 1e-12 else None

    grecs = {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho,
             "vanna": vanna, "vomma": vomma, "charm": charm, "lambda": elasticite,
             "color": None, "speed": None, "zomma": None, "ultima": None}

    if ordre3:
        gamma_en = lambda i, j=0, l=0: (v(i + 1, j, 0, l) - 2 * v(i, j, 0, l) + v(i - 1, j, 0, l)) / (hS * hS)
        grecs["color"] = (gamma_en(0, 0, 1) - gamma) / dt
        grecs["speed"] = (gamma_en(1) - gamma_en(-1)) / (2 * hS)
        grecs["zomma"] = (gamma_en(0, 1) - gamma_en(0, -1)) / (2 * hv)
        vomma_en = lambda j: (v(0, j + 1) - 2 * v(0, j) + v(0, j - 1)) / (hv * hv)
        grecs["ultima"] = (vomma_en(1) - vomma_en(-1)) / (2 * hv)
    return grecs


def grecs_pour_interface(f, S, sigma, r, dt, ordre3=False, **pas):
    """Grecs prêts à afficher : unités de lecture + liste libellée."""
    brut = grecs_diff_finies(f, S, sigma, r, dt, ordre3, **pas)
    return oe.grecs_liste(oe.grecs_affichage(brut))


# =====================================================================
# Grecs par produit
# =====================================================================
# Pour Phoenix, Athéna et DRA, le prix est en % du nominal et ne dépend que du
# rapport S / S_initial : on calcule donc les grecs avec un spot de référence
# de 100. Le delta se lit alors « en points de nominal pour +1 % de spot », le
# vega « pour +1 point de volatilité », etc. Le prix est multiplié par 100
# (98,7 = 98,7 % du nominal).
# Le spot bouge en gardant le STRIKE INITIAL fixe : on compense en ajustant
# strike_pct (ou les bornes), sinon les barrières suivraient le spot et le delta
# serait nul.

S_REF = 100.0


def _decalage_temps(dates, tau):
    """Dates d'observation après écoulement de tau années (elles se rapprochent)."""
    dates = np.asarray(dates, dtype=float) - tau
    if dates[0] <= 0:
        raise ValueError("La première date d'observation est trop proche pour calculer le theta.")
    return dates


def _pas_temps(dates):
    return min(1.0 / 365.0, float(np.asarray(dates)[0]) / 2.0)


def grecs_phoenix(r, q, sigma, obs_dates, K_auto, B_phoenix, B_pdi, coupon, n_simulations=50000,
                  memory=False, has_autocall=True, bonus_threshold=None, bonus_amount=0.0,
                  strike_pct=1.0, seed=42):
    """Grecs du Phoenix (Monte Carlo, mêmes tirages à chaque calcul)."""
    import strutu_engine as se

    def f(S, sigma, r, tau):
        res = se.analyse_phoenix(S, r, q, sigma, _decalage_temps(obs_dates, tau), K_auto, B_phoenix,
                                 B_pdi, coupon, n_simulations, memory, has_autocall, bonus_threshold,
                                 bonus_amount, strike_pct * S_REF / S, seed)
        return 100.0 * res["prix"]
    return grecs_pour_interface(f, S_REF, sigma, r, _pas_temps(obs_dates),
                                h_spot=0.02, h_vol=0.01, h_taux=0.001)


def grecs_plain(r, q, sigma, obs_dates, K_auto, B_pdi, coupon, n_simulations=50000,
                first_call_date=None, has_autocall=True, strike_pct=1.0, seed=42):
    """Grecs de l'Autocall Plain (Athéna), Monte Carlo à graine fixe."""
    import strutu_engine as se

    def f(S, sigma, r, tau):
        res = se.analyse_autocall_plain(S, r, q, sigma, _decalage_temps(obs_dates, tau), K_auto, B_pdi,
                                        coupon, n_simulations, first_call_date, seed, has_autocall,
                                        strike_pct * S_REF / S)
        return 100.0 * res["prix"]
    return grecs_pour_interface(f, S_REF, sigma, r, _pas_temps(obs_dates),
                                h_spot=0.02, h_vol=0.01, h_taux=0.001)


def grecs_dra(methode, r, q, sigma, T, borne_basse_pct, borne_haute_pct, coupon_annuel,
              frequence_paiement="trimestriel", n_simulations=50000, seed=42):
    """Grecs du DRA Daily. En "bs", la valeur est une formule fermée : les 13 grecs sont disponibles."""
    import fixings_engine as fe

    def f(S, sigma, r, tau):
        # bornes fixes en niveau : quand le spot bouge, leur % du spot s'ajuste
        return 100.0 * fe.valeur_dra(methode, S, r, q, sigma, T - tau, borne_basse_pct * S_REF / S,
                                     borne_haute_pct * S_REF / S, coupon_annuel, frequence_paiement,
                                     n_simulations, seed)
    return grecs_pour_interface(f, S_REF, sigma, r, 1.0 / 252.0, ordre3=(methode == "bs"),
                                h_spot=0.01 if methode == "bs" else 0.02,
                                h_vol=0.005 if methode == "bs" else 0.01,
                                h_taux=0.0005 if methode == "bs" else 0.001)


def grecs_accumulateur(sens, S0, r, q, sigma, T, strike_pct, ko_pct, levier=2.0, quantite=1.0,
                       frequence="quotidien", n_garanti=0, livraison_au_ko=False,
                       n_simulations=50000, seed=42):
    """Grecs de l'accumulateur / décumulateur, en monnaie (le delta est un nombre d'actions équivalent).

    Le temps qui passe = un constat de moins (theta hors flux déjà encaissés).
    """
    import fixings_engine as fe
    d, n_fix = fe.verifier_accumulateur(sens, S0, r, q, sigma, T, strike_pct, ko_pct, levier, quantite,
                                        frequence, n_garanti, n_simulations)
    freq = fe.FREQUENCES_CONSTAT[frequence]
    K, H = strike_pct * S0, ko_pct * S0       # niveaux absolus, fixés à la signature

    def f(S, sigma, r, tau):
        n = n_fix - int(round(tau * freq))
        res = fe._simuler_accumulateur(d, S, r, q, sigma, n, freq, K / S, H / S, levier, quantite,
                                       max(0, n_garanti - int(round(tau * freq))), livraison_au_ko,
                                       n_simulations, seed)
        return float(np.mean(res["valeur"]))
    grecs = grecs_pour_interface(f, S0, sigma, r, 1.0 / freq, h_spot=0.02, h_vol=0.01, h_taux=0.001)
    # Lambda = delta * S / valeur n'a pas de sens quand le contrat vaut ~0 par construction.
    for g in grecs:
        if g["cle"] == "lambda":
            g["valeur"], g["indisponible"] = None, True
    return grecs
