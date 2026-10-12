// Exportação para a planilha de coleta da MLR (9.5): botões nas abas Comentários e Corpus que baixam um .xlsx NOVO no formato da aba de
// trechos (T_Trechos_Tematicos), com duplicatas marcadas contra a planilha do usuário (só leitura, indicada por caminho).
// Injetado por este arquivo. Usa $, esc, api, fmtNum, slugAtual (app.js).

const cmlr = { celula: null };
const CHAVE_PLANILHA = 'raiox.planilhaColeta';

function lerPlanilhaColeta() { try { return localStorage.getItem(CHAVE_PLANILHA) || ''; } catch { return ''; } }
function gravarPlanilhaColeta(v) { try { localStorage.setItem(CHAVE_PLANILHA, v); } catch { /* sem armazenamento: segue */ } }

function blocoColeta(prefixo, extra) {
  const d = document.createElement('details');
  d.className = 'coleta-mlr'; d.id = `${prefixo}-coleta`;
  d.innerHTML = `
    <summary><b>Exportar para a planilha de coleta da MLR (.xlsx novo)</b></summary>
    <p class="discreto">Gera um arquivo <b>novo</b> com as mesmas colunas da aba de trechos (a sua planilha é só lida, nunca alterada): trecho original literal, página,
      código/tema quando conhecidos, "Motivo da coleta" = "Raio-X: ..." e tradução vazia. Trechos que já estão na sua planilha (texto normalizado) vêm marcados como DUPLICADO.</p>
    <p class="barra">
      <label class="inline">Planilha de coleta (caminho, só leitura) <input type="text" id="${prefixo}-coleta-ref" size="48" placeholder="C:\\...\\Coleta_Dados_MLR.xlsx (opcional: copia o cabeçalho e checa duplicatas)"></label>
      <label class="inline check"><input type="checkbox" id="${prefixo}-coleta-omitir"> omitir os duplicados</label>
    </p>
    <p class="barra">${extra}
      <button type="button" id="${prefixo}-coleta-previa" class="sec">Pré-visualizar contagens</button>
      <button type="button" id="${prefixo}-coleta-baixar">Baixar .xlsx</button>
      <span id="${prefixo}-coleta-msg" class="discreto" role="status"></span></p>`;
  d.querySelector(`#${prefixo}-coleta-ref`).value = lerPlanilhaColeta();
  d.querySelector(`#${prefixo}-coleta-ref`).addEventListener('change', (ev) => gravarPlanilhaColeta(ev.target.value.trim()));
  return d;
}

function corpoColeta(prefixo, selecao) {
  const ref = $(`#${prefixo}-coleta-ref`).value.trim();
  gravarPlanilhaColeta(ref);
  return { selecao, planilha_referencia: ref || null, incluir_duplicados: !$(`#${prefixo}-coleta-omitir`).checked };
}

async function postColeta(prefixo, selecao, previa) {
  const msg = $(`#${prefixo}-coleta-msg`);
  if (!slugAtual) return;
  const corpo = JSON.stringify(corpoColeta(prefixo, selecao));
  const url = `/api/projetos/${slugAtual}/exportar/coleta${previa ? '/previa' : '.xlsx'}`;
  try {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: corpo });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw new Error(typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail || r.statusText));
    }
    if (previa) {
      const j = await r.json();
      msg.textContent = `${j.selecionados} trecho(s) selecionado(s); ${j.exportados} linha(s) na exportação; ${j.duplicados_na_planilha} já constam na planilha (${j.trechos_na_planilha} lidos)`
        + (j.duplicados_na_selecao ? `; ${j.duplicados_na_selecao} repetidos na seleção` : '') + '.';
      return;
    }
    const resumo = JSON.parse(r.headers.get('X-Raiox-Resumo') || '{}');
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `coleta_raiox_${slugAtual}.xlsx`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    msg.textContent = `Exportado: ${resumo.exportados} linha(s); ${resumo.duplicados_na_planilha} duplicada(s) ${resumo.incluir_duplicados ? 'marcada(s)' : 'omitida(s)'}.`;
  } catch (e) { msg.textContent = e.message; }
}

function selecaoComentarios() {
  const sel = [{ tipo: 'comentario' }];
  if ($('#cm-coleta-llm') && $('#cm-coleta-llm').checked) sel.push({ tipo: 'codificacao' });
  return sel;
}

async function selecaoCorpus() {
  const parte = $('#cp-coleta-parte').value;
  if (parte === '__celula') {
    if (!cmlr.celula) throw new Error('Clique numa célula da planilha do corpus primeiro.');
    return [{ tipo: 'celula', documento_id: cmlr.celula.doc, parte: cmlr.celula.parte }];
  }
  const dados = await api(`/api/projetos/${slugAtual}/corpus/planilha`);
  const sel = dados.linhas.filter((l) => l.partes[parte] && l.partes[parte].metodo !== 'nao').map((l) => ({ tipo: 'celula', documento_id: l.documento_id, parte }));
  if (!sel.length) throw new Error('Nenhum documento tem trecho nesta parte.');
  return sel;
}

async function montarColeta() {
  const cm = $('#cm-contagem');
  if (cm && !$('#cm-coleta')) {
    const d = blocoColeta('cm', '<label class="inline check"><input type="checkbox" id="cm-coleta-llm"> incluir trechos codificados pelo LLM (15.1)</label>');
    cm.parentNode.insertBefore(d, cm.nextSibling);
    $('#cm-coleta-previa').addEventListener('click', () => postColeta('cm', selecaoComentarios(), true));
    $('#cm-coleta-baixar').addEventListener('click', () => postColeta('cm', selecaoComentarios(), false));
  }
  const cp = $('#cp-msg');
  if (cp && !$('#cp-coleta')) {
    const d = blocoColeta('cp', '<label class="inline">Trechos de <select id="cp-coleta-parte"><option value="__celula">a célula aberta</option></select></label>');
    cp.parentNode.parentNode.insertBefore(d, cp.parentNode.nextSibling);
    const run = (previa) => async () => {
      try { await postColeta('cp', await selecaoCorpus(), previa); } catch (e) { $('#cp-coleta-msg').textContent = e.message; }
    };
    $('#cp-coleta-previa').addEventListener('click', run(true));
    $('#cp-coleta-baixar').addEventListener('click', run(false));
    d.addEventListener('toggle', async () => {
      if (!d.open || $('#cp-coleta-parte').options.length > 1 || !slugAtual) return;
      try {
        const dados = await api(`/api/projetos/${slugAtual}/corpus/planilha`);
        $('#cp-coleta-parte').insertAdjacentHTML('beforeend', dados.partes.map((p) => `<option value="${esc(p.chave)}">coluna "${esc(p.rotulo)}" (todos os documentos)</option>`).join(''));
      } catch { /* a lista de partes volta a ser tentada ao reabrir */ }
    });
  }
}

// guarda a última célula do corpus clicada (documento + parte) para a opção "a célula aberta"
document.addEventListener('click', (ev) => {
  const c = ev.target.closest && ev.target.closest('.cp-cel');
  if (c && c.dataset.doc) cmlr.celula = { doc: +c.dataset.doc, parte: c.dataset.parte };
});

montarColeta();
