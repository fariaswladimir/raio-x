// Revisão dos comentários por regra (entregável 8.2): contagem por status, filtros, cartões com evidência e ações.
// Usa $, esc, api, fmtNum e slugAtual de app.js (carregado antes).
const cm = { lista: [], resumo: null, sel: new Set(), projeto: null, seq: 0 };
const CM_STATUS = ['sugerido', 'revisar', 'aceito', 'editado', 'rejeitado', 'obsoleto'];
const CM_ROTULO = {
  g2: 'G²', log_ratio: 'Log Ratio', p: 'p', a: 'freq. A', b: 'freq. B', por_10k_a: 'A por 10 mil', por_10k_b: 'B por 10 mil',
  docs_a: 'docs A', docs_b: 'docs B', ll: 'LL', mi: 'MI', o11: 'coocorrências', c1: 'freq. do colocado', e11: 'esperado',
  z: 'z', mattr: 'MATTR', media: 'média', desvio: 'desvio', n_comparaveis: 'docs comparáveis', freq: 'freq.', por_10k: 'por 10 mil',
  docs: 'docs', n_docs: 'nº docs', posicao: 'posição', tokens: 'palavras', tokens_total: 'palavras (total)', pct: '% do corpus',
  razao: 'razão', rel_ultimo: 'por 10 mil (último ano)', rel_media: 'média anterior', freq_ultimo: 'freq. último ano',
  docs_ultimo: 'docs último ano', ano_ultimo: 'ano', pct_maior_doc: '% no maior doc.', janela: 'janela', n_pend: 'pendências',
  n_total: 'total', n_excl: 'excluídos', n_av: 'avisos',
};

function cmRevisor() {
  try { return localStorage.getItem('raiox.revisor') || ''; } catch { return ''; }
}

function cmGuardarRevisor(valor) {
  try { localStorage.setItem('raiox.revisor', valor); } catch { /* navegação privada: segue sem lembrar */ }
}

function cmNum(chave, v) {
  if (v == null) return '—';
  if (typeof v !== 'number') return String(v);
  if (chave === 'p') return v < 0.0001 ? v.toExponential(1).replace('.', ',') : fmtNum(v, 4);
  return Number.isInteger(v) ? fmtNum(v) : fmtNum(v, Math.abs(v) < 10 ? 3 : 1);
}

function cmMetricas(m) {
  const itens = Object.entries(m || {}).filter(([, v]) => v == null || ['number', 'string'].includes(typeof v)).slice(0, 9);
  return itens.map(([k, v]) => `${esc(CM_ROTULO[k] || k)} ${esc(cmNum(k, v))}`).join(' · ');
}

function cmDestacar(trecho, termos) {
  const lista = (termos || []).filter(Boolean).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (!lista.length) return esc(trecho);
  return trecho.split(new RegExp(`(${lista.join('|')})`, 'gi'))
    .map((parte, i) => (i % 2 ? `<mark>${esc(parte)}</mark>` : esc(parte))).join('');
}

function cmEvidencias(c) {
  if (!c.evidencias.length) return '';
  return '<ul class="cm-ev">' + c.evidencias.map((e) => {
    const pag = e.pagina != null ? `p. ${e.pagina}` : 'sem página';
    const clicavel = e.posicao != null;
    return `<li class="${clicavel ? 'clicavel' : ''}" ${clicavel ? `data-doc="${e.documento_id}" data-pos="${e.posicao}" title="Clique para ver o contexto ampliado"` : ''}>
      <b>${esc(e.documento)}</b> <span class="discreto">${pag}</span> — ${e.termo.length || clicavel ? '“…' : ''}${cmDestacar(e.trecho, e.termo)}${e.termo.length || clicavel ? '…”' : ''}</li>`;
  }).join('') + '</ul>';
}

function cmLlmRotulo(c) {
  return c.origem === 'llm' ? `<span class="badge llm" title="Texto redigido por um LLM: é só sugestão até você aceitar">LLM (${esc((c.llm && c.llm.modelo) || c.regra.replace('LLM:', ''))})</span>` : '';
}

function cmVerificacao(c) {
  const v = c.verificacao;
  if (c.origem !== 'llm' || !v) return '';
  const itens = [];
  if (v.numeros_nao_encontrados.length) itens.push(`Números que não estão nas métricas fornecidas: <b>${v.numeros_nao_encontrados.map(esc).join(', ')}</b>`);
  if (v.citacoes_invalidas.length) itens.push(`Citações que não correspondem às evidências: <b>${v.citacoes_invalidas.map(esc).join(', ')}</b>`);
  if (v.trechos_nao_encontrados.length) itens.push(`Trechos entre aspas que não aparecem nas evidências: <b>${v.trechos_nao_encontrados.map((t) => '“' + esc(t) + '”').join('; ')}</b>`);
  const uso = c.llm && c.llm.uso && c.llm.uso.input_tokens != null ? ` · ${fmtNum(c.llm.uso.input_tokens)} tokens de entrada, ${fmtNum(c.llm.uso.output_tokens || 0)} de saída` : '';
  const quem = c.llm ? `<span class="discreto">${esc(c.llm.provedor)} · ${esc(c.llm.modelo)}${uso}${c.llm.request_id ? ' · ' + esc(c.llm.request_id) : ''}</span>` : '';
  return v.ok
    ? `<div class="cm-verif ok"><b>Conferência automática:</b> ${fmtNum(v.numeros_verificados)} número(s) conferidos; nenhum problema. ${quem}</div>`
    : `<div class="cm-verif"><b>Conferência automática encontrou problemas:</b><ul>${itens.map((i) => `<li>${i}</li>`).join('')}</ul>${quem}</div>`;
}

function cmBotoes(c) {
  const b = (acao, rotulo, extra) => `<button type="button" class="sec" data-acao="${acao}" ${extra || ''}>${rotulo}</button>`;
  if (c.status === 'obsoleto') return b('rejeitar', 'Rejeitar') + b('anotar', 'Anotar');
  const llm = c.origem === 'llm';
  return (c.status !== 'aceito' ? b('aceitar', c.status === 'revisar' ? (llm ? 'Aceitar mesmo assim' : 'Manter texto anterior (aceitar)') : 'Aceitar') : '')
    + (c.status === 'revisar' && c.texto_original && !llm ? b('aceitar', 'Aceitar proposta nova', 'data-proposta="1"') : '')
    + b('editar', 'Editar') + (c.status !== 'rejeitado' ? b('rejeitar', 'Rejeitar') : '') + b('anotar', 'Anotar')
    + (c.status !== 'sugerido' ? b('reabrir', 'Reabrir') : '');
}

function cmCartao(c) {
  const revisar = c.status === 'revisar' && c.origem !== 'llm'
    ? `<div class="cm-aviso"><b>Revisar:</b> ${esc(c.motivo_revisao || 'a evidência mudou.')}
       ${c.texto_original && c.texto_original !== c.texto ? `<div><span class="discreto">Proposta nova do motor:</span> ${esc(c.texto_original)}</div>` : ''}</div>`
    : '';
  const quem = c.revisor ? ` · ${esc(c.revisor)}` : '';
  return `<article class="cm st-${esc(c.status)}" data-id="${c.id}">
    <div class="cm-cab">
      <input type="checkbox" data-sel aria-label="Selecionar comentário ${c.id}" ${cm.sel.has(c.id) ? 'checked' : ''}>
      <span class="badge regra" title="${esc(c.chave || '')}">${esc(c.regra)}</span>${cmLlmRotulo(c)}
      <span class="badge">${esc(c.analise_tipo || '')}</span>
      <span class="badge status ${esc(c.status)}">${esc(c.status)}</span>
      <span class="discreto">força ${c.forca == null ? '—' : esc(fmtNum(c.forca, 1))}${quem}</span>
    </div>
    <p class="cm-texto">${esc(c.texto)}</p>
    ${revisar}
    ${c.origem === 'llm' ? cmVerificacao(c) : `<div class="cm-met">${cmMetricas(c.metricas)}</div>`}
    ${cmEvidencias(c)}
    ${c.nota ? `<div class="cm-nota"><b>Nota:</b> ${esc(c.nota)}</div>` : ''}
    <div class="cm-acoes">${cmBotoes(c)}</div>
  </article>`;
}

function cmAtualizarCartao(c) {
  const velho = $(`#cm-lista [data-id="${c.id}"]`);
  const filtro = $('#cm-status').value;
  if (filtro && !filtro.split(',').includes(c.status)) { velho && velho.remove(); return; }
  const tmp = document.createElement('div');
  tmp.innerHTML = cmCartao(c);
  if (velho) velho.replaceWith(tmp.firstElementChild);
}

function cmContagem() {
  const r = cm.resumo;
  if (!r) { $('#cm-contagem').innerHTML = ''; $('#cm-info').textContent = ''; return; }
  const atual = $('#cm-status').value;
  $('#cm-info').textContent = `(${r.total} no total)`;
  $('#cm-contagem').innerHTML = `<button type="button" class="chip cm-chip ${atual ? '' : 'ativo'}" data-st="">todos <b>${r.total}</b></button>`
    + CM_STATUS.map((s) => `<button type="button" class="chip cm-chip ${atual === s ? 'ativo' : ''}" data-st="${s}">${s} <b>${r.por_status[s] || 0}</b></button>`).join('');
}

async function carregarComentarios() {
  if (!slugAtual) return;
  if (cm.projeto !== slugAtual) { cm.projeto = slugAtual; cm.sel.clear(); }
  const seq = ++cm.seq;
  const q = new URLSearchParams();
  if ($('#cm-status').value) q.set('status', $('#cm-status').value);
  if ($('#cm-analise').value) q.set('analise', $('#cm-analise').value);
  if ($('#cm-origem').value) q.set('origem', $('#cm-origem').value);
  try {
    const [resumo, lista] = await Promise.all([
      api(`/api/projetos/${slugAtual}/comentarios/resumo`),
      api(`/api/projetos/${slugAtual}/comentarios?${q}`),
    ]);
    if (seq !== cm.seq) return;
    cm.resumo = resumo; cm.lista = lista;
    const ids = new Set(lista.map((c) => c.id));
    cm.sel.forEach((id) => { if (!ids.has(id)) cm.sel.delete(id); });
    cmContagem();
    $('#cm-lista').innerHTML = lista.length ? lista.map(cmCartao).join('')
      : `<p class="vazio">${resumo.total ? 'Nenhum comentário com este filtro.' : 'Sem comentários ainda: execute o pipeline do projeto (etapa "comentarios").'}</p>`;
    $('#cm-todos').checked = false;
  } catch (e) {
    $('#cm-msg').textContent = e.message; $('#cm-msg').className = 'erro';
  }
}

function cmMensagem(texto, erro) {
  const m = $('#cm-msg');
  m.textContent = texto; m.className = erro ? 'erro' : 'discreto';
}

async function cmAgir(id, corpo) {
  corpo.revisor = $('#cm-revisor').value.trim() || undefined;
  try {
    const c = await api(`/api/projetos/${slugAtual}/comentarios/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo),
    });
    const i = cm.lista.findIndex((x) => x.id === id);
    if (i >= 0) cm.lista[i] = c;
    cmAtualizarCartao(c);
    cmMensagem('');
    cm.resumo = await api(`/api/projetos/${slugAtual}/comentarios/resumo`);
    cmContagem();
  } catch (e) {
    cmMensagem(e.message, true);
  }
}

function cmEditor(art, tipo) {
  const c = cm.lista.find((x) => x.id === +art.dataset.id);
  const campo = tipo === 'editar' ? c.texto : (c.nota || '');
  const acoes = art.querySelector('.cm-acoes');
  acoes.insertAdjacentHTML('beforebegin', `<div class="cm-editor"><textarea class="cm-edit" maxlength="5000" aria-label="${tipo === 'editar' ? 'Texto do comentário' : 'Nota'}">${esc(campo)}</textarea>
    <div class="cm-acoes"><button type="button" data-salvar="${tipo}">Salvar</button><button type="button" class="sec" data-cancelar>Cancelar</button></div></div>`);
  acoes.hidden = true;
  art.querySelector('.cm-edit').focus();
}

async function cmContexto(li) {
  const aberto = li.querySelector('.ctx');
  if (aberto) { aberto.remove(); return; }
  const div = document.createElement('div');
  div.className = 'ctx'; div.textContent = 'Carregando contexto…';
  li.appendChild(div);
  try {
    const r = await api(`/api/projetos/${slugAtual}/analises/kwic/contexto?documento_id=${li.dataset.doc}&posicao=${li.dataset.pos}&janela=60`);
    div.innerHTML = `…${esc(r.esquerda)}<mark>${esc(r.termo)}</mark>${esc(r.direita)}… <span class="discreto">${esc(r.citacao)}</span>`;
  } catch (e) {
    div.textContent = e.message;
  }
}

$('#cm-lista').addEventListener('click', (ev) => {
  const art = ev.target.closest('.cm');
  if (!art) return;
  const id = +art.dataset.id;
  const botao = ev.target.closest('button');
  if (botao) {
    if (botao.dataset.salvar) {
      const valor = art.querySelector('.cm-edit').value;
      cmAgir(id, botao.dataset.salvar === 'editar' ? { acao: 'editar', texto: valor } : { acao: 'anotar', nota: valor });
    } else if (botao.hasAttribute('data-cancelar')) {
      art.querySelector('.cm-editor').remove(); art.querySelector('.cm-acoes').hidden = false;
    } else if (botao.dataset.acao === 'editar' || botao.dataset.acao === 'anotar') {
      if (!art.querySelector('.cm-editor')) cmEditor(art, botao.dataset.acao);
    } else if (botao.dataset.acao) {
      cmAgir(id, { acao: botao.dataset.acao, usar_proposta: botao.dataset.proposta === '1' });
    }
    return;
  }
  const li = ev.target.closest('li.clicavel');
  if (li) cmContexto(li);
});

$('#cm-lista').addEventListener('change', (ev) => {
  if (!ev.target.matches('[data-sel]')) return;
  const id = +ev.target.closest('.cm').dataset.id;
  if (ev.target.checked) cm.sel.add(id); else cm.sel.delete(id);
});

$('#cm-todos').addEventListener('change', (ev) => {
  document.querySelectorAll('#cm-lista [data-sel]').forEach((c) => {
    c.checked = ev.target.checked;
    const id = +c.closest('.cm').dataset.id;
    if (ev.target.checked) cm.sel.add(id); else cm.sel.delete(id);
  });
});

$('#cm-contagem').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-st]');
  if (!b) return;
  $('#cm-status').value = b.dataset.st;
  carregarComentarios();
});

for (const id of ['#cm-status', '#cm-analise', '#cm-origem']) $(id).addEventListener('change', carregarComentarios);

$('#cm-revisor').value = cmRevisor();
$('#cm-revisor').addEventListener('change', (ev) => cmGuardarRevisor(ev.target.value.trim()));

async function cmLote(acao) {
  const ids = [...cm.sel];
  if (!ids.length) return cmMensagem('Selecione ao menos um comentário.', true);
  try {
    const r = await api(`/api/projetos/${slugAtual}/comentarios/lote`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, acao, revisor: $('#cm-revisor').value.trim() || undefined }),
    });
    cm.sel.clear();
    await carregarComentarios();
    cmMensagem(`${r.atualizados} atualizado(s)${r.ignorados.length ? `, ${r.ignorados.length} ignorado(s)` : ''}.`);
  } catch (e) {
    cmMensagem(e.message, true);
  }
}

$('#cm-lote-aceitar').addEventListener('click', () => cmLote('aceitar'));
$('#cm-lote-rejeitar').addEventListener('click', () => cmLote('rejeitar'));

$('#cm-checar').addEventListener('click', async () => {
  cmMensagem('Conferindo evidências e números…');
  try {
    const r = await api(`/api/projetos/${slugAtual}/comentarios/checagem`, { method: 'POST' });
    await carregarComentarios();
    cmMensagem(r.falhas.length
      ? `${r.verificados} conferido(s): ${r.falhas.length} reprovado(s) e enviado(s) para revisar (motivo em cada comentário).`
      : `${r.verificados} conferido(s): nenhuma evidência ou número inválido.`, r.falhas.length > 0);
  } catch (e) {
    cmMensagem(e.message, true);
  }
});
