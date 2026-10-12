// Painel "Similaridade entre documentos" (6.3): dendrograma SVG, mapa 2D, vizinhos e termos característicos dos grupos.
// Usa $, esc, api, fmtNum, slugAtual (app.js) e rx, rxUrl, rxEscopo, termoHtml (raiox.js). Sem bibliotecas; cores por --c1..--c8.

const sm = { r: null, doc: null, seq: 0 };
const SVGNS = 'http://www.w3.org/2000/svg';
const FORMAS = ['circulo', 'quadrado', 'triangulo', 'losango', 'cruz', 'estrela'];

const corCluster = (c) => `var(--c${((c - 1) % 8) + 1})`;

function paramsSimilaridade(extra) {
  const e = rxEscopo();
  const p = { por: $('#sm-por').value, metodo: $('#sm-metodo').value, max_df: $('#sm-maxdf').value || 0.9, ...(e.escopo === 'documento' ? { escopo: 'corpus' } : e), ...extra };
  if ($('#sm-k').value) p.k = $('#sm-k').value;
  return p;
}

// Marcador por grupo do documento (forma) com centro em (x, y) e "raio" r.
function marcadorSvg(forma, x, y, r, atributos) {
  const a = Object.entries(atributos).map(([k, v]) => `${k}="${v}"`).join(' ');
  switch (forma) {
    case 'quadrado': return `<rect x="${x - r}" y="${y - r}" width="${2 * r}" height="${2 * r}" ${a}/>`;
    case 'triangulo': return `<polygon points="${x},${y - r * 1.2} ${x + r * 1.1},${y + r * 0.9} ${x - r * 1.1},${y + r * 0.9}" ${a}/>`;
    case 'losango': return `<polygon points="${x},${y - r * 1.3} ${x + r * 1.3},${y} ${x},${y + r * 1.3} ${x - r * 1.3},${y}" ${a}/>`;
    case 'cruz': return `<polygon points="${x - r * 0.4},${y - r * 1.2} ${x + r * 0.4},${y - r * 1.2} ${x + r * 0.4},${y - r * 0.4} ${x + r * 1.2},${y - r * 0.4} ${x + r * 1.2},${y + r * 0.4} ${x + r * 0.4},${y + r * 0.4} ${x + r * 0.4},${y + r * 1.2} ${x - r * 0.4},${y + r * 1.2} ${x - r * 0.4},${y + r * 0.4} ${x - r * 1.2},${y + r * 0.4} ${x - r * 1.2},${y - r * 0.4} ${x - r * 0.4},${y - r * 0.4}" ${a}/>`;
    case 'estrela': {
      const pts = [];
      for (let i = 0; i < 10; i++) { const rr = i % 2 ? r * 0.55 : r * 1.3, ang = -Math.PI / 2 + i * Math.PI / 5; pts.push(`${(x + rr * Math.cos(ang)).toFixed(1)},${(y + rr * Math.sin(ang)).toFixed(1)}`); }
      return `<polygon points="${pts.join(' ')}" ${a}/>`;
    }
    default: return `<circle cx="${x}" cy="${y}" r="${r}" ${a}/>`;
  }
}

function formaDoGrupo(grupo) {
  const i = (sm.r ? sm.r.documentos.map((d) => d.grupo).filter((g, k, v) => v.indexOf(g) === k).sort() : []).indexOf(grupo);
  return FORMAS[(i < 0 ? 0 : i) % FORMAS.length];
}

function dicaDoc(d, ev) {
  const dica = $('#sm-dica');
  dica.hidden = false;
  const viz = d.vizinhos[0] ? `<br>mais parecido: ${esc(d.vizinhos[0].rotulo)} (${fmtNum(d.vizinhos[0].similaridade, 2)})` : '';
  dica.innerHTML = `<b>${esc(d.rotulo)}</b><br>grupo de similaridade ${d.cluster} · ${esc(d.grupo)} · ${esc(d.ano)}<br>${fmtNum(d.n_termos)} termos${viz}`;
  dica.style.left = Math.min(ev.clientX + 14, window.innerWidth - 270) + 'px';
  dica.style.top = Math.min(ev.clientY + 14, window.innerHeight - 90) + 'px';
}

// ---------- dendrograma horizontal (raiz à esquerda, folhas à direita) ----------

function desenharDendrograma() {
  const alvo = $('#sm-dend');
  const r = sm.r;
  if (!r) { alvo.innerHTML = ''; return; }
  const n = r.documentos.length, dend = r.dendrograma, passo = 18, mt = 8, ml = 10, largPlot = 380, largRotulo = 190;
  const W = ml + largPlot + largRotulo, H = mt * 2 + n * passo;
  const y = new Array(n + dend.fusoes.length), x = new Array(n + dend.fusoes.length), grupos = new Array(n + dend.fusoes.length);
  dend.ordem_folhas.forEach((idx, pos) => { y[idx] = mt + pos * passo + passo / 2; x[idx] = 0; grupos[idx] = new Set([r.documentos[idx].cluster]); });
  const hmax = Math.max(...dend.fusoes.map((f) => f.altura), 1e-9);
  const px = (h) => ml + (1 - h / hmax) * largPlot;
  const linhas = [];
  dend.fusoes.forEach((f, i) => {
    const id = n + i;
    y[id] = (y[f.esquerda] + y[f.direita]) / 2; x[id] = f.altura;
    grupos[id] = new Set([...grupos[f.esquerda], ...grupos[f.direita]]);
    const cor = grupos[id].size === 1 ? corCluster([...grupos[id]][0]) : 'var(--suave)';
    const xm = px(f.altura).toFixed(1);
    linhas.push(`<path d="M${px(x[f.esquerda]).toFixed(1)},${y[f.esquerda]} H${xm} V${y[f.direita]} H${px(x[f.direita]).toFixed(1)}" fill="none" stroke="${cor}" stroke-width="1.5"><title>distância ${fmtNum(f.altura, 3)} · ${f.tamanho} documentos</title></path>`);
  });
  let corte = '';
  if (dend.altura_corte != null) {
    const xc = px(dend.altura_corte).toFixed(1);
    corte = `<line x1="${xc}" x2="${xc}" y1="${mt - 4}" y2="${H - mt + 4}" stroke="var(--suave)" stroke-dasharray="4 3"/><text x="${xc}" y="${mt - 1}" font-size="9" fill="var(--suave)" text-anchor="middle">corte k=${r.k}</text>`;
  }
  const rotulos = dend.ordem_folhas.map((idx) => {
    const d = r.documentos[idx], sel = sm.doc === d.id;
    return `<g class="sm-folha${sel ? ' sel' : ''}" data-id="${d.id}" style="cursor:pointer"><rect x="${ml + largPlot}" y="${y[idx] - passo / 2}" width="${largRotulo}" height="${passo}" fill="${sel ? 'var(--marca)' : 'transparent'}"/>` +
      `<circle cx="${ml + largPlot}" cy="${y[idx]}" r="3.5" fill="${corCluster(d.cluster)}"/>` +
      `<text x="${ml + largPlot + 9}" y="${y[idx] + 4}" font-size="11.5" fill="${corCluster(d.cluster)}" font-weight="600">${esc(d.rotulo)}</text>` +
      `<title>${esc(d.arquivo)} · grupo ${d.cluster} · ${esc(d.grupo)}</title></g>`;
  });
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" xmlns="${SVGNS}" style="display:block">${linhas.join('')}${corte}${rotulos.join('')}</svg>`;
}

// ---------- mapa 2D ----------

function desenharMapa() {
  const alvo = $('#sm-mapa');
  const r = sm.r;
  if (!r) { alvo.innerHTML = ''; $('#sm-legenda').innerHTML = ''; return; }
  const W = 520, H = 380, m = 28;
  const xs = r.documentos.map((d) => d.x), ys = r.documentos.map((d) => d.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const sx = (v) => m + ((v - x0) / ((x1 - x0) || 1)) * (W - 2 * m), sy = (v) => H - m - ((v - y0) / ((y1 - y0) || 1)) * (H - 2 * m);
  const pts = r.documentos.map((d) => {
    const sel = sm.doc === d.id, cx = sx(d.x).toFixed(1), cy = sy(d.y).toFixed(1);
    const mk = marcadorSvg(formaDoGrupo(d.grupo), +cx, +cy, sel ? 8 : 6, { fill: corCluster(d.cluster), 'fill-opacity': 0.85, stroke: sel ? 'var(--texto)' : 'var(--painel)', 'stroke-width': sel ? 2.5 : 1.2 });
    const rot = sel ? `<text x="${cx}" y="${+cy - 12}" font-size="11.5" text-anchor="middle" fill="var(--texto)" font-weight="700" paint-order="stroke" stroke="var(--painel)" stroke-width="3">${esc(d.rotulo)}</text>` : '';
    return `<g class="sm-pt" data-id="${d.id}" style="cursor:pointer">${mk}${rot}</g>`;
  });
  const ve = r.variancia_explicada;
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" xmlns="${SVGNS}" style="display:block;max-height:420px"><rect x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" fill="none" stroke="var(--borda)"/>${pts.join('')}</svg>`;
  $('#sm-mapa-info').textContent = `(MDS clássico: eixo 1 = ${fmtNum(ve[0] * 100, 0)}%, eixo 2 = ${fmtNum(ve[1] * 100, 0)}% da variação)`;
  const ks = [...new Set(r.documentos.map((d) => d.cluster))].sort((a, b) => a - b);
  const gs = [...new Set(r.documentos.map((d) => d.grupo))].sort();
  $('#sm-legenda').innerHTML = ks.map((k) => `<span class="chip"><i style="background:${corCluster(k)}"></i>grupo ${k}</span>`).join('') +
    gs.map((g) => `<span class="chip"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">${marcadorSvg(formaDoGrupo(g), 7, 7, 4.5, { fill: 'var(--suave)' })}</svg>${esc(g)}</span>`).join('');
}

// ---------- vizinhos e termos ----------

function renderVizinhos() {
  const r = sm.r, el = $('#tab-sm-viz');
  if (!r) { el.innerHTML = ''; return; }
  const d = r.documentos.find((x) => x.id === sm.doc) || r.documentos[0];
  const max = Math.max(...d.vizinhos.map((v) => v.similaridade), 0.0001);
  const linhas = d.vizinhos.map((v, i) =>
    `<tr><td>${i + 1}</td><td><a href="#" class="doc-link" data-sm-doc="${v.id}">${esc(v.rotulo)}</a></td>
     <td>${fmtNum(v.similaridade, 3)}</td><td><span class="divbar" style="grid-template-columns:${(v.similaridade / max * 100).toFixed(0)}% 1fr;width:96px"><i style="background:${corCluster(v.cluster)};height:100%"></i><b style="width:0"></b></span></td>
     <td><span class="chip"><i style="background:${corCluster(v.cluster)}"></i>${v.cluster}</span></td></tr>`).join('');
  el.innerHTML = `<thead><tr><th>#</th><th>Documento</th><th title="Cosseno TF-IDF">Similaridade</th><th></th><th title="Grupo de similaridade">Grupo</th></tr></thead><tbody>${linhas}</tbody>`;
}

function renderTermosGrupos() {
  const r = sm.r, el = $('#sm-termos');
  if (!r) { el.innerHTML = ''; return; }
  el.innerHTML = r.grupos.map((g) => {
    const rotulos = g.ids.map((id) => r.documentos.find((d) => d.id === id)).filter(Boolean).map((d) => d.rotulo);
    const termos = g.termos.map((t) => `<span title="média no grupo ${fmtNum(t.media_grupo, 3)} − média geral ${fmtNum(t.media_corpus, 3)} = ${fmtNum(t.diferenca, 3)} · em ${t.docs_no_grupo} de ${g.documentos} doc.">${termoHtml(t.termo, r.unidade)}</span>`).join(' ');
    return `<div class="sm-cartao" style="border-left-color:${corCluster(g.cluster)}"><b style="color:${corCluster(g.cluster)}">Grupo ${g.cluster}</b>
      <span class="discreto"> · ${g.documentos} doc.: ${esc(rotulos.slice(0, 6).join(', '))}${rotulos.length > 6 ? '…' : ''}</span><div class="sm-termos-lista">${termos || '<span class="discreto">sem termos com diferença positiva</span>'}</div></div>`;
  }).join('');
}

function selecionarDocumentoSim(id) {
  sm.doc = id;
  if ($('#sm-doc').value !== String(id)) $('#sm-doc').value = String(id);
  desenharDendrograma(); desenharMapa(); renderVizinhos();
}

function renderSimilaridade() {
  const r = sm.r;
  $('#sm-aviso').hidden = true;
  if (!r.documentos.some((d) => d.id === sm.doc)) sm.doc = r.documentos[0].id;
  $('#sm-doc').innerHTML = r.documentos.map((d) => `<option value="${d.id}">${esc(d.rotulo)}</option>`).join('');
  $('#sm-doc').value = String(sm.doc);
  const sils = r.k_automatico && r.silhuetas.length ? ` · silhueta por k: ${r.silhuetas.map((s) => `${s.k}=${fmtNum(s.silhueta, 2)}`).join(', ')}` : '';
  $('#sm-info').textContent = `(${r.n_documentos} documentos · ${fmtNum(r.n_termos)} termos · k = ${r.k}${r.k_automatico ? ' (automático)' : ''}${r.excluidos.length ? ` · ${r.excluidos.length} excluído(s): ${r.excluidos.map((e) => e.rotulo).join(', ')}` : ''})`;
  $('#sm-dend-info').textContent = `(${r.metodo === 'ward' ? 'Ward' : 'ligação média'}${sils})`;
  desenharDendrograma(); desenharMapa(); renderVizinhos(); renderTermosGrupos();
}

async function carregarSimilaridade() {
  if (!slugAtual || !rx.resumo) return;
  const seq = ++sm.seq;
  $('#sm-csv').href = rxUrl('similaridade.csv', paramsSimilaridade());
  $('#sm-csv2').href = rxUrl('agrupamentos.csv', paramsSimilaridade());
  try {
    const r = await api(rxUrl('similaridade', paramsSimilaridade()));
    if (seq !== sm.seq) return;
    sm.r = r;
    renderSimilaridade();
  } catch (e) {
    if (seq !== sm.seq) return;
    sm.r = null;
    for (const id of ['#sm-dend', '#sm-mapa', '#sm-legenda', '#sm-termos', '#tab-sm-viz']) $(id).innerHTML = '';
    $('#sm-info').textContent = '';
    $('#sm-aviso').hidden = false;
    $('#sm-aviso').textContent = e.message;
  }
}

function limparSimilaridade() {
  sm.r = null;
  for (const id of ['#sm-dend', '#sm-mapa', '#sm-legenda', '#sm-termos', '#tab-sm-viz']) $(id).innerHTML = '';
  $('#sm-info').textContent = '';
}

$('#p-simil').addEventListener('click', (ev) => {
  const el = ev.target.closest('.sm-folha, .sm-pt, a[data-sm-doc]');
  if (!el) return;
  ev.preventDefault();
  selecionarDocumentoSim(+(el.dataset.id || el.dataset.smDoc));
});
$('#p-simil').addEventListener('mousemove', (ev) => {
  const el = ev.target.closest('.sm-pt');
  if (!el || !sm.r) { $('#sm-dica').hidden = true; return; }
  const d = sm.r.documentos.find((x) => x.id === +el.dataset.id);
  if (d) dicaDoc(d, ev);
});
$('#sm-mapa').addEventListener('mouseleave', () => { $('#sm-dica').hidden = true; });
$('#sm-doc').addEventListener('change', () => selecionarDocumentoSim(+$('#sm-doc').value));
for (const id of ['#sm-por', '#sm-metodo', '#sm-k', '#sm-maxdf']) $(id).addEventListener('change', carregarSimilaridade);
$('#sm-calcular').addEventListener('click', carregarSimilaridade);
