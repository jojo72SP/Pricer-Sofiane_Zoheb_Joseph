"""Options classiques : Black-Scholes (formules fermées) et Monte Carlo, avec grecs.

Conventions : r, q, sigma en décimal (0,25 = 25 %), T en années, un seul
sous-jacent. Le rendement de dividende q est continu (chapitre 4 du cours).

Deux méthodes de valorisation, mêmes entrées, mêmes sorties :
- "bs" : formule fermée du chapitre 7 et grecs analytiques des chapitres 8-9 ;
- "mc" : simulation Monte Carlo (chapitre 11) avec variables antithétiques,
  grecs par différences finies sur les MÊMES tirages (nombres aléatoires communs),
  ce qui évite que le bruit de simulation pollue les différences.
"""
import math

import numpy as np

_SQRT_2 = math.sqrt(2.0)
_SQRT_2PI = math.sqrt(2.0 * math.pi)
_erf_vec = np.vectorize(math.erf, otypes=[float])

KINDS = ("call", "put")
SIDES = {"long": 1, "short": -1}
METHODS = ("bs", "mc")


# =========================
# Loi normale
# =========================

def norm_cdf(x):
    """Fonction de répartition N(x), pour un scalaire ou un tableau."""
    if np.ndim(x) == 0:
        return 0.5 * (1.0 + math.erf(float(x) / _SQRT_2))
    return 0.5 * (1.0 + _erf_vec(np.asarray(x, dtype=float) / _SQRT_2))


def norm_pdf(x):
    """Densité de la loi normale centrée réduite."""
    return np.exp(-0.5 * np.square(x)) / _SQRT_2PI


# =========================
# Validation
# =========================

def verifier_option(S, K, T, r, q, sigma):
    """Refuse les paramètres inexploitables (Black-Scholes exige T et sigma > 0)."""
    for nom, v in (("Le spot", S), ("Le strike", K), ("La maturité", T),
                   ("Le taux", r), ("Le dividende", q), ("La volatilité", sigma)):
        if isinstance(v, bool) or not np.isscalar(v) or not np.isfinite(v):
            raise ValueError(f"{nom} doit être un nombre fini.")
    if S <= 0 or K <= 0:
        raise ValueError("Le spot et le strike doivent être strictement positifs.")
    if T <= 0:
        raise ValueError("La maturité doit être strictement positive.")
    if sigma <= 0:
        raise ValueError("La volatilité doit être strictement positive.")


def _verifier_type(kind):
    if kind not in KINDS:
        raise ValueError("Le type d'option doit être 'call' ou 'put'.")


# =========================
# Black-Scholes : prix
# =========================

def _d1_d2(S, K, T, r, q, sigma):
    vol = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol
    return d1, d1 - vol


def bs_price(kind, S, K, T, r, q, sigma):
    """Prix Black-Scholes d'un call ou d'un put européen (dividende continu q)."""
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    if kind == "call":
        return S * math.exp(-q * T) * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * math.exp(-q * T) * norm_cdf(-d1)


def bs_price_array(kind, S_arr, K, T, r, q, sigma):
    """Même prix, pour toute une grille de spots (sert aux courbes de calendar)."""
    S_arr = np.asarray(S_arr, dtype=float)
    if T <= 0:
        return np.maximum(S_arr - K, 0.0) if kind == "call" else np.maximum(K - S_arr, 0.0)
    S_safe = np.maximum(S_arr, 1e-12)
    vol = sigma * math.sqrt(T)
    d1 = (np.log(S_safe / K) + (r - q + 0.5 * sigma * sigma) * T) / vol
    d2 = d1 - vol
    if kind == "call":
        return S_safe * math.exp(-q * T) * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S_safe * math.exp(-q * T) * norm_cdf(-d1)


# =========================
# Black-Scholes : grecs bruts (par unité de chaque variable)
# =========================

def bs_grecs(kind, S, K, T, r, q, sigma):
    """Grecs analytiques bruts d'UNE option longue.

    Unités brutes : vega, vanna, vomma, zomma, ultima par unité de sigma ;
    theta, charm, color par année ; rho par unité de taux.
    La conversion en unités de lecture (point de vol, jour...) est faite par
    grecs_affichage.
    """
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    sq = math.sqrt(T)
    eq, er = math.exp(-q * T), math.exp(-r * T)
    phi = float(norm_pdf(d1))
    n1, n2 = norm_cdf(d1), norm_cdf(d2)
    call = kind == "call"
    prix = bs_price(kind, S, K, T, r, q, sigma)

    delta = eq * n1 if call else eq * (n1 - 1.0)
    gamma = eq * phi / (S * sigma * sq)
    vega = S * eq * phi * sq
    terme_commun = -S * eq * phi * sigma / (2.0 * sq)
    if call:
        theta = terme_commun - r * K * er * n2 + q * S * eq * n1
        rho = K * T * er * n2
    else:
        theta = terme_commun + r * K * er * norm_cdf(-d2) - q * S * eq * norm_cdf(-d1)
        rho = -K * T * er * norm_cdf(-d2)

    # Grecs secondaires
    vanna = -eq * phi * d2 / sigma
    vomma = vega * d1 * d2 / sigma
    crochet = 2.0 * (r - q) * T - d2 * sigma * sq
    derive_q = q * eq * n1 if call else -q * eq * norm_cdf(-d1)
    charm = derive_q - eq * phi * crochet / (2.0 * T * sigma * sq)
    # Color = variation du gamma quand le temps passe (signe vérifié par différences finies)
    color = eq * phi / (2.0 * S * T * sigma * sq) * (2.0 * q * T + 1.0 + d1 * crochet / (sigma * sq))
    speed = -gamma / S * (d1 / (sigma * sq) + 1.0)
    zomma = gamma * (d1 * d2 - 1.0) / sigma
    ultima = -vega / (sigma * sigma) * (d1 * d2 * (1.0 - d1 * d2) + d1 * d1 + d2 * d2)
    elasticite = delta * S / prix if abs(prix) > 1e-12 else None

    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho,
            "vanna": vanna, "vomma": vomma, "charm": charm, "color": color,
            "speed": speed, "zomma": zomma, "ultima": ultima, "lambda": elasticite}


# =========================
# Monte Carlo : prix et grecs par différences finies
# =========================

def tirages_normaux(n_simulations, seed):
    """Tirages normaux de base. Avec les variables antithétiques, n tirages
    servent n paires de trajectoires (Z et -Z), soit 2n trajectoires."""
    n_paires = max(1, int(n_simulations) // 2)
    return np.random.default_rng(seed).standard_normal(n_paires)


def mc_valeurs(kind, S, K, T, r, q, sigma, Z):
    """Valeur actualisée du payoff par paire antithétique (tableau de taille len(Z))."""
    derive = (r - q - 0.5 * sigma * sigma) * T
    diffusion = sigma * math.sqrt(T)
    S1 = S * np.exp(derive + diffusion * Z)
    S2 = S * np.exp(derive - diffusion * Z)
    if kind == "call":
        p = 0.5 * (np.maximum(S1 - K, 0.0) + np.maximum(S2 - K, 0.0))
    else:
        p = 0.5 * (np.maximum(K - S1, 0.0) + np.maximum(K - S2, 0.0))
    return math.exp(-r * T) * p


def mc_prix(kind, S, K, T, r, q, sigma, Z):
    """Prix Monte Carlo et erreur type (écart-type des paires / racine du nombre de paires)."""
    v = mc_valeurs(kind, S, K, T, r, q, sigma, Z)
    erreur = float(np.std(v, ddof=1) / math.sqrt(v.size)) if v.size > 1 else 0.0
    return float(np.mean(v)), erreur


def mc_grecs(kind, S, K, T, r, q, sigma, Z):
    """Grecs d'UNE option longue par différences finies centrées, mêmes tirages Z.

    Disponibles : delta, gamma, vega, theta, rho, vanna, vomma, charm, lambda.
    Color, speed, zomma et ultima (dérivées d'ordre 3) sont trop bruitées en
    Monte Carlo : elles restent à None, réservées à la méthode Black-Scholes.
    """
    def f(S_=S, v_=sigma, r_=r, T_=T):
        return float(np.mean(mc_valeurs(kind, S_, K, T_, r_, q, v_, Z)))

    hS, hv, hr = 0.01 * S, min(0.005, sigma / 2.0), 0.0005
    dt = min(1.0 / 365.0, T / 2.0)
    base = f()
    up, dn = f(S_=S + hS), f(S_=S - hS)
    delta = (up - dn) / (2 * hS)
    gamma = (up - 2 * base + dn) / (hS * hS)
    v_up, v_dn = f(v_=sigma + hv), f(v_=sigma - hv)
    vega = (v_up - v_dn) / (2 * hv)
    vomma = (v_up - 2 * base + v_dn) / (hv * hv)
    rho = (f(r_=r + hr) - f(r_=r - hr)) / (2 * hr)
    theta = (f(T_=T - dt) - base) / dt            # variation de valeur quand le temps passe
    delta_vp = (f(S_=S + hS, v_=sigma + hv) - f(S_=S - hS, v_=sigma + hv)) / (2 * hS)
    delta_vm = (f(S_=S + hS, v_=sigma - hv) - f(S_=S - hS, v_=sigma - hv)) / (2 * hS)
    vanna = (delta_vp - delta_vm) / (2 * hv)
    delta_t = (f(S_=S + hS, T_=T - dt) - f(S_=S - hS, T_=T - dt)) / (2 * hS)
    charm = (delta_t - delta) / dt                # variation du delta quand le temps passe
    elasticite = delta * S / base if abs(base) > 1e-12 else None
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho,
            "vanna": vanna, "vomma": vomma, "charm": charm, "color": None,
            "speed": None, "zomma": None, "ultima": None, "lambda": elasticite}


# =========================
# Présentation des grecs
# =========================

# (clé, libellé, groupe, unité de lecture)
GRECS_INFO = [
    ("delta", "Delta (Δ)", "primaire", "variation de valeur pour +1 de spot"),
    ("gamma", "Gamma (Γ)", "primaire", "variation du delta pour +1 de spot"),
    ("vega", "Vega (ν)", "primaire", "variation de valeur pour +1 point de volatilité"),
    ("theta", "Theta (Θ)", "primaire", "variation de valeur par jour calendaire"),
    ("rho", "Rho (ρ)", "primaire", "variation de valeur pour +1 point de taux"),
    ("vanna", "Vanna", "secondaire", "variation du delta pour +1 point de volatilité"),
    ("vomma", "Vomma (Volga)", "secondaire", "variation du vega pour +1 point de volatilité"),
    ("charm", "Charm", "secondaire", "variation du delta par jour"),
    ("color", "Color", "secondaire", "variation du gamma par jour"),
    ("speed", "Speed", "secondaire", "variation du gamma pour +1 de spot"),
    ("zomma", "Zomma", "secondaire", "variation du gamma pour +1 point de volatilité"),
    ("ultima", "Ultima", "secondaire", "variation du vomma pour +1 point de volatilité"),
    ("lambda", "Lambda (élasticité)", "secondaire", "variation en % de la valeur pour +1 % de spot"),
]

_ECHELLES = {"vega": 100.0, "theta": 365.0, "rho": 100.0, "vanna": 100.0,
             "vomma": 1e4, "charm": 365.0, "color": 365.0, "zomma": 100.0,
             "ultima": 1e6}


def grecs_affichage(brut):
    """Convertit des grecs bruts en unités de lecture (point de vol, jour, point de taux)."""
    sortie = {}
    for cle, _, _, _ in GRECS_INFO:
        v = brut.get(cle)
        sortie[cle] = None if v is None else float(v) / _ECHELLES.get(cle, 1.0)
    return sortie


def grecs_liste(affiche, methode="bs"):
    """Liste prête pour l'interface : libellé, valeur (ou None), groupe, unité."""
    liste = []
    for cle, libelle, groupe, unite in GRECS_INFO:
        v = affiche.get(cle)
        liste.append({"cle": cle, "libelle": libelle, "groupe": groupe, "unite": unite,
                      "valeur": None if v is None else round(float(v), 8),
                      "indisponible": v is None})
    return liste


def multiplier_grecs(brut, facteur):
    """Multiplie des grecs bruts par un facteur (signe de la position, quantité)."""
    return {k: (None if v is None else v * facteur) for k, v in brut.items()}


def additionner_grecs(liste_de_grecs):
    """Somme des grecs bruts de plusieurs jambes ; None si une jambe ne le fournit pas."""
    total = {}
    for cle, _, _, _ in GRECS_INFO:
        valeurs = [g.get(cle) for g in liste_de_grecs]
        total[cle] = None if any(v is None for v in valeurs) else float(sum(valeurs))
    return total


# =========================
# Courbes de gain à l'échéance
# =========================

def trouver_breakevens(grille, pnl):
    """Points où le P&L change de signe (interpolation linéaire entre deux points)."""
    grille, pnl = np.asarray(grille, float), np.asarray(pnl, float)
    points = []
    for i in range(len(grille) - 1):
        a, b = pnl[i], pnl[i + 1]
        if a == 0.0:
            points.append(float(grille[i]))
        elif a * b < 0.0:
            t = a / (a - b)
            points.append(float(grille[i] + t * (grille[i + 1] - grille[i])))
    if pnl[-1] == 0.0:
        points.append(float(grille[-1]))
    return sorted(set(round(p, 6) for p in points))


def profil_extremes(grille, pnl, pnl_en_zero):
    """Gain max et perte max d'un profil ; None si la borne est illimitée."""
    grille, pnl = np.asarray(grille, float), np.asarray(pnl, float)
    pente_droite = (pnl[-1] - pnl[-2]) / (grille[-1] - grille[-2])
    tout = np.append(pnl, pnl_en_zero)
    gain = None if pente_droite > 1e-9 else float(tout.max())
    perte = None if pente_droite < -1e-9 else float(tout.min())
    return {"gain_max": gain, "perte_max": perte,
            "gain_illimite": bool(pente_droite > 1e-9), "perte_illimitee": bool(pente_droite < -1e-9)}


def grille_spot(S, niveaux, n_points=241, bas=0.5, haut=1.5):
    """Grille de cours à l'échéance autour du spot et des strikes."""
    centres = [S] + [v for v in niveaux if v]
    return np.linspace(max(0.01, min(centres) * bas), max(centres) * haut, n_points)


# =========================
# Analyse complète d'une option
# =========================

def analyser_option(kind, side, S, K, T, r, q, sigma, method="bs",
                    n_simulations=100000, seed=42):
    """Prix, grecs et profil de gain d'une option (long/short call/put).

    Renvoie la prime par option (toujours positive), la valeur de la position
    (signée), la valeur intrinsèque et la valeur temps (chapitre 2.4), les
    grecs de la position et le P&L à l'échéance (primes non actualisées, comme
    dans le cours).
    """
    _verifier_type(kind)
    if side not in SIDES:
        raise ValueError("La position doit être 'long' ou 'short'.")
    if method not in METHODS:
        raise ValueError("La méthode doit être 'bs' ou 'mc'.")
    verifier_option(S, K, T, r, q, sigma)
    signe = SIDES[side]

    if method == "bs":
        prime = bs_price(kind, S, K, T, r, q, sigma)
        erreur = None
        brut = bs_grecs(kind, S, K, T, r, q, sigma)
    else:
        Z = tirages_normaux(n_simulations, seed)
        prime, erreur = mc_prix(kind, S, K, T, r, q, sigma, Z)
        brut = mc_grecs(kind, S, K, T, r, q, sigma, Z)

    intrinseque = max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)
    grecs_pos = multiplier_grecs(brut, signe)

    grille = grille_spot(S, [K])
    payoff = np.maximum(grille - K, 0.0) if kind == "call" else np.maximum(K - grille, 0.0)
    pnl = signe * (payoff - prime)
    pnl_zero = signe * ((0.0 if kind == "call" else K) - prime)

    return {
        "methode": method, "type": kind, "position": side,
        "prime": float(prime), "valeur_position": float(signe * prime),
        "erreur_type": erreur,
        "ic95": None if erreur is None else (prime - 1.96 * erreur, prime + 1.96 * erreur),
        "valeur_intrinseque": float(intrinseque), "valeur_temps": float(prime - intrinseque),
        "grecs": grecs_liste(grecs_affichage(grecs_pos), method),
        "ST_grid": grille.tolist(), "payoff": (signe * payoff).tolist(), "pnl": pnl.tolist(),
        "breakevens": trouver_breakevens(grille, pnl),
        "extremes": profil_extremes(grille, pnl, pnl_zero),
        "n_simulations": None if method == "bs" else int(2 * Z.size),
    }
