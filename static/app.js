'use strict';
/* Pricer — logique de la page.
   Plan du fichier :
   1. Outils de mise en forme       4. Onglet I   : options
   2. Onglets et paramètres t0      5. Onglet II  : stratégies
   3. Graphique, tableaux, calculs  6. Onglet III : produits structurés (Phoenix, Athéna, accumulateur, DRA) */

// =====================================================================
// 1. Outils de mise en forme
// =====================================================================
const $ = id => document.getElementById(id);
const nf = (min, max) => new Intl.NumberFormat('fr-FR', {minimumFractionDigits: min, maximumFractionDigits: max});
const fmt = x => nf(2, 4).format(x);
const fmtMontant = v => nf(2, 2).format(v);
const fmtPct = x => nf(2, 2).format(x) + ' %';
const fmtNb = v => nf(0, 2).format(v);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
// Les grecs sont de tailles très différentes : on adapte le nombre de décimales.
function fmtGrec(v) {
  const a = Math.abs(v);
  const d = a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.01 ? 4 : 6;
  return nf(d, d).format(v);
}

// =====================================================================
// 2. Onglets et paramètres de marché à t0
// =====================================================================
const state = {methode: 'bs', devise: '', volMarche: {hist: null, vix: null}};

document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach(t => {
    const actif = t === tab;
    t.classList.toggle('active', actif);
    t.setAttribute('aria-selected', actif);
  });
  ['panel-options', 'panel-strategies', 'panel-structured'].forEach(id => { $(id).hidden = id !== tab.dataset.panel; });
}));

function setMethode(m) {
  state.methode = m;
  $('m-bs').setAttribute('aria-pressed', m === 'bs');
  $('m-mc').setAttribute('aria-pressed', m === 'mc');
}
$('m-bs').addEventListener('click', () => setMethode('bs'));
$('m-mc').addEventListener('click', () => setMethode('mc'));

// Volatilité à t0 : saisie manuelle, historique 1 an ou VIX. Le champ reste toujours visible.
function appliquerSourceSigma() {
  const source = $('m-sigma-source').value;
  const manuelle = source === 'manual';
  $('m-sigma').readOnly = !manuelle;
  if (!manuelle) {
    const v = state.volMarche[source];
    $('m-sigma').value = v == null ? '' : Number(v).toFixed(2);
    if (v == null) $('m-status').textContent = "Cherche d'abord un ticker pour obtenir cette volatilité, ou repasse en saisie manuelle.";
  }
}
$('m-sigma-source').addEventListener('change', appliquerSourceSigma);

function spotChange() { document.dispatchEvent(new Event('spotchange')); }
$('m-s0').addEventListener('input', spotChange);

// Lit et vérifie les paramètres de marché (envoyés à chaque calcul).
function lireMarche() {
  for (const id of ['m-s0', 'm-sigma', 'm-r', 'm-q', 'm-nsims', 'm-seed']) {
    if (!$(id).reportValidity()) throw new Error('Corrige les paramètres de marché (bloc t₀ en haut de page).');
  }
  const S0 = Number($('m-s0').value), sigma = Number($('m-sigma').value);
  if (!(S0 > 0)) throw new Error('Le spot S₀ doit être strictement positif.');
  if (!(sigma > 0)) throw new Error('Renseigne la volatilité σ à t₀ (strictement positive).');
  return {S0, sigma, r: $('m-r').value, q: $('m-q').value, methode: state.methode,
          n_simulations: $('m-nsims').value, seed: $('m-seed').value};
}

// Recherche de ticker : suggestions puis récupération du spot, de la devise et des volatilités.
(function brancherRechercheTicker() {
  const input = $('m-ticker'), boite = $('m-ticker-results');
  let minuteur = null, version = 0;
  input.addEventListener('input', () => {
    clearTimeout(minuteur);
    const requete = input.value.trim();
    if (!requete) { boite.hidden = true; return; }
    minuteur = setTimeout(async () => {
      try {
        const rep = await fetch('/api/search_ticker?q=' + encodeURIComponent(requete));
        const data = await rep.json();
        if (!data.results || !data.results.length) { boite.hidden = true; return; }
        boite.innerHTML = data.results.map(r =>
          `<div class="ticker-hit" data-symbol="${esc(r.symbol)}"><strong>${esc(r.symbol)}</strong> — ${esc(r.name || '')} <span style="color:var(--muted)">${esc(r.exchange || '')}</span></div>`).join('');
        boite.hidden = false;
        boite.querySelectorAll('[data-symbol]').forEach(el => el.addEventListener('click', () => {
          input.value = el.dataset.symbol;
          boite.hidden = true;
          chargerMarche(el.dataset.symbol);
        }));
      } catch (e) { /* recherche facultative : pas d'erreur bloquante */ }
    }, 350);
  });
  document.addEventListener('click', e => { if (!boite.contains(e.target) && e.target !== input) boite.hidden = true; });

  async function chargerMarche(symbole) {
    const v = ++version, statut = $('m-status');
    statut.textContent = 'Récupération des données de marché…';
    try {
      const rep = await fetch('/api/market/' + encodeURIComponent(symbole));
      const data = await rep.json();
      if (v !== version) return;
      if (!rep.ok) throw new Error(data.error || 'Données indisponibles.');
      $('m-s0').value = data.S0;
      state.devise = data.devise || '';
      state.volMarche = {hist: data.vol_hist, vix: data.vix};
      // La vol historique convient mieux à une action que le VIX, qui mesure le S&P 500.
      $('m-sigma-source').value = data.vol_hist != null ? 'hist' : (data.vix != null ? 'vix' : 'manual');
      appliquerSourceSigma();
      const vol = x => x == null ? 'n.d.' : fmtMontant(x) + ' %';
      statut.textContent = `${symbole} (${state.devise}) · spot ${data.S0} · vol. historique ${vol(data.vol_hist)} · VIX ${vol(data.vix)}`;
      spotChange();
    } catch (err) {
      if (v === version) statut.textContent = 'Erreur : ' + err.message + ' Tu peux saisir le spot et la volatilité à la main.';
    }
  }
})();

// =====================================================================
// 3. Graphique, tableaux et calculs
// =====================================================================
let chartId = 0;
// xs : abscisses ; series : [{key, values, color?}] ; breakevens : abscisses des points morts.
// opts : labels, markers [{x,label,color}], xLabel, yLabel, fillKey (série dont l'aire est colorée).
function renderChart(xs, series, breakevens, opts = {}) {
  const W = 760, H = 340, L = 66, R = 18, top = 38, bottom = 48;
  const id = ++chartId;
  const xmin = xs[0], xmax = xs[xs.length - 1];
  const tous = series.flatMap(s => s.values);
  const pad = Math.max((Math.max(...tous) - Math.min(...tous)) * .12, 1e-9, Math.abs(Math.max(...tous)) * 0.02);
  const ymin = opts.yMin !== undefined ? opts.yMin : Math.min(0, ...tous) - pad;
  const ymax = opts.yMax !== undefined ? opts.yMax : Math.max(0, ...tous) + pad;
  const X = x => L + (x - xmin) / (xmax - xmin) * (W - L - R);
  const Y = y => top + (ymax - y) / (ymax - ymin) * (H - top - bottom);
  const nb = v => nf(0, Math.abs(v) < 10 ? 2 : 0).format(v);
  // Graduations « rondes » (1, 2, 5 × puissance de 10) : jamais de 3,66 ou de 101,4.
  const graduations = (min, max, n) => {
    const brut = (max - min) / n, p = Math.pow(10, Math.floor(Math.log10(brut))), f = brut / p;
    const pas = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
    const vals = [];
    for (let v = Math.ceil(min / pas - 1e-9) * pas; v <= max + pas * 1e-9; v += pas) vals.push(Math.abs(v) < pas * 1e-9 ? 0 : v);
    const dec = Math.min(4, Math.max(0, -Math.floor(Math.log10(pas) + 1e-9)));
    return {vals, fmt: v => nf(dec, dec).format(v)};
  };
  const couleurs = {payoff: '#14213d', pnl: '#b08d2f'};
  const tirets = {payoff: '6 5', pnl: '0'};
  const libelles = Object.assign({payoff: 'Payoff brut', pnl: 'Profit net'}, opts.labels || {});
  const couleur = s => s.color || couleurs[s.key] || '#14213d';

  let c = `<rect x="0" y="0" width="${W}" height="${H}" fill="#fff"/>`;
  const gy = graduations(ymin, ymax, 5), gx = graduations(xmin, xmax, 6);
  gy.vals.forEach(y => {
    c += `<line x1="${L}" x2="${W - R}" y1="${Y(y)}" y2="${Y(y)}" stroke="#eee9da"/>`;
    c += `<text x="${L - 8}" y="${Y(y) + 4}" text-anchor="end">${gy.fmt(y)}</text>`;
  });
  gx.vals.forEach(x => {
    c += `<line x1="${X(x)}" x2="${X(x)}" y1="${top}" y2="${H - bottom}" stroke="#f4f0e4"/>`;
    c += `<text x="${X(x)}" y="${H - bottom + 20}" text-anchor="middle">${gx.fmt(x)}</text>`;
  });
  c += `<text x="${(W + L - R) / 2}" y="${H - 8}" text-anchor="middle">${esc(opts.xLabel || 'Cours du sous-jacent à l’échéance')}</text>`;
  if (opts.yLabel) c += `<text transform="rotate(-90)" x="${-(H + top - bottom) / 2}" y="15" text-anchor="middle">${esc(opts.yLabel)}</text>`;

  // Aire verte (gain) et rouge (perte) sous la courbe de référence
  const zero = Y(0);
  c += `<defs><clipPath id="h${id}"><rect x="${L}" y="${top}" width="${W - L - R}" height="${Math.max(zero - top, 0)}"/></clipPath>
        <clipPath id="b${id}"><rect x="${L}" y="${zero}" width="${W - L - R}" height="${Math.max(H - bottom - zero, 0)}"/></clipPath></defs>`;
  const ref = series.find(s => s.key === (opts.fillKey || 'pnl'));
  if (ref) {
    const pts = xs.map((x, i) => `L${X(x).toFixed(2)},${Y(ref.values[i]).toFixed(2)}`).join(' ');
    const aire = `M${X(xmin)},${zero} ${pts} L${X(xmax)},${zero} Z`;
    c += `<path d="${aire}" fill="#1b7a4b" fill-opacity=".13" clip-path="url(#h${id})"/>`;
    c += `<path d="${aire}" fill="#b3261e" fill-opacity=".13" clip-path="url(#b${id})"/>`;
  }
  c += `<line x1="${L}" x2="${W - R}" y1="${zero}" y2="${zero}" stroke="#9aa1b3"/>`;

  (opts.markers || []).forEach((m, i) => {
    if (m.x < xmin || m.x > xmax) return;
    c += `<line x1="${X(m.x)}" x2="${X(m.x)}" y1="${top}" y2="${H - bottom}" stroke="${m.color}" stroke-dasharray="2 4"/>`;
    c += `<text x="${X(m.x) + 5}" y="${top + 14 + i * 14}" style="fill:${m.color};paint-order:stroke;stroke:#fff;stroke-width:4px">${esc(m.label)}</text>`;
  });
  series.forEach(s => {
    const d = xs.map((x, i) => (i ? 'L' : 'M') + X(x).toFixed(2) + ',' + Y(s.values[i]).toFixed(2)).join(' ');
    c += `<path d="${d}" fill="none" stroke="${couleur(s)}" stroke-width="${s.key === 'pnl' ? 2.4 : 1.8}" stroke-dasharray="${tirets[s.key] || '0'}" stroke-linejoin="round"/>`;
  });
  (breakevens || []).forEach(be => {
    c += `<line x1="${X(be)}" x2="${X(be)}" y1="${top}" y2="${H - bottom}" stroke="#b08d2f" stroke-dasharray="3 4"/>`;
    c += `<circle cx="${X(be)}" cy="${zero}" r="4.5" fill="#fff" stroke="#b08d2f" stroke-width="1.8"/>`;
    c += `<text x="${X(be) + 7}" y="${zero - 9}" style="fill:#7a5f14;paint-order:stroke;stroke:#fff;stroke-width:4px">${nb(be)}</text>`;
  });
  // Légende
  let lx = L;
  const ly = top - 16;
  series.forEach(s => {
    const lib = libelles[s.key] || s.key;
    c += `<line x1="${lx}" x2="${lx + 18}" y1="${ly}" y2="${ly}" stroke="${couleur(s)}" stroke-width="2.2" stroke-dasharray="${tirets[s.key] || '0'}"/>`;
    c += `<text x="${lx + 24}" y="${ly + 4}" style="fill:#3d4a63">${esc(lib)}</text>`;
    lx += 24 + lib.length * 6.3 + 22;
  });
  if ((breakevens || []).length) {
    c += `<circle cx="${lx + 5}" cy="${ly}" r="4.5" fill="#fff" stroke="#b08d2f" stroke-width="1.8"/>`;
    c += `<text x="${lx + 15}" y="${ly + 4}" style="fill:#3d4a63">Point mort</text>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.aria || 'Graphique')}">${c}</svg>`;
}

// rows : [[libellé, valeur, classe?]] ; classe : pos, neg ou small (texte long)
function metricsGrid(rows) {
  return '<div class="metrics">' + rows.map(([l, v, cls]) =>
    `<div class="metric"><p>${esc(l)}</p><strong class="${cls || ''}">${v}</strong></div>`).join('') + '</div>';
}
const carte = (titre, corps) => `<div class="card chart-card"><h2>${esc(titre)}</h2>${corps}</div>`;

// Tableau des grecs : primaires puis secondaires, avec leur unité de lecture.
// badge : texte affiché quand un grec d'ordre 3 n'est pas disponible.
function greeksCard(grecs, {badge = 'B&S uniquement', note = ''} = {}) {
  if (!grecs) return carte('Grecs', '<p class="chart-note">Les grecs n’ont pas pu être calculés pour ces paramètres.</p>');
  const ordre3 = ['color', 'speed', 'zomma', 'ultima'];
  const titres = {primaire: 'Grecs primaires', secondaire: 'Grecs secondaires (principaux)'};
  let groupe = '', html = '';
  grecs.forEach(g => {
    if (g.groupe !== groupe) { groupe = g.groupe; html += `<tr class="groupe"><td colspan="3">${titres[g.groupe] || g.groupe}</td></tr>`; }
    const valeur = g.indisponible
      ? '—' + (ordre3.includes(g.cle) ? `<span class="badge">${esc(badge)}</span>` : '')
      : fmtGrec(g.valeur);
    html += `<tr><td>${esc(g.libelle)}</td><td>${valeur}</td><td class="unite">${esc(g.unite)}</td></tr>`;
  });
  return carte('Grecs', `<table class="tbl"><thead><tr><th>Grec</th><th>Valeur</th><th style="text-align:left;padding-left:14px">Lecture</th></tr></thead><tbody>${html}</tbody></table>
    ${note ? `<p class="chart-note">${esc(note)}</p>` : ''}`);
}

// Lance un calcul : bouton bloqué, délai maximal, message d'erreur lisible.
async function runCalc({url, payload, bouton, statut, message = 'Calcul en cours…', delai = 120000, onData}) {
  bouton.disabled = true;
  statut.className = 'status';
  statut.textContent = message;
  const controle = new AbortController();
  const minuteur = setTimeout(() => controle.abort(), delai);
  try {
    const rep = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                  body: JSON.stringify(payload), signal: controle.signal});
    const data = await rep.json().catch(() => ({}));
    if (!rep.ok) throw new Error(data.error || 'Calcul indisponible.');
    const affiche = onData(data);
    if (affiche !== false) statut.textContent = 'Calcul terminé.';
  } catch (err) {
    statut.className = 'status error';
    statut.textContent = err.name === 'AbortError' ? 'Calcul trop long. Réduis le nombre de simulations et réessaie.' : err.message;
  } finally {
    clearTimeout(minuteur);
    bouton.disabled = false;
  }
}
const erreurStatut = (statut, err) => { statut.className = 'status error'; statut.textContent = err.message; };
const libMethode = d => d.methode === 'bs' ? 'Black-Scholes · formule fermée'
  : `Monte Carlo · ${fmtNb(d.n_simulations)} trajectoires`;
const listePM = be => be && be.length ? be.map(fmtMontant).join(' · ') : '—';
const gainTxt = (ex) => ex.gain_illimite ? 'Illimité' : fmtMontant(ex.gain_max);
const perteTxt = (ex) => ex.perte_illimitee ? 'Illimitée' : fmtMontant(ex.perte_max);
const grec = (d, cle) => { const g = (d.grecs || []).find(x => x.cle === cle); return g && g.valeur != null ? fmtGrec(g.valeur) : '—'; };
const noteGrecsOptions = m => m === 'bs'
  ? 'Formules analytiques du cours (chapitres 8 et 9). Vega, vanna, vomma, zomma, ultima : pour +1 point de volatilité ; theta, charm, color : par jour ; rho : pour +1 point de taux.'
  : 'Grecs par différences finies sur les mêmes tirages Monte Carlo. Les grecs d’ordre 3 (color, speed, zomma, ultima) sont trop bruités en simulation : ils ne sont disponibles qu’en Black-Scholes.';

// =====================================================================
// 4. Onglet I : options vanilles
// =====================================================================
(function () {
  const K = $('opt-k');
  K.addEventListener('input', () => { K.dataset.touched = '1'; });
  document.addEventListener('spotchange', () => {
    const s = Number($('m-s0').value);
    if (!K.dataset.touched && s > 0) K.value = Math.round(s * 100) / 100;
  });

  $('form-option').addEventListener('submit', async e => {
    e.preventDefault();
    const statut = $('opt-status');
    if (!e.target.reportValidity()) return;
    let m;
    try { m = lireMarche(); } catch (err) { return erreurStatut(statut, err); }
    const payload = {...m, type: $('opt-type').value, position: $('opt-side').value,
                     K: $('opt-k').value, T: Number($('opt-months').value) / 12};
    await runCalc({url: '/api/option', payload, bouton: e.target.querySelector('button'), statut, onData: d => {
      const ex = d.extremes, long = d.position === 'long';
      const mc = d.methode === 'mc';
      $('opt-results').innerHTML = metricsGrid([
        ['Prime de l’option', fmtMontant(d.prime)],
        ['Valeur de la position', fmtMontant(d.valeur_position), d.valeur_position >= 0 ? 'pos' : 'neg'],
        ['Valeur intrinsèque', fmtMontant(d.valeur_intrinseque)],
        ['Valeur temps', fmtMontant(d.valeur_temps)],
        ['Point mort à l’échéance', listePM(d.breakevens)],
        ['Gain maximal', gainTxt(ex), 'pos'],
        ['Perte maximale', perteTxt(ex), 'neg'],
        ['Méthode', libMethode(d), 'small'],
        [mc ? 'Intervalle de confiance 95 %' : 'Position', mc ? `${fmt(d.ic95[0])} – ${fmt(d.ic95[1])}` : (long ? 'Acheteur : paie la prime' : 'Vendeur : encaisse la prime'), 'small'],
      ]) + carte('Profil à l’échéance', renderChart(d.ST_grid,
        [{key: 'payoff', values: d.payoff}, {key: 'pnl', values: d.pnl}], d.breakevens, {
          labels: {payoff: 'Payoff (sans prime)', pnl: 'Profit net (prime incluse)'},
          markers: [{x: Number($('opt-k').value), label: 'Strike', color: '#3d4a63'}],
          aria: 'Payoff et profit d’une option à l’échéance'}) +
        '<p class="chart-note">Profit à l’échéance en intégrant la prime, sans actualisation, comme dans le cours (ch. 2.5).</p>')
        + greeksCard(d.grecs, {note: noteGrecsOptions(d.methode)});
    }});
  });
})();

// =====================================================================
// 5. Onglet II : stratégies du chapitre 3
// =====================================================================
(function () {
  const catalogue = {};
  const NOMS = {K: 'Strike K', K1: 'Strike bas K1', K2: 'Strike haut K2'};
  const BAS = ['long_strangle', 'short_strangle', 'collar', 'risk_reversal', 'bear_put_spread'];
  // Mêmes strikes par défaut que le serveur : ATM, ±10 %.
  const defauts = (nom, s) => {
    const r = x => Math.round(x * 100) / 100;
    return {K: r(s), K1: r(BAS.includes(nom) ? s * 0.9 : s), K2: r(s * 1.1)};
  };
  const spot = () => { const s = Number($('m-s0').value); return s > 0 ? s : 100; };

  function afficherStrategie() {
    const nom = $('strat-select').value, s = catalogue[nom];
    if (!s) return;
    const d = $('strat-desc');
    d.hidden = false;
    d.innerHTML = `<b>${esc(s.nom)}</b> (cours §${esc(s.section)})<br>Construction : ${esc(s.construction)}<br>Vue : ${esc(s.vue)}<br>${esc(s.interet)}`;
    const def = defauts(nom, spot());
    let html = s.parametres.map(p => `<div><label for="sp-${p}">${NOMS[p]}</label><input id="sp-${p}" type="number" value="${def[p]}" min="0.0001" step="any" required></div>`).join('');
    if (nom === 'risk_reversal') html += '<div class="full"><label for="sp-sens">Sens</label><select id="sp-sens"><option value="haussier">Haussier : long call, short put</option><option value="baissier">Baissier : long put, short call</option></select></div>';
    $('strat-params').innerHTML = html;
    $('strat-params').querySelectorAll('input').forEach(i => i.addEventListener('input', () => { i.dataset.touched = '1'; }));
  }
  $('strat-select').addEventListener('change', afficherStrategie);
  document.addEventListener('spotchange', () => {
    const def = defauts($('strat-select').value, spot());
    $('strat-params').querySelectorAll('input').forEach(i => { if (!i.dataset.touched) i.value = def[i.id.slice(3)]; });
  });

  fetch('/api/strategies').then(r => r.json()).then(d => {
    d.strategies.forEach(s => { catalogue[s.cle] = s; });
    $('strat-select').innerHTML = d.strategies.map(s => `<option value="${esc(s.cle)}">${esc(s.nom)}</option>`).join('');
    afficherStrategie();
  }).catch(() => erreurStatut($('strat-status'), new Error('Catalogue des stratégies indisponible : relance le serveur.')));

  $('form-strategy').addEventListener('submit', async e => {
    e.preventDefault();
    const statut = $('strat-status');
    if (!e.target.reportValidity()) return;
    let m;
    try { m = lireMarche(); } catch (err) { return erreurStatut(statut, err); }
    const nom = $('strat-select').value;
    const payload = {...m, strategie: nom, T: Number($('strat-months').value) / 12};
    catalogue[nom].parametres.forEach(p => { payload[p] = $('sp-' + p).value; });
    if ($('sp-sens')) payload.sens = $('sp-sens').value;
    await runCalc({url: '/api/strategie', payload, bouton: e.target.querySelector('button'), statut, onData: d => {
      const ex = d.extremes, mc = d.methode === 'mc';
      const niveaux = [...new Set(d.jambes.filter(j => j.K).map(j => j.K))];
      const lignes = d.jambes.map(j => `<tr><td>${esc(j.libelle)}</td><td>${j.position === 'long' ? 'Long' : 'Short'}</td><td>${j.K ? fmtMontant(j.K) : '—'}</td><td>${j.T ? fmtMontant(j.T) : '—'}</td><td>${fmtMontant(j.prix_unitaire)}</td></tr>`).join('');
      $('strat-results').innerHTML = metricsGrid([
        ['Coût net à l’entrée', `${fmtMontant(Math.abs(d.cout_net))} (${d.nature})`],
        ['Vue de marché', esc(d.vue), 'small'],
        ['Point(s) mort', listePM(d.breakevens)],
        ['Gain maximal', gainTxt(ex), 'pos'],
        ['Perte maximale', perteTxt(ex), 'neg'],
        ['Delta net', grec(d, 'delta')],
        ['Vega net (par point de vol)', grec(d, 'vega')],
        ['Theta net (par jour)', grec(d, 'theta')],
        ['Méthode', libMethode(d) + (mc ? ` · IC 95 % ${fmt(d.ic95[0])} – ${fmt(d.ic95[1])}` : ''), 'small'],
      ]) + carte('Profil à l’échéance', renderChart(d.ST_grid, [{key: 'pnl', values: d.pnl}], d.breakevens, {
          labels: {pnl: 'Profit net de la stratégie'},
          markers: niveaux.map(k => ({x: k, label: 'K ' + fmtNb(k), color: '#3d4a63'})),
          aria: 'Profil de gain de la stratégie à l’échéance'}) +
        '<p class="chart-note">Profit à l’échéance, primes non actualisées (cours, ch. 3). Les prix de toutes les jambes utilisent la même volatilité : le smile et le skew ne sont pas modélisés.</p>')
        + carte('Composition', `<table class="tbl"><thead><tr><th>Jambe</th><th>Position</th><th>Strike</th><th>Maturité (ans)</th><th>Prix unitaire</th></tr></thead><tbody>${lignes}</tbody></table>
          <p class="chart-note">${esc(d.construction)}. ${esc(d.interet)}</p>`)
        + greeksCard(d.grecs, {note: noteGrecsOptions(d.methode) + ' Grecs de la stratégie entière (somme des jambes).'});
    }});
  });
})();

// =====================================================================
// 6. Onglet III : produits structurés
// =====================================================================
const MESSAGE_VIDE = '<div class="empty">Lance un calcul pour voir les résultats.</div>';
let selectionVersion = 0;   // permet d'ignorer un résultat arrivé après un changement de produit

function afficherProduit() {
  const produit = $('struct-product').value;
  ++selectionVersion;
  document.querySelectorAll('#panel-structured form').forEach(f => { f.hidden = !f.dataset.product.split(' ').includes(produit); });
  $('mc-only-note').hidden = produit === 'dra';
  if (produit === 'accumulateur' || produit === 'decumulateur') configurerAccumulateur(produit);
  $('st-results').innerHTML = MESSAGE_VIDE;
}
$('struct-product').addEventListener('change', afficherProduit);

// Montant et résumé communs au Phoenix et à l'Athéna
function metriquesStructure(d) {
  const marge = d.marge_emetteur_pct ?? d.ecart_souscription_pct;
  return metricsGrid([
    ['Prix théorique', fmtPct(d.prix_pct)],
    ['Valeur pour le montant investi', fmtMontant(d.prix)],
    ['Marge émetteur', fmtPct(marge), marge >= 0 ? 'pos' : 'neg'],
    ['Probabilité de perte en capital', fmtPct(d.proba_perte_capital_pct)],
    ['Durée de vie moyenne', fmtMontant(d.duree_de_vie_moyenne) + ' ans'],
    ['Va jusqu’à maturité', fmtPct(d.proba_maturite_pct)],
    ['Remboursement moyen si perte', d.remboursement_moyen_si_perte_pct === null ? '—' : fmtPct(d.remboursement_moyen_si_perte_pct)],
    ['Coupons moyens actualisés', fmtPct(d.coupons_moyens_actualises_pct)],
    ['Intervalle de confiance 95 %', `${fmtPct(d.ic95_pct[0])} – ${fmtPct(d.ic95_pct[1])}`, 'small'],
  ]);
}
const NOTE_GRECS_STRUCT = 'Grecs par différences finies sur les mêmes tirages Monte Carlo, prix en points de nominal pour un spot de référence de 100 : delta pour +1 % de spot, vega pour +1 point de volatilité, theta par jour, rho pour +1 point de taux. Le gamma est bruité (barrières) : augmente le nombre de simulations pour le stabiliser.';

// ---------- Phoenix ----------
(function () {
  const spot = () => { const s = Number($('m-s0').value); return s > 0 ? s : 100; };
  $('phx-stepup-on').addEventListener('change', () => {
    const on = $('phx-stepup-on').checked;
    $('phx-stepup-wrap').hidden = !on;
    $('phx-stepup').required = on;
  });
  // Les dates se construisent à partir de la maturité et de la fréquence : jamais saisies à la main.
  function majDates() {
    const pas = 12 / Number($('phx-freq').value), mois = $('phx-months');
    mois.step = pas; mois.min = pas;
    const n = Number(mois.value) / pas;
    $('phx-dates-hint').textContent = Number.isInteger(n) && n > 0
      ? `${n} date(s) d'observation, tous les ${pas} mois.` : `La maturité doit être un multiple de ${pas} mois.`;
  }
  function niveau(pct) {
    const p = nf(0, 2).format(pct) + ' %';
    return `${p} du départ (${fmt(spot() * pct / 100)}${state.devise ? ' ' + state.devise : ''})`;
  }
  function majIndices() {
    const k = Number($('phx-kauto').value), bc = Number($('phx-bcoupon').value), bp = Number($('phx-bpdi').value);
    $('phx-kauto-hint').textContent = $('phx-autocall').checked
      ? `À chaque date, si le sous-jacent est au-dessus de ${niveau(k)}, tu récupères ton capital + le coupon et le produit s'arrête.`
      : 'Désactivé : le produit va toujours jusqu’à maturité.';
    $('phx-bcoupon-hint').textContent = `À chaque date, s'il est au-dessus de ${niveau(bc)}, tu touches le coupon.`;
    $('phx-bpdi-hint').textContent = `À maturité, s'il est sous ${niveau(bp)}, tu perds autant que la baisse du sous-jacent.`;
  }
  // Ordre des barrières : protection ≤ coupon ≤ rappel (message natif du navigateur).
  function verifierBarrieres() {
    const k = Number($('phx-kauto').value), bc = Number($('phx-bcoupon').value), bp = Number($('phx-bpdi').value);
    $('phx-bpdi').setCustomValidity(bp > bc ? 'La protection doit être ≤ à la barrière coupon.' : '');
    $('phx-bcoupon').setCustomValidity($('phx-autocall').checked && bc > k ? 'La barrière coupon doit être ≤ à la barrière de rappel.' : '');
  }
  ['phx-kauto', 'phx-bcoupon', 'phx-bpdi'].forEach(id => $(id).addEventListener('input', () => { majIndices(); verifierBarrieres(); }));
  $('phx-autocall').addEventListener('change', () => { $('phx-kauto').disabled = !$('phx-autocall').checked; majIndices(); verifierBarrieres(); });
  $('phx-freq').addEventListener('change', majDates);
  $('phx-months').addEventListener('input', majDates);
  document.addEventListener('spotchange', majIndices);
  majDates(); majIndices();

  $('form-phoenix').addEventListener('submit', async e => {
    e.preventDefault();
    const statut = $('phx-status');
    verifierBarrieres();
    if (!e.target.reportValidity()) return;
    let m;
    try { m = lireMarche(); } catch (err) { return erreurStatut(statut, err); }
    const freq = Number($('phx-freq').value), nDates = Number($('phx-months').value) / (12 / freq);
    const c0 = Number($('phx-coupon').value), hausse = $('phx-stepup-on').checked ? Number($('phx-stepup').value) : 0;
    const coupon = hausse > 0 ? Array.from({length: nDates}, (_, i) => c0 + i * hausse) : c0;
    const payload = {...m, nominal: $('phx-nominal').value, T: Number($('phx-months').value) / 12, frequence: freq,
      coupon, K_auto: $('phx-kauto').value, B_phoenix: $('phx-bcoupon').value, B_pdi: $('phx-bpdi').value,
      memory: $('phx-memory').checked, has_autocall: $('phx-autocall').checked,
      bonus_threshold: $('phx-bonus-threshold').value, bonus_amount: $('phx-bonus-amount').value || 0, avec_grecs: true};
    delete payload.methode;
    const version = selectionVersion;
    await runCalc({url: '/api/phoenix', payload, bouton: e.target.querySelector('button'), statut,
      message: 'Simulation en cours…', onData: d => {
      if (version !== selectionVersion) return false;
      const niv = d.niveaux, n = d.obs_dates.length;
      const marqueurs = [niv.autocall !== null ? {x: niv.autocall, label: 'Rappel', color: '#14213d'} : null,
        {x: niv.coupon, label: 'Coupon', color: '#1b7a4b'}, {x: niv.protection, label: 'Protection', color: '#b3261e'}].filter(Boolean);
      const lignes = d.obs_dates.map((t, i) => `<tr><td>${fmt(t)} an(s)</td><td>${fmtPct(d.coupon_schedule_pct[i])}</td><td>${i === n - 1 ? '—' : fmtPct(d.proba_rappel_par_date_pct[i])}</td></tr>`).join('');
      $('st-results').innerHTML = metriquesStructure(d)
        + carte('Remboursement à maturité', renderChart(d.ST_grid, [{key: 'payoff', values: d.payoff}, {key: 'pnl', values: d.pnl}], [], {
            labels: {payoff: 'Remboursement à maturité', pnl: 'Gain ou perte vs montant investi'},
            xLabel: state.devise ? `Prix du sous-jacent à maturité (${state.devise})` : 'Niveau du sous-jacent à maturité',
            markers: marqueurs, aria: 'Remboursement du Phoenix à maturité'}) +
          '<p class="chart-note">Cas où le produit n’a pas été rappelé avant maturité. Seul le coupon de la dernière date est compté : les coupons déjà versés et l’effet mémoire dépendent du chemin suivi.</p>')
        + carte('Calendrier d’observation', `<table class="tbl"><thead><tr><th>Date</th><th>Coupon de la période</th><th>Probabilité de rappel</th></tr></thead><tbody>${lignes}</tbody></table>`)
        + greeksCard(d.grecs, {badge: 'non calculé (bruit MC)', note: NOTE_GRECS_STRUCT});
    }});
  });
})();

// ---------- Athéna (Autocall Plain) ----------
(function () {
  const p = 'ac-plain-';
  const f = id => $(p + id);
  function validerDates() {
    const freq = Number(f('freq').value), mois = Number(f('months').value), n = mois * freq / 12;
    f('months').setCustomValidity(n > 0 && Math.abs(n - Math.round(n)) < 1e-9 ? '' : 'La maturité doit correspondre à un nombre entier de périodes d’observation.');
    f('first').setCustomValidity(!f('autocall').checked || Number(f('first').value) <= mois ? '' : 'Le premier rappel ne peut pas être après la maturité.');
  }
  function majAutocall() {
    const actif = f('autocall').checked;
    f('first').disabled = !actif;
    f('first').parentElement.hidden = !actif;
    document.querySelector('label[for="ac-plain-barrier"]').textContent = actif ? 'Rappel et coupon final (%)' : 'Seuil du coupon final (%)';
    validerDates();
  }
  f('protection').addEventListener('change', () => { f('ki').disabled = !f('protection').checked; });
  ['freq', 'months', 'first'].forEach(id => f(id).addEventListener('input', validerDates));
  f('autocall').addEventListener('change', majAutocall);
  majAutocall();

  function afficher(d) {
    const rappel = d.has_autocall !== false;
    const lignes = d.obs_dates.map((t, i) => {
      const derniere = i === d.obs_dates.length - 1;
      const col = derniere ? 'Maturité' : !rappel ? 'Désactivé' : t < d.first_call_date ? 'Non autorisé' : fmtPct(d.proba_rappel_par_date_pct[i]);
      return `<tr><td>${fmt(t)} ans</td><td>${fmtPct(d.coupon_pct * (i + 1))}</td><td>${col}</td></tr>`;
    }).join('');
    const marqueurs = [{x: d.niveaux.coupon, label: rappel ? 'Rappel / coupon final' : 'Coupon final', color: '#14213d'},
      ...(d.niveaux.protection === null ? [] : [{x: d.niveaux.protection, label: 'Protection', color: '#b3261e'}])];
    $('st-results').innerHTML = metriquesStructure(d)
      + carte(rappel ? 'Remboursement à maturité' : 'Remboursement à maturité (sans rappel)', renderChart(d.ST_grid,
          [{key: 'payoff', values: d.payoff}, {key: 'pnl', values: d.pnl}], [], {
            labels: {payoff: 'Remboursement à maturité', pnl: 'Gain ou perte vs montant investi'},
            xLabel: 'Prix du sous-jacent à maturité (même unité que le spot)', markers: marqueurs,
            aria: 'Remboursement de l’Athéna à maturité'}) +
        '<p class="chart-note">Cas où le produit n’a pas été rappelé avant maturité. Tous les coupons accumulés sont versés si le seuil final est atteint, sinon aucun. Montants non actualisés.</p>')
      + carte('Calendrier des observations', `<table class="tbl"><thead><tr><th>Date</th><th>Coupon accumulé</th><th>Rappel à cette date</th></tr></thead><tbody>${lignes}</tbody></table>
          <p class="chart-note">Le coupon accumulé est conditionnel au remboursement : ce tableau ne représente pas des coupons versés à chaque date. ${d.remboursement_moyen_si_perte_pct === null ? 'Aucune perte de capital dans les simulations.' : 'Capital moyen remboursé en cas de perte : ' + fmtPct(d.remboursement_moyen_si_perte_pct) + '.'} ${fmtNb(d.n_simulations)} simulations · graine ${d.seed}.</p>`)
      + greeksCard(d.grecs, {badge: 'non calculé (bruit MC)', note: NOTE_GRECS_STRUCT});
  }

  $('form-autocall_plain').addEventListener('submit', async e => {
    e.preventDefault();
    const statut = $(p + 'status');
    validerDates();
    if (!e.target.reportValidity()) return;
    let m;
    try { m = lireMarche(); } catch (err) { return erreurStatut(statut, err); }
    const payload = {produit: 'autocall_plain', ...m, nominal: f('nominal').value, T: Number(f('months').value) / 12,
      frequence: f('freq').value, coupon: f('coupon').value, K_auto: f('barrier').value, protection: f('protection').checked,
      B_pdi: f('ki').value, has_autocall: f('autocall').checked, first_call_months: f('autocall').checked ? f('first').value : 0, avec_grecs: true};
    delete payload.methode;
    const version = selectionVersion;
    await runCalc({url: '/api/autocall', payload, bouton: e.target.querySelector('button'), statut,
      message: 'Calcul Monte Carlo en cours…', delai: 90000, onData: d => { if (version !== selectionVersion) return false; afficher(d); }});
  });
})();

// ---------- Accumulateur / décumulateur ----------
let sensAccu = 'accumulateur';
function configurerAccumulateur(sens) {
  sensAccu = sens;
  const accu = sens === 'accumulateur';
  $('acc-strike').value = accu ? 90 : 110;
  $('acc-ko').value = accu ? 105 : 95;
  $('acc-strike-label').textContent = accu ? 'Strike d’achat (%)' : 'Strike de vente (%)';
  $('acc-ko-label').textContent = accu ? 'Barrière KO haute (%)' : 'Barrière KO basse (%)';
  $('accu-desc').innerHTML = accu
    ? '<b>Accumulateur classique.</b> À chaque constat, l’investisseur achète la quantité au strike (décoté). Si le cours atteint la barrière KO, le contrat s’arrête ; sous le strike, il achète <b>levier ×</b> la quantité. Valorisation Monte Carlo, constats observés un à un.'
    : '<b>Décumulateur classique</b> (miroir de l’accumulateur). À chaque constat, l’investisseur vend la quantité au strike (majoré). Si le cours atteint la barrière KO basse, le contrat s’arrête ; au-dessus du strike, il vend <b>levier ×</b> la quantité.';
  verifierAccu();
}
function verifierAccu() {
  const k = Number($('acc-strike').value), ko = Number($('acc-ko').value), accu = sensAccu === 'accumulateur';
  $('acc-ko').setCustomValidity(accu ? (k < ko && ko > 100 ? '' : 'Accumulateur : strike < barrière KO, et KO au-dessus de 100 %.')
                                     : (k > ko && ko < 100 ? '' : 'Décumulateur : strike > barrière KO, et KO sous 100 %.'));
}
(function () {
  ['acc-strike', 'acc-ko'].forEach(id => $(id).addEventListener('input', verifierAccu));
  const vide = '<p class="chart-note">';
  $('form-accu').addEventListener('submit', async e => {
    e.preventDefault();
    const statut = $('acc-status');
    verifierAccu();
    if (!e.target.reportValidity()) return;
    let m;
    try { m = lireMarche(); } catch (err) { return erreurStatut(statut, err); }
    const payload = {...m, sens: sensAccu, T: Number($('acc-months').value) / 12, frequence: $('acc-freq').value,
      strike_pct: $('acc-strike').value, ko_pct: $('acc-ko').value, levier: $('acc-levier').value, quantite: $('acc-qte').value,
      n_garanti: $('acc-garanti').value, livraison_au_ko: $('acc-livraison').checked, zero_cout: $('acc-zero').checked, avec_grecs: true};
    delete payload.methode;
    const version = selectionVersion;
    await runCalc({url: '/api/accumulateur', payload, bouton: e.target.querySelector('button'), statut,
      message: 'Simulation constat par constat en cours…', delai: 180000, onData: d => {
      if (version !== selectionVersion) return false;
      const accu = d.produit === 'accumulateur', S0 = d.parametres.S0;
      const zc = d.strike_zero_cout_pct == null ? '— (case à cocher)' : `${fmtPct(d.strike_zero_cout_pct)} (≈ ${fmtMontant(S0 * d.strike_zero_cout_pct / 100)})`;
      const xs = d.proba_ko_cumulee_pct.map((_, i) => i + 1);
      $('st-results').innerHTML = metricsGrid([
        ['Valeur du contrat (investisseur)', fmtMontant(d.valeur), d.valeur >= 0 ? 'pos' : 'neg'],
        ['Valeur en % du notionnel', fmtPct(d.valeur_pct_notionnel)],
        ['Probabilité de KO', fmtPct(d.proba_ko_pct)],
        ['Durée de vie moyenne', fmtMontant(d.duree_de_vie_moyenne) + ' an(s)'],
        ['Unités moyennes échangées', `${fmtNb(d.unites_moyennes)} / ${fmtNb(d.unites_max_sans_ko)}`],
        ['Probabilité d’entrer en zone de levier', fmtPct(d.proba_levier_pct)],
        [accu ? 'Strike d’achat' : 'Strike de vente', fmtMontant(d.strike)],
        ['Barrière KO', fmtMontant(d.barriere_ko)],
        ['Strike « zéro coût »', zc, 'small'],
      ]) + carte('Gain par constat selon le cours', renderChart(d.S_grid, [{key: 'pnl', values: d.gain_par_constat}], [], {
          labels: {pnl: 'Gain par constat'}, xLabel: 'Cours au constat',
          markers: [{x: d.strike, label: 'Strike', color: '#3d4a63'}, {x: d.barriere_ko, label: 'KO', color: '#b3261e'}],
          aria: 'Gain par constat de l’accumulateur'}) +
        `<p class="chart-note">Au-delà de la barrière KO le contrat s’arrête (rien n’est livré ce jour-là, sauf option « livraison le jour du KO »). Dans la zone adverse, le gain est multiplié par le levier.</p>`)
        + carte('Probabilité de KO cumulée', renderChart(xs, [{key: 'payoff', values: d.proba_ko_cumulee_pct, color: '#b3261e'}], [], {
          labels: {payoff: 'Probabilité de KO cumulée (%)'}, xLabel: `Constat n° (${d.n_constats} au total)`, fillKey: 'none',
          yMin: 0, yMax: 100,
          aria: 'Probabilité de KO cumulée'}) +
        `<p class="chart-note">Valeur négative = le contrat coûte à l’investisseur à la signature : l’émetteur se rémunère par le levier et le KO. Un contrat « zéro coût » vaut 0. ${fmtNb(d.n_simulations)} simulations, intervalle de confiance 95 % de la valeur : ${fmtMontant(d.ic95[0])} à ${fmtMontant(d.ic95[1])}.</p>`)
        + greeksCard(d.grecs, {badge: 'non calculé (bruit MC)',
          note: 'Grecs en monnaie par différences finies (mêmes tirages) : le delta se lit comme un nombre d’actions équivalent. Theta = un constat de moins, hors flux déjà encaissés. Lambda n’a pas de sens ici (le contrat vaut ~0 par construction).'});
    }});
  });
})();

// ---------- DRA Daily ----------
(function () {
  $('form-dra').addEventListener('submit', async e => {
    e.preventDefault();
    const statut = $('dra-status');
    const bas = Number($('dra-low').value), haut = Number($('dra-high').value);
    $('dra-high').setCustomValidity(bas < haut ? '' : 'La borne haute doit être supérieure à la borne basse.');
    if (!e.target.reportValidity()) return;
    let m;
    try { m = lireMarche(); } catch (err) { return erreurStatut(statut, err); }
    const payload = {...m, nominal: $('dra-nominal').value, T: Number($('dra-months').value) / 12,
      borne_basse_pct: bas, borne_haute_pct: haut, coupon_annuel: $('dra-coupon').value,
      frequence_paiement: $('dra-freq').value, avec_grecs: true};
    const version = selectionVersion;
    await runCalc({url: '/api/dra', payload, bouton: e.target.querySelector('button'), statut,
      message: 'Calcul en cours…', delai: 180000, onData: d => {
      if (version !== selectionVersion) return false;
      const mc = d.methode === 'mc';
      const marge = d.marge_emetteur_pct;
      const lignes = d.dates_paiement.map((t, i) => `<tr><td>${fmt(t)} an(s)</td><td>${fmtPct(d.presence_par_periode_pct[i])}</td><td>${fmtPct(d.coupons_espere_par_periode_pct[i])}</td></tr>`).join('');
      const taux = d.coupon_par_jour.map(v => v * 252 * 100);
      $('st-results').innerHTML = metricsGrid([
        ['Prix théorique', fmtPct(d.prix_pct)],
        ['Valeur pour le montant investi', fmtMontant(d.prix)],
        ['Marge émetteur', fmtPct(marge), marge >= 0 ? 'pos' : 'neg'],
        ['Capital garanti (valeur actualisée)', fmtPct(d.valeur_capital_pct)],
        ['Valeur des coupons', fmtPct(d.valeur_coupons_pct)],
        ['Présence moyenne dans la fourchette', fmtPct(d.presence_moyenne_pct)],
        ['Coupon annualisé espéré', fmtPct(d.coupon_annualise_espere_pct)],
        ['Probabilité de n’avoir aucun coupon', d.proba_coupon_nul_pct == null ? '— (Monte Carlo)' : fmtPct(d.proba_coupon_nul_pct)],
        ['Méthode', mc ? `Monte Carlo · ${fmtNb(d.n_simulations)} trajectoires · IC 95 % ${fmtPct(d.ic95_pct[0])} – ${fmtPct(d.ic95_pct[1])}` : 'Black-Scholes · somme de probabilités digitales', 'small'],
      ]) + carte('Coupon accumulé selon le cours du jour', renderChart(d.S_grid, [{key: 'pnl', values: taux}], [], {
          labels: {pnl: 'Coupon annualisé accumulé ce jour-là (%)'}, xLabel: 'Cours du sous-jacent un jour d’observation',
          markers: [{x: d.borne_basse, label: 'Borne basse', color: '#3d4a63'}, {x: d.borne_haute, label: 'Borne haute', color: '#3d4a63'}],
          aria: 'Coupon accumulé selon le cours'}) +
        `<p class="chart-note">Chaque jour d’observation (${d.n_observations} au total) passé dans la fourchette accumule 1/252 du coupon annuel. Le capital est remboursé à 100 % à maturité.</p>`)
        + carte('Calendrier des paiements', `<table class="tbl"><thead><tr><th>Paiement à</th><th>Présence attendue dans la fourchette</th><th>Coupon espéré</th></tr></thead><tbody>${lignes}</tbody></table>`)
        + greeksCard(d.grecs, {note: 'Prix en points de nominal pour un spot de référence de 100 : delta pour +1 % de spot, vega pour +1 point de volatilité, theta par jour, rho pour +1 point de taux. '
          + (mc ? 'Différences finies sur les mêmes tirages ; les grecs d’ordre 3 ne sont disponibles qu’en Black-Scholes.' : 'Formule fermée dérivée numériquement : les 13 grecs sont disponibles.')});
    }});
  });
})();

afficherProduit();
