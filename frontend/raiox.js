// Raio-x descritivo (Frente 5): resumo, frequências, tendências, KWIC e colocações; comparação entre grupos (keyness, 6.1). Funcional, sem polimento (layout Voyant = Frente 10.2).
// Usa $, esc, api, fmtNum e slugAtual de app.js (carregado antes).
const rx = { termos: [], resumo: null, hits: [], total: 0, projeto: null, tamanhoPagina: 200, seq: { freq: 0, tend: 0, kwic: 0, col: 0, key: 0 } };
const MAX_TERMOS = 6;
const cor = (i) => `var(--c${(i % MAX_TERMOS) + 1})`;

function rxUrl(caminho, extra) {
  const q = new URLSearchParams(extra || {});
  return `/api/projetos/${slugAtual}/analises/${caminho}?${q}`;
}

function rxEscopo() {
  const e = $('#rx-escopo').value;
  return e === 'corpus' ? { escopo: 'corpus' } : { escopo: e, valor: $('#rx-valor').value };
}

function rxMensagemTabela(corpo, colunas, texto) {
  corpo.innerHTML = `<tr><td colspan="${colunas}" class="discreto">${esc(texto)}</td></tr>`;
}

// ---------- resumo ----------

function termoHtml(t, por) {
  const sel = rx.termos.includes(t) ? ' sel' : '';
  return `<span class="termo${sel}" data-term="${esc(t)}"${por ? ` data-por="${por}"` : ''}>${esc(t)}</span>`;
}

function docLink(d) {
  return `<a href="#" class="doc-link" data-rx-doc="${d.documento_id}">${esc(d.rotulo)}</a>`;
}

function renderResumo() {
  const r = rx.resumo, c = r.corpus;
  const m = (x, d) => (x == null ? '—' : fmtNum(x, d));
  const lista = (itens, f) => itens.map((d) => `${docLink(d)} <span class="discreto">(${f(d)})</span>`).join(', ') || '—';
  $('#rx-resumo-info').textContent = `(${c.n_documentos} documentos; tokens = palavras do corpo, sem referências)`;
  $('#rx-resumo').innerHTML = `
    <div><span class="num"><b>${fmtNum(c.n_documentos)}</b>documentos</span>
      <span class="num"><b>${fmtNum(c.tokens)}</b>tokens (corpo)</span>
      <span class="num"><b>${fmtNum(c.tokens_total)}</b>tokens (total)</span>
      <span class="num"><b>${fmtNum(c.tipos_lema)}</b>tipos (lema)</span>
      <span class="num"><b>${fmtNum(c.tipos_forma)}</b>tipos (forma)</span>
      <span class="num" title="tipos / tokens; depende do tamanho do texto"><b>${m(c.densidade_forma, 3)}</b>densidade</span>
      <span class="num" title="Média móvel (janela ${c.mattr_janela}) dos documentos com pelo menos ${c.mattr_janela} tokens: ${c.mattr_documentos_comparaveis}"><b>${m(c.mattr_media, 3)}</b>MATTR médio</span>
      <span class="num"><b>${m(c.media_tokens, 0)}</b>média/doc</span>
      <span class="num"><b>${m(c.mediana_tokens, 0)}</b>mediana/doc</span></div>
    <h5>Termos mais frequentes (lema, sem palavras vazias)</h5>
    <div>${c.top_termos.map((t) => `${termoHtml(t.termo, 'lema')} <span class="discreto">(${fmtNum(t.freq)})</span>`).join(', ')}</div>
    <h5>Mais longos</h5><div>${lista(c.mais_longos, (d) => fmtNum(d.tokens))}</div>
    <h5>Mais curtos</h5><div>${lista(c.mais_curtos, (d) => fmtNum(d.tokens))}</div>
    <h5>Maior MATTR</h5><div>${lista(c.maior_mattr, (d) => fmtNum(d.mattr, 3))}</div>
    <h5>Menor MATTR</h5><div>${lista(c.menor_mattr, (d) => fmtNum(d.mattr, 3))}</div>
    <h5>Documentos por ano</h5><div>${c.documentos_por_ano.map((a) => `${esc(a.ano)}: <b>${a.documentos}</b>`).join(' · ') || '—'}</div>
    <h5>Documentos por grupo</h5><div>${c.documentos_por_grupo.map((g) => `${esc(g.grupo)}: <b>${g.documentos}</b>`).join(' · ') || '—'}</div>`;
  $('#tab-resumo-docs tbody').innerHTML = r.documentos.map((d) =>
    `<tr><td>${docLink(d)}</td><td>${d.paginas ?? '—'}</td><td>${fmtNum(d.tokens)}</td><td>${fmtNum(d.tipos_lema)}</td>
     <td title="${d.mattr_ttr ? 'menos de ' + c.mattr_janela + ' tokens: razão tipo/ocorrência simples (não comparável)' : ''}">${d.mattr == null ? '—' : fmtNum(d.mattr, 3)}${d.mattr_ttr ? '*' : ''}</td>
     <td>${d.pct_corpo == null ? '—' : fmtNum(d.pct_corpo, 1) + '%'}</td>
     <td>${d.termos_distintivos.map((t) => termoHtml(t.termo, 'lema')).join(', ')}</td></tr>`).join('')
    || '<tr><td colspan="7" class="discreto">Sem documentos.</td></tr>';
}

function preencherValores() {
  const e = $('#rx-escopo').value, r = rx.resumo;
  $('#rx-valor-rotulo').hidden = e === 'corpus';
  const opcoes = e === 'documento' ? r.documentos.map((d) => [d.documento_id, d.rotulo])
    : e === 'grupo' ? r.corpus.documentos_por_grupo.map((g) => [g.grupo, g.grupo])
    : e === 'ano' ? r.corpus.documentos_por_ano.map((a) => [a.ano, a.ano]) : [];
  $('#rx-valor').innerHTML = opcoes.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join('');
}

// ---------- seleção de termos ----------

function atualizarSelecao(recarregar) {
  $('#rx-termos').value = rx.termos.join(', ');
  $('#rx-q').value = rx.termos.join(', ');
  $('#rx-col-q').value = rx.termos[0] || '';
  $('#rx-chips').innerHTML = rx.termos.map((t, i) =>
    `<span class="chip"><i style="background:${cor(i)}"></i>${esc(t)} <a href="#" data-remover="${esc(t)}" title="Remover" aria-label="Remover ${esc(t)}">×</a></span>`).join('');
  document.querySelectorAll('#raiox .termo').forEach((el) => el.classList.toggle('sel', rx.termos.includes(el.dataset.term)));
  if (typeof desenharCirrus === 'function') desenharCirrus();
  if (typeof aoMudarSelecao === 'function') aoMudarSelecao();
  if (recarregar) recarregarPaineis(['tend', 'kwic', 'col']);
}

function escolherTermo(termo, somar) {
  if (somar) {
    rx.termos = rx.termos.includes(termo) ? rx.termos.filter((t) => t !== termo) : [...rx.termos, termo].slice(-MAX_TERMOS);
  } else {
    rx.termos = [termo];
  }
  atualizarSelecao(true);
}

function termosDoCampo() {
  return $('#rx-termos').value.split(',').map((t) => t.trim()).filter(Boolean).slice(0, MAX_TERMOS);
}

// ---------- frequências ----------

async function carregarFrequencias() {
  if (!slugAtual || !rx.resumo) return;
  const corpo = $('#tab-freq tbody'), seq = ++rx.seq.freq;
  const limiteTabela = +$('#rx-freq-limite').value;
  const q = { por: $('#rx-por').value, vazias: $('#rx-vazias').value, limite: limiteTabela, filtro: $('#rx-freq-filtro').value.trim(), ...rxEscopo() };
  $('#rx-freq-csv').href = rxUrl('frequencias.csv', { ...q, limite: 5000 });
  try {
    // Busca ao menos 200 termos: o Cirrus usa os primeiros N (controle deslizante) e a tabela só o limite escolhido.
    const r = await api(rxUrl('frequencias', { ...q, limite: Math.max(limiteTabela, 200) }));
    if (seq !== rx.seq.freq) return;
    rx.freq = r;
    if (typeof desenharCirrus === 'function') desenharCirrus();
    $('#rx-freq-info').textContent = `(${fmtNum(r.tipos)} termos · ${fmtNum(r.tokens)} palavras contadas · ${r.documentos} doc.)`;
    corpo.innerHTML = r.itens.slice(0, limiteTabela).map((t, i) =>
      `<tr><td>${i + 1}</td><td>${termoHtml(t.termo)}</td><td>${fmtNum(t.freq)}</td><td>${fmtNum(t.por_10k, 1)}</td><td>${t.docs}</td></tr>`).join('')
      || '<tr><td colspan="5" class="discreto">Sem termos.</td></tr>';
  } catch (e) {
    rx.freq = null;
    if (typeof desenharCirrus === 'function') desenharCirrus();
    $('#rx-freq-info').textContent = '';
    rxMensagemTabela(corpo, 5, e.message);
  }
}

// ---------- tendências ----------

let ultimaTendencia = null;

async function carregarTendencias() {
  if (!slugAtual || !rx.resumo) return;
  const seq = ++rx.seq.tend;
  if (!rx.termos.length) { ultimaTendencia = null; desenharGrafico(); return; }
  try {
    const r = await api(rxUrl('tendencias', { termos: rx.termos.join(','), por: $('#rx-por').value, agrupar: $('#rx-agrupar').value, metrica: $('#rx-metrica').value }));
    if (seq !== rx.seq.tend) return;
    ultimaTendencia = r;
    $('#rx-tend-info').textContent = `(${r.categorias.length} ${r.agrupar === 'documento' ? 'documentos' : r.agrupar === 'ano' ? 'anos' : 'grupos'})`;
  } catch (e) {
    ultimaTendencia = null;
    $('#rx-tend-info').textContent = e.message;
  }
  desenharGrafico();
}

function desenharGrafico() {
  const el = $('#rx-grafico'), dica = $('#rx-dica'), r = ultimaTendencia;
  const W = el.clientWidth, H = el.clientHeight;
  $('#rx-legenda').innerHTML = r ? r.series.map((s, k) => `<span class="chip"><i style="background:${cor(k)}"></i>${esc(s.termo)}</span>`).join('') : '';
  if (!W) return;
  if (!r || !r.categorias.length) { el.innerHTML = '<p class="discreto" style="padding:10px">Selecione um termo (clique numa palavra das tabelas).</p>'; return; }
  const cats = r.categorias, rel = r.metrica === 'rel';
  const ymax = Math.max(1e-9, ...r.series.flatMap((s) => s.valores));
  const m = { l: 46, r: 12, t: 12, b: 30 }, iw = Math.max(10, W - m.l - m.r), ih = H - m.t - m.b;
  const X = (i) => m.l + (cats.length === 1 ? iw / 2 : (i / (cats.length - 1)) * iw);
  const Y = (v) => m.t + ih - (v / ymax) * ih;
  const passo = Math.max(1, Math.ceil((cats.length * 30) / iw));
  const curto = (c) => (r.agrupar === 'documento' ? c.rotulo.split(' · ')[0] : c.rotulo);
  let g = '';
  for (let k = 0; k <= 4; k++) {
    const v = (ymax * k) / 4, y = Y(v);
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" stroke="var(--borda)"/><text x="${m.l - 6}" y="${y + 3}" text-anchor="end">${fmtNum(v, v < 10 && rel ? 1 : 0)}</text>`;
  }
  cats.forEach((c, i) => {
    const ancora = cats.length > 1 && i === cats.length - 1 ? 'end' : cats.length > 1 && i === 0 ? 'start' : 'middle'; // não corta o rótulo nas bordas
    if (i % passo === 0) g += `<text x="${ancora === 'end' ? Math.min(X(i) + 6, W - 2) : ancora === 'start' ? Math.max(X(i) - 6, 2) : X(i)}" y="${H - m.b + 16}" text-anchor="${ancora}">${esc(curto(c))}</text>`;
  });
  r.series.forEach((s, k) => {
    g += `<polyline fill="none" stroke="${cor(k)}" stroke-width="2" stroke-linejoin="round" points="${s.valores.map((v, i) => `${X(i)},${Y(v)}`).join(' ')}"/>`;
    if (cats.length <= 80) s.valores.forEach((v, i) => { g += `<circle cx="${X(i)}" cy="${Y(v)}" r="2.5" fill="${cor(k)}"/>`; });
  });
  const larg = cats.length > 1 ? iw / (cats.length - 1) : iw;
  cats.forEach((c, i) => { g += `<rect class="hov" data-i="${i}" x="${X(i) - larg / 2}" y="${m.t}" width="${larg}" height="${ih}" fill="transparent"/>`; });
  el.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="Tendência dos termos selecionados">${g}<line id="rx-cursor" y1="${m.t}" y2="${m.t + ih}" stroke="var(--suave)" stroke-dasharray="3 3" style="display:none"/></svg>`;
  const cursor = $('#rx-cursor');
  el.querySelectorAll('rect.hov').forEach((rc) => {
    const i = +rc.dataset.i;
    rc.addEventListener('mousemove', (ev) => {
      dica.hidden = false;
      dica.innerHTML = `<b>${esc(cats[i].rotulo)}</b> <span class="discreto">(${fmtNum(cats[i].tokens)} palavras)</span><br>` +
        r.series.map((s, k) => `<span style="color:${cor(k)}">●</span> ${esc(s.termo)}: ${fmtNum(s.rel[i], 2)} / 10 mil <span class="discreto">(${fmtNum(s.brutos[i])}×)</span>`).join('<br>');
      dica.style.left = Math.min(ev.clientX + 14, window.innerWidth - 270) + 'px';
      dica.style.top = (ev.clientY + 14) + 'px';
      cursor.setAttribute('x1', X(i)); cursor.setAttribute('x2', X(i)); cursor.style.display = '';
    });
    rc.addEventListener('mouseleave', () => { dica.hidden = true; cursor.style.display = 'none'; });
  });
}

let timerResize = null;
window.addEventListener('resize', () => { clearTimeout(timerResize); timerResize = setTimeout(desenharGrafico, 150); });

// ---------- KWIC ----------

function paramsKwic(extra) {
  return { q: $('#rx-q').value.trim(), por: $('#rx-por').value, janela: $('#rx-janela').value, ordem: $('#rx-ordem').value,
    incluir_excluidas: $('#rx-excluidas').checked, quebrar: $('#rx-ng-quebrar').checked, ...rxEscopo(), ...extra };
}

function linhaKwic(h, n) {
  const pag = h.pagina == null ? '' : h.pagina;
  const marca = h.ruido ? ` <span class="selo-ruido" title="Segmento marcado como ruído (${esc(h.ruido)}): fora da CHD, da similitude e dos n-gramas">ruído</span>` : '';
  return `<tr class="hit${h.ruido ? ' ruido' : ''}" data-n="${n}"><td title="${esc(h.arquivo)}">${esc(h.rotulo)}${marca}</td><td>${pag}</td>
    <td class="esq">${esc(h.esquerda)}</td><td class="kw">${esc(h.termo)}</td><td>${esc(h.direita)}</td></tr>`;
}

async function buscarKwic(reiniciar) {
  if (!slugAtual || !rx.resumo) return;
  const corpo = $('#tab-kwic tbody'), seq = ++rx.seq.kwic, q = $('#rx-q').value.trim();
  $('#rx-kwic-csv').href = rxUrl('kwic.csv', paramsKwic());
  if (!q) { corpo.innerHTML = ''; $('#rx-kwic-info').textContent = ''; $('#rx-kwic-mais').hidden = true; rx.hits = []; return; }
  if (reiniciar) { rx.hits = []; }
  try {
    const r = await api(rxUrl('kwic', paramsKwic({ offset: rx.hits.length, limit: rx.tamanhoPagina })));
    if (seq !== rx.seq.kwic) return;
    rx.hits = rx.hits.concat(r.itens);
    rx.total = r.total;
    corpo.innerHTML = rx.hits.map(linhaKwic).join('') ||
      `<tr><td colspan="5" class="discreto">Nenhuma ocorrência${r.por === 'lema' ? ' (por lema: digite o lema, ex.: agent, ou use agent*)' : ''}.</td></tr>`;
    const formas = r.formas.slice(0, 8).map((f) => f.forma).join(', ');
    $('#rx-kwic-info').textContent = `(${fmtNum(r.total)} ocorrências em ${r.documentos_com_ocorrencias} documento(s)` +
      (formas ? ` · formas: ${formas}${r.formas.length > 8 ? '…' : ''}` : '') + (rx.hits.length < r.total ? ` · mostrando ${rx.hits.length}` : '') + ')';
    $('#rx-kwic-mais').hidden = rx.hits.length >= r.total;
  } catch (e) {
    rxMensagemTabela(corpo, 5, e.message);
    $('#rx-kwic-info').textContent = '';
    $('#rx-kwic-mais').hidden = true;
  }
}

async function copiar(texto) {
  try { await navigator.clipboard.writeText(texto); return true; } catch { /* tenta o método antigo */ }
  const ta = document.createElement('textarea');
  ta.value = texto; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  ta.remove();
  return ok;
}

async function alternarContexto(tr) {
  const prox = tr.nextElementSibling;
  if (prox && prox.classList.contains('exp')) { prox.remove(); return; }
  const h = rx.hits[+tr.dataset.n];
  const linha = document.createElement('tr');
  linha.className = 'exp';
  linha.innerHTML = '<td colspan="5" class="discreto">Carregando contexto…</td>';
  tr.after(linha);
  try {
    const r = await api(rxUrl('kwic/contexto', { documento_id: h.documento_id, posicao: h.posicao, janela: 60, incluir_excluidas: $('#rx-excluidas').checked }));
    linha.innerHTML = `<td colspan="5">…${esc(r.esquerda)}<mark>${esc(r.termo)}</mark>${esc(r.direita)}… <span class="discreto">${esc(r.citacao)}</span>
      <div style="margin-top:6px"><button type="button" class="sec" data-copiar>Copiar trecho com citação</button>
      <span class="discreto">${esc(r.arquivo)} · seção: ${esc(r.secao)}</span></div></td>`;
    linha.querySelector('[data-copiar]').addEventListener('click', async (ev) => {
      ev.stopPropagation();
      ev.target.textContent = (await copiar(r.citacao_completa)) ? 'Copiado ✓' : 'Não foi possível copiar';
    });
  } catch (e) {
    linha.innerHTML = `<td colspan="5" class="discreto">${esc(e.message)}</td>`;
  }
}

// ---------- colocações (5.4) ----------

let ultimaColocacao = null;

function paramsColocacoes(extra) {
  return { q: $('#rx-col-q').value.trim(), por: $('#rx-por').value, esquerda: $('#rx-col-esq').value, direita: $('#rx-col-dir').value,
    ordem: $('#rx-col-ordem').value, min_freq: $('#rx-col-min').value, min_freq_colocado: $('#rx-col-minc').value,
    vazias: $('#rx-vazias').value, ...rxEscopo(), ...extra };
}

function perfilHtml(c, esq, dir) {
  const vals = [];
  for (let r = -esq; r <= dir; r++) if (r) vals.push([r, c.posicoes[String(r)] || 0]);
  const max = Math.max(1, ...vals.map((v) => v[1]));
  const barras = vals.map(([r, v]) => `<i class="${r > 0 ? 'dir' : ''}" style="height:${Math.round((v / max) * 18)}px" title="${r > 0 ? 'R' + r : 'L' + -r}: ${v}"></i>`);
  barras.splice(esq, 0, '<b title="nó"></b>');
  return `<span class="perfil" aria-label="Perfil por posição">${barras.join('')}</span>`;
}

async function carregarColocacoes() {
  if (!slugAtual || !rx.resumo) return;
  const corpo = $('#tab-col tbody'), seq = ++rx.seq.col, q = $('#rx-col-q').value.trim();
  $('#rx-col-csv').href = rxUrl('colocacoes.csv', paramsColocacoes({ limite: 1000 }));
  if (!q) { ultimaColocacao = null; corpo.innerHTML = ''; $('#rx-col-info').textContent = ''; desenharRede(); return; }
  try {
    const r = await api(rxUrl('colocacoes', paramsColocacoes({ limite: 100 })));
    if (seq !== rx.seq.col) return;
    ultimaColocacao = r;
    const p = r.parametros;
    $('#rx-col-info').textContent = `(nó: ${r.no.termos.join(', ')} · ${fmtNum(r.ocorrencias_no)} ocorrências em ${r.documentos_com_no} doc. · ` +
      `janela ${p.esquerda}E/${p.direita}D · R1 = ${fmtNum(r.R1)} posições · N = ${fmtNum(r.N)} · ${fmtNum(r.total_candidatos)} colocados)`;
    corpo.innerHTML = r.colocados.map((c, i) =>
      `<tr${rx.termos.includes(c.termo) ? ' class="sel"' : ''}><td>${i + 1}</td><td>${termoHtml(c.termo)}</td><td>${fmtNum(c.o11)}</td>
       <td title="p = ${c.p.toExponential(2)}">${fmtNum(c.ll, 1)}</td><td>${fmtNum(c.mi, 2)}</td><td>${fmtNum(c.logdice, 2)}</td>
       <td>${fmtNum(c.c1)}</td><td>${perfilHtml(c, p.esquerda, p.direita)}</td></tr>`).join('')
      || `<tr><td colspan="8" class="discreto">Nenhum colocado com esses limiares${r.ocorrencias_no ? '' : ' (o nó não ocorre no escopo)'}.</td></tr>`;
  } catch (e) {
    ultimaColocacao = null;
    $('#rx-col-info').textContent = '';
    rxMensagemTabela(corpo, 8, e.message);
  }
  desenharRede();
}

function desenharRede() {
  const el = $('#rx-col-rede'), r = ultimaColocacao;
  const W = el.clientWidth, H = el.clientHeight;
  if (!W) return;
  const top = r ? r.colocados.filter((c) => c.ll > 0).slice(0, 12) : [];
  if (!top.length) { el.innerHTML = '<p class="discreto" style="padding:10px">Sem colocados para desenhar.</p>'; return; }
  // Disposição determinística: colocados em círculo, os mais fortes (LL) mais perto do nó.
  // Elipse com folga para os rótulos à esquerda/direita.
  const cx = W / 2, cy = H / 2, rx_ = Math.max(40, W / 2 - 95), ry = Math.max(40, H / 2 - 30);
  const maxLL = top[0].ll, maxC = Math.max(...top.map((c) => c.c1));
  const pts = top.map((c, i) => {
    const ang = -Math.PI / 2 + (2 * Math.PI * i) / top.length;
    const f = 0.55 + 0.45 * (i / Math.max(1, top.length - 1));
    return { c, x: cx + f * rx_ * Math.cos(ang), y: cy + f * ry * Math.sin(ang) };
  });
  let g = pts.map((p) => `<line x1="${cx}" y1="${cy}" x2="${p.x}" y2="${p.y}" stroke="var(--c1)" stroke-opacity=".45" stroke-width="${(1 + 6 * p.c.ll / maxLL).toFixed(1)}"><title>${esc(r.no.termos.join(', '))} — ${esc(p.c.termo)}: LL ${fmtNum(p.c.ll, 1)}, freq ${p.c.o11}</title></line>`).join('');
  g += pts.map((p) => {
    const rr = 4 + 8 * Math.sqrt(p.c.c1 / maxC);
    const ancora = p.x < cx - 5 ? 'end' : p.x > cx + 5 ? 'start' : 'middle';
    const dx = ancora === 'end' ? -rr - 3 : ancora === 'start' ? rr + 3 : 0, dy = ancora === 'middle' ? -rr - 4 : 4;
    return `<g data-term="${esc(p.c.termo)}" class="termo-rede"><circle cx="${p.x}" cy="${p.y}" r="${rr}" fill="var(--c2)" fill-opacity=".8"/>` +
      `<text x="${p.x + dx}" y="${p.y + dy}" text-anchor="${ancora}">${esc(p.c.termo)}</text></g>`;
  }).join('');
  g += `<circle cx="${cx}" cy="${cy}" r="13" fill="var(--c1)"/><text x="${cx}" y="${cy - 18}" text-anchor="middle" style="font-weight:700;font-size:13px">${esc(r.no.termos.join(', '))}</text>`;
  el.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="Rede do nó com os colocados mais fortes">${g}</svg>`;
}

window.addEventListener('resize', () => { clearTimeout(timerResize); timerResize = setTimeout(() => { desenharGrafico(); desenharRede(); }, 150); });

// ---------- carga e eventos ----------

async function carregarRaioX() {
  if (!slugAtual) return;
  const novo = rx.projeto !== slugAtual;
  try {
    rx.resumo = await api(rxUrl('resumo'));
  } catch (e) {
    rx.resumo = null;
    $('#rx-status').textContent = `(${e.message})`;
    $('#rx-resumo').innerHTML = '<span class="discreto">Execute o pipeline do projeto para ver o raio-x descritivo.</span>';
    for (const id of ['#tab-resumo-docs', '#tab-freq', '#tab-kwic', '#tab-col', '#tab-ng']) $(id + ' tbody').innerHTML = '';
    for (const id of ['#tab-key-a', '#tab-key-b']) $(id).innerHTML = '';
    $('#rx-key-info').textContent = '';
    $('#rx-grafico').innerHTML = '';
    rx.freq = null;
    if (typeof desenharCirrus === 'function') desenharCirrus();
    if (typeof limparSimilaridade === 'function') limparSimilaridade();
    if (typeof limparDicionario === 'function') limparDicionario();
    if (typeof limparTextometria === 'function') limparTextometria();
    return;
  }
  rx.projeto = slugAtual; // só depois de existir resumo: assim a seleção inicial acontece na primeira execução do projeto
  $('#rx-status').textContent = '';
  renderResumo();
  if (novo) {
    $('#rx-escopo').value = 'corpus';
    rx.termos = rx.resumo.corpus.top_termos.length ? [rx.resumo.corpus.top_termos[0].termo] : [];
    api(`/api/projetos/${slugAtual}/parametros`).then((p) => {
      const j = Math.min(40, Math.max(2, p.kwic_janela || 10));
      $('#rx-janela').value = j; $('#rx-janela-valor').textContent = j;
      const c = Math.min(20, Math.max(1, p.colocacao_janela || 5));
      $('#rx-col-esq').value = c; $('#rx-col-dir').value = c;
      carregarColocacoes();
    }).catch(() => {});
  }
  const valorAntigo = $('#rx-valor').value;
  preencherValores();
  if ([...$('#rx-valor').options].some((o) => o.value === valorAntigo)) $('#rx-valor').value = valorAntigo;
  atualizarSelecao(false);
  rx.carregada = {};
  mostrarSub(rx.sub, true); // só a sub-aba aberta carrega os dados; as outras carregam ao abrir (10.3)
}

// ---------- sub-abas temáticas (10.3): carga preguiçosa e lembrança da sub-aba ----------

const SUBS = {
  descritivo: ['freq', 'tend', 'kwic', 'ng'],
  comparativo: ['key', 'simil', 'dic', 'esp'],
  tematico: ['afc', 'tem'],
  associacoes: ['col', 'tc'],
};
const CARREGADORES = {
  freq: () => carregarFrequencias(), tend: () => carregarTendencias(), kwic: () => buscarKwic(true), ng: () => carregarNgramas(true),
  key: () => carregarLadosKeyness(), simil: () => typeof carregarSimilaridade === 'function' && carregarSimilaridade(),
  dic: () => typeof carregarDicionario === 'function' && carregarDicionario(),
  esp: () => typeof carregarEspecificidades === 'function' && carregarEspecificidades(),
  afc: () => typeof carregarAfc === 'function' && carregarAfc(),
  tem: () => typeof carregarTematico === 'function' && carregarTematico(),
  col: () => carregarColocacoes(), tc: () => carregarTermosCompostos(),
};
rx.sub = (() => { try { const v = localStorage.getItem('raiox.subaba'); return SUBS[v] ? v : 'descritivo'; } catch { return 'descritivo'; } })();
rx.carregada = {};

// Recarrega os painéis indicados (chaves de CARREGADORES) na sub-aba aberta e marca as demais como desatualizadas.
function recarregarPaineis(chaves) {
  for (const sub of Object.keys(SUBS)) {
    const dela = SUBS[sub].filter((k) => chaves.includes(k));
    if (!dela.length) continue;
    if (sub === rx.sub) dela.forEach((k) => CARREGADORES[k]());
    else rx.carregada[sub] = false;
  }
}

function mostrarSub(nome, recarregarTudo) {
  if (!SUBS[nome]) nome = 'descritivo';
  rx.sub = nome;
  try { localStorage.setItem('raiox.subaba', nome); } catch { /* sem armazenamento: segue sem lembrar */ }
  const DESC = {
    descritivo: 'Frequências, tendências, n-gramas, contextos e resumo do corpus.',
    comparativo: 'Keyness, especificidades, similaridade entre documentos e dicionário: comparam grupos, anos e documentos.',
    tematico: 'Classes (Reinert), AFC e similitude: a estrutura temática do corpus.',
    associacoes: 'Links e colocações do termo escolhido e termos compostos.',
  };
  $('#rx-sub-desc').textContent = DESC[nome];
  const grade = $('.grade-an');
  if (grade) grade.dataset.sub = nome;
  document.querySelectorAll('#rx-subabas button').forEach((b) => {
    b.classList.toggle('on', b.dataset.sub === nome);
    b.setAttribute('aria-selected', b.dataset.sub === nome ? 'true' : 'false');
  });
  if (rx.resumo && (recarregarTudo || !rx.carregada[nome])) {
    rx.carregada[nome] = true;
    SUBS[nome].forEach((k) => CARREGADORES[k]());
  }
  if (typeof redesenharPaineis === 'function') setTimeout(redesenharPaineis, 0);
}

document.querySelectorAll('#rx-subabas button').forEach((b) => b.addEventListener('click', () => mostrarSub(b.dataset.sub)));

$('#raiox').addEventListener('click', (ev) => {
  const t = ev.target.closest('.termo, g[data-term]');
  if (t) {
    if (t.dataset.por && t.dataset.por !== $('#rx-por').value) { $('#rx-por').value = t.dataset.por; carregarFrequencias(); }
    escolherTermo(t.dataset.term, ev.ctrlKey || ev.shiftKey || ev.metaKey);
    return;
  }
  const rem = ev.target.closest('a[data-remover]');
  if (rem) { ev.preventDefault(); rx.termos = rx.termos.filter((x) => x !== rem.dataset.remover); atualizarSelecao(true); return; }
  const d = ev.target.closest('a[data-rx-doc]');
  if (d) {
    ev.preventDefault();
    $('#rx-escopo').value = 'documento'; preencherValores(); $('#rx-valor').value = d.dataset.rxDoc;
    recarregarPaineis(['freq', 'kwic', 'col', 'ng', 'simil']);
    return;
  }
  const linha = ev.target.closest('#tab-kwic tr.hit');
  if (linha) alternarContexto(linha);
});

$('#rx-usar').addEventListener('click', () => { rx.termos = termosDoCampo(); atualizarSelecao(true); });
$('#rx-termos').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { rx.termos = termosDoCampo(); atualizarSelecao(true); } });
$('#rx-por').addEventListener('change', () => recarregarPaineis(['freq', 'tend', 'kwic', 'col', 'ng', 'key', 'esp', 'afc', 'tem']));
$('#rx-escopo').addEventListener('change', () => { preencherValores(); recarregarPaineis(['freq', 'kwic', 'col', 'ng', 'simil']); });
$('#rx-valor').addEventListener('change', () => recarregarPaineis(['freq', 'kwic', 'col', 'ng', 'simil']));
for (const id of ['#rx-freq-limite']) $(id).addEventListener('change', carregarFrequencias);
$('#rx-vazias').addEventListener('change', () => recarregarPaineis(['freq', 'key', 'col', 'esp', 'afc', 'tem']));
let timerFiltro = null;
$('#rx-freq-filtro').addEventListener('input', () => { clearTimeout(timerFiltro); timerFiltro = setTimeout(carregarFrequencias, 250); });
for (const id of ['#rx-agrupar', '#rx-metrica']) $(id).addEventListener('change', carregarTendencias);
let timerJanela = null;
$('#rx-janela').addEventListener('input', () => {
  $('#rx-janela-valor').textContent = $('#rx-janela').value;
  clearTimeout(timerJanela); timerJanela = setTimeout(() => buscarKwic(true), 250);
});
for (const id of ['#rx-ordem', '#rx-excluidas']) $(id).addEventListener('change', () => buscarKwic(true));
$('#rx-kwic-buscar').addEventListener('click', () => buscarKwic(true));
$('#rx-q').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') buscarKwic(true); });
$('#rx-kwic-mais').addEventListener('click', () => buscarKwic(false));
$('#rx-vazias').addEventListener('change', carregarColocacoes);
for (const id of ['#rx-col-esq', '#rx-col-dir', '#rx-col-ordem', '#rx-col-min', '#rx-col-minc']) $(id).addEventListener('change', carregarColocacoes);
$('#rx-col-buscar').addEventListener('click', carregarColocacoes);
$('#rx-col-q').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') carregarColocacoes(); });

// ---------- keyness entre grupos (6.1) ----------

rx.key = { lados: null, ultimo: null };

function paramsKeyness(extra) {
  return { particao: $('#rx-key-part').value, a: $('#rx-key-a').value, b: $('#rx-key-b').value, por: $('#rx-por').value,
    vazias: $('#rx-vazias').value, ordem: $('#rx-key-ordem').value, min_freq: $('#rx-key-min').value,
    min_docs_a: $('#rx-key-docs').value, min_docs_b: $('#rx-key-docs').value, bonferroni: $('#rx-key-bonf').checked, ...extra };
}

function preencherLadosKeyness() {
  const l = rx.key.lados;
  if (!l) return;
  const grupo = $('#rx-key-part').value === 'grupo';
  const itens = grupo ? l.grupos : l.anos;
  const opt = (v, t) => `<option value="${esc(v)}">${esc(t)}</option>`;
  const rotulo = (i) => `${i.valor} (${i.documentos} doc.)`;
  const antigoA = $('#rx-key-a').value, antigoB = $('#rx-key-b').value;
  $('#rx-key-a').innerHTML = itens.map((i) => opt(i.valor, rotulo(i))).join('');
  $('#rx-key-b').innerHTML = opt('resto', 'resto (todos os demais)') + itens.map((i) => opt(i.valor, rotulo(i))).join('');
  const tem = (sel, v) => [...$(sel).options].some((o) => o.value === v);
  const preferido = itens.find((i) => i.valor !== 'sem grupo' && i.valor !== 's/ano') || itens[0];
  $('#rx-key-a').value = tem('#rx-key-a', antigoA) ? antigoA : (preferido ? preferido.valor : '');
  $('#rx-key-b').value = tem('#rx-key-b', antigoB) && antigoB !== $('#rx-key-a').value ? antigoB : 'resto';
}

function barraDivergente(lr, maximo) {
  const w = Math.min(100, Math.abs(lr) / maximo * 100).toFixed(0);
  return `<span class="divbar" title="Log Ratio ${fmtNum(lr, 2)}"><i class="neg" style="width:${lr < 0 ? w : 0}%"></i><b></b><i class="pos" style="width:${lr > 0 ? w : 0}%"></i></span>`;
}

function fmtP(p) { return p < 0.0001 ? p.toExponential(1).replace('.', ',') : fmtNum(p, 4); }

function tabelaKeyness(el, itens, maximo, por, vazio) {
  const cab = `<thead><tr><th>#</th><th>Termo</th><th title="Frequência em A">Freq. A</th><th title="Frequência em B">Freq. B</th>
    <th title="Por 10 mil palavras em A">/10k A</th><th title="Por 10 mil palavras em B">/10k B</th>
    <th title="Log-likelihood G² (2 células)">G²</th><th title="Qui-quadrado, 1 g.l.">p</th>
    <th title="Log2 da razão das frequências relativas (Hardie 2014)">Log Ratio</th><th></th>
    <th title="Documentos de A / de B em que o termo ocorre">Docs A/B</th></tr></thead>`;
  const linhas = itens.map((k, i) =>
    `<tr${rx.termos.includes(k.termo) ? ' class="sel"' : ''}><td>${i + 1}</td><td>${termoHtml(k.termo, por)}</td>
     <td>${fmtNum(k.a)}</td><td>${fmtNum(k.b)}</td><td>${fmtNum(k.por_10k_a, 1)}</td><td>${fmtNum(k.por_10k_b, 1)}</td>
     <td>${fmtNum(Math.abs(k.g2), 1)}</td><td title="p ajustado (Bonferroni) = ${fmtP(k.p_bonferroni)}">${fmtP(k.p)}</td>
     <td title="${k.pct_diff == null ? 'só em ' + (k.so_em_a ? 'A' : 'B') : '%DIFF = ' + fmtNum(k.pct_diff, 0) + '%'}">${fmtNum(k.log_ratio, 2)}${k.so_em_a ? ' <span class="discreto">só A</span>' : k.so_em_b ? ' <span class="discreto">só B</span>' : ''}</td>
     <td>${barraDivergente(k.log_ratio, maximo)}</td><td>${k.docs_a}/${k.docs_b}</td></tr>`).join('');
  el.innerHTML = cab + `<tbody>${linhas || `<tr><td colspan="11" class="discreto">${esc(vazio)}</td></tr>`}</tbody>`;
}

async function carregarKeyness() {
  if (!slugAtual || !rx.resumo) return;
  const seq = ++rx.seq.key;
  const vazioMsg = (t) => { for (const id of ['#tab-key-a', '#tab-key-b']) $(id).innerHTML = `<tbody><tr><td class="discreto">${esc(t)}</td></tr></tbody>`; };
  $('#rx-key-vazio').hidden = !rx.key.lados || rx.key.lados.grupos_definidos >= 2;
  if (!$('#rx-key-a').value) { $('#rx-key-info').textContent = ''; vazioMsg('Sem valores para comparar.'); return; }
  $('#rx-key-csv').href = rxUrl('keyness.csv', paramsKeyness({ limite: 1000 }));
  try {
    const r = await api(rxUrl('keyness', paramsKeyness({ limite: 50 })));
    if (seq !== rx.seq.key) return;
    rx.key.ultimo = r;
    const maximo = Math.max(1, ...[...r.positivas, ...r.negativas].map((k) => Math.abs(k.log_ratio)));
    $('#rx-key-info').textContent = `(A: ${r.lado_a.valor} · ${r.lado_a.documentos} doc. · ${fmtNum(r.lado_a.tokens)} palavras | B: ${r.lado_b.valor} · ` +
      `${r.lado_b.documentos} doc. · ${fmtNum(r.lado_b.tokens)} palavras | ${fmtNum(r.termos_testados)} termos testados, p < ${fmtP(r.limiar_p)})`;
    $('#rx-key-tit-a').textContent = `A (${r.lado_a.valor}) sobre-representado: ${fmtNum(r.total_positivas)} palavras-chave`;
    $('#rx-key-tit-b').textContent = `B (${r.lado_b.valor}) sobre-representado: ${fmtNum(r.total_negativas)} palavras-chave`;
    const por = $('#rx-por').value;
    tabelaKeyness($('#tab-key-a'), r.positivas, maximo, por, 'Nenhuma palavra-chave com esses limiares.');
    tabelaKeyness($('#tab-key-b'), r.negativas, maximo, por, 'Nenhuma palavra-chave com esses limiares.');
  } catch (e) {
    if (seq !== rx.seq.key) return;
    rx.key.ultimo = null;
    $('#rx-key-info').textContent = '';
    vazioMsg(e.message);
  }
}

async function carregarLadosKeyness() {
  try {
    rx.key.lados = await api(rxUrl('grupos'));
  } catch (e) {
    rx.key.lados = null;
  }
  const l = rx.key.lados;
  if (l && l.grupos_definidos < 2 && $('#rx-key-part').value === 'grupo' && l.anos.length >= 2) $('#rx-key-part').value = 'ano';
  preencherLadosKeyness();
  carregarKeyness();
}

$('#rx-key-part').addEventListener('change', () => { preencherLadosKeyness(); carregarKeyness(); });
for (const id of ['#rx-key-a', '#rx-key-b', '#rx-key-ordem', '#rx-key-min', '#rx-key-docs', '#rx-key-bonf']) $(id).addEventListener('change', carregarKeyness);
$('#rx-key-buscar').addEventListener('click', carregarKeyness);


// ---------- termos compostos (4.3) ----------

// A chave do termo composto é o lema ("unite state"); a lista mostra a forma original mais frequente ("United States").
function termoExibido(t) {
  const mostra = t.exibicao || t.termo;
  const sel = rx.termos.includes(t.termo) ? ' sel' : '';
  const lema = mostra.toLowerCase() === t.termo ? '' : ` <span class="discreto">(lema: ${esc(t.termo)})</span>`;
  return `<span class="termo${sel}" data-term="${esc(t.termo)}" data-por="termo">${esc(mostra)}</span>${lema}`;
}

async function carregarTermosCompostos() {
  const tab = $('#tab-tc');
  try {
    const r = await api(rxUrl('termos-compostos', { origem: $('#rx-tc-origem').value, limite: 300 }));
    $('#rx-tc-info').textContent = `(${fmtNum(r.total)} termos${r.ativa ? '' : ', desligados'} · ${r.bloqueados.length} bloqueados)`;
    $('#rx-tc-aviso').textContent = r.desatualizado ? 'Parâmetros alterados: execute o pipeline para aplicar.' : '';
    const linhas = r.itens.map((t) => `<tr><td>${termoExibido(t)}</td><td class="num">${fmtNum(t.freq ?? 0)}</td><td class="num">${fmtNum(t.docs ?? 0)}</td>
      <td class="num">${t.score == null ? '—' : t.score.toFixed(1)}</td><td>${esc(t.origem)}</td>
      <td>${t.origem === 'automatico' ? `<button type="button" data-tc="aceitar" data-termo="${esc(t.termo)}">Aceitar</button> ` : ''}<button type="button" data-tc="bloquear" data-termo="${esc(t.termo)}">Bloquear</button></td></tr>`);
    const bloq = r.bloqueados.map((t) => `<tr class="discreto"><td>${esc(t)}</td><td colspan="3"></td><td>bloqueado</td><td><button type="button" data-tc="desbloquear" data-termo="${esc(t)}">Desbloquear</button></td></tr>`);
    tab.innerHTML = '<tr><th>Termo</th><th>Freq.</th><th>Docs</th><th>Escore (G²)</th><th>Origem</th><th></th></tr>'
      + ([...linhas, ...bloq].join('') || '<tr><td colspan="6" class="discreto">Nenhum termo composto (execute o pipeline).</td></tr>');
  } catch (e) {
    tab.innerHTML = `<tr><td class="discreto">${esc(e.message)}</td></tr>`;
    $('#rx-tc-info').textContent = '';
  }
}

async function editarTermosCompostos(corpo) {
  try {
    const r = await api(`/api/projetos/${slugAtual}/analises/termos-compostos`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo),
    });
    $('#rx-tc-aviso').textContent = r.mensagem;
    carregarTermosCompostos();
  } catch (e) {
    $('#rx-tc-aviso').textContent = e.message;
  }
}

$('#tab-tc').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-tc]');
  if (b) editarTermosCompostos({ [b.dataset.tc]: [b.dataset.termo] });
});
$('#rx-tc-origem').addEventListener('change', carregarTermosCompostos);
$('#rx-tc-add').addEventListener('click', () => {
  const t = $('#rx-tc-novo').value.trim();
  if (t) { editarTermosCompostos({ aceitar: [t] }); $('#rx-tc-novo').value = ''; }
});


// ---------- n-gramas (5.5) ----------

const ng = { itens: [], total: 0, seq: 0, tamanhoPagina: 200 };

function paramsNgramas(extra) {
  return { por: $('#rx-ng-por').value, n_min: $('#rx-ng-nmin').value, n_max: $('#rx-ng-nmax').value, stop: $('#rx-ng-stop').value,
    quebrar: $('#rx-ng-quebrar').checked, min_freq: Math.max(1, +$('#rx-ng-minf').value || 1), min_docs: Math.max(1, +$('#rx-ng-mind').value || 1),
    contem: $('#rx-ng-contem').value.trim(), posicao: $('#rx-ng-pos').value, ordem: $('#rx-ng-ordem').value, ...rxEscopo(), ...extra };
}

function linhaNgrama(g, i) {
  return `<tr class="hit" data-i="${i}" title="Abrir nos contextos (KWIC)"><td>${i + 1}</td><td>${esc(g.ngrama)}</td><td>${g.n}</td><td>${fmtNum(g.freq)}</td>
    <td>${fmtNum(g.por_10k, 1)}</td><td>${g.docs}</td><td>${fmtNum(g.concentracao * 100, 0)}%</td></tr>`;
}

async function carregarNgramas(reiniciar) {
  if (!slugAtual || !rx.resumo) return;
  if (+$('#rx-ng-nmin').value > +$('#rx-ng-nmax').value) $('#rx-ng-nmax').value = $('#rx-ng-nmin').value;
  const corpo = $('#tab-ng tbody'), seq = ++ng.seq;
  $('#rx-ng-csv').href = rxUrl('ngramas.csv', paramsNgramas({ limite: 5000 }));
  if (reiniciar) ng.itens = [];
  if (reiniciar) rxMensagemTabela(corpo, 7, 'Calculando…');
  try {
    const r = await api(rxUrl('ngramas', paramsNgramas({ offset: ng.itens.length, limite: ng.tamanhoPagina })));
    if (seq !== ng.seq) return;
    ng.itens = ng.itens.concat(r.itens);
    ng.total = r.total;
    corpo.innerHTML = ng.itens.map(linhaNgrama).join('') || '<tr><td colspan="7" class="discreto">Nenhum n-grama com esses filtros.</td></tr>';
    $('#rx-ng-info').textContent = `(${fmtNum(r.total)} n-gramas · ${fmtNum(r.tokens)} palavras · ${r.documentos} doc.` +
      (ng.itens.length < r.total ? ` · mostrando ${fmtNum(ng.itens.length)}` : '') + ')';
    $('#rx-ng-mais').hidden = ng.itens.length >= r.total;
  } catch (e) {
    if (seq !== ng.seq) return;
    rxMensagemTabela(corpo, 7, e.message);
    $('#rx-ng-info').textContent = '';
    $('#rx-ng-mais').hidden = true;
  }
}

// Clicar num n-grama abre a concordância da frase (entre aspas), na mesma unidade (forma ou lema) e com a mesma regra de pontuação.
function abrirNgramaNoKwic(g) {
  $('#rx-q').value = `"${g.ngrama}"`;
  const por = $('#rx-ng-por').value;
  if ($('#rx-por').value !== por) { $('#rx-por').value = por; $('#rx-por').dispatchEvent(new Event('change')); } else buscarKwic(true);
  $('#p-kwic').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

$('#tab-ng').addEventListener('click', (ev) => {
  const tr = ev.target.closest('tr.hit');
  if (tr) abrirNgramaNoKwic(ng.itens[+tr.dataset.i]);
});
for (const id of ['#rx-ng-nmin', '#rx-ng-nmax', '#rx-ng-por', '#rx-ng-stop', '#rx-ng-quebrar', '#rx-ng-minf', '#rx-ng-mind', '#rx-ng-pos', '#rx-ng-ordem']) {
  $(id).addEventListener('change', () => carregarNgramas(true));
}
$('#rx-ng-buscar').addEventListener('click', () => carregarNgramas(true));
$('#rx-ng-contem').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') carregarNgramas(true); });
$('#rx-ng-mais').addEventListener('click', () => carregarNgramas(false));
