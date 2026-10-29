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
