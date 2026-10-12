// Painéis "Classes (Reinert)" (7.1) e "Similitude / Rede" (7.2 + 15.2).
// Usa $, esc, api, fmtNum, slugAtual (app.js), rx, rxUrl, termoHtml, escolherTermo (raiox.js) e SVG_NS (textometria.js).
// Sem bibliotecas: SVG com var(--...); o servidor calcula classes, coordenadas do layout, comunidades e centralidades.

const tm = { rn: null, sl: null, rnParams: null, seq: { rn: 0, sl: 0 } };
const corClasse = (k) => (k ? `var(--c${((k - 1) % 8) + 1})` : 'var(--suave)');

function marcaSel(t) { return rx.termos.includes(t); }

// ---------- Reinert ----------

function paramsReinert() {
  if (!tm.rnParams) return {}; // 1ª carga: parâmetros do projeto (mesmo cálculo da etapa, já em cache)
  return tm.rnParams;
}

function lerControlesReinert() {
  tm.rnParams = {
    classes: Math.min(30, Math.max(2, +$('#rn-classes').value || 10)),
    min_freq: Math.max(1, +$('#rn-min').value || 3),
    min_classe: Math.max(0, +$('#rn-minc').value || 0),
    dupla: $('#rn-dupla').checked,
  };
}

function classeFinalDaFolha(r, no) {
  return r.dupla ? (no.classe_final || null) : (no.classe || null);
}

function desenharDendrograma() {
  const alvo = $('#rn-dendro'), r = tm.rn;
  if (!r) { alvo.innerHTML = ''; return; }
  const nos = r.dendrogramas[0].nos;
  const porId = Object.fromEntries(nos.map((n) => [n.id, n]));
  const folhas = [], prof = { 0: 0 };
  const pilha = [0];
  while (pilha.length) {
    const n = porId[pilha.pop()];
    for (const f of n.filhos) prof[f] = prof[n.id] + 1;
    if (n.filhos.length) pilha.push(...[...n.filhos].reverse()); else folhas.push(n);
  }
  const maxProf = Math.max(...Object.values(prof));
  // folhas descartadas/instáveis (em geral grupos minúsculos de segmentos atípicos) ficam estreitas
  const larg = (f) => (classeFinalDaFolha(r, f) ? 74 : 16);
  const ml = 12, mt = 14, dy = Math.max(18, Math.min(34, 260 / Math.max(1, maxProf)));
  const W = Math.max(320, ml * 2 + folhas.reduce((s, f) => s + larg(f), 0)), base = mt + maxProf * dy;
  const H = base + 58;
  const x = {}, y = {};
  let acum = ml;
  folhas.forEach((f) => { x[f.id] = acum + larg(f) / 2; y[f.id] = base; acum += larg(f); });
  const posicao = (id) => {
    const n = porId[id];
    if (!n.filhos.length) return x[id];
    x[id] = n.filhos.map(posicao).reduce((a, b) => a + b, 0) / n.filhos.length;
    y[id] = mt + prof[id] * dy;
    return x[id];
  };
  posicao(0);
  const linhas = nos.filter((n) => n.filhos.length).map((n) => n.filhos.map((f) =>
    `<path d="M${x[n.id].toFixed(1)} ${y[n.id].toFixed(1)} H${x[f].toFixed(1)} V${y[f].toFixed(1)}" fill="none" stroke="var(--suave)" stroke-width="1.3">
      <title>${n.n} segmentos · χ² da bipartição ${fmtNum(n.chi2, 0)} (corte ${fmtNum(n.chi2_corte, 0)}) · λ1 ${fmtNum(n.lambda1, 3)} · ${n.movidos} realocados</title></path>`).join('')).join('');
  const total = r.segmentos_total;
  const rotulos = folhas.map((f) => {
    const k = classeFinalDaFolha(r, f), cx = x[f.id];
    const largura = larg(f) - 8, alt = 36;
    if (!k) {
      const motivo = f.descartada ? 'descartada (menor que a classe mínima)' : (r.dupla ? 'instável (fora das classes estáveis)' : '');
      return `<g><title>${fmtNum(f.n)} segmentos não classificados · ${motivo}</title><rect x="${(cx - largura / 2).toFixed(1)}" y="${base + 4}" width="${largura}" height="${alt}" rx="3" fill="var(--borda)" fill-opacity="0.5"/>
        <text x="${cx.toFixed(1)}" y="${base + 52}" font-size="9" text-anchor="middle" fill="var(--suave)">${fmtNum(f.n)}</text></g>`;
    }
    const c = r.classes.find((q) => q.classe === k);
    const pct = c ? c.pct : 100 * f.n / total;
    return `<g class="rn-folha" data-classe="${k}" style="cursor:pointer"><title>Classe ${k}: ${fmtNum(c ? c.n_st : f.n)} segmentos (${fmtNum(pct, 1)}% dos classificados)</title>
      <rect x="${(cx - largura / 2).toFixed(1)}" y="${base + 4}" width="${largura}" height="${alt}" rx="4" fill="${corClasse(k)}" fill-opacity="0.18" stroke="${corClasse(k)}" stroke-width="1.5"/>
      <text x="${cx.toFixed(1)}" y="${base + 19}" font-size="12" font-weight="700" text-anchor="middle" fill="${corClasse(k)}">Classe ${k}</text>
      <text x="${cx.toFixed(1)}" y="${base + 33}" font-size="10.5" text-anchor="middle" fill="var(--texto)">${fmtNum(pct, 1)}%</text></g>`;
  }).join('');
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" xmlns="${SVG_NS}" style="display:block;max-width:none">${linhas}${rotulos}</svg>`;
}

function listaVariaveis(c) {
  const partes = [];
  for (const [v, nome] of [['documento', 'doc.'], ['grupo', 'grupo'], ['ano', 'ano']]) {
    const itens = (c.variaveis[v] || []).slice(0, 3);
    if (itens.length) partes.push(`<b>${nome}</b> ${itens.map((i) => `${esc(i.modalidade)} <span title="χ² ${fmtNum(i.chi2, 1)} · ${i.st_classe} de ${i.st_total} ST">(${fmtNum(i.chi2, 0)})</span>`).join(', ')}`);
  }
  return partes.join('<br>') || '<span>nenhuma variável associada</span>';
}

function renderColunasReinert() {
  const r = tm.rn;
  $('#rn-colunas').innerHTML = r.classes.map((c) => {
    const max = Math.max(...c.formas.map((f) => f.chi2), 1);
    const palavras = c.formas.slice(0, 30).map((f) => {
      const tam = 11 + 11 * Math.sqrt(f.chi2 / max);
      return `<span class="termo${marcaSel(f.forma) ? ' sel' : ''}" data-term="${esc(f.forma)}" data-por="lema" style="font-size:${tam.toFixed(1)}px"
        title="χ² ${fmtNum(f.chi2, 1)} · p ${f.p < 0.0001 ? '< 0,0001' : fmtNum(f.p, 4)} · ${f.freq_classe} de ${f.freq_total} segmentos com a forma (${fmtNum(f.pct_classe, 1)}% nesta classe)">${esc(f.forma)}</span>`;
    }).join('');
    return `<div class="rn-col" style="border-top-color:${corClasse(c.classe)}">
      <b style="color:${corClasse(c.classe)}">Classe ${c.classe}</b> <span class="discreto">${fmtNum(c.n_st)} ST · ${fmtNum(c.pct, 1)}% · ${c.n_documentos} doc.</span>
      <div class="rn-palavras">${palavras || '<span class="discreto">sem formas características</span>'}</div>
      <div class="rn-var">${listaVariaveis(c)}</div></div>`;
  }).join('');
}

function desenharAfcReinert() {
  const alvo = $('#rn-afc'), a = tm.rn && tm.rn.afc;
  if (!a || a.k < 1) { alvo.innerHTML = '<p class="discreto">AFC indisponível (menos de 2 classes).</p>'; $('#rn-afc-info').textContent = ''; return; }
  const b2 = a.k >= 2;
  $('#rn-afc-info').textContent = `(eixo 1: ${fmtNum(a.eixos[0].pct, 1)}%${b2 ? ` · eixo 2: ${fmtNum(a.eixos[1].pct, 1)}%` : ''})`;
  const porClasse = {};
  for (const f of a.formas) (porClasse[f.classe] = porClasse[f.classe] || []).push(f);
  const formas = Object.values(porClasse).flatMap((l) => l.sort((p, q) => q.chi2 - p.chi2).slice(0, 15));
  const W = 640, H = 480, m = 30;
  const cy = (o) => (b2 ? o.coord[1] : 0);
  const todos = [...formas, ...a.classes];
  const xs = todos.map((o) => o.coord[0]), ys = todos.map(cy);
  let [x0, x1, y0, y1] = [Math.min(...xs, 0), Math.max(...xs, 0), Math.min(...ys, 0), Math.max(...ys, 0)];
  if (y1 - y0 < 1e-9) { y0 = -1; y1 = 1; }
  const sx = (v) => m + ((v - x0) / ((x1 - x0) || 1)) * (W - 2 * m), sy = (v) => H - m - ((v - y0) / ((y1 - y0) || 1)) * (H - 2 * m);
  const ocupadas = [];
  const livre = (c) => c.x >= 0 && c.x + c.w <= W && c.y >= 0 && c.y + c.h <= H &&
    !ocupadas.some((o) => c.x < o.x + o.w && c.x + c.w > o.x && c.y < o.y + o.h && c.y + c.h > o.y);
  const marcas = a.classes.map((c) => {
    const px = sx(c.coord[0]), py = sy(cy(c));
    ocupadas.push({ x: px - 7, y: py - 7, w: 14, h: 14 });
    return `<g><title>Classe ${c.classe}</title><circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="7" fill="${corClasse(c.classe)}" stroke="var(--texto)"/>
      <text x="${(px + 9).toFixed(1)}" y="${(py - 8).toFixed(1)}" font-size="12" font-weight="700" fill="${corClasse(c.classe)}" paint-order="stroke" stroke="var(--painel)" stroke-width="3">${c.classe}</text></g>`;
  });
  const maxChi = Math.max(...formas.map((f) => f.chi2), 1);
  const rot = [...formas].sort((p, q) => q.chi2 - p.chi2).map((f) => {
    const size = 9.5 + 8 * Math.sqrt(f.chi2 / maxChi), w = f.forma.length * size * 0.56, h = size;
    const px = sx(f.coord[0]), py = sy(cy(f));
    let caixa = null;
    for (const [dx, dy] of [[-w / 2, -h / 2], [-w / 2, -h - 2], [-w / 2, 2], [4, -h / 2], [-w - 4, -h / 2]]) {
      const c = { x: px + dx, y: py + dy, w, h };
      if (livre(c)) { caixa = c; break; }
    }
    const sel = marcaSel(f.forma);
    if (!caixa) return `<g data-term="${esc(f.forma)}" data-por="lema" style="cursor:pointer"><circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="2" fill="${corClasse(f.classe)}"/></g>`;
    ocupadas.push(caixa);
    const fundo = sel ? `<rect x="${caixa.x.toFixed(1)}" y="${caixa.y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" fill="var(--marca)"/>` : '';
    return `<g data-term="${esc(f.forma)}" data-por="lema" style="cursor:pointer"><title>${esc(f.forma)} · classe ${f.classe} · χ² ${fmtNum(f.chi2, 1)}</title>${fundo}<text x="${caixa.x.toFixed(1)}" y="${(caixa.y + h * 0.82).toFixed(1)}" font-size="${size.toFixed(1)}" fill="${corClasse(f.classe)}" font-weight="${sel ? 700 : 500}">${esc(f.forma)}</text></g>`;
  });
  const ex = sy(0).toFixed(1), ey = sx(0).toFixed(1);
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" xmlns="${SVG_NS}" style="display:block;max-height:540px">
    <rect x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" fill="none" stroke="var(--borda)"/>
    <line x1="0" x2="${W}" y1="${ex}" y2="${ex}" stroke="var(--borda)" stroke-dasharray="3 3"/>
    ${b2 ? `<line x1="${ey}" x2="${ey}" y1="0" y2="${H}" stroke="var(--borda)" stroke-dasharray="3 3"/>` : ''}
    ${rot.reverse().join('')}${marcas.join('')}</svg>`;
}

function renderSegmentosReinert() {
  const r = tm.rn;
  $('#rn-segmentos').innerHTML = r.classes.map((c) => `<details class="rn-det"${c.classe <= 3 ? ' open' : ''}>
      <summary><b style="color:${corClasse(c.classe)}">Classe ${c.classe}</b> <span class="discreto">${c.formas.slice(0, 4).map((f) => esc(f.forma)).join(', ')}</span></summary>
      ${c.segmentos.slice(0, 3).map((s) => `<div class="rn-seg" style="border-color:${corClasse(c.classe)}">
        <span class="discreto">${esc(s.rotulo)}, p. ${s.pagina} · pontuação ${fmtNum(s.pontuacao, 0)}</span><br>${esc(s.texto)}</div>`).join('')}
    </details>`).join('');
}

function renderReinert() {
  const r = tm.rn;
  const p = r.parametros;
  $('#rn-classes').value = p.classes; $('#rn-min').value = p.min_freq; $('#rn-minc').value = p.min_classe; $('#rn-dupla').checked = p.dupla;
  $('#rn-info').textContent = `(${r.k} classes · retenção ${fmtNum(r.retencao_pct, 1)}% = ${fmtNum(r.segmentos_classificados)} de ${fmtNum(r.segmentos_total)} segmentos · ${fmtNum(r.formas_ativas)} formas ativas · classe mín. ${r.min_classe} ST${r.dupla ? ' · classificação dupla' : ''})`;
  const avisos = [...r.avisos];
  $('#rn-aviso').hidden = !avisos.length;
  $('#rn-aviso').textContent = avisos.join(' ');
  desenharDendrograma(); renderColunasReinert(); desenharAfcReinert(); renderSegmentosReinert();
}

async function carregarReinert() {
  if (!slugAtual || !rx.resumo) return;
  const seq = ++tm.seq.rn;
  const p = paramsReinert();
  $('#rn-csv').href = rxUrl('reinert/classes.csv', p);
  $('#rn-csv-seg').href = rxUrl('reinert/segmentos.csv', p);
  $('#rn-info').textContent = '(calculando…)';
  try {
    const r = await api(rxUrl('reinert', p));
    if (seq !== tm.seq.rn) return;
    tm.rn = r;
    renderReinert();
  } catch (e) {
    if (seq !== tm.seq.rn) return;
    tm.rn = null;
    for (const id of ['#rn-dendro', '#rn-colunas', '#rn-afc', '#rn-segmentos']) $(id).innerHTML = '';
    $('#rn-info').textContent = '';
    $('#rn-aviso').hidden = false; $('#rn-aviso').textContent = e.message;
  }
}

// ---------- Similitude / rede ----------

function paramsSimilitude() {
  return { indice: $('#sl-indice').value, arvore: $('#sl-arvore').value, comunidades: $('#sl-com').checked,
    n_formas: Math.min(300, Math.max(3, +$('#sl-n').value || 60)) };
}

function casco(pontos) { // envoltória convexa (cadeia monótona de Andrew)
  const p = [...pontos].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return p;
  const cruz = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const inf = [], sup = [];
  for (const q of p) { while (inf.length >= 2 && cruz(inf[inf.length - 2], inf[inf.length - 1], q) <= 0) inf.pop(); inf.push(q); }
  for (const q of [...p].reverse()) { while (sup.length >= 2 && cruz(sup[sup.length - 2], sup[sup.length - 1], q) <= 0) sup.pop(); sup.push(q); }
  return inf.slice(0, -1).concat(sup.slice(0, -1));
}

function desenharGrafoSl() {
  const alvo = $('#sl-grafo'), r = tm.sl;
  if (!r) { alvo.innerHTML = ''; return; }
  const comOn = $('#sl-com').checked && r.comunidades.length > 0;
  const W = 760, H = 600, m = 46;
  const pos = Object.fromEntries(r.nos.map((n) => [n.forma, [m + n.x * (W - 2 * m), m + n.y * (H - 2 * m)]]));
  const cor = (c) => (comOn && c ? corClasse(c) : 'var(--texto)');
  const halos = comOn ? r.comunidades.filter((c) => c.n >= 1).map((c) => {
    const pts = c.formas.map((f) => pos[f]);
    const h = casco(pts);
    const d = h.length === 1 ? `M${h[0][0]} ${h[0][1]} l0.01 0` : `M${h.map((q) => `${q[0].toFixed(1)} ${q[1].toFixed(1)}`).join(' L')}${h.length > 2 ? ' Z' : ''}`;
    return `<path d="${d}" fill="${corClasse(c.comunidade)}" fill-opacity="0.13" stroke="${corClasse(c.comunidade)}" stroke-opacity="0.13" stroke-width="40" stroke-linejoin="round" stroke-linecap="round"/>`;
  }).join('') : '';
  const maxW = Math.max(...r.arestas.map((a) => a.peso), 1e-9);
  const arestas = r.arestas.map((a) => {
    const [x1, y1] = pos[a.a], [x2, y2] = pos[a.b];
    return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="var(--suave)" stroke-opacity="0.75" stroke-width="${(0.6 + 6 * a.peso / maxW).toFixed(2)}">
      <title>${esc(a.a)} — ${esc(a.b)}: ${r.indice} ${fmtNum(a.peso, r.indice === 'coocorrencia' ? 0 : 3)} · ${a.coocorrencias} segmentos juntos · Jaccard ${fmtNum(a.jaccard, 3)}</title></line>`;
  }).join('');
  const maxF = Math.max(...r.nos.map((n) => n.freq), 1);
  const nos = [...r.nos].sort((p, q) => p.freq - q.freq).map((n) => {
    const [x, y] = pos[n.forma], size = 10 + 14 * Math.sqrt(n.freq / maxF), sel = marcaSel(n.forma);
    const w = n.forma.length * size * 0.56;
    return `<g data-term="${esc(n.forma)}" data-por="lema" data-no="${esc(n.forma)}" style="cursor:pointer">
      ${sel ? `<rect x="${(x - w / 2 - 2).toFixed(1)}" y="${(y - size * 0.8).toFixed(1)}" width="${(w + 4).toFixed(1)}" height="${(size * 1.1).toFixed(1)}" fill="var(--marca)"/>` : ''}
      <text x="${x.toFixed(1)}" y="${(y + size * 0.3).toFixed(1)}" font-size="${size.toFixed(1)}" text-anchor="middle" font-weight="${sel ? 800 : 600}" fill="${cor(n.comunidade)}"
        paint-order="stroke" stroke="var(--painel)" stroke-width="3">${esc(n.forma)}</text></g>`;
  }).join('');
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" xmlns="${SVG_NS}" style="display:block;max-width:none">${halos}${arestas}${nos}</svg>`;
}

function renderTabelaSl() {
  const r = tm.sl;
  const comOn = $('#sl-com').checked && r.comunidades.length > 0;
  $('#sl-mod').textContent = r.modularidade == null ? '' : `(Louvain · modularidade Q = ${fmtNum(r.modularidade, 3)})`;
  $('#sl-comms').innerHTML = comOn ? r.comunidades.filter((c) => c.n > 1).map((c) => `<div class="sm-cartao" style="border-left-color:${corClasse(c.comunidade)}">
      <b style="color:${corClasse(c.comunidade)}">Comunidade ${c.comunidade}</b> <span class="discreto">${c.n} palavras</span>
      <div class="sm-termos-lista">${c.formas.map((f) => termoHtml(f, 'lema')).join('')}</div></div>`).join('') : '<p class="discreto">Comunidades desligadas.</p>';
  const linhas = [...r.nos].sort((p, q) => q.pagerank - p.pagerank).map((n) => `<tr><td>${termoHtml(n.forma, 'lema')}</td><td>${fmtNum(n.freq)}</td>
      <td>${comOn && n.comunidade ? `<i class="sl-pt" style="background:${corClasse(n.comunidade)}"></i>${n.comunidade}` : '—'}</td><td>${n.grau}</td>
      <td>${fmtNum(n.grau_ponderado, r.indice === 'coocorrencia' ? 0 : 2)}</td><td>${fmtNum(n.intermediacao, 3)}</td><td>${fmtNum(n.pagerank, 3)}</td></tr>`).join('');
  $('#tab-sl-nos').innerHTML = `<thead><tr><th>Forma</th><th>Freq.</th><th title="Comunidade (Louvain)">Com.</th><th title="Nº de arestas">Grau</th>
    <th title="Soma dos pesos das arestas">Grau pond.</th><th title="Intermediação (betweenness) normalizada, distância = 1/peso">Interm.</th><th>PageRank</th></tr></thead><tbody>${linhas}</tbody>`;
}

function renderSimilitude() {
  const r = tm.sl;
  $('#sl-info').textContent = `(${r.n_formas} formas · ${r.n_arestas} arestas · ${fmtNum(r.segmentos)} segmentos · ${r.ferramenta_equivalente})`;
  $('#sl-aviso').hidden = !r.mensagem;
  $('#sl-aviso').textContent = r.mensagem || '';
  desenharGrafoSl(); renderTabelaSl();
}

async function carregarSimilitude() {
  if (!slugAtual || !rx.resumo) return;
  const seq = ++tm.seq.sl;
  const p = paramsSimilitude();
  $('#sl-csv-nos').href = rxUrl('similitude/nos.csv', p);
  $('#sl-csv-arestas').href = rxUrl('similitude/arestas.csv', p);
  try {
    const r = await api(rxUrl('similitude', p));
    if (seq !== tm.seq.sl) return;
    tm.sl = r;
    renderSimilitude();
  } catch (e) {
    if (seq !== tm.seq.sl) return;
    tm.sl = null;
    for (const id of ['#sl-grafo', '#sl-comms', '#tab-sl-nos']) $(id).innerHTML = '';
    $('#sl-info').textContent = ''; $('#sl-mod').textContent = '';
    $('#sl-aviso').hidden = false; $('#sl-aviso').textContent = e.message;
  }
}

function dicaSl(ev) {
  const dica = $('#sl-dica'), r = tm.sl;
  const g = ev.target.closest('#sl-grafo g[data-no]');
  if (!g || !r) { dica.hidden = true; return; }
  const n = r.nos.find((x) => x.forma === g.dataset.no);
  if (!n) { dica.hidden = true; return; }
  dica.hidden = false;
  dica.innerHTML = `<b>${esc(n.forma)}</b> <span class="discreto">(freq ${fmtNum(n.freq)} · ${fmtNum(n.n_st)} segmentos)</span><br>comunidade ${n.comunidade ?? '—'} · grau ${n.grau} · grau pond. ${fmtNum(n.grau_ponderado, 2)}<br>intermediação ${fmtNum(n.intermediacao, 3)} · PageRank ${fmtNum(n.pagerank, 3)}`;
  dica.style.left = Math.min(ev.clientX + 14, window.innerWidth - 270) + 'px';
  dica.style.top = Math.min(ev.clientY + 14, window.innerHeight - 90) + 'px';
}

// ---------- ganchos (chamados por textometria.js) ----------

function carregarTematico() { carregarReinert(); carregarSimilitude(); }

function limparTematico() {
  tm.rn = tm.sl = null; tm.rnParams = null;
  for (const id of ['#rn-dendro', '#rn-colunas', '#rn-afc', '#rn-segmentos', '#sl-grafo', '#sl-comms', '#tab-sl-nos']) $(id).innerHTML = '';
  for (const id of ['#rn-info', '#sl-info', '#sl-mod', '#rn-afc-info']) $(id).textContent = '';
}

function aoMudarSelecaoTematico() {
  if (tm.sl) desenharGrafoSl();
  if (tm.rn) desenharAfcReinert();
}

$('#rn-calcular').addEventListener('click', () => { lerControlesReinert(); carregarReinert(); });
$('#rn-dupla').addEventListener('change', () => { lerControlesReinert(); carregarReinert(); });
$('#rn-dendro').addEventListener('click', (ev) => {
  const g = ev.target.closest('g[data-classe]');
  if (!g) return;
  const col = document.querySelectorAll('#rn-colunas .rn-col')[+g.dataset.classe - 1];
  if (col) col.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
});
$('#sl-calcular').addEventListener('click', carregarSimilitude);
for (const id of ['#sl-indice', '#sl-arvore', '#sl-n']) $(id).addEventListener('change', carregarSimilitude);
$('#sl-com').addEventListener('change', () => { if (tm.sl) { desenharGrafoSl(); renderTabelaSl(); } });
$('#sl-grafo').addEventListener('mousemove', dicaSl);
$('#sl-grafo').addEventListener('mouseleave', () => { $('#sl-dica').hidden = true; });
