// Painel "Estilometria" (15.6) em Análises > Comparativo: Delta de Burrows e variantes, dendrograma, consenso entre faixas
// de MFW, mapa PCA (com cargas) ou MDS, vizinhos e perfil de estilo. Injetado por este arquivo (o HTML só carrega o script).
// Usa $, esc, api, fmtNum, slugAtual (app.js), rx, rxUrl, SUBS, CARREGADORES (raiox.js) e marcadorSvg (similaridade.js).

const es = { r: null, seq: 0, doc: null };
const ES_DIST = [['delta_classico', 'Delta clássico (Burrows)'], ['cosine_delta', 'Cosine Delta (Würzburg)'], ['argamon', 'Delta quadrático (Argamon)'],
  ['eder', 'Delta de Eder'], ['eder_simples', 'Delta simples de Eder'], ['cosseno', 'Cosseno das frequências']];
const ES_MFW = [50, 100, 200, 300, 400, 500, 750, 1000];
const esCor = (c) => `var(--c${((c - 1) % 8) + 1})`;
const ES_FORMAS = ['circulo', 'quadrado', 'triangulo', 'losango', 'cruz', 'estrela'];

function montarPainelEstilometria() {
  if ($('#p-estilo') || !$('#p-simil')) return;
  const p = document.createElement('div');
  p.className = 'painel larga'; p.id = 'p-estilo'; p.dataset.sub = 'comparativo';
  p.innerHTML = `
    <div class="p-cab"><b>Estilometria (Delta)</b> <span class="discreto p-info" id="es-info"></span>
      <span class="p-ctl"><a class="botao sec peq" id="es-csv-d" download="estilometria_distancias.csv" href="#">Distâncias CSV</a>
        <a class="botao sec peq" id="es-csv-c" download="estilometria_cargas.csv" href="#">Cargas CSV</a>
        <a class="botao sec peq" id="es-csv-u" download="estilometria_unidades.csv" href="#">Unidades CSV</a></span></div>
    <div class="p-corpo livre">
      <p class="es-aviso" id="es-cuidado" role="note"><b>Cuidado:</b> neste corpus os documentos têm muitos autores, gêneros (artigo, relatório, capítulo) e mais de um idioma.
        A distância estilométrica reflete sobretudo gênero/registro, idioma e tradução, <b>não autoria</b>; atribuição de autoria está fora do escopo.</p>
      <p class="barra">
        <label class="inline">Distância <select id="es-dist">${ES_DIST.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select></label>
        <label class="inline">MFW <input type="range" id="es-mfw" min="0" max="${ES_MFW.length - 1}" step="1" value="1" aria-label="Número de palavras mais frequentes">
          <output id="es-mfw-v">100</output></label>
        <label class="inline" title="Palavra precisa aparecer em pelo menos esta % das unidades">Culling %
          <input type="number" id="es-cull" min="0" max="100" step="10" value="0" class="curto"></label>
        <label class="inline">Unidade <select id="es-unid"><option value="documento">documento</option><option value="amostra">amostras de tamanho fixo</option></select></label>
        <label class="inline" id="es-tam-l" hidden>Tokens/amostra <input type="number" id="es-tam" min="500" max="20000" step="500" value="2000" class="curto"></label>
        <label class="inline">Ligação <select id="es-met"><option value="ward">Ward (ward.D, como o stylo)</option><option value="average">média (UPGMA)</option></select></label>
        <label class="inline">Grupos (k) <select id="es-k"><option value="">automático</option>${[2, 3, 4, 5, 6, 7, 8].map((k) => `<option>${k}</option>`).join('')}</select></label>
        <label class="inline">Cor <select id="es-cor"><option value="cluster">grupo estilométrico</option><option value="grupo">grupo (metadado)</option><option value="ano">ano</option><option value="idioma">idioma</option></select></label>
        <button id="es-calcular" type="button">Calcular</button>
      </p>
      <p id="es-msg" class="vazio" hidden></p>
      <div class="sm-grade">
        <div><h5 class="sm-tit">Dendrograma <span class="discreto" id="es-dend-info"></span></h5>
          <div class="sm-rolagem" id="es-dend" role="img" aria-label="Dendrograma estilométrico"></div></div>
        <div><h5 class="sm-tit">Mapa <select id="es-mapa-tipo" aria-label="Tipo de mapa"><option value="pca">PCA (correlação)</option><option value="pcacov">PCA (covariância)</option><option value="mds">MDS da distância</option></select>
          <label class="es-chk discreto"><input type="checkbox" id="es-cargas"> cargas</label> <span class="discreto" id="es-mapa-info"></span></h5>
          <div id="es-mapa" class="sm-mapa" role="img" aria-label="Mapa dos documentos"></div><div id="es-legenda" class="chips"></div>
          <div id="es-cargas-tab" class="es-cargas" hidden></div></div>
      </div>
      <div class="sm-grade">
        <div><h5 class="sm-tit">Consenso entre faixas de MFW <span class="discreto" id="es-cons-info"></span></h5>
          <div class="rolagem"><table id="tab-es-grupos"></table></div>
          <div class="rolagem es-alta"><table id="tab-es-pares"></table></div></div>
        <div><h5 class="sm-tit">Vizinhos mais próximos de <select id="es-doc" aria-label="Documento de referência"></select></h5>
          <div class="rolagem"><table id="tab-es-viz"></table></div>
          <h5 class="sm-tit">Perfil de estilo (palavras funcionais vs. corpus)</h5><div id="es-perfil"></div></div>
      </div>
      <div id="es-dica" class="dica" hidden></div>
      <p class="discreto">Atributos: as N palavras mais frequentes (MFW) pela forma em minúsculas, <b>com</b> palavras vazias (as funcionais são o sinal), só do corpo e sem ruído.
        Frequências relativas (%) e escores z com desvio-padrão amostral. Delta clássico = média de |Δz|; Argamon = euclidiana dos z / N; Eder = |Δz| ponderado por (N − i + 2)/N;
        Eder simples = Manhattan de √f; Cosine Delta = 1 − cosseno dos z. Definições do stylo (R) 0.7.71, conferidas numericamente. Consenso: uma árvore por faixa de MFW
        (100, 200, …, 500), como aproximação da árvore de consenso de Eder (2017); não é reamostragem. Amostras de tamanho fixo comparam textos de extensões diferentes.</p>
    </div>`;
  $('#p-simil').parentNode.insertBefore(p, ($('#p-agr') || $('#p-simil')).nextSibling);
  $('#es-mfw').addEventListener('input', () => { $('#es-mfw-v').textContent = ES_MFW[+$('#es-mfw').value]; });
  for (const id of ['#es-dist', '#es-mfw', '#es-unid', '#es-met', '#es-k']) $(id).addEventListener('change', carregarEstilometria);
  $('#es-unid').addEventListener('change', () => { $('#es-tam-l').hidden = $('#es-unid').value !== 'amostra'; });
  $('#es-calcular').addEventListener('click', carregarEstilometria);
  $('#es-mapa-tipo').addEventListener('change', () => ($('#es-mapa-tipo').value === 'pcacov' || es.r?.pca.tipo === 'covariancia') ? carregarEstilometria() : desenharEstilo());
  for (const id of ['#es-cor', '#es-cargas']) $(id).addEventListener('change', desenharEstilo);
  $('#es-doc').addEventListener('change', () => { es.doc = +$('#es-doc').value; renderVizinhosEstilo(); });
  for (const alvo of ['#es-mapa', '#es-dend']) {
    $(alvo).addEventListener('mousemove', (ev) => {
      const el = ev.target.closest('[data-i]'), dica = $('#es-dica');
      const u = el && es.r ? es.r.unidades[+el.dataset.i] : null;
      if (!u) { dica.hidden = true; return; }
      dica.hidden = false;
      const v = u.vizinhos[0] ? `<br>mais próximo: ${esc(u.vizinhos[0].rotulo)} (${fmtNum(u.vizinhos[0].distancia, 3)})` : '';
      dica.innerHTML = `<b>${esc(u.rotulo)}</b><br>grupo ${u.cluster} · ${esc(u.grupo)} · ${esc(u.ano)} · ${esc(u.idioma)} · ${fmtNum(u.tokens)} tokens${v}`;
      dica.style.left = Math.min(ev.clientX + 14, window.innerWidth - 270) + 'px';
      dica.style.top = Math.min(ev.clientY + 14, window.innerHeight - 90) + 'px';
    });
    $(alvo).addEventListener('mouseleave', () => { $('#es-dica').hidden = true; });
  }
}

function paramsEstilometria() {
  const p = { distancia: $('#es-dist').value, mfw: ES_MFW[+$('#es-mfw').value], culling: $('#es-cull').value || 0, unidade: $('#es-unid').value,
    metodo: $('#es-met').value, pca: $('#es-mapa-tipo').value === 'pcacov' ? 'covariancia' : 'correlacao' };
  if (p.unidade === 'amostra') p.tamanho_amostra = $('#es-tam').value || 2000;
  if ($('#es-k').value) p.k = $('#es-k').value;
  return p;
}

// Cor de cada unidade conforme o seletor (grupo estilométrico ou metadado); devolve [função, legenda].
function coresEstilo() {
  const r = es.r, modo = $('#es-cor').value;
  if (modo === 'cluster') {
    const ks = [...new Set(r.unidades.map((u) => u.cluster))].sort((a, b) => a - b);
    return [(u) => esCor(u.cluster), ks.map((k) => [esCor(k), `grupo ${k}`])];
  }
  const vals = [...new Set(r.unidades.map((u) => String(u[modo])))].sort();
  const f = (u) => esCor(vals.indexOf(String(u[modo])) + 1);
  return [f, vals.map((v, i) => [esCor(i + 1), v])];
}

function desenharDendroEstilo() {
  const alvo = $('#es-dend'), r = es.r;
  const n = r.unidades.length, dend = r.dendrograma, passo = 16, mt = 8, ml = 8, largPlot = 300, largRotulo = 200;
  const W = ml + largPlot + largRotulo, H = mt * 2 + n * passo;
  const [cor] = coresEstilo();
  const y = [], x = [], gr = [];
  dend.ordem_folhas.forEach((idx, pos) => { y[idx] = mt + pos * passo + passo / 2; x[idx] = 0; gr[idx] = new Set([r.unidades[idx].cluster]); });
  const hmax = Math.max(...dend.fusoes.map((f) => f.altura), 1e-9), px = (h) => ml + (1 - h / hmax) * largPlot;
  const linhas = dend.fusoes.map((f, i) => {
    const id = n + i; y[id] = (y[f.esquerda] + y[f.direita]) / 2; x[id] = f.altura; gr[id] = new Set([...gr[f.esquerda], ...gr[f.direita]]);
    const c = gr[id].size === 1 ? esCor([...gr[id]][0]) : 'var(--suave)';
    return `<path d="M${px(x[f.esquerda]).toFixed(1)},${y[f.esquerda]} H${px(f.altura).toFixed(1)} V${y[f.direita]} H${px(x[f.direita]).toFixed(1)}" fill="none" stroke="${c}" stroke-width="1.4"><title>altura ${fmtNum(f.altura, 3)} · ${f.tamanho} unidades</title></path>`;
  });
  let corte = '';
  if (dend.altura_corte != null) { const xc = px(dend.altura_corte).toFixed(1); corte = `<line x1="${xc}" x2="${xc}" y1="${mt - 4}" y2="${H - mt + 4}" stroke="var(--suave)" stroke-dasharray="4 3"/>`; }
  const rot = dend.ordem_folhas.map((idx) => {
    const u = r.unidades[idx];
    return `<g data-i="${idx}"><circle cx="${ml + largPlot}" cy="${y[idx]}" r="3.5" fill="${cor(u)}"/><text x="${ml + largPlot + 8}" y="${y[idx] + 4}" font-size="11" fill="${cor(u)}" font-weight="600">${esc(u.rotulo)}</text></g>`;
  });
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg" style="display:block">${linhas.join('')}${corte}${rot.join('')}</svg>`;
  $('#es-dend-info').textContent = `(${r.metodo === 'ward' ? 'Ward' : 'média'} · k = ${r.k}${r.k_automatico ? ' automático' : ''}${r.silhueta != null ? ` · silhueta ${fmtNum(r.silhueta, 2)}` : ''})`;
}

function desenharMapaEstilo() {
  const r = es.r, alvo = $('#es-mapa'), mds = $('#es-mapa-tipo').value === 'mds', comCargas = !mds && $('#es-cargas').checked;
  const [cor, leg] = coresEstilo();
  const W = 520, H = 380, m = 30;
  const xs = r.unidades.map((u) => (mds ? u.mx : u.x)), ys = r.unidades.map((u) => (mds ? u.my : u.y));
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const sx = (v) => m + ((v - x0) / ((x1 - x0) || 1)) * (W - 2 * m), sy = (v) => H - m - ((v - y0) / ((y1 - y0) || 1)) * (H - 2 * m);
  const gs = [...new Set(r.unidades.map((u) => u.grupo))].sort();
  const pts = r.unidades.map((u, i) => `<g data-i="${i}">${marcadorSvg(ES_FORMAS[Math.max(0, gs.indexOf(u.grupo)) % ES_FORMAS.length], +sx(xs[i]).toFixed(1), +sy(ys[i]).toFixed(1), 5.5,
    { fill: cor(u), 'fill-opacity': 0.85, stroke: 'var(--painel)', 'stroke-width': 1.1 })}</g>`);
  let setas = '';
  if (comCargas) {  // biplot: as 12 palavras de maior carga em cada eixo, como setas a partir do centro do mapa
    const pal = new Map();
    for (const c of r.pca.cargas) for (const it of [...c.positivas, ...c.negativas]) pal.set(it.palavra, true);
    const todas = r.pca.cargas_todas.filter((c) => pal.has(c.palavra));
    const lmax = Math.max(...todas.map((c) => Math.hypot(c.pc1, c.pc2)), 1e-9), esc0 = Math.min(W, H) * 0.4 / lmax;
    const cx = sx(0), cy = sy(0);
    setas = todas.map((c) => { const ex = cx + c.pc1 * esc0, ey = cy - c.pc2 * esc0;
      return `<line x1="${cx.toFixed(1)}" y1="${cy.toFixed(1)}" x2="${ex.toFixed(1)}" y2="${ey.toFixed(1)}" stroke="var(--suave)" stroke-width="0.8" opacity="0.7"/><text x="${ex.toFixed(1)}" y="${ey.toFixed(1)}" font-size="10" fill="var(--texto)" opacity="0.85">${esc(c.palavra)}</text>`; }).join('');
  }
  const ve = mds ? r.mds.variancia_explicada : r.pca.variancia_explicada, nome = mds ? 'Dim' : 'PC';
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" xmlns="http://www.w3.org/2000/svg" style="display:block;max-height:420px"><rect x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" fill="none" stroke="var(--borda)"/>` +
    `<text x="${W / 2}" y="${H - 8}" font-size="10" fill="var(--suave)" text-anchor="middle">${nome}1 (${fmtNum(ve[0] * 100, 1)}%)</text>` +
    `<text x="10" y="${H / 2}" font-size="10" fill="var(--suave)" text-anchor="middle" transform="rotate(-90 10 ${H / 2})">${nome}2 (${fmtNum(ve[1] * 100, 1)}%)</text>${setas}${pts.join('')}</svg>`;
  $('#es-mapa-info').textContent = mds ? '(MDS clássico da matriz de distâncias)' : `(PCA ${r.pca.tipo === 'correlacao' ? 'dos escores z' : 'das frequências'} · ${r.pca.n_palavras} palavras)`;
  $('#es-legenda').innerHTML = leg.map(([c, t]) => `<span class="chip"><i style="background:${c}"></i>${esc(t)}</span>`).join('') +
    gs.map((g) => `<span class="chip"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">${marcadorSvg(ES_FORMAS[gs.indexOf(g) % ES_FORMAS.length], 7, 7, 4.5, { fill: 'var(--suave)' })}</svg>${esc(g)}</span>`).join('');
  const tab = $('#es-cargas-tab');
  tab.hidden = mds;
  if (!mds) tab.innerHTML = r.pca.cargas.map((c) => `<div><b>PC${c.eixo}</b> <span class="discreto">+</span> ${c.positivas.slice(0, 8).map((x) => esc(x.palavra)).join(', ')}
      <br><span class="discreto">−</span> ${c.negativas.slice(0, 8).map((x) => esc(x.palavra)).join(', ')}</div>`).join('');
}

function renderConsensoEstilo() {
  const c = es.r.consenso;
  if (!c) { $('#tab-es-grupos').innerHTML = ''; $('#tab-es-pares').innerHTML = ''; $('#es-cons-info').textContent = '(faixas insuficientes)'; return; }
  $('#es-cons-info').textContent = `(${c.n_arvores} árvores: MFW ${c.bandas.join(', ')}${c.bandas_ajustadas ? ' — ajustadas ao vocabulário' : ''})`;
  $('#tab-es-grupos').innerHTML = '<thead><tr><th>Grupo</th><th>Unid.</th><th title="Fração das árvores em que exatamente este grupo forma um clado">Clado</th><th title="Fração média das árvores em que dois membros caem no mesmo grupo (corte em k)">Pares juntos</th></tr></thead><tbody>' +
    c.grupos.map((g) => `<tr><td><b style="color:${esCor(g.cluster)}">${g.cluster}</b></td><td>${g.unidades}</td><td>${g.clado == null ? '—' : fmtNum(g.clado * 100, 0) + '%'}</td><td>${g.pares_juntos == null ? '—' : fmtNum(g.pares_juntos * 100, 0) + '%'}</td></tr>`).join('') + '</tbody>';
  $('#tab-es-pares').innerHTML = '<thead><tr><th>Par</th><th>Juntos</th><th>Distância</th></tr></thead><tbody>' +
    c.pares.slice(0, 25).map((p) => `<tr><td>${esc(p.rotulo_a)} ↔ ${esc(p.rotulo_b)}</td><td>${fmtNum(p.frequencia * 100, 0)}%</td><td>${fmtNum(p.distancia, 3)}</td></tr>`).join('') + '</tbody>';
}

function renderVizinhosEstilo() {
  const r = es.r;
  const u = r.unidades.find((x) => x.i === es.doc) || r.unidades[0];
  $('#tab-es-viz').innerHTML = '<thead><tr><th>#</th><th>Unidade</th><th>Distância</th><th>Grupo</th></tr></thead><tbody>' +
    u.vizinhos.map((v, k) => `<tr><td>${k + 1}</td><td>${esc(v.rotulo)}</td><td>${fmtNum(v.distancia, 3)}</td><td style="color:${esCor(v.cluster)}">${v.cluster}</td></tr>`).join('') + '</tbody>';
  const p = r.perfis.find((x) => x.id === u.id);
  if (!p) { $('#es-perfil').innerHTML = ''; return; }
  const lista = (xs) => xs.map((x) => `<span title="z = ${fmtNum(x.z, 2)}; ${fmtNum(x.freq, 3)}% (corpus ${fmtNum(x.freq_corpus, 3)}%)">${esc(x.palavra)} <small class="discreto">${x.z > 0 ? '+' : ''}${fmtNum(x.z, 1)}</small></span>`).join(', ');
  $('#es-perfil').innerHTML = `<p class="discreto">${esc(p.rotulo)}: MFW cobrem ${fmtNum(p.cobertura_mfw * 100, 1)}% dos tokens (corpus ${fmtNum(p.cobertura_corpus * 100, 1)}%) ·
      distância média aos demais ${p.distancia_media == null ? '—' : fmtNum(p.distancia_media, 3)}</p>
    <p><b>Acima do corpus:</b> ${lista(p.acima) || '—'}</p><p><b>Abaixo do corpus:</b> ${lista(p.abaixo) || '—'}</p>`;
}

function desenharEstilo() {
  if (!es.r) return;
  desenharDendroEstilo();
  desenharMapaEstilo();
}

function renderEstilometria() {
  const r = es.r;
  $('#es-msg').hidden = true;
  $('#es-mfw-v').textContent = ES_MFW[+$('#es-mfw').value];
  const exc = r.excluidos.length ? ` · ${r.excluidos.length} excluído(s)` : '';
  const coes = r.coesao ? ` · ${fmtNum(r.coesao.vizinho_do_mesmo_documento * 100, 0)}% das amostras têm o vizinho no mesmo documento` : '';
  $('#es-info').textContent = `(${r.nome_distancia} · ${r.mfw_efetivo} MFW${r.culling ? ` · culling ${r.culling}%` : ''} · ${r.n_unidades} ${r.unidade === 'amostra' ? 'amostras' : 'documentos'}${exc}${coes})`;
  const sel = $('#es-doc');
  sel.innerHTML = r.unidades.map((u) => `<option value="${u.i}">${esc(u.rotulo)}</option>`).join('');
  if (es.doc == null || !r.unidades.some((u) => u.i === es.doc)) es.doc = r.unidades[0].i;
  sel.value = es.doc;
  const q = paramsEstilometria();
  $('#es-csv-d').href = rxUrl('estilometria/distancias.csv', q);
  $('#es-csv-c').href = rxUrl('estilometria/cargas.csv', q);
  $('#es-csv-u').href = rxUrl('estilometria/unidades.csv', q);
  desenharEstilo();
  renderConsensoEstilo();
  renderVizinhosEstilo();
}

async function carregarEstilometria() {
  montarPainelEstilometria();
  if (!slugAtual || !$('#p-estilo')) return;
  const seq = ++es.seq;
  $('#es-msg').hidden = false; $('#es-msg').textContent = 'Calculando…';
  try {
    const r = await api(rxUrl('estilometria', paramsEstilometria()));
    if (seq !== es.seq) return;
    es.r = r;
    renderEstilometria();
  } catch (e) {
    if (seq !== es.seq) return;
    limparEstilometria();
    $('#es-msg').hidden = false; $('#es-msg').textContent = e.message;
  }
}

function limparEstilometria() {
  es.r = null;
  if (!$('#p-estilo')) return;
  for (const id of ['#es-dend', '#es-mapa', '#es-legenda', '#tab-es-grupos', '#tab-es-pares', '#tab-es-viz', '#es-perfil', '#es-cargas-tab']) $(id).innerHTML = '';
  $('#es-info').textContent = '';
}

montarPainelEstilometria();
if (typeof SUBS !== 'undefined' && !SUBS.comparativo.includes('estilo')) {
  SUBS.comparativo.push('estilo');
  CARREGADORES.estilo = carregarEstilometria;
}
if (typeof limparSimilaridade === 'function') {
  const limparAnterior = window.limparSimilaridade || limparSimilaridade;
  window.limparSimilaridade = function () { limparAnterior(); limparEstilometria(); };
}
