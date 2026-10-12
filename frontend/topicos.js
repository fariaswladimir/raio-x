// Painel "Tópicos" (15.7 / 7.4) na sub-aba Temático: LDA (Gibbs), NMF e LSA com coerência (UMass, NPMI, C_v),
// cartões com palavras dimensionadas pelo peso, mapa tópico × ano/grupo, trechos com página e varredura de K.
// Usa $, esc, api, fmtNum, slugAtual (app.js), rx, rxUrl, SUBS, CARREGADORES (raiox.js) e SVG_NS (textometria.js).
// Clicar numa palavra seleciona o termo nos demais painéis (o clique em .termo é tratado em raiox.js).

const tp = { r: null, params: null, seq: 0, seqV: 0, varr: null };
const corTopico = (j) => `var(--c${(j % 8) + 1})`;

function paramsTopicos() {
  return tp.params || {}; // 1ª carga: parâmetros do projeto (o servidor reaproveita o instantâneo da etapa)
}

function lerControlesTopicos() {
  tp.params = {
    modelo: $('#tp-modelo').value,
    k: Math.min(40, Math.max(2, +$('#tp-k').value || 8)),
    unidade: $('#tp-unidade').value,
    iteracoes: Math.min(20000, Math.max(10, +$('#tp-it').value || 1000)),
  };
  if ($('#tp-perp').checked && tp.params.modelo === 'lda') tp.params.perplexidade = true;
}

function palavrasDoTopico(t, lista, cor) {
  const max = Math.max(...lista.map((w) => Math.abs(w.peso)), 1e-12);
  return lista.map((w) => {
    const tam = 11 + 11 * Math.sqrt(Math.abs(w.peso) / max);
    const sel = rx.termos.includes(w.termo) ? ' sel' : '';
    return `<span class="termo tp-pal${sel}" data-term="${esc(w.termo)}" data-por="lema" style="font-size:${tam.toFixed(1)}px;color:${cor}" title="peso ${fmtNum(w.peso, 4)}">${esc(w.termo)}</span>`;
  }).join(' ');
}

function renderCartoes() {
  const r = tp.r;
  const pct = r.pesos_sao_proporcoes;
  $('#tp-cartoes').innerHTML = r.topicos.map((t, j) => `<div class="tp-cartao" style="border-top-color:${corTopico(j)}">
    <div class="tp-cab"><b style="color:${corTopico(j)}">Tópico ${t.id}</b>
      <span class="discreto">${pct ? `${fmtNum(100 * t.prevalencia, 1)}% do corpus` : `${fmtNum(100 * t.prevalencia, 1)}% da variância`}</span></div>
    <div class="tp-palavras">${palavrasDoTopico(t, t.palavras, corTopico(j))}</div>
    ${t.palavras_negativas ? `<div class="tp-palavras tp-neg"><span class="discreto">polo negativo:</span> ${palavrasDoTopico(t, t.palavras_negativas, 'var(--suave)')}</div>` : ''}
    <div class="discreto tp-coer">C_v ${fmtNum(t.coerencia.cv, 3)} · NPMI ${fmtNum(t.coerencia.npmi, 3)} · UMass ${fmtNum(t.coerencia.umass, 2)}</div>
    <div class="discreto tp-docs">${t.documentos.slice(0, 3).map((d) => `${esc(d.rotulo)} (${pct ? fmtNum(100 * d.peso, 0) + '%' : fmtNum(d.peso, 2)})`).join(' · ')}</div>
  </div>`).join('');
}

function renderMapa() {
  const r = tp.r, ag = r[$('#tp-part').value];
  if (!ag || !ag.partes.length) { $('#tp-mapa').innerHTML = '<p class="discreto">Sem partes.</p>'; return; }
  const max = Math.max(...ag.matriz.flat().map(Math.abs), 1e-12);
  const pct = r.pesos_sao_proporcoes;
  const cel = (v) => {
    const a = Math.round(100 * Math.abs(v) / max);
    const base = v >= 0 ? 'var(--destaque)' : 'var(--erro)';
    return `<td class="tp-cel" style="background:color-mix(in srgb, ${base} ${a}%, transparent)" title="${pct ? fmtNum(100 * v, 1) + '%' : fmtNum(v, 3)}">${pct ? fmtNum(100 * v, 0) : fmtNum(v, 2)}</td>`;
  };
  $('#tp-mapa').innerHTML = `<table class="tp-tab"><thead><tr><th>Tópico</th>${ag.partes.map((p, i) => `<th title="${ag.n_documentos[i]} doc.">${esc(p)}<br><span class="discreto">n=${ag.n_documentos[i]}</span></th>`).join('')}</tr></thead>
    <tbody>${r.topicos.map((t, j) => `<tr><th style="color:${corTopico(j)}" title="${esc(t.palavras.slice(0, 5).map((w) => w.termo).join(', '))}">${t.id} · ${esc(t.palavras.slice(0, 3).map((w) => w.termo).join(', '))}</th>${ag.matriz[j].map(cel).join('')}</tr>`).join('')}</tbody></table>
    <p class="discreto">${pct ? 'Proporção média do tópico (%) nos documentos de cada parte.' : 'Coordenada média (LSA: não é proporção; vermelho = negativo).'} ${esc(r.nota_agregacao)}</p>`;
}

function renderTrechos() {
  const r = tp.r;
  $('#tp-trechos').innerHTML = r.topicos.map((t, j) => `<details class="rn-det"${j < 2 ? ' open' : ''}>
    <summary><b style="color:${corTopico(j)}">Tópico ${t.id}</b> <span class="discreto">${esc(t.palavras.slice(0, 5).map((w) => w.termo).join(', '))}</span></summary>
    ${t.trechos.length ? t.trechos.map((s) => `<div class="rn-seg" style="border-color:${corTopico(j)}">
      <span class="discreto">${esc(s.rotulo)}, p. ${s.pagina ?? '?'} · ${fmtNum(s.peso, 3)}</span><br>${esc(s.texto)}</div>`).join('') : '<p class="discreto">Sem trecho com tokens suficientes.</p>'}
  </details>`).join('');
}

function renderTopicos() {
  const r = tp.r;
  $('#tp-modelo').value = r.modelo; $('#tp-k').value = r.k; $('#tp-unidade').value = r.unidade; $('#tp-it').value = r.iteracoes;
  const aj = r.ajuste || {};
  const extra = r.modelo === 'lda' ? ` · alfa ${fmtNum(aj.alpha, 2)}, beta ${aj.beta}, aquecimento ${aj.burn_in}, ${aj.amostras} amostras` :
    r.modelo === 'nmf' ? ` · ${aj.iteracoes_usadas} iterações, erro relativo ${fmtNum(aj.erro_relativo, 3)}` : '';
  $('#tp-info').textContent = `(${r.modelo.toUpperCase()} · K = ${r.k} · ${fmtNum(r.n_unidades)} ${r.unidade === 'segmento' ? 'segmentos' : 'documentos'} · ${fmtNum(r.n_termos)} termos · ${fmtNum(r.n_tokens)} tokens · semente ${r.semente}${extra})`;
  const m = r.coerencia_media;
  $('#tp-coer').innerHTML = [`<span class="chip">C_v médio <b>${fmtNum(m.cv, 3)}</b></span>`, `<span class="chip">NPMI médio <b>${fmtNum(m.npmi, 3)}</b></span>`,
    `<span class="chip">UMass médio <b>${fmtNum(m.umass, 2)}</b></span>`,
    r.perplexidade ? `<span class="chip" title="${esc(r.perplexidade.metodo)}">perplexidade <b>${fmtNum(r.perplexidade.valor, 1)}</b> (${r.perplexidade.documentos_teste} doc. retidos)</span>` : ''].join('');
  $('#tp-aviso').hidden = !r.avisos.length;
  $('#tp-aviso').textContent = r.avisos.join(' ');
  renderCartoes(); renderMapa(); renderTrechos();
}

async function carregarTopicos() {
  if (!slugAtual || !rx.resumo) return;
  const seq = ++tp.seq;
  const p = paramsTopicos();
  $('#tp-csv-pal').href = rxUrl('topicos/palavras.csv', p);
  $('#tp-csv-doc').href = rxUrl('topicos/documentos.csv', p);
  $('#tp-info').textContent = (p.modelo || 'lda') === 'lda' ? '(calculando… o LDA com 1000 iterações pode levar 1 a 2 minutos)' : '(calculando…)';
  try {
    const r = await api(rxUrl('topicos', p));
    if (seq !== tp.seq) return;
    tp.r = r;
    renderTopicos();
  } catch (e) {
    if (seq !== tp.seq) return;
    tp.r = null;
    for (const id of ['#tp-cartoes', '#tp-mapa', '#tp-trechos', '#tp-coer']) $(id).innerHTML = '';
    $('#tp-info').textContent = '';
    $('#tp-aviso').hidden = false; $('#tp-aviso').textContent = e.message;
  }
}

// ---------- varredura de K ----------

function miniGrafico(linhas, campo, titulo, melhorMaior) {
  const pts = linhas.filter((l) => l[campo] != null);
  if (!pts.length) return '';
  const W = 230, H = 130, ml = 42, mr = 8, mt = 18, mb = 22;
  const ks = linhas.map((l) => l.k), vs = pts.map((l) => l[campo]);
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (hi - lo < 1e-9) { lo -= 0.5; hi += 0.5; }
  const sx = (k) => ml + (W - ml - mr) * (k - ks[0]) / Math.max(1, ks[ks.length - 1] - ks[0]);
  const sy = (v) => mt + (H - mt - mb) * (1 - (v - lo) / (hi - lo));
  const melhor = pts.reduce((a, b) => ((melhorMaior ? b[campo] > a[campo] : b[campo] < a[campo]) ? b : a));
  const caminho = pts.map((l, i) => `${i ? 'L' : 'M'}${sx(l.k).toFixed(1)} ${sy(l[campo]).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" xmlns="${SVG_NS}" class="tp-mini" role="img" aria-label="${esc(titulo)} por K">
    <text x="${ml}" y="12" font-size="11" fill="var(--texto)" font-weight="600">${esc(titulo)}</text>
    <text x="${ml - 4}" y="${sy(hi) + 4}" font-size="9" text-anchor="end" fill="var(--suave)">${fmtNum(hi, 2)}</text>
    <text x="${ml - 4}" y="${sy(lo) + 4}" font-size="9" text-anchor="end" fill="var(--suave)">${fmtNum(lo, 2)}</text>
    <line x1="${ml}" x2="${W - mr}" y1="${H - mb}" y2="${H - mb}" stroke="var(--borda)"/>
    ${ks.map((k) => `<text x="${sx(k)}" y="${H - 8}" font-size="9" text-anchor="middle" fill="var(--suave)">${k}</text>`).join('')}
    <path d="${caminho}" fill="none" stroke="var(--destaque)" stroke-width="1.6"/>
    ${pts.map((l) => `<circle cx="${sx(l.k)}" cy="${sy(l[campo])}" r="${l === melhor ? 4 : 2.5}" fill="${l === melhor ? 'var(--c2)' : 'var(--destaque)'}"><title>K = ${l.k}: ${fmtNum(l[campo], 3)}</title></circle>`).join('')}
  </svg>`;
}

async function varrerTopicos() {
  if (!slugAtual) return;
  const seq = ++tp.seqV;
  const p = { modelo: $('#tp-v-modelo').value, k_min: +$('#tp-v-min').value || 3, k_max: +$('#tp-v-max').value || 12,
    unidade: $('#tp-unidade').value, iteracoes: +$('#tp-v-it').value || 200 };
  $('#tp-csv-var').href = rxUrl('topicos/varredura.csv', p);
  $('#tp-varredura').innerHTML = `<p class="discreto">Calculando ${p.k_max - p.k_min + 1} modelos${p.modelo === 'lda' ? ' (LDA + perplexidade: alguns minutos)' : ''}…</p>`;
  try {
    const r = await api(rxUrl('topicos/varredura', p));
    if (seq !== tp.seqV) return;
    tp.varr = r;
    $('#tp-varredura').innerHTML = `<div class="tp-minis">${miniGrafico(r.linhas, 'cv', 'C_v (maior é melhor)', true)}${miniGrafico(r.linhas, 'npmi', 'NPMI (maior é melhor)', true)}
      ${miniGrafico(r.linhas, 'umass', 'UMass (mais perto de 0 é melhor)', true)}${miniGrafico(r.linhas, 'perplexidade', 'Perplexidade (menor é melhor)', false)}</div>
      <p class="discreto">${esc(r.nota)} ${fmtNum(r.n_unidades)} unidades, ${fmtNum(r.n_termos)} termos, ${r.iteracoes} iterações, semente ${r.semente}.</p>`;
  } catch (e) {
    if (seq !== tp.seqV) return;
    $('#tp-varredura').innerHTML = `<p class="vazio">${esc(e.message)}</p>`;
  }
}

$('#tp-calcular').addEventListener('click', () => { lerControlesTopicos(); carregarTopicos(); });
$('#tp-part').addEventListener('change', () => { if (tp.r) renderMapa(); });
$('#tp-varrer').addEventListener('click', varrerTopicos);

// A seleção vinda de outros painéis já realça os .termo de #raiox (atualizarSelecao em raiox.js).

// Registro na sub-aba Temático (carga preguiçosa de raiox.js), sem editar raiox.js.
if (typeof SUBS !== 'undefined' && SUBS.tematico && !SUBS.tematico.includes('top')) {
  SUBS.tematico.push('top');
  CARREGADORES.top = () => carregarTopicos();
}
