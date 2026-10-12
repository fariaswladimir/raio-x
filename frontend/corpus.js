// Aba "Corpus" (Frente 16): metadados por documento (16.4) e planilha do corpus (16.1/16.2) com .xlsx e .bib (16.3).
// Usa $, esc, api e slugAtual (app.js).

const cp = { meta: null, plan: null, parteSel: null, docSel: null };

function cpUrl(caminho, q) {
  const s = new URLSearchParams(q || {}).toString();
  return `/api/projetos/${slugAtual}/${caminho}${s ? '?' + s : ''}`;
}
function cpMsg(id, texto, erro) {
  const m = $(id);
  if (!m) return;
  m.textContent = texto || '';
  m.className = erro ? 'erro' : 'discreto';
}
function cpValor(v) {
  if (v == null) return '';
  return Array.isArray(v) ? v.join('; ') : String(v);
}

async function carregarCorpus() {
  if (!slugAtual) return;
  $('#cp-xlsx').href = cpUrl('exportar/planilha-corpus.xlsx');
  $('#cp-bib').href = cpUrl('exportar/bibliometrix.bib');
  try {
    const cfg = await api('/api/config/metadados');
    $('#cp-email').value = cfg.email_contato || '';
    $('#cp-privacidade').textContent = cfg.aviso_privacidade;
    await cpCarregarMeta();
    await cpCarregarPlanilha();
  } catch (e) { cpMsg('#cp-msg', e.message, true); }
}

// ---------- metadados ----------

async function cpCarregarMeta() {
  cp.meta = await api(cpUrl('metadados'));
  const cob = cp.meta.cobertura;
  $('#cp-cob-meta').innerHTML = Object.entries(cob.campos).map(([c, v]) =>
    `<span class="chip">${esc(c)}: ${v.com_valor}/${cob.documentos} <small>${Object.entries(v.por_origem).map(([o, n]) => `${esc(o)} ${n}`).join(', ')}</small></span>`).join(' ') +
    ` <span class="chip">conflitos: ${cob.conflitos}</span>`;
  const campos = ['titulo', 'autores', 'ano', 'doi', 'fonte', 'tipo_documento'];
  $('#cp-tab-meta tbody').innerHTML = cp.meta.documentos.map((d) => {
    const cel = campos.map((c) => {
      const v = d.campos[c];
      if (!v) return '<td class="discreto">—</td>';
      const alt = (v.alternativas || []).map((a) => `${a.origem}: ${cpValor(a.valor)}`).join(' | ');
      return `<td title="${esc(alt)}"><span class="selo">${esc(v.origem)}</span>${v.conflito ? ' <span class="selo erro" title="' + esc(alt) + '">conflito</span>' : ''} ${esc(cpValor(v.valor)).slice(0, 120)}</td>`;
    }).join('');
    const sug = d.grupo_sugerido && d.grupo_sugerido.valor
      ? `<span title="Trilha: ${esc(d.grupo_sugerido.trilha)}">${esc(d.grupo_sugerido.valor)}</span> ${d.grupo_difere ? `<button type="button" class="sec peq" data-confirmar="${d.documento_id}">aplicar</button>` : '✓'}`
      : '';
    return `<tr><td>${esc(d.rotulo)}</td>${cel}<td>${esc(d.grupo || '')}</td><td>${sug}</td><td><button type="button" class="sec peq" data-editar="${d.documento_id}">editar</button></td></tr>`;
  }).join('');
}

async function cpExtrair() {
  const online = $('#cp-online').checked;
  cpMsg('#cp-msg-meta', 'Extraindo…');
  try {
    const r = await api(cpUrl('metadados/extrair', { online: online ? 'true' : 'false', fonte: $('#cp-fonte').value }), { method: 'POST' });
    cpMsg('#cp-msg-meta', `${r.documentos} documento(s) lidos${r.online ? `; online: ${r.online.com_resposta}/${r.online.consultados} com resposta` : ''}.`);
    await cpCarregarMeta();
    await cpCarregarPlanilha();
  } catch (e) { cpMsg('#cp-msg-meta', e.message, true); }
}

async function cpImportarIndice() {
  const arq = $('#cp-indice').files[0];
  if (!arq) return;
  cpMsg('#cp-msg-meta', 'Importando o índice…');
  try {
    const r = await api(cpUrl('metadados/importar-indice', { nome: arq.name }), { method: 'POST', body: arq });
    cpMsg('#cp-msg-meta', `${r.casados} de ${r.linhas} linhas casadas por nome de arquivo; ${r.sugestoes_de_grupo.length} sugestões de grupo (nenhum grupo foi alterado).`);
    await cpCarregarMeta();
  } catch (e) { cpMsg('#cp-msg-meta', e.message, true); }
}

async function cpEditar(id) {
  const d = cp.meta.documentos.find((x) => x.documento_id === Number(id));
  const alteracoes = {};
  for (const c of ['titulo', 'autores', 'ano', 'doi']) {
    const atual = d.campos[c] ? cpValor(d.campos[c].valor) : '';
    const novo = prompt(`${c} (vazio = voltar ao automático)`, atual);
    if (novo === null) return;
    if (novo !== atual) alteracoes[c] = novo;
  }
  if (!Object.keys(alteracoes).length) return;
  try {
    await api(cpUrl(`metadados/${id}`), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(alteracoes) });
    await cpCarregarMeta();
    await cpCarregarPlanilha();
  } catch (e) { cpMsg('#cp-msg-meta', e.message, true); }
}

async function cpConfirmarGrupos(ids) {
  try {
    const r = await api(cpUrl('metadados/grupos/confirmar'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ documento_ids: ids }) });
    cpMsg('#cp-msg-meta', `${r.aplicados.length} grupo(s) aplicado(s).`);
    await cpCarregarMeta();
  } catch (e) { cpMsg('#cp-msg-meta', e.message, true); }
}

async function cpSalvarEmail() {
  try {
    await api('/api/config/metadados', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email_contato: $('#cp-email').value }) });
    cpMsg('#cp-msg-meta', 'E-mail de contato salvo.');
  } catch (e) { cpMsg('#cp-msg-meta', e.message, true); }
}

// ---------- planilha ----------

async function cpCarregarPlanilha() {
  cp.plan = await api(cpUrl('corpus/planilha'));
  const p = cp.plan;
  $('#cp-cob-plan').innerHTML = p.partes.map((x) => {
    const c = p.cobertura[x.chave];
    return `<tr><td>${esc(x.rotulo)}</td><td>${c.secao}</td><td>${c.padrao}</td><td>${c.llm}</td><td>${c.nao}</td></tr>`;
  }).join('');
  $('#cp-tab-plan thead').innerHTML = `<tr><th>Documento</th>${p.partes.map((x) => `<th>${esc(x.rotulo)}</th>`).join('')}<th>Sugestões LLM</th></tr>`;
  $('#cp-tab-plan tbody').innerHTML = p.linhas.map((l) => `<tr><td title="${esc(l.titulo || l.arquivo)}">${esc(l.rotulo)}</td>` +
    p.partes.map((x) => {
      const c = l.partes[x.chave];
      const marca = c.metodo === 'nao' ? 'nao' : c.metodo;
      return `<td class="cp-cel cp-${marca}" data-doc="${l.documento_id}" data-parte="${x.chave}" title="${esc(c.texto)}">${c.metodo === 'nao' ? '<span class="discreto">não encontrado</span>' : esc(c.texto).slice(0, 90) + '…'}${c.sugestoes.length ? ' <span class="selo">LLM?</span>' : ''}</td>`;
    }).join('') + `<td>${l.sugestoes_llm ? '<span class="selo">sim</span>' : ''}</td></tr>`).join('');
}

async function cpAbrirCelula(doc, parte) {
  cp.docSel = doc; cp.parteSel = parte;
  const r = await api(cpUrl('corpus/planilha/celula', { documento_id: doc, parte }));
  const trechos = r.trechos.map((t) => `<li><b>${esc(t.paginas || (t.pagina ? 'p. ' + t.pagina : ''))}</b> <span class="selo">${esc(t.metodo)}</span>
    <small>seção: ${esc(t.titulo_secao || t.secao || '')}; regra: ${esc(t.regra || '')}${t.nota != null ? '; nota ' + t.nota : ''}</small><br>${esc(t.texto)}
    ${t.contexto ? `<br><a href="#" data-contexto="${esc(t.contexto)}">ver contexto (KWIC)</a>` : ''}</li>`).join('');
  const sug = r.sugestoes.map((s) => `<li><span class="selo">${esc(s.origem)} · ${esc(s.status)}</span> <b>p. ${esc(s.pagina)}</b> ${esc(s.texto)}
    <br><button type="button" class="sec peq" data-decidir="aceitar" data-i="${s.indice}">aceitar</button>
    <button type="button" class="sec peq" data-decidir="rejeitar" data-i="${s.indice}">rejeitar</button></li>`).join('');
  $('#cp-detalhe').innerHTML = `<h4>${esc(r.rotulo)} · ${esc(r.rotulo_parte)} <small class="discreto">(${esc(r.metodo)})</small></h4>
    ${trechos ? `<ul>${trechos}</ul>` : '<p class="discreto">não encontrado</p>'}
    ${sug ? `<h5>Sugestões do LLM (conferidas: a frase existe no documento)</h5><ul>${sug}</ul>` : ''}<div id="cp-contexto" class="discreto"></div>`;
}

async function cpExtrairLLM() {
  cpMsg('#cp-msg-plan', 'Pedindo ao LLM as partes vazias ou fracas…');
  try {
    const r = await api(cpUrl('corpus/planilha/llm/extrair'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    cpMsg('#cp-msg-plan', `${r.sugestoes} sugestão(ões) conferida(s) contra o texto${r.erros.length ? `; ${r.erros.length} erro(s): ${r.erros[0].erro}` : ''}.`, r.erros.length > 0);
    await cpCarregarPlanilha();
  } catch (e) { cpMsg('#cp-msg-plan', e.message, true); }
}

document.addEventListener('click', async (ev) => {
  const t = ev.target;
  if (!t.closest || !t.closest('#aba-corpus')) return;
  if (t.dataset.confirmar) cpConfirmarGrupos([Number(t.dataset.confirmar)]);
  else if (t.dataset.editar) cpEditar(t.dataset.editar);
  else if (t.dataset.decidir) {
    await api(cpUrl(`corpus/planilha/llm/${cp.docSel}/${cp.parteSel}`), { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: t.dataset.decidir, indices: [Number(t.dataset.i)] }) });
    await cpAbrirCelula(cp.docSel, cp.parteSel);
    await cpCarregarPlanilha();
  } else if (t.dataset.contexto) {
    ev.preventDefault();
    const c = await api(t.dataset.contexto);
    $('#cp-contexto').innerHTML = `${esc(c.esquerda)} <mark>${esc(c.termo)}</mark> ${esc(c.direita)}<br><b>${esc(c.citacao)}</b>`;
  } else {
    const cel = t.closest('.cp-cel');
    if (cel) cpAbrirCelula(cel.dataset.doc, cel.dataset.parte).catch((e) => cpMsg('#cp-msg-plan', e.message, true));
  }
});
$('#cp-extrair').addEventListener('click', cpExtrair);
$('#cp-indice').addEventListener('change', cpImportarIndice);
$('#cp-salvar-email').addEventListener('click', cpSalvarEmail);
$('#cp-aplicar-grupos').addEventListener('click', () => cpConfirmarGrupos(null));
$('#cp-llm').addEventListener('click', cpExtrairLLM);
