// Painel "Keyness contra corpus de referência" (15.8) em Análises > Comparativo: importa uma lista de frequências (ou uma pasta
// de .txt) por projeto e compara o corpus (ou um grupo/ano) com ela. Injetado por este arquivo (o HTML só carrega o script).
// Usa $, esc, api, fmtNum, slugAtual (app.js), rx, rxUrl, termoHtml, fmtP, tabelaKeyness, SUBS, CARREGADORES (raiox.js).

const kr = { refs: [], seq: 0, ultimo: null };

function montarPainelKeynessReferencia() {
  if ($('#p-keyref') || !$('#p-key')) return;
  const p = document.createElement('div');
  p.className = 'painel larga'; p.id = 'p-keyref'; p.dataset.sub = 'comparativo';
  p.innerHTML = `
    <div class="p-cab"><b>Keyness contra corpus de referência</b> <span class="discreto p-info" id="kr-info"></span>
      <span class="p-ctl"><a class="botao sec peq" id="kr-csv" download="keyness_referencia.csv" href="#">CSV</a></span></div>
    <div class="p-corpo livre">
      <p class="aviso" role="note"><b>Atenção:</b> a referência precisa ser <b>comparável</b> ao corpus (mesmo idioma e, de preferência, gênero próximo).
        Contra uma referência de outro gênero (legendas, notícias, redes sociais), quase todo termo técnico aparece como palavra-chave.
        O Raio-X <b>não traz</b> corpus de referência (licenças): importe uma lista de frequências de um corpus que você tem o direito de usar.</p>
      <p class="barra">
        <label class="inline">Referência <select id="kr-ref"></select></label>
        <label class="inline">Corpus <select id="kr-escopo"><option value="corpus">inteiro</option><option value="grupo">grupo</option><option value="ano">ano</option></select></label>
        <label class="inline" id="kr-valor-l" hidden><select id="kr-valor" aria-label="Grupo ou ano"></select></label>
        <label class="inline">Unidade <select id="kr-por"><option value="lema">lema</option><option value="forma">forma</option></select></label>
        <label class="inline">Ordenar por <select id="kr-ordem"><option value="ll">G²</option><option value="logratio">Log Ratio</option></select></label>
        <label class="inline">Freq. mín. <input type="number" id="kr-min" min="1" value="5" class="curto"></label>
        <label class="inline">Docs mín. <input type="number" id="kr-docs" min="1" value="2" class="curto"></label>
        <label class="inline">Fora da referência
          <select id="kr-oov"><option value="incluir">mostrar (marcadas)</option><option value="excluir">ocultar</option></select></label>
        <label class="inline check"><input type="checkbox" id="kr-bonf"> Bonferroni</label>
        <button id="kr-calcular" type="button">Comparar</button>
      </p>
      <div id="kr-ficha" class="discreto"></div>
      <p id="kr-msg" class="vazio" hidden></p>
      <div id="kr-avisos" class="aviso" hidden></div>
      <div class="key-grade">
        <div><h5 class="key-tit a" id="kr-tit-a">Corpus sobre-representado</h5><div class="rolagem alta"><table class="tab-key" id="tab-kr-a"></table></div></div>
        <div><h5 class="key-tit b" id="kr-tit-b">Referência sobre-representada</h5><div class="rolagem alta"><table class="tab-key" id="tab-kr-b"></table></div></div>
      </div>
      <details id="kr-importar"><summary><b>Importar referência</b></summary>
        <p class="discreto">Formato: um termo por linha, <code>termo;frequência</code> (ou separado por tabulação/vírgula; cabeçalho opcional; milhar com ponto ou vírgula aceito).
          O total de palavras da referência pode vir numa linha <code># total: 1000000</code> ou no campo abaixo; sem total usa-se a soma da lista
          (aproximação, se a lista for truncada). Alternativa: informe o caminho de uma pasta de .txt/.md, contada com o mesmo tokenizador e lematizador do projeto.
          Lista de formas é lematizada na importação (soma das formas de cada lema) para o modo "lema".</p>
        <p class="barra">
          <label class="inline">Nome <input type="text" id="kr-nome" placeholder="ex.: Lista geral EN (minha cópia)"></label>
          <label class="inline">Idioma <select id="kr-idioma"><option value="en">en</option><option value="pt">pt</option><option value="es">es</option></select></label>
          <label class="inline">Fonte/licença <input type="text" id="kr-fonte" placeholder="corpus, versão, licença"></label>
          <label class="inline">Total de palavras <input type="number" id="kr-total" min="1" placeholder="opcional" class="curto"></label>
        </p>
        <p class="barra">
          <label class="inline">Arquivo da lista <input type="file" id="kr-arquivo" accept=".csv,.tsv,.txt"></label>
          <label class="inline">ou caminho (arquivo/pasta) <input type="text" id="kr-caminho" placeholder="C:\\corpora\\referencia"></label>
          <button id="kr-enviar" type="button">Importar</button>
          <button id="kr-remover" type="button" class="sec">Remover a selecionada</button>
        </p>
        <p id="kr-imp-msg" class="discreto"></p>
      </details>
      <p class="discreto">G² de 2 células e Log Ratio como na keyness entre grupos (6.1); lado A = corpus do projeto, lado B = referência. Termos do corpus ausentes
        da referência (fora da referência) usam 0,5 no lugar de zero no Log Ratio e vêm marcados. Equivale à Keyword List do AntConc com corpus de referência
        e ao KeyWords do WordSmith.</p>
    </div>`;
  $('#p-key').parentNode.insertBefore(p, $('#p-key').nextSibling);
  for (const id of ['#kr-ref', '#kr-por', '#kr-ordem', '#kr-min', '#kr-docs', '#kr-oov', '#kr-bonf', '#kr-valor']) $(id).addEventListener('change', carregarKeynessReferencia);
  $('#kr-escopo').addEventListener('change', () => { preencherValoresKr(); carregarKeynessReferencia(); });
  $('#kr-calcular').addEventListener('click', carregarKeynessReferencia);
  $('#kr-enviar').addEventListener('click', importarReferenciaKr);
  $('#kr-remover').addEventListener('click', removerReferenciaKr);
}

function paramsKr(extra) {
  const q = { referencia: $('#kr-ref').value, escopo: $('#kr-escopo').value, por: $('#kr-por').value, ordem: $('#kr-ordem').value,
    min_freq: $('#kr-min').value, min_docs: $('#kr-docs').value, oov: $('#kr-oov').value, bonferroni: $('#kr-bonf').checked,
    vazias: $('#rx-vazias') ? $('#rx-vazias').value : 'filtrar', ...extra };
  if (q.escopo !== 'corpus') q.valor = $('#kr-valor').value;
  return q;
}

async function preencherValoresKr() {
  const esc_ = $('#kr-escopo').value;
  $('#kr-valor-l').hidden = esc_ === 'corpus';
  if (esc_ === 'corpus') return;
  try {
    const l = (rx.key && rx.key.lados) || await api(rxUrl('grupos'));
    const itens = esc_ === 'grupo' ? l.grupos : l.anos;
    $('#kr-valor').innerHTML = itens.map((i) => `<option value="${esc(i.valor)}">${esc(i.valor)} (${i.documentos} doc.)</option>`).join('');
  } catch (e) { $('#kr-valor').innerHTML = ''; }
}

async function carregarReferenciasKr() {
  try {
    const r = await api(`/api/projetos/${slugAtual}/referencias`);
    kr.refs = r.itens;
  } catch (e) { kr.refs = []; }
  const antigo = $('#kr-ref').value;
  $('#kr-ref').innerHTML = kr.refs.map((x) => `<option value="${esc(x.id)}">${esc(x.nome)} (${esc(x.idioma)}, ${fmtNum(x.tokens)} palavras)</option>`).join('')
    || '<option value="">(nenhuma importada)</option>';
  if (kr.refs.some((x) => x.id === antigo)) $('#kr-ref').value = antigo;
}

function fichaKr(ref) {
  if (!ref) return '';
  return `<b>${esc(ref.nome)}</b> · fonte: ${esc(ref.fonte || 'não informada')} · idioma ${esc(ref.idioma)} · ${fmtNum(ref.tokens)} palavras `
    + `(${ref.tipo === 'textos' ? `${fmtNum(ref.arquivos)} arquivos contados aqui` : ref.total_declarado ? 'total informado' : 'total = soma da lista'}) · `
    + `${fmtNum(ref.tipos_forma)} formas, ${fmtNum(ref.tipos_lema)} lemas · importada em ${esc(ref.importada_em || '')}`;
}

async function carregarKeynessReferencia() {
  if (!slugAtual || !$('#p-keyref')) return;
  const seq = ++kr.seq;
  await carregarReferenciasKr();
  const vazio = (t) => { for (const id of ['#tab-kr-a', '#tab-kr-b']) $(id).innerHTML = `<tbody><tr><td class="discreto">${esc(t)}</td></tr></tbody>`; };
  $('#kr-msg').hidden = true; $('#kr-avisos').hidden = true;
  const sel = kr.refs.find((x) => x.id === $('#kr-ref').value);
  $('#kr-ficha').innerHTML = fichaKr(sel);
  if (!sel) { $('#kr-info').textContent = ''; vazio('Importe uma referência (abaixo) para comparar.'); return; }
  if ($('#kr-escopo').value !== 'corpus' && !$('#kr-valor').value) await preencherValoresKr();
  $('#kr-csv').href = `/api/projetos/${slugAtual}/analises/keyness-referencia.csv?${new URLSearchParams(paramsKr({ limite: 1000 }))}`;
  try {
    const r = await api(`/api/projetos/${slugAtual}/analises/keyness-referencia?${new URLSearchParams(paramsKr({ limite: 50 }))}`);
    if (seq !== kr.seq) return;
    kr.ultimo = r;
    const maximo = Math.max(1, ...[...r.positivas, ...r.negativas].map((k) => Math.abs(k.log_ratio)));
    $('#kr-info').textContent = `(${r.corpus.valor} · ${r.corpus.documentos} doc. · ${fmtNum(r.corpus.tokens)} palavras | referência ${fmtNum(r.referencia.tokens)} palavras | `
      + `${fmtNum(r.termos_testados)} termos testados, p < ${fmtP(r.limiar_p)}; ${fmtNum(r.oov_testados)} fora da referência)`;
    $('#kr-tit-a').textContent = `Corpus sobre-representado: ${fmtNum(r.total_positivas)} palavras-chave`;
    $('#kr-tit-b').textContent = `Referência sobre-representada: ${fmtNum(r.total_negativas)} termos`;
    tabelaKeyness($('#tab-kr-a'), r.positivas.map((k) => ({ ...k, so_em_a: k.oov, docs_b: '—' })), maximo, r.por, 'Nenhuma palavra-chave com esses limiares.');
    tabelaKeyness($('#tab-kr-b'), r.negativas.map((k) => ({ ...k, docs_b: '—' })), maximo, r.por, 'Nenhum termo com esses limiares.');
    if (r.avisos.length) { $('#kr-avisos').hidden = false; $('#kr-avisos').textContent = r.avisos.join(' '); }
  } catch (e) {
    if (seq !== kr.seq) return;
    $('#kr-info').textContent = '';
    $('#kr-msg').hidden = false; $('#kr-msg').textContent = e.message;
    vazio('');
  }
}

async function importarReferenciaKr() {
  const corpo = { nome: $('#kr-nome').value.trim(), idioma: $('#kr-idioma').value, fonte: $('#kr-fonte').value.trim() };
  if ($('#kr-total').value) corpo.total = +$('#kr-total').value;
  const arq = $('#kr-arquivo').files[0];
  if (arq) corpo.conteudo = await arq.text();
  else if ($('#kr-caminho').value.trim()) corpo.caminho = $('#kr-caminho').value.trim();
  const msg = $('#kr-imp-msg');
  try {
    const r = await api(`/api/projetos/${slugAtual}/referencias`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) });
    msg.textContent = `Importada: ${r.nome} (${fmtNum(r.tokens)} palavras, ${fmtNum(r.tipos_forma)} formas).`;
    await carregarReferenciasKr();
    $('#kr-ref').value = r.id;
    carregarKeynessReferencia();
  } catch (e) { msg.textContent = e.message; }
}

async function removerReferenciaKr() {
  const id = $('#kr-ref').value;
  if (!id || !confirm('Remover esta referência do projeto?')) return;
  try {
    await api(`/api/projetos/${slugAtual}/referencias/${encodeURIComponent(id)}`, { method: 'DELETE' });
  } catch (e) { $('#kr-imp-msg').textContent = e.message; return; }
  carregarKeynessReferencia();
}

montarPainelKeynessReferencia();
if (typeof SUBS !== 'undefined' && !SUBS.comparativo.includes('keyref')) {
  SUBS.comparativo.push('keyref');
  CARREGADORES.keyref = carregarKeynessReferencia;
}
