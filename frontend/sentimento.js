// Painel "Sentimento (léxico)" (15.10) em Análises > Comparativo: polaridade por documento, grupo e ano, e as frases mais
// positivas/negativas com a página. Exploratório. Léxicos PT/ES são importados pelo usuário (não acompanham o Raio-X).
// Usa $, esc, api, fmtNum, slugAtual (app.js), rx, rxUrl, docLink (raiox.js), SUBS, CARREGADORES.

const sn = { r: null, seq: 0 };

function montarPainelSentimento() {
  if ($('#p-sent') || !$('#p-key')) return;
  const p = document.createElement('div');
  p.className = 'painel larga'; p.id = 'p-sent'; p.dataset.sub = 'comparativo';
  p.innerHTML = `
    <div class="p-cab"><b>Sentimento por léxico</b> <span class="discreto p-info" id="sn-info"></span>
      <span class="p-ctl"><a class="botao sec peq" id="sn-csv" download="sentimento.csv" href="#">CSV</a></span></div>
    <div class="p-corpo livre">
      <p class="aviso" role="note"><b>Uso exploratório:</b> prosa acadêmica é, em geral, neutra, e os léxicos foram construídos para outros gêneros (redes sociais,
        resenhas, notícias). Termos técnicos como "limitação" ou "risco" contam como negativos sem expressar opinião. Leia a distribuição e os trechos extremos,
        não o escore como o tom do artigo.</p>
      <p class="barra">
        <label class="inline">Léxico PT <select id="sn-lex-pt"></select></label>
        <label class="inline">Léxico ES <select id="sn-lex-es"></select></label>
        <button id="sn-calcular" type="button">Calcular</button>
      </p>
      <p id="sn-msg" class="vazio" hidden></p>
      <div class="sm-grade">
        <div><h5 class="sm-tit">Por grupo</h5><div class="rolagem"><table id="tab-sn-grupo"></table></div>
          <h5 class="sm-tit">Por ano</h5><div class="rolagem"><table id="tab-sn-ano"></table></div></div>
        <div><h5 class="sm-tit">Por documento</h5><div class="rolagem alta"><table id="tab-sn-doc"></table></div></div>
      </div>
      <div class="sm-grade">
        <div><h5 class="sm-tit">Frases mais positivas</h5><div class="rolagem alta"><table id="tab-sn-pos"></table></div></div>
        <div><h5 class="sm-tit">Frases mais negativas</h5><div class="rolagem alta"><table id="tab-sn-neg"></table></div></div>
      </div>
      <p id="sn-ignorados" class="discreto"></p>
      <details><summary><b>Importar léxico (PT/ES)</b></summary>
        <p class="discreto">Inglês usa o VADER (pacote <code>vaderSentiment</code>, licença MIT, escore compound por frase). Para português, importe o arquivo que você
          baixou do OpLexicon (PUCRS) ou do SentiLex-PT: o Raio-X não os distribui porque a licença de redistribuição não está confirmada. Formatos: <code>termo;polaridade</code>,
          OpLexicon (<code>termo,classe,polaridade,fonte</code>) ou SentiLex-PT (<code>lema.PoS=Adj;...;POL:N0=-1</code>). O léxico fica na sua pasta de configuração, não no projeto.
          Cálculo: soma das polaridades com negação simples (3 palavras), normalizada por soma/√(soma²+15); positivo &ge; 0,05, negativo &le; -0,05.</p>
        <p class="barra">
          <label class="inline">Nome <input type="text" id="sn-nome" placeholder="ex.: OpLexicon 3.0"></label>
          <label class="inline">Idioma <select id="sn-idioma"><option value="pt">pt</option><option value="es">es</option><option value="en">en</option></select></label>
          <label class="inline">Fonte <input type="text" id="sn-fonte" placeholder="origem e licença"></label>
          <label class="inline">Arquivo <input type="file" id="sn-arquivo" accept=".txt,.csv,.tsv"></label>
          <button id="sn-importar" type="button">Importar</button>
          <button id="sn-remover" type="button" class="sec">Remover o PT selecionado</button>
        </p>
        <p id="sn-imp-msg" class="discreto"></p>
      </details>
    </div>`;
  $('#p-key').parentNode.insertBefore(p, $('#p-key').nextSibling);
  $('#sn-calcular').addEventListener('click', carregarSentimento);
  for (const id of ['#sn-lex-pt', '#sn-lex-es']) $(id).addEventListener('change', carregarSentimento);
  $('#sn-importar').addEventListener('click', importarLexicoSn);
  $('#sn-remover').addEventListener('click', async () => {
    const id = $('#sn-lex-pt').value;
    if (!id || !confirm('Remover este léxico da sua configuração?')) return;
    try { await api(`/api/config/sentimento/lexicos/${encodeURIComponent(id)}`, { method: 'DELETE' }); } catch (e) { $('#sn-imp-msg').textContent = e.message; return; }
    carregarSentimento();
  });
}

const fmtEsc = (x) => (x == null ? '—' : (x > 0 ? '+' : '') + fmtNum(x, 3));

function paramsSn() {
  const q = {};
  if ($('#sn-lex-pt').value) q.lexico_pt = $('#sn-lex-pt').value;
  if ($('#sn-lex-es').value) q.lexico_es = $('#sn-lex-es').value;
  return q;
}

function tabelaAgregado(el, itens, rotulo) {
  el.innerHTML = `<thead><tr><th>${rotulo}</th><th>Docs</th><th>Frases</th><th title="Média dos escores das frases">Escore</th><th>% pos.</th><th>% neutras</th><th>% neg.</th></tr></thead><tbody>`
    + (itens.map((g) => `<tr><td>${esc(g.valor)}</td><td class="num">${g.documentos}</td><td class="num">${fmtNum(g.frases)}</td><td class="num">${fmtEsc(g.media)}</td>
      <td class="num">${g.positivo}</td><td class="num">${g.neutro}</td><td class="num">${g.negativo}</td></tr>`).join('') || '<tr><td colspan="7" class="discreto">Sem dados.</td></tr>') + '</tbody>';
}

function tabelaFrases(el, itens) {
  el.innerHTML = '<thead><tr><th>Escore</th><th>Documento</th><th>Pág.</th><th>Frase</th></tr></thead><tbody>'
    + (itens.map((f) => `<tr><td class="num">${fmtEsc(f.escore)}</td><td>${docLink({ documento_id: f.documento_id, rotulo: f.rotulo })}</td><td class="num">${f.pagina ?? '—'}</td><td>${esc(f.texto)}</td></tr>`).join('')
      || '<tr><td colspan="4" class="discreto">Nenhuma.</td></tr>') + '</tbody>';
}

async function carregarSentimento() {
  if (!slugAtual || !$('#p-sent')) return;
  const seq = ++sn.seq;
  $('#sn-msg').hidden = true;
  try {
    const lx = await api('/api/config/sentimento/lexicos');
    const preencher = (sel, idioma) => {
      const atual = $(sel).value;
      const itens = lx.itens.filter((l) => l.idioma === idioma);
      $(sel).innerHTML = '<option value="">(mais recente)</option>' + itens.map((l) => `<option value="${esc(l.id)}">${esc(l.nome)} (${fmtNum(l.termos)} termos)</option>`).join('');
      if (itens.some((l) => l.id === atual)) $(sel).value = atual;
    };
    preencher('#sn-lex-pt', 'pt'); preencher('#sn-lex-es', 'es');
    const q = paramsSn();
    $('#sn-csv').href = `/api/projetos/${slugAtual}/analises/sentimento.csv?${new URLSearchParams(q)}`;
    const r = await api(`/api/projetos/${slugAtual}/analises/sentimento?${new URLSearchParams(q)}`);
    if (seq !== sn.seq) return;
    sn.r = r;
    $('#sn-info').textContent = `(${fmtNum(r.documentos.length)} documentos · ${fmtNum(r.corpus.frases)} frases · escore médio ${fmtEsc(r.corpus.media)} · `
      + `${r.corpus.positivo}% pos., ${r.corpus.neutro}% neutras, ${r.corpus.negativo}% neg.)`;
    tabelaAgregado($('#tab-sn-grupo'), r.por_grupo, 'Grupo');
    tabelaAgregado($('#tab-sn-ano'), r.por_ano, 'Ano');
    $('#tab-sn-doc').innerHTML = '<thead><tr><th>Documento</th><th>Idioma</th><th>Método</th><th>Frases</th><th>Escore</th><th>% pos.</th><th>% neg.</th><th title="Frases com algum termo do léxico">Cobertura</th></tr></thead><tbody>'
      + r.documentos.map((d) => `<tr><td>${docLink({ documento_id: d.id, rotulo: d.rotulo })}</td><td>${d.idioma}</td><td>${esc(d.metodo)}</td><td class="num">${d.frases}</td>
        <td class="num">${fmtEsc(d.media)}</td><td class="num">${d.positivo}</td><td class="num">${d.negativo}</td><td class="num">${d.cobertura == null ? '—' : d.cobertura + '%'}</td></tr>`).join('') + '</tbody>';
    tabelaFrases($('#tab-sn-pos'), r.mais_positivas);
    tabelaFrases($('#tab-sn-neg'), r.mais_negativas);
    $('#sn-ignorados').textContent = r.ignorados.length
      ? `Ignorados (${r.ignorados.length}): ` + r.ignorados.slice(0, 6).map((i) => `${i.rotulo} (${i.motivo})`).join('; ') + (r.ignorados.length > 6 ? '…' : '') : '';
  } catch (e) {
    if (seq !== sn.seq) return;
    $('#sn-msg').hidden = false; $('#sn-msg').textContent = e.message;
  }
}

async function importarLexicoSn() {
  const arq = $('#sn-arquivo').files[0];
  const msg = $('#sn-imp-msg');
  if (!arq) { msg.textContent = 'Escolha o arquivo do léxico.'; return; }
  try {
    const r = await api('/api/config/sentimento/lexicos', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome: $('#sn-nome').value.trim(), idioma: $('#sn-idioma').value, fonte: $('#sn-fonte').value.trim(), conteudo: await arq.text() }) });
    msg.textContent = `Importado: ${r.nome} (${fmtNum(r.termos)} termos; ${fmtNum(r.positivos)} positivos, ${fmtNum(r.negativos)} negativos).`;
    carregarSentimento();
  } catch (e) { msg.textContent = e.message; }
}

montarPainelSentimento();
if (typeof SUBS !== 'undefined' && !SUBS.comparativo.includes('sent')) {
  SUBS.comparativo.push('sent');
  CARREGADORES.sent = carregarSentimento;
}
