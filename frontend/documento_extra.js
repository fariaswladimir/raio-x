// "Raio-x do documento" (15.3 legibilidade, 15.4 palavras-chave, 15.5 resumo extrativo) na Visão geral e painel
// "Agrupamento (k-means/espectral/PCA)" (15.9) em Análises > Comparativo. Tudo é injetado por este arquivo (o HTML só carrega o script).
// Usa $, esc, api, fmtNum, slugAtual (app.js) e rx, rxUrl, SUBS, CARREGADORES (raiox.js). Sem bibliotecas; cores por --c1..--c8.

const rd = { id: null, dados: null, seq: 0 };
const ag = { r: null, seq: 0 };
const METODOS_CHAVE = [['rake', 'RAKE'], ['yake', 'YAKE'], ['textrank', 'TextRank']];
const METODOS_RESUMO = [['mmr', 'MMR (diversidade)'], ['textrank', 'TextRank'], ['lexrank', 'LexRank']];
const NOMES_INDICE = {
  flesch_en: 'Flesch (EN)', flesch_pt: 'Flesch PT (Martins et al.)', flesch_kincaid: 'Flesch-Kincaid (série)',
  gunning_fog: 'Gunning Fog (série)', coleman_liau: 'Coleman-Liau (série)', smog: 'SMOG (série)',
};
const DICAS_INDICE = {
  flesch_en: '206,835 − 1,015·ASL − 84,6·ASW; 0 a 100, maior = mais fácil',
  flesch_pt: '248,835 − 1,015·ASL − 84,6·ASW (Martins et al., 1996); maior = mais fácil',
  flesch_kincaid: '0,39·ASL + 11,8·ASW − 15,59; série escolar dos EUA',
  gunning_fog: '0,4·(ASL + 100·palavras complexas/palavras); série escolar',
  coleman_liau: '0,0588·L − 0,296·S − 15,8; série escolar (usa letras)',
  smog: '1,043·√(polissílabos·30/frases) + 3,1291; série escolar',
};

// ---------- estrutura injetada ----------

function montarPainelDocumento() {
  if ($('#painel-rxdoc')) return;
  const alvo = $('#painel-secoes');
  if (!alvo) return;
  const sec = document.createElement('div');
  sec.id = 'painel-rxdoc';
  sec.hidden = true;
  sec.innerHTML = `
    <h3>Raio-x do documento: <span id="rd-nome"></span> <button class="sec" id="rd-fechar" type="button">Fechar</button></h3>
    <p class="discreto" id="rd-status"></p>
    <div id="rd-corpo" hidden>
      <h4 class="rd-tit">Legibilidade <span class="discreto" id="rd-leg-info"></span></h4>
      <div id="rd-principal" class="rd-principal"></div>
      <div id="rd-avisos"></div>
      <div class="rolagem"><table id="tab-rd-leg"></table></div>
      <p class="discreto">Sobre o corpo do documento (sem referências nem ruído). A fórmula principal é a do idioma do documento; Fog, Kincaid,
        Coleman-Liau e SMOG foram calibrados para o inglês e, em português, servem só para comparar documentos. Artigos com tabelas e listas distorcem as frases:
        veja o número de frases e os avisos.</p>
      <h4 class="rd-tit">Palavras-chave <span class="discreto">RAKE, YAKE e TextRank no texto do documento; TF-IDF compara com o corpus</span>
        <span class="p-ctl"><a class="botao sec peq" id="rd-pk-csv" download="palavras_chave.csv" href="#">CSV</a></span></h4>
      <div id="rd-chaves" class="rd-colunas"></div>
      <p class="discreto">RAKE e TextRank: maior pontuação é melhor; YAKE: <b>menor</b> é melhor. Sem etiquetador, o TextRank filtra só por palavras vazias, e o
        RAKE favorece frases longas. Os métodos discordam: compare e escolha por inspeção.</p>
      <h4 class="rd-tit">Resumo extrativo
        <span class="p-ctl">
          <select id="rd-res-metodo" aria-label="Método do resumo">${METODOS_RESUMO.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select>
          <label class="inline">frases <input type="number" id="rd-res-n" min="1" max="15" value="5" class="curto" aria-label="Número de frases"></label>
          <a class="botao sec peq" id="rd-res-csv" download="resumo.csv" href="#">CSV</a></span></h4>
      <p class="discreto" id="rd-res-info"></p>
      <ol id="rd-resumo" class="rd-resumo"></ol>
      <p class="discreto">Frases do próprio documento, na ordem do texto, com a página de onde vêm: confira o contexto antes de citar. O MMR evita frases redundantes;
        TextRank e LexRank escolhem as mais centrais.</p>
    </div>`;
  alvo.parentNode.insertBefore(sec, alvo);
  $('#rd-fechar').addEventListener('click', fecharRaioXDoc);
  $('#rd-res-metodo').addEventListener('change', carregarResumoDoc);
  $('#rd-res-n').addEventListener('change', carregarResumoDoc);
}

function fecharRaioXDoc() {
  rd.id = null; rd.dados = null; rd.seq++;
  $('#painel-rxdoc').hidden = true;
}

// ---------- legibilidade ----------

const ESCALAS = { flesch_en: [0, 100, true], flesch_pt: [0, 100, true] };

function marcador(id, valor) {
  const [min, max, maiorFacil] = ESCALAS[id] || [0, 20, false];
  const pct = Math.max(0, Math.min(100, ((valor - min) / (max - min)) * 100));
  const fundo = maiorFacil ? 'linear-gradient(90deg, var(--erro), var(--aviso), var(--ok))' : 'linear-gradient(90deg, var(--ok), var(--aviso), var(--erro))';
  return `<span class="rd-escala" style="background:${fundo}" role="img" aria-label="posição na escala"><i style="left:${pct.toFixed(1)}%"></i></span>`;
}

function renderLegibilidade(leg) {
  const p = leg.principal;
  const idiomas = { en: 'inglês', pt: 'português', es: 'espanhol' };
  $('#rd-leg-info').textContent = `(idioma: ${idiomas[leg.idioma] || 'indeterminado'} · ${fmtNum(leg.frases)} frases · ${fmtNum(leg.palavras)} palavras · ${fmtNum(leg.palavras_por_frase, 1)} palavras/frase · ${fmtNum(leg.silabas_por_palavra, 2)} sílabas/palavra · ${fmtNum(leg.siglas)} siglas fora da conta)`;
  $('#rd-principal').innerHTML = p
    ? `<div class="rd-cartao"><div class="rd-num">${fmtNum(p.valor, 1)}</div><div><b>${esc(NOMES_INDICE[p.id])}</b><br><span class="rd-faixa">${esc(p.faixa)}</span>${marcador(p.id, p.valor)}</div></div>`
    : '<div class="vazio">Idioma sem fórmula de Flesch validada aqui: veja os índices de série, só para comparar documentos.</div>';
  const avisos = leg.avisos.map((a) => `<li>${esc(a)}</li>`).join('');
  $('#rd-avisos').innerHTML = leg.confiavel && !avisos ? '<span class="badge status aceito">divisão em frases plausível</span>'
    : `<div class="vazio"><b>${leg.confiavel ? 'Atenção' : 'Divisão em frases pouco confiável'}</b><ul class="rd-lista">${avisos}</ul></div>`;
  $('#tab-rd-leg').innerHTML = '<thead><tr><th>Índice</th><th>Valor</th><th>Faixa</th><th></th></tr></thead><tbody>' +
    Object.entries(leg.indices).map(([id, v]) => `<tr${leg.formula_principal === id ? ' class="rd-sel"' : ''}><td title="${esc(DICAS_INDICE[id])}">${esc(NOMES_INDICE[id])}</td>
      <td>${fmtNum(v.valor, 1)}</td><td>${esc(v.faixa)}</td><td>${ESCALAS[id] ? marcador(id, v.valor) : ''}</td></tr>`).join('') + '</tbody>';
}

// ---------- palavras-chave ----------

function colunaChave(titulo, itens, dica, formatar) {
  const lis = itens.length ? itens.map((x, i) => `<li>${formatar(x, i)}</li>`).join('') : '<li class="discreto">sem resultado</li>';
  return `<div class="rd-col"><h5 title="${esc(dica)}">${esc(titulo)}</h5><ol>${lis}</ol></div>`;
}

function renderChaves(d) {
  const html = METODOS_CHAVE.map(([m, nome]) => colunaChave(nome, d.palavras_chave[m] || [],
    m === 'yake' ? 'menor pontuação = melhor' : 'maior pontuação = melhor',
    (x) => `<span class="termo-chave">${esc(x.frase)}</span> <span class="discreto" title="pontuação · frequência · páginas">${fmtNum(x.pontuacao, m === 'yake' ? 4 : 2)} · ${x.frequencia}× · ${x.paginas.length ? 'p. ' + x.paginas.join(', ') : 'sem página'}</span>`)).join('');
  const tf = colunaChave('TF-IDF (5.1)', d.tfidf || [], 'termos distintivos do documento em relação ao corpus, por lema',
    (x) => `<span class="termo-chave">${esc(x.termo)}</span> <span class="discreto">${fmtNum(x.freq)}×</span>`);
  $('#rd-chaves').innerHTML = html + tf;
}

// ---------- resumo ----------

function renderResumoDoc(r) {
  $('#rd-res-info').textContent = `${r.frases.length} de ${fmtNum(r.n_candidatas)} frases candidatas (${fmtNum(r.total_frases)} frases no corpo do documento) · método ${r.metodo}`;
  $('#rd-resumo').innerHTML = r.frases.length ? r.frases.map((f) =>
    `<li><span class="badge" title="seção ${esc(f.secao)}">${f.pagina == null ? 'sem página' : 'p. ' + esc(f.pagina)} · ${esc(f.secao)}</span> <span class="badge" title="ordem de seleção pelo método">#${f.classificacao}</span> ${esc(f.texto)}</li>`).join('')
    : '<li class="discreto">Nenhuma frase elegível neste documento.</li>';
}

async function carregarResumoDoc() {
  if (!rd.id) return;
  const seq = ++rd.seq;
  const q = new URLSearchParams({ documento_id: rd.id, metodo: $('#rd-res-metodo').value, n: $('#rd-res-n').value || 5 });
  $('#rd-res-csv').href = `/api/projetos/${slugAtual}/analises/sumarizacao.csv?${q}`;
  try {
    const r = await api(`/api/projetos/${slugAtual}/analises/sumarizacao?${q}`);
    if (seq !== rd.seq) return;
    renderResumoDoc(r);
  } catch (e) {
    if (seq !== rd.seq) return;
    $('#rd-resumo').innerHTML = `<li class="discreto">${esc(e.message)}</li>`;
  }
}

async function abrirRaioXDoc(id, nome) {
  montarPainelDocumento();
  rd.id = id;
  const seq = ++rd.seq;
  $('#painel-rxdoc').hidden = false;
  $('#rd-nome').textContent = nome;
  $('#rd-corpo').hidden = true;
  $('#rd-status').textContent = 'Calculando legibilidade, palavras-chave e resumo...';
  $('#painel-rxdoc').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  try {
    const d = await api(`/api/projetos/${slugAtual}/analises/documento-extra/${id}`);
    if (seq !== rd.seq) return;
    rd.dados = d;
    $('#rd-status').textContent = '';
    $('#rd-corpo').hidden = false;
    renderLegibilidade(d.legibilidade);
    renderChaves(d);
    $('#rd-pk-csv').href = `/api/projetos/${slugAtual}/analises/palavras-chave.csv?documento_id=${id}`;
    $('#rd-res-metodo').value = 'mmr';
    renderResumoDoc(d.resumos.mmr);
    $('#rd-res-n').value = d.resumos.mmr.n;
    $('#rd-res-csv').href = `/api/projetos/${slugAtual}/analises/sumarizacao.csv?documento_id=${id}&metodo=mmr&n=${d.resumos.mmr.n}`;
  } catch (e) {
    if (seq !== rd.seq) return;
    $('#rd-status').textContent = e.message + ' Execute o pipeline do projeto para gerar o texto limpo.';
  }
}

// Acrescenta o link "raio-x" na primeira coluna da tabela de documentos (a tabela é refeita a cada abertura do projeto).
function adicionarLinksRaioX() {
  document.querySelectorAll('#tab-docs tbody tr').forEach((tr) => {
    if (tr.querySelector('a[data-rxdoc]')) return;
    const base = tr.querySelector('a[data-secoes]');
    if (!base) return;
    const a = document.createElement('a');
    a.href = '#'; a.className = 'doc-link rd-link'; a.dataset.rxdoc = base.dataset.secoes; a.dataset.nome = base.dataset.nome;
    a.textContent = 'raio-x'; a.title = 'Legibilidade, palavras-chave e resumo deste documento';
    base.parentNode.append(' · ', a);
  });
}

// ---------- agrupamento (15.9) ----------

const corGrupo = (c) => `var(--c${((c - 1) % 8) + 1})`;
const FORMAS_AG = ['circulo', 'quadrado', 'triangulo', 'losango', 'cruz', 'estrela'];

function montarPainelAgrupamento() {
  if ($('#p-agr') || !$('#p-simil')) return;
  const p = document.createElement('div');
  p.className = 'painel larga'; p.id = 'p-agr'; p.dataset.sub = 'comparativo';
  p.innerHTML = `
    <div class="p-cab"><b>Agrupamento (k-means/espectral/PCA)</b> <span class="discreto p-info" id="ag-info"></span>
      <span class="p-ctl"><a class="botao sec peq" id="ag-csv" download="agrupamento.csv" href="#">CSV</a></span></div>
    <div class="p-corpo livre">
      <p class="barra">
        <label class="inline">Método
          <select id="ag-metodo"><option value="kmeans" selected>k-means (k-means++, 10 reinícios)</option><option value="espectral">espectral (Laplaciano normalizado)</option></select></label>
        <label class="inline">Grupos (k)
          <select id="ag-k"><option value="">automático (silhueta)</option>${[2, 3, 4, 5, 6, 7, 8].map((k) => `<option>${k}</option>`).join('')}</select></label>
        <label class="inline">Unidade
          <select id="ag-por"><option value="lema">lema</option><option value="forma">forma</option><option value="termo">termo (inclui compostos)</option></select></label>
        <button id="ag-calcular" type="button">Calcular</button>
      </p>
      <p id="ag-aviso" class="vazio" hidden></p>
      <div class="sm-grade">
        <div><h5 class="sm-tit">Mapa PCA dos documentos <span class="discreto" id="ag-pca-info"></span></h5>
          <div id="ag-mapa" class="sm-mapa" role="img" aria-label="Mapa PCA dos documentos"></div><div id="ag-legenda" class="chips"></div></div>
        <div><h5 class="sm-tit">Silhueta e concordância com o Ward por k <span class="discreto" id="ag-sil-info"></span></h5>
          <div class="rolagem"><table id="tab-ag-sil"></table></div></div>
      </div>
      <h5 class="sm-tit">Termos característicos de cada grupo</h5>
      <div id="ag-termos" class="sm-termos"></div>
      <div id="ag-dica" class="dica" hidden></div>
      <p class="discreto">Mesma matriz TF-IDF da similaridade (lemas, sem palavras vazias, df ≥ 2 e ≤ 0,9·N). k-means: Lloyd com inicialização k-means++, 10 reinícios, semente 42.
        Espectral: Laplaciano normalizado do grafo kNN (10 vizinhos) de cosseno, com k-means nos autovetores. k automático = maior silhueta (1 − cosseno) de 2 a 8.
        PCA: SVD do TF-IDF centrado (não coincide com o mapa MDS da similaridade). ARI = índice de Rand ajustado contra o corte do Ward no mesmo k (1 = partições iguais; perto de 0 = acordo ao acaso).
        Cor = grupo do algoritmo; forma = grupo do documento (metadado).</p>
    </div>`;
  $('#p-simil').insertAdjacentElement('afterend', p);
  for (const id of ['#ag-metodo', '#ag-k', '#ag-por']) $(id).addEventListener('change', carregarAgrupamento);
  $('#ag-calcular').addEventListener('click', carregarAgrupamento);
  $('#ag-mapa').addEventListener('mousemove', (ev) => {
    const el = ev.target.closest('.ag-pt'), dica = $('#ag-dica');
    const d = el && ag.r ? ag.r.documentos.find((x) => x.id === +el.dataset.id) : null;
    if (!d) { dica.hidden = true; return; }
    dica.hidden = false;
    dica.innerHTML = `<b>${esc(d.rotulo)}</b><br>grupo ${d.cluster} (Ward: ${d.ward}) · ${esc(d.grupo)} · ${esc(d.ano)}`;
    dica.style.left = Math.min(ev.clientX + 14, window.innerWidth - 270) + 'px';
    dica.style.top = Math.min(ev.clientY + 14, window.innerHeight - 90) + 'px';
  });
  $('#ag-mapa').addEventListener('mouseleave', () => { $('#ag-dica').hidden = true; });
}

function paramsAgrupamento() {
  const p = { metodo: $('#ag-metodo').value, por: $('#ag-por').value };
  if ($('#ag-k').value) p.k = $('#ag-k').value;
  return p;
}

function desenharMapaAgrupamento() {
  const alvo = $('#ag-mapa'), r = ag.r;
  if (!r) { alvo.innerHTML = ''; $('#ag-legenda').innerHTML = ''; return; }
  const W = 520, H = 380, m = 28;
  const xs = r.documentos.map((d) => d.x), ys = r.documentos.map((d) => d.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const sx = (v) => m + ((v - x0) / ((x1 - x0) || 1)) * (W - 2 * m), sy = (v) => H - m - ((v - y0) / ((y1 - y0) || 1)) * (H - 2 * m);
  const gs = [...new Set(r.documentos.map((d) => d.grupo))].sort();
  const forma = (g) => FORMAS_AG[Math.max(0, gs.indexOf(g)) % FORMAS_AG.length];
  const pts = r.documentos.map((d) => {
    const mk = marcadorSvg(forma(d.grupo), +sx(d.x).toFixed(1), +sy(d.y).toFixed(1), 6, { fill: corGrupo(d.cluster), 'fill-opacity': 0.85, stroke: 'var(--painel)', 'stroke-width': 1.2 });
    return `<g class="ag-pt" data-id="${d.id}">${mk}</g>`;
  });
  const ve = r.pca.variancia_explicada;
  alvo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" xmlns="http://www.w3.org/2000/svg" style="display:block;max-height:420px"><rect x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" fill="none" stroke="var(--borda)"/>` +
    `<text x="${W / 2}" y="${H - 8}" font-size="10" fill="var(--suave)" text-anchor="middle">PC1 (${fmtNum(ve[0] * 100, 1)}%)</text>` +
    `<text x="10" y="${H / 2}" font-size="10" fill="var(--suave)" text-anchor="middle" transform="rotate(-90 10 ${H / 2})">PC2 (${fmtNum(ve[1] * 100, 1)}%)</text>${pts.join('')}</svg>`;
  $('#ag-pca-info').textContent = `(PC1 ${fmtNum(ve[0] * 100, 1)}% + PC2 ${fmtNum(ve[1] * 100, 1)}% = ${fmtNum(r.pca.soma_eixos * 100, 1)}% da variância)`;
  const ks = [...new Set(r.documentos.map((d) => d.cluster))].sort((a, b) => a - b);
  $('#ag-legenda').innerHTML = ks.map((k) => `<span class="chip"><i style="background:${corGrupo(k)}"></i>grupo ${k}</span>`).join('') +
    gs.map((g) => `<span class="chip"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">${marcadorSvg(forma(g), 7, 7, 4.5, { fill: 'var(--suave)' })}</svg>${esc(g)}</span>`).join('');
}

function renderAgrupamento() {
  const r = ag.r;
  $('#ag-aviso').hidden = true;
  const nome = r.metodo === 'kmeans' ? 'k-means' : 'espectral';
  $('#ag-info').textContent = `(${nome} · ${r.n_documentos} documentos · ${fmtNum(r.n_termos)} termos · k = ${r.k}${r.k_automatico ? ' (automático)' : ''} · silhueta ${fmtNum(r.silhueta, 3)} · ARI vs Ward = ${fmtNum(r.ari_ward, 2)}${r.excluidos.length ? ` · ${r.excluidos.length} excluído(s)` : ''})`;
  const maxS = Math.max(...r.silhuetas.map((s) => s.silhueta), 0.0001);
  $('#tab-ag-sil').innerHTML = '<thead><tr><th>k</th><th>Silhueta</th><th></th><th title="Índice de Rand ajustado contra o Ward no mesmo k">ARI vs Ward</th></tr></thead><tbody>' +
    r.silhuetas.map((s, i) => `<tr${s.k === r.k ? ' class="rd-sel"' : ''}><td>${s.k}</td><td>${fmtNum(s.silhueta, 3)}</td>
      <td><span class="rd-barra"><i style="width:${Math.max(2, (s.silhueta / maxS) * 100).toFixed(0)}%"></i></span></td><td>${fmtNum(r.ari_ward_por_k[i].ari_ward, 2)}</td></tr>`).join('') + '</tbody>';
  $('#ag-sil-info').textContent = '(linha destacada = k usado)';
  desenharMapaAgrupamento();
  $('#ag-termos').innerHTML = r.grupos.map((g) => {
    const rotulos = g.ids.map((id) => r.documentos.find((d) => d.id === id)).filter(Boolean).map((d) => d.rotulo);
    const termos = g.termos.map((t) => `<span title="diferença de média TF-IDF ${fmtNum(t.diferenca, 3)}">${esc(t.termo)}</span>`).join(' ');
    return `<div class="sm-cartao" style="border-left-color:${corGrupo(g.cluster)}"><b style="color:${corGrupo(g.cluster)}">Grupo ${g.cluster}</b>
      <span class="discreto"> · ${g.documentos} doc.: ${esc(rotulos.slice(0, 6).join(', '))}${rotulos.length > 6 ? '…' : ''}</span><div class="sm-termos-lista">${termos || '<span class="discreto">sem termos com diferença positiva</span>'}</div></div>`;
  }).join('');
}

async function carregarAgrupamento() {
  montarPainelAgrupamento();
  if (!slugAtual || !rx.resumo || !$('#p-agr')) return;
  const seq = ++ag.seq;
  const q = paramsAgrupamento();
  $('#ag-csv').href = rxUrl('agrupamento.csv', q);
  $('#ag-aviso').hidden = true;
  try {
    const r = await api(rxUrl('agrupamento', q));
    if (seq !== ag.seq) return;
    ag.r = r;
    renderAgrupamento();
  } catch (e) {
    if (seq !== ag.seq) return;
    limparAgrupamento();
    $('#ag-aviso').hidden = false;
    $('#ag-aviso').textContent = e.message;
  }
}

function limparAgrupamento() {
  ag.r = null;
  if (!$('#p-agr')) return;
  for (const id of ['#ag-mapa', '#ag-legenda', '#ag-termos', '#tab-ag-sil']) $(id).innerHTML = '';
  $('#ag-info').textContent = '';
}

// ---------- ligações com o restante da interface ----------

document.addEventListener('click', (ev) => {
  const a = ev.target.closest('a[data-rxdoc]');
  if (!a) return;
  ev.preventDefault();
  abrirRaioXDoc(+a.dataset.rxdoc, a.dataset.nome || '');
});

if ($('#tab-docs tbody')) {
  new MutationObserver(() => {
    adicionarLinksRaioX();
    if (rd.id && !document.querySelector(`#tab-docs a[data-rxdoc="${rd.id}"]`)) fecharRaioXDoc(); // outro projeto aberto
  }).observe($('#tab-docs tbody'), { childList: true });
  adicionarLinksRaioX();
}
montarPainelDocumento();
montarPainelAgrupamento();
if (typeof SUBS !== 'undefined' && !SUBS.comparativo.includes('agr')) {
  SUBS.comparativo.push('agr');
  CARREGADORES.agr = carregarAgrupamento;
}
if (typeof limparSimilaridade === 'function') {
  const limparOriginal = limparSimilaridade;
  window.limparSimilaridade = function () { limparOriginal(); limparAgrupamento(); };
}
