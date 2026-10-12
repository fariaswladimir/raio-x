// Painéis "Especificidades por parte" (6.2) e "AFC" (7.3); a partição "classe" usa as classes da CHD (7.1, tematico.js).
// Usa $, esc, api, fmtNum, slugAtual (app.js) e rx, rxUrl, termoHtml, escolherTermo (raiox.js). Sem bibliotecas; SVG com var(--...).

const tx = { es: null, termo: null, termoR: null, af: null, seq: { es: 0, termo: 0, af: 0 } };
const SVG_NS = 'http://www.w3.org/2000/svg';

function fmtScore(it) {
  if (it.acima_do_teto) return it.score > 0 ? '> 50' : '< −50';
  return fmtNum(it.score, 1);
}

// ---------- especificidades ----------

function paramsEsp(extra) {
  return { particao: $('#es-part').value, por: $('#rx-por').value, vazias: $('#rx-vazias').value,
    min_freq: $('#es-min').value || 5, limiar: $('#es-limiar').value || 2, ...extra };
}

function itemEsp(it, por) {
  const dica = `f = ${fmtNum(it.f)} na parte · esperada ${fmtNum(it.esperada, 1)} · F = ${fmtNum(it.F)} no corpus · ${fmtNum(it.por_10k, 1)} por 10 mil`;
  return `<li title="${esc(dica)}">${termoHtml(it.termo, por)} <span class="es-sc ${it.score > 0 ? 'pos' : 'neg'}">${fmtScore(it)}</span></li>`;
}

function renderEspecificidades() {
  const r = tx.es;
  const por = $('#rx-por').value;
  $('#es-info').textContent = `(${r.partes.length} partes · ${fmtNum(r.termos_testados)} termos com F ≥ ${r.parametros.min_freq} · T = ${fmtNum(r.T)} palavras${r.partes_excluidas.length ? ` · ${r.partes_excluidas.length} parte(s) sem tokens` : ''})`;
  $('#es-colunas').innerHTML = r.partes.map((p) => `<div class="es-col">
      <b title="${esc(p.rotulo)}">${esc(p.rotulo)}</b><span class="discreto"> ${fmtNum(p.tokens)} palavras · ${p.n_positivas} + / ${p.n_negativas} −</span>
      <ol class="es-lista">${p.positivas.map((i) => itemEsp(i, por)).join('') || '<li class="discreto">nenhum específico positivo</li>'}</ol>
      <ol class="es-lista neg">${p.negativas.map((i) => itemEsp(i, por)).join('') || '<li class="discreto">nenhum específico negativo</li>'}</ol>
    </div>`).join('');
}

function desenharBarrasTermo() {
  const alvo = $('#es-barras'), r = tx.termoR;
  if (!r) { alvo.innerHTML = ''; return; }
  const n = r.partes.length, passo = 20, mt = 22, ml = 150, mr = 50, W = 640, H = mt + n * passo + 10;
  const max = Math.max(r.limiar * 1.5, ...r.partes.map((p) => Math.abs(p.score)));
  const meio = ml + (W - ml - mr) / 2, escala = (W - ml - mr) / 2 / max;
  const x = (v) => meio + v * escala;
  const barras = r.partes.map((p, i) => {
    const y = mt + i * passo, v = p.score, cor = p.banal ? 'var(--suave)' : (v > 0 ? 'var(--c1)' : 'var(--c2)');
    const x0 = Math.min(x(0), x(v)), w = Math.max(1, Math.abs(x(v) - x(0)));
    const rot = esc(p.rotulo.length > 24 ? p.rotulo.slice(0, 23) + '…' : p.rotulo);
    const val = p.acima_do_teto ? (v > 0 ? '> 50' : '< −50') : fmtNum(v, 1);
    return `<g><title>${esc(p.rotulo)}: score ${val} · f = ${fmtNum(p.f)} (esperada ${fmtNum(p.esperada, 1)}) · ${fmtNum(p.por_10k, 1)} por 10 mil${p.banal ? ' · banal' : ''}</title>
      <text x="${ml - 6}" y="${y + passo / 2 + 4}" font-size="11.5" text-anchor="end" fill="var(--texto)">${rot}</text>
      <rect x="${x0.toFixed(1)}" y="${y + 3}" width="${w.toFixed(1)}" height="${passo - 6}" fill="${cor}" fill-opacity="${p.banal ? 0.5 : 0.9}"/>
      <text x="${(v >= 0 ? x(v) + 4 : x(v) - 4).toFixed(1)}" y="${y + passo / 2 + 4}" font-size="10.5" text-anchor="${v >= 0 ? 'start' : 'end'}" fill="var(--suave)">${val}</text></g>`;
  });
  const ref = [-r.limiar, r.limiar].map((v) => `<line x1="${x(v).toFixed(1)}" x2="${x(v).toFixed(1)}" y1="${mt - 6}" y2="${H - 6}" stroke="var(--suave)" stroke-dasharray="4 3"/>
    <text x="${x(v).toFixed(1)}" y="${mt - 9}" font-size="10" text-anchor="${v > 0 ? 'start' : 'end'}" fill="var(--suave)">${v > 0 ? '+' : '−'}${fmtNum(r.limiar, 1)}</text>`).join('');
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" xmlns="${SVG_NS}" style="display:block;max-width:${W}px">
    <line x1="${x(0)}" x2="${x(0)}" y1="${mt - 6}" y2="${H - 6}" stroke="var(--borda)"/>${ref}${barras.join('')}</svg>`;
}

async function carregarTermoEsp() {
  const termo = rx.termos[0];
  tx.termo = termo || null;
  if (!termo || !slugAtual || !rx.resumo) { tx.termoR = null; $('#es-termo-nome').textContent = '(clique num termo)'; desenharBarrasTermo(); return; }
  const seq = ++tx.seq.termo;
  $('#es-termo-nome').textContent = `"${termo}"`;
  try {
    const r = await api(rxUrl('especificidades/termo', paramsEsp({ termo })));
    if (seq !== tx.seq.termo) return;
    tx.termoR = r;
    $('#es-termo-nome').textContent = `"${r.termo}" (F = ${fmtNum(r.F)})`;
  } catch (e) {
    if (seq !== tx.seq.termo) return;
    tx.termoR = null;
    $('#es-termo-nome').textContent = `"${termo}": ${e.message}`;
  }
  desenharBarrasTermo();
}

async function carregarEspecificidades() {
  if (!slugAtual || !rx.resumo) return;
  const seq = ++tx.seq.es;
  const p = paramsEsp({ limite: $('#es-limite').value || 10 });
  $('#es-csv').href = rxUrl('especificidades.csv', paramsEsp());
  try {
    const r = await api(rxUrl('especificidades', p));
    if (seq !== tx.seq.es) return;
    tx.es = r;
    $('#es-aviso').hidden = true;
    renderEspecificidades();
  } catch (e) {
    if (seq !== tx.seq.es) return;
    tx.es = null;
    $('#es-colunas').innerHTML = ''; $('#es-info').textContent = '';
    $('#es-aviso').hidden = false; $('#es-aviso').textContent = e.message;
  }
  carregarTermoEsp();
}

// ---------- AFC ----------

function paramsAfc() {
  return { particao: $('#af-part').value, por: $('#rx-por').value, vazias: $('#rx-vazias').value,
    n_termos: Math.min(500, Math.max(2, +$('#af-n').value || 100)), selecao: $('#af-selecao').value };
}

function eixosAfc() {
  const [a, b] = $('#af-eixos').value.split(',').map((v) => +v - 1);
  const k = tx.af ? tx.af.k : 2;
  return { a: Math.min(a, k - 1), b: k >= 2 ? Math.min(b, k - 1) : null };
}

function desenharAfc() {
  const alvo = $('#af-mapa'), r = tx.af;
  if (!r || r.k < 1) { alvo.innerHTML = ''; return; }
  const { a, b } = eixosAfc();
  const cy = (o) => (b == null ? 0 : o.coord[b]);
  let termos = r.linhas;
  if ($('#af-ctr').checked) termos = termos.filter((t) => t.ctr[a] > r.ctr_media_linhas || (b != null && t.ctr[b] > r.ctr_media_linhas));
  const W = 640, H = 480, m = 34;
  const todos = [...termos, ...r.colunas];
  const xs = todos.map((o) => o.coord[a]), ys = todos.map(cy);
  let [x0, x1, y0, y1] = [Math.min(...xs, 0), Math.max(...xs, 0), Math.min(...ys, 0), Math.max(...ys, 0)];
  if (y1 - y0 < 1e-9) { y0 = -1; y1 = 1; }
  const sx = (v) => m + ((v - x0) / ((x1 - x0) || 1)) * (W - 2 * m), sy = (v) => H - m - ((v - y0) / ((y1 - y0) || 1)) * (H - 2 * m);
  const ocupadas = [];
  const livre = (c) => c.x >= 0 && c.x + c.w <= W && c.y >= 0 && c.y + c.h <= H &&
    !ocupadas.some((o) => c.x < o.x + o.w && c.x + c.w > o.x && c.y < o.y + o.h && c.y + c.h > o.y);
  // partes primeiro (sempre rotuladas), depois termos por contribuição decrescente; rótulo que não cabe vira só um ponto
  const partes = r.colunas.map((c, i) => {
    const px = sx(c.coord[a]), py = sy(cy(c)), w = c.rotulo.length * 7.4 + 8, h = 16;
    ocupadas.push({ x: px - 6, y: py - 6, w: 12, h: 12 });
    let caixa = null;
    for (const [dx, dy] of [[8, -h / 2], [-w - 8, -h / 2], [-w / 2, -h - 8], [-w / 2, 8], [8, -h - 6], [8, 6]]) {
      const c2 = { x: px + dx, y: py + dy, w, h };
      if (livre(c2)) { caixa = c2; break; }
    }
    if (caixa) ocupadas.push(caixa);
    const rot = caixa ? `<text x="${(caixa.x + 4).toFixed(1)}" y="${(caixa.y + 12).toFixed(1)}" font-size="12.5" font-weight="700" fill="var(--texto)" paint-order="stroke" stroke="var(--painel)" stroke-width="3">${esc(c.rotulo)}</text>` : '';
    return `<g class="af-parte" data-parte="${i}" style="cursor:default"><rect x="${(px - 5).toFixed(1)}" y="${(py - 5).toFixed(1)}" width="10" height="10" fill="var(--c2)" stroke="var(--texto)" stroke-width="1.2"/>${rot}</g>`;
  });
  const ctrMax = Math.max(...termos.map((t) => Math.max(t.ctr[a], b != null ? t.ctr[b] : 0)), 1e-9);
  const ordem = [...termos].sort((p, q) => Math.max(q.ctr[a], b != null ? q.ctr[b] : 0) - Math.max(p.ctr[a], b != null ? p.ctr[b] : 0));
  const rotulos = ordem.map((t) => {
    const ctr = Math.max(t.ctr[a], b != null ? t.ctr[b] : 0);
    const size = 9.5 + 9 * Math.sqrt(ctr / ctrMax), w = t.termo.length * size * 0.56, h = size;
    const px = sx(t.coord[a]), py = sy(cy(t));
    let caixa = null;
    for (const [dx, dy] of [[-w / 2, -h / 2], [-w / 2, -h - 2], [-w / 2, 2], [4, -h / 2], [-w - 4, -h / 2], [-w / 2, -2 * h - 2], [-w / 2, h + 2]]) {
      const c = { x: px + dx, y: py + dy, w, h };
      if (livre(c)) { caixa = c; break; }
    }
    const sel = rx.termos.includes(t.termo);
    const corT = sel ? 'var(--texto)' : 'var(--c1)';
    if (!caixa) return `<g data-term="${esc(t.termo)}" data-por="${esc($('#rx-por').value)}" style="cursor:pointer"><circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="2.2" fill="${corT}" fill-opacity="0.6"/></g>`;
    ocupadas.push(caixa);
    const fundo = sel ? `<rect x="${caixa.x.toFixed(1)}" y="${caixa.y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" fill="var(--marca)"/>` : '';
    return `<g data-term="${esc(t.termo)}" data-por="${esc($('#rx-por').value)}" style="cursor:pointer">${fundo}<text x="${caixa.x.toFixed(1)}" y="${(caixa.y + h * 0.82).toFixed(1)}" font-size="${size.toFixed(1)}" fill="${corT}" font-weight="${sel ? 700 : 500}">${esc(t.termo)}</text></g>`;
  });
  const eixoX = sy(0).toFixed(1), eixoY = sx(0).toFixed(1);
  const pct = (e) => (e == null ? '' : `${e + 1} (${fmtNum(r.eixos[e].pct, 1)}%)`);
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" xmlns="${SVG_NS}" style="display:block;max-height:560px">
    <rect x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" fill="none" stroke="var(--borda)"/>
    <line x1="0" x2="${W}" y1="${eixoX}" y2="${eixoX}" stroke="var(--borda)" stroke-dasharray="3 3"/>
    ${b != null ? `<line x1="${eixoY}" x2="${eixoY}" y1="0" y2="${H}" stroke="var(--borda)" stroke-dasharray="3 3"/>` : ''}
    <text x="${W - 6}" y="${+eixoX - 5}" font-size="11" text-anchor="end" fill="var(--suave)">eixo ${pct(a)}</text>
    ${b != null ? `<text x="${+eixoY + 5}" y="13" font-size="11" fill="var(--suave)">eixo ${pct(b)}</text>` : ''}
    ${partes.join('')}${rotulos.reverse().join('')}</svg>`;
}

function renderTabelasAfc() {
  const r = tx.af;
  const maxPct = Math.max(...r.eixos.map((e) => e.pct), 1e-9);
  $('#tab-af-eixos').innerHTML = `<thead><tr><th>Eixo</th><th title="Inércia principal (λ)">Autovalor</th><th>%</th><th>% acum.</th><th></th></tr></thead><tbody>${
    r.eixos.map((e) => `<tr><td>${e.eixo}</td><td>${fmtNum(e.autovalor, 5)}</td><td>${fmtNum(e.pct, 1)}</td><td>${fmtNum(e.pct_acumulado, 1)}</td>
      <td><span class="divbar" style="grid-template-columns:${(e.pct / maxPct * 100).toFixed(0)}% 1fr;width:80px"><i style="background:var(--c1);height:100%"></i><b style="width:0"></b></span></td></tr>`).join('')
  }<tr><td colspan="5" class="discreto">inércia total ${fmtNum(r.inercia_total, 5)} = χ² ${fmtNum(r.chi2, 1)} / n ${fmtNum(r.n)}</td></tr></tbody>`;
  const { a, b } = eixosAfc();
  const por = $('#rx-por').value;
  const linhasEixo = (e) => [...r.linhas].sort((p, q) => q.ctr[e] - p.ctr[e]).slice(0, 10).map((t) =>
    `<tr><td>${e + 1}</td><td>${termoHtml(t.termo, por)}</td><td>${fmtNum(t.ctr[e], 1)}</td><td>${t.coord[e] >= 0 ? '+' : '−'}</td><td>${fmtNum(t.cos2[e], 2)}</td></tr>`).join('');
  $('#af-ctr-tit').textContent = `(10 termos por eixo; média = ${fmtNum(r.ctr_media_linhas, 2)}%)`;
  $('#tab-af-ctr').innerHTML = `<thead><tr><th>Eixo</th><th>Termo</th><th title="Contribuição ao eixo (%)">ctr %</th><th title="Lado do eixo">lado</th><th>cos²</th></tr></thead><tbody>${linhasEixo(a)}${b != null ? linhasEixo(b) : ''}</tbody>`;
}

function renderAfc() {
  const r = tx.af;
  $('#af-info').textContent = `(${r.n_linhas} termos × ${r.n_colunas} partes · ${r.k} eixo(s)${r.partes_excluidas.length ? ` · fora: ${r.partes_excluidas.map((p) => p.rotulo).join(', ')}` : ''})`;
  [...$('#af-eixos').options].forEach((o) => { o.disabled = Math.max(...o.value.split(',').map(Number)) > Math.max(r.k, 2); });
  if ($('#af-eixos').selectedOptions[0].disabled) $('#af-eixos').value = '1,2';
  $('#af-aviso').hidden = !r.mensagem;
  $('#af-aviso').textContent = r.mensagem || '';
  desenharAfc(); renderTabelasAfc();
}

async function carregarAfc() {
  if (!slugAtual || !rx.resumo) return;
  const seq = ++tx.seq.af;
  $('#af-csv').href = rxUrl('afc.csv', paramsAfc());
  try {
    const r = await api(rxUrl('afc', paramsAfc()));
    if (seq !== tx.seq.af) return;
    tx.af = r;
    renderAfc();
  } catch (e) {
    if (seq !== tx.seq.af) return;
    tx.af = null;
    for (const id of ['#af-mapa', '#tab-af-eixos', '#tab-af-ctr']) $(id).innerHTML = '';
    $('#af-info').textContent = '';
    $('#af-aviso').hidden = false; $('#af-aviso').textContent = e.message;
  }
}

function dicaAfc(ev) {
  const dica = $('#af-dica'), r = tx.af;
  const g = ev.target.closest('#af-mapa g[data-term], #af-mapa g[data-parte]');
  if (!g || !r) { dica.hidden = true; return; }
  const o = g.dataset.parte != null ? r.colunas[+g.dataset.parte] : r.linhas.find((t) => t.termo === g.dataset.term);
  if (!o) { dica.hidden = true; return; }
  const { a, b } = eixosAfc();
  const eixo = (e) => `eixo ${e + 1}: coord ${fmtNum(o.coord[e], 3)} · ctr ${fmtNum(o.ctr[e], 1)}% · cos² ${fmtNum(o.cos2[e], 2)}`;
  dica.hidden = false;
  dica.innerHTML = `<b>${esc(o.termo || o.rotulo)}</b> <span class="discreto">(${o.termo ? 'termo' : 'parte'}, freq ${fmtNum(o.freq)})</span><br>${eixo(a)}${b != null ? '<br>' + eixo(b) : ''}<br>qualidade (soma dos cos² nos ${r.k} eixos) ${fmtNum(o.qualidade, 2)}`;
  dica.style.left = Math.min(ev.clientX + 14, window.innerWidth - 270) + 'px';
  dica.style.top = Math.min(ev.clientY + 14, window.innerHeight - 100) + 'px';
}

// ---------- ganchos ----------

function carregarTextometria() {
  carregarEspecificidades(); carregarAfc();
  if (typeof carregarTematico === 'function') carregarTematico(); // tematico.js (7.1, 7.2)
}

function limparTextometria() {
  tx.es = tx.af = tx.termoR = null;
  for (const id of ['#es-colunas', '#es-barras', '#af-mapa', '#tab-af-eixos', '#tab-af-ctr']) $(id).innerHTML = '';
  $('#es-info').textContent = ''; $('#af-info').textContent = '';
  if (typeof limparTematico === 'function') limparTematico();
}

// chamada por atualizarSelecao (raiox.js): gráfico do termo e destaque no mapa seguem a seleção
function aoMudarSelecao() {
  if (rx.termos[0] !== tx.termo) carregarTermoEsp();
  if (tx.af) desenharAfc();
  if (typeof aoMudarSelecaoTematico === 'function') aoMudarSelecaoTematico();
}

$('#es-calcular').addEventListener('click', carregarEspecificidades);
for (const id of ['#es-part', '#es-min', '#es-limiar', '#es-limite']) $(id).addEventListener('change', carregarEspecificidades);
$('#af-calcular').addEventListener('click', carregarAfc);
for (const id of ['#af-part', '#af-n', '#af-selecao']) $(id).addEventListener('change', carregarAfc);
$('#af-eixos').addEventListener('change', () => { if (tx.af) { desenharAfc(); renderTabelasAfc(); } });
$('#af-ctr').addEventListener('change', () => { if (tx.af) desenharAfc(); });
$('#af-mapa').addEventListener('mousemove', dicaAfc);
$('#af-mapa').addEventListener('mouseleave', () => { $('#af-dica').hidden = true; });
