"""Tests des moteurs ajoutés : options, stratégies, accumulateur/décumulateur, DRA, grecs, routes.

Lancer : python -m unittest discover -s tests -v
Les tests vérifient des propriétés financières (parité call-put, formules du
cours, cohérence Black-Scholes / Monte Carlo), pas seulement l'absence d'erreur.
"""
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fixings_engine as fe
import greeks_engine as ge
import options_engine as oe
import strategies_engine as se
import strutu_engine as st
import main

S, K, T, R, Q, SIG = 100.0, 105.0, 0.5, 0.03, 0.01, 0.25


def valeur_grec(liste, cle):
    return next(g["valeur"] for g in liste if g["cle"] == cle)


class TestOptions(unittest.TestCase):
    def test_parite_call_put(self):
        c, p = oe.bs_price("call", S, K, T, R, Q, SIG), oe.bs_price("put", S, K, T, R, Q, SIG)
        self.assertAlmostEqual(c - p, S * math.exp(-Q * T) - K * math.exp(-R * T), places=10)

    def test_grecs_analytiques_contre_differences_finies(self):
        f = lambda S, sigma, r, tau: oe.bs_price("call", S, K, T - tau, r, Q, sigma)
        fd = ge.grecs_diff_finies(f, S, SIG, R, 1 / 365, ordre3=True)
        an = oe.bs_grecs("call", S, K, T, R, Q, SIG)
        for cle in ("delta", "gamma", "vega", "theta", "rho", "vanna", "vomma", "charm", "color", "speed", "zomma"):
            # theta, charm et color utilisent une différence AVANT en temps (pas de 1/365) : biais en O(dt), tolérance 1 %
            tolerance_relative = 1e-2 if cle in ("theta", "charm", "color") else 2e-3
            self.assertAlmostEqual(fd[cle], an[cle], delta=max(tolerance_relative * abs(an[cle]), 2e-5), msg=cle)

    def test_monte_carlo_proche_de_black_scholes(self):
        bs = oe.analyser_option("call", "long", S, K, T, R, Q, SIG, "bs")
        mc = oe.analyser_option("call", "long", S, K, T, R, Q, SIG, "mc", 200000, 1)
        self.assertLess(abs(mc["prime"] - bs["prime"]), 4 * mc["erreur_type"])
        self.assertAlmostEqual(valeur_grec(mc["grecs"], "delta"), valeur_grec(bs["grecs"], "delta"), delta=0.01)

    def test_signes_du_tableau_du_cours(self):
        """Chapitre 10 : acheteur call + + + - + ; vendeur call - - - + - ; acheteur put - + + - - ; vendeur put + - - + +."""
        attendu = {("call", "long"): (1, 1, 1, -1, 1), ("call", "short"): (-1, -1, -1, 1, -1),
                   ("put", "long"): (-1, 1, 1, -1, -1), ("put", "short"): (1, -1, -1, 1, 1)}
        for (kind, side), signes in attendu.items():
            res = oe.analyser_option(kind, side, S, K, T, R, Q, SIG, "bs")
            lus = tuple(np.sign(valeur_grec(res["grecs"], c)) for c in ("delta", "gamma", "vega", "theta", "rho"))
            self.assertEqual(lus, tuple(float(x) for x in signes), (kind, side))

    def test_short_est_l_oppose_du_long(self):
        lg, sh = oe.analyser_option("put", "long", S, K, T, R, Q, SIG), oe.analyser_option("put", "short", S, K, T, R, Q, SIG)
        np.testing.assert_allclose(np.array(lg["pnl"]), -np.array(sh["pnl"]))

    def test_valeur_intrinseque_et_temps(self):
        r = oe.analyser_option("call", "long", 120, 100, 1, R, Q, SIG)
        self.assertAlmostEqual(r["valeur_intrinseque"], 20.0)
        self.assertAlmostEqual(r["valeur_temps"], r["prime"] - 20.0)

    def test_parametres_invalides(self):
        for mauvais in (dict(T=0), dict(sigma=0), dict(K=-1), dict(S=0)):
            p = dict(S=100, K=100, T=1, r=.03, q=0, sigma=.2); p.update(mauvais)
            with self.assertRaises(ValueError):
                oe.analyser_option("call", "long", p["S"], p["K"], p["T"], p["r"], p["q"], p["sigma"])
        with self.assertRaises(ValueError):
            oe.analyser_option("straddle", "long", S, K, T, R, Q, SIG)


class TestStrategies(unittest.TestCase):
    def run_strat(self, nom, methode="bs", **p):
        return se.analyser_strategie(nom, S, {"T": T, **p}, R, Q, SIG, methode, 100000, 1)

    def test_covered_call_formules_du_cours(self):
        C = oe.bs_price("call", S, 105, T, R, Q, SIG)
        res = self.run_strat("covered_call", K=105)
        self.assertAlmostEqual(res["breakevens"][0], S - C, places=4)
        self.assertAlmostEqual(res["extremes"]["gain_max"], (105 - S) + C, places=4)
        self.assertAlmostEqual(res["extremes"]["perte_max"], -(S - C), places=4)

    def test_protective_put_formules_du_cours(self):
        P = oe.bs_price("put", S, 95, T, R, Q, SIG)
        res = self.run_strat("protective_put", K=95)
        self.assertAlmostEqual(res["breakevens"][0], S + P, places=4)
        self.assertAlmostEqual(res["extremes"]["perte_max"], -(S + P - 95), places=4)
        self.assertTrue(res["extremes"]["gain_illimite"])

    def test_straddle_points_morts_symetriques(self):
        res = self.run_strat("long_straddle", K=100)
        prime = res["cout_net"]
        self.assertAlmostEqual(res["breakevens"][0], 100 - prime, places=4)
        self.assertAlmostEqual(res["breakevens"][1], 100 + prime, places=4)
        self.assertAlmostEqual(res["extremes"]["perte_max"], -prime, places=4)

    def test_forward_synthetique_parite(self):
        res = self.run_strat("forward_synthetique", K=100)
        self.assertAlmostEqual(res["cout_net"], S * math.exp(-Q * T) - 100 * math.exp(-R * T), places=8)
        self.assertAlmostEqual(valeur_grec(res["grecs"], "vega"), 0.0, places=8)

    def test_spreads_gain_et_perte_bornes(self):
        bull = self.run_strat("bull_call_spread", K1=100, K2=110)
        self.assertAlmostEqual(bull["extremes"]["gain_max"], 10 - bull["cout_net"], places=4)
        self.assertAlmostEqual(bull["extremes"]["perte_max"], -bull["cout_net"], places=4)
        bear = self.run_strat("bear_put_spread", K1=90, K2=100)
        self.assertAlmostEqual(bear["extremes"]["gain_max"], 10 - bear["cout_net"], places=4)

    def test_collar_delta_entre_0_et_1(self):
        res = self.run_strat("collar", K1=90, K2=110)
        self.assertTrue(0 < valeur_grec(res["grecs"], "delta") < 1)

    def test_short_est_l_oppose_du_long(self):
        lg, sh = self.run_strat("long_strangle", K1=90, K2=110), self.run_strat("short_strangle", K1=90, K2=110)
        self.assertAlmostEqual(lg["cout_net"], -sh["cout_net"], places=10)

    def test_monte_carlo_coherent(self):
        bs, mc = self.run_strat("collar", K1=90, K2=110), self.run_strat("collar", "mc", K1=90, K2=110)
        self.assertLess(abs(bs["cout_net"] - mc["cout_net"]), 4 * mc["erreur_type"])

    def test_les_11_strategies_du_projet_tournent_sans_calendar(self):
        self.assertEqual(len(se.STRATEGIES), 11)
        self.assertNotIn("calendar", se.STRATEGIES)

    def test_erreurs(self):
        with self.assertRaises(ValueError):
            self.run_strat("long_strangle", K1=110, K2=90)
        with self.assertRaises(ValueError):
            self.run_strat("collar", K1=90)
        with self.assertRaises(ValueError):
            self.run_strat("calendar", K=100)


class TestFixings(unittest.TestCase):
    def test_accumulateur_vol_quasi_nulle_valeur_connue(self):
        # r = q et sigma ~ 0 : le spot reste à 100, jamais de KO ni de levier, gain de 10 par constat
        res = fe.analyser_accumulateur("accumulateur", 100, 0.03, 0.03, 1e-6, 1.0, 0.90, 1.10, n_simulations=2000)
        attendu = sum(10 * math.exp(-0.03 * i / 252) for i in range(1, 253))
        self.assertAlmostEqual(res["valeur"], attendu, delta=1e-2)
        self.assertEqual(res["proba_ko"], 0.0)

    def test_decumulateur_est_le_miroir_de_l_accumulateur(self):
        a = fe.analyser_accumulateur("accumulateur", 100, 0.03, 0.03, 1e-6, 1.0, 0.90, 1.10, n_simulations=2000)
        d = fe.analyser_accumulateur("decumulateur", 100, 0.03, 0.03, 1e-6, 1.0, 1.10, 0.90, n_simulations=2000)
        self.assertAlmostEqual(a["valeur"], d["valeur"], delta=1e-2)

    def test_ko_cumule_croissant_et_coherent(self):
        res = fe.analyser_accumulateur("accumulateur", 100, R, Q, SIG, 1.0, 0.90, 1.05, n_simulations=5000, seed=3)
        c = np.array(res["proba_ko_cumulee"])
        self.assertTrue(np.all(np.diff(c) >= -1e-12))
        self.assertAlmostEqual(c[-1], res["proba_ko"], places=10)

    def test_constats_garantis_empechent_le_ko(self):
        sans = fe.analyser_accumulateur("accumulateur", 100, R, Q, SIG, 0.25, 0.90, 1.02, n_simulations=5000, seed=3)
        avec = fe.analyser_accumulateur("accumulateur", 100, R, Q, SIG, 0.25, 0.90, 1.02, n_garanti=30, n_simulations=5000, seed=3)
        self.assertLess(avec["proba_ko"], sans["proba_ko"])

    def test_strike_zero_cout(self):
        for sens, ko in (("accumulateur", 1.05), ("decumulateur", 0.95)):
            k = fe.strike_zero_cout(sens, 100, R, Q, SIG, 0.5, ko, n_simulations=5000, iterations=18)
            v = fe.valeur_accumulateur(sens, 100, R, Q, SIG, 0.5, k, ko, n_simulations=5000)
            # précision de la dichotomie à 18 itérations : la valeur du contrat est de l'ordre de plusieurs centaines hors du strike optimal
            self.assertAlmostEqual(v, 0.0, delta=0.1, msg=sens)
        self.assertLess(fe.strike_zero_cout("accumulateur", 100, R, Q, SIG, 0.5, 1.05, n_simulations=5000, iterations=18), 1.0)

    def test_dra_black_scholes_egal_monte_carlo(self):
        for bas, haut in ((0.9, 1.1), (0.8, 1.2)):
            b = fe.analyser_dra("bs", 100, R, Q, 0.2, 2.0, bas, haut, 0.08)
            m = fe.analyser_dra("mc", 100, R, Q, 0.2, 2.0, bas, haut, 0.08, n_simulations=100000, seed=7)
            self.assertLess(abs(m["prix"] - b["prix"]), 4 * m["erreur_type"])

    def test_dra_cas_limites(self):
        large = fe.analyser_dra("bs", 100, R, Q, 0.2, 2.0, 0.001, 1000, 0.08)
        self.assertAlmostEqual(large["presence_moyenne"], 1.0, places=6)      # toujours dans la fourchette
        etroit = fe.analyser_dra("bs", 100, R, Q, 0.2, 2.0, 1.0, 1.0001, 0.08)
        self.assertAlmostEqual(etroit["prix"], etroit["valeur_capital"], delta=1e-3)  # presque jamais : capital seul

    def test_dra_prix_croit_avec_la_largeur_de_la_fourchette(self):
        prix = [fe.analyser_dra("bs", 100, R, Q, 0.2, 2.0, 1 - w, 1 + w, 0.08)["prix"] for w in (0.05, 0.1, 0.2, 0.4)]
        self.assertEqual(prix, sorted(prix))

    def test_erreurs(self):
        with self.assertRaises(ValueError):
            fe.analyser_accumulateur("accumulateur", 100, R, Q, SIG, 1.0, 1.10, 1.05)   # strike > KO
        with self.assertRaises(ValueError):
            fe.analyser_accumulateur("decumulateur", 100, R, Q, SIG, 1.0, 0.90, 1.05)   # KO au-dessus du spot
        with self.assertRaises(ValueError):
            fe.analyser_dra("bs", 100, R, Q, SIG, 1.0, 1.1, 0.9, 0.08)                   # bornes inversées


class TestGrecsProduits(unittest.TestCase):
    dates = [0.5, 1, 1.5, 2, 2.5, 3]

    def test_dra_grecs_black_scholes_et_monte_carlo_concordent(self):
        bs = ge.grecs_dra("bs", R, Q, 0.2, 2.0, 0.9, 1.1, 0.08)
        mc = ge.grecs_dra("mc", R, Q, 0.2, 2.0, 0.9, 1.1, 0.08, n_simulations=50000)
        for cle, tol in (("delta", 0.01), ("vega", 0.03), ("rho", 0.05)):
            self.assertAlmostEqual(valeur_grec(bs, cle), valeur_grec(mc, cle), delta=tol, msg=cle)
        self.assertIsNotNone(valeur_grec(bs, "ultima"))
        self.assertIsNone(valeur_grec(mc, "ultima"))      # ordre 3 : trop bruité en Monte Carlo

    def test_phoenix_signes_economiques(self):
        g = ge.grecs_phoenix(R, Q, 0.22, self.dates, 1.0, 0.7, 0.6, 0.04, 50000, True)
        self.assertGreater(valeur_grec(g, "delta"), 0)    # le client est long le sous-jacent via la protection vendue
        self.assertLess(valeur_grec(g, "vega"), 0)        # vendeur de volatilité

    def test_accumulateur_et_decumulateur_delta_opposes(self):
        a = ge.grecs_accumulateur("accumulateur", 100, R, Q, SIG, 0.5, 0.90, 1.05, n_simulations=10000)
        d = ge.grecs_accumulateur("decumulateur", 100, R, Q, SIG, 0.5, 1.10, 0.95, n_simulations=10000)
        self.assertGreater(valeur_grec(a, "delta"), 0)
        self.assertLess(valeur_grec(d, "delta"), 0)

    def test_strike_pct_de_l_autocall_plain_ne_change_rien_par_defaut(self):
        a = st.analyse_autocall_plain(100, R, Q, 0.22, self.dates, 1.0, 0.6, 0.03, 20000, seed=5)
        b = st.analyse_autocall_plain(100, R, Q, 0.22, self.dates, 1.0, 0.6, 0.03, 20000, seed=5, strike_pct=1.0)
        self.assertEqual(a, b)


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()

    def post(self, url, corps):
        rep = self.client.post(url, json=corps)
        return rep.status_code, rep.get_json()

    marche = {"S0": 100, "r": 3, "q": 1, "sigma": 25}

    def test_option(self):
        code, d = self.post("/api/option", {**self.marche, "type": "call", "position": "long", "K": 105, "T": 0.5, "methode": "bs"})
        self.assertEqual(code, 200)
        self.assertAlmostEqual(d["prime"], oe.bs_price("call", 100, 105, 0.5, 0.03, 0.01, 0.25), places=8)
        self.assertEqual(len(d["grecs"]), 13)
        code, d = self.post("/api/option", {**self.marche, "type": "put", "position": "short", "K": 95, "T": 1, "methode": "mc", "n_simulations": 20000})
        self.assertEqual(code, 200)
        self.assertIsNotNone(d["erreur_type"])

    def test_option_erreurs(self):
        for corps in ({**self.marche, "type": "call", "position": "long", "K": 100, "T": 0},
                      {**self.marche, "type": "call", "position": "long", "K": 100, "T": 1, "methode": "xyz"},
                      {**self.marche, "sigma": 0, "type": "call", "position": "long", "K": 100, "T": 1},
                      {"type": "call", "position": "long", "K": 100, "T": 1}):
            code, d = self.post("/api/option", corps)
            self.assertEqual(code, 400, corps)
            self.assertIn("error", d)

    def test_strategies_catalogue_et_calcul(self):
        rep = self.client.get("/api/strategies").get_json()
        self.assertEqual(len(rep["strategies"]), 11)
        for s in rep["strategies"]:
            code, d = self.post("/api/strategie", {**self.marche, "strategie": s["cle"], "T": 0.5})   # strikes par défaut
            self.assertEqual(code, 200, s["cle"])
            self.assertTrue(d["jambes"])

    def test_strategie_inconnue(self):
        code, d = self.post("/api/strategie", {**self.marche, "strategie": "calendar", "T": 0.5})
        self.assertEqual(code, 400)

    def test_accumulateur(self):
        code, d = self.post("/api/accumulateur", {**self.marche, "sens": "accumulateur", "T": 0.5, "strike_pct": 90, "ko_pct": 105,
                                                  "n_simulations": 5000, "zero_cout": True})
        self.assertEqual(code, 200)
        self.assertLess(d["strike_zero_cout_pct"], 100)
        self.assertEqual(len(d["grecs"]), 13)
        code, d = self.post("/api/accumulateur", {**self.marche, "sens": "decumulateur", "T": 0.5, "n_simulations": 5000})
        self.assertEqual(code, 200)
        code, d = self.post("/api/accumulateur", {**self.marche, "sens": "accumulateur", "T": 0.5, "strike_pct": 110, "ko_pct": 105})
        self.assertEqual(code, 400)

    def test_dra(self):
        for methode in ("bs", "mc"):
            code, d = self.post("/api/dra", {**self.marche, "sigma": 20, "T": 2, "methode": methode, "borne_basse_pct": 90,
                                             "borne_haute_pct": 110, "coupon_annuel": 8, "n_simulations": 5000})
            self.assertEqual(code, 200, methode)
            self.assertGreater(d["prix_pct"], 90)
        code, d = self.post("/api/dra", {**self.marche, "T": 2, "borne_basse_pct": 110, "borne_haute_pct": 90, "coupon_annuel": 8})
        self.assertEqual(code, 400)

    def test_phoenix_et_autocall_renvoient_les_grecs(self):
        corps = {**self.marche, "sigma": 22, "T": 3, "frequence": 2, "B_phoenix": 70, "B_pdi": 60, "coupon": 4,
                 "memory": True, "n_simulations": 5000, "seed": 1}
        code, d = self.post("/api/phoenix", corps)
        self.assertEqual(code, 200)
        self.assertEqual(len(d["grecs"]), 13)
        code, d = self.post("/api/autocall", {**self.marche, "sigma": 22, "produit": "autocall_plain", "T": 3, "frequence": 2,
                                              "K_auto": 100, "coupon": 3, "B_pdi": 60, "n_simulations": 5000})
        self.assertEqual(code, 200)
        self.assertEqual(len(d["grecs"]), 13)
        code, d = self.post("/api/phoenix", {**corps, "avec_grecs": False})
        self.assertIsNone(d["grecs"])


if __name__ == "__main__":
    unittest.main()
