// Aba "Coleta" (Frente 17): protocolo editável (17.1), coleta automática com progresso (17.2), matriz de revisão, exportações e concordância (17.3).
// Usa $, esc, slugAtual (app.js) e lerPlanilhaColeta/gravarPlanilhaColeta (coleta_mlr.js).

const cg = { itens: [], erros: [], versao: 0, abrev: new Set(), antesNumero: new Set(), maxFrases: 2, avisoPalavras: 40, tipos: [], partes: [], matriz: null, sub: 'protocolo', timer: null, sujo: false };
const CG_STATUS = { sugerido: 'sugerido', aceito: 'aceito', editado: 'editado', rejeitado: 'rejeitado', nao_encontrado: 'não encontrado', nao_se_aplica: 'não se aplica' };

function cgUrl(caminho, q) {
  const s = new URLSearchParams(q || {}).toString();
  return `/api/projetos/${slugAtual}/coleta/${caminho}${s ? '?' + s : ''}`;
}
function cgMsg(id, texto, erro) {
  const m = $(id);
  if (!m) return;
  m.textContent = texto || '';
  m.className = erro ? 'erro' : 'discreto';
}
async function cgApi(caminho, opcoes, cru) {
  const r = await fetch(caminho, opcoes);
  if (cru && r.ok) return r;
  const corpo = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = corpo.detail;
    const e = new Error(typeof d === 'string' ? d : (d && d.mensagem) || JSON.stringify(d || corpo));
    if (d && d.erros) e.erros = d.erros;
    throw e;
  }
  return corpo;
}
const cgJson = (corpo, metodo) => ({ method: metodo || 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo || {}) });

// ---------- regra das frases (mesma do servidor: app/services/coleta/protocolo.py) ----------

function cgEhAbreviacao(antes, resto) {
  const m = /(\p{L}[\p{L}\p{N}_.]*)$/u.exec(antes);
  if (!m) return false;
  const palavra = m[1].toLowerCase().replace(/\.+$/, '');
  if (cg.antesNumero.has(palavra)) return /^\s*\d/.test(resto);
  if (cg.abrev.has(palavra)) return true;
  return m[1].length === 1 && m[1] === m[1].toUpperCase() && m[1] !== m[1].toLowerCase();
}
function cgFrases(texto) {
  const t = String(texto || '').split(/\s+/).filter(Boolean).join(' ');
  if (!t) return [];
  const saida = []; let ini = 0;
  const re = /([.?!…]+)(["'”’)\]]*)(?=\s|$)/g;
  let m;
  while ((m = re.exec(t)) !== null) {
    const pont = m[1], fim = m.index + m[0].length;
    const resto = t.slice(fim).replace(/^\s+/, '');
    if (!resto) break;
    if (/[.…]/.test(pont[0])) {
      if (!/^["'“‘(\[]*[A-ZÀ-ÖØ-Þ0-9]/.test(resto)) continue;
      if (pont === '.' && cgEhAbreviacao(t.slice(ini, m.index), resto)) continue;
    }
    saida.push(t.slice(ini, fim).trim()); ini = fim;
  }
  const ultimo = t.slice(ini).trim();
  if (ultimo) saida.push(ultimo);
  return saida;
}
function cgContador(texto) {
  const n = cgFrases(texto).length, p = (String(texto || '').match(/\S+/g) || []).length;
  const ruim = n > cg.maxFrases;
  const aviso = !ruim && p > cg.avisoPalavras ? ` · ${p} palavras (acima de ~${cg.avisoPalavras})` : '';
  return { n, p, ruim, html: `<span class="${ruim ? 'erro' : (aviso ? 'avis' : 'discreto')}">${n}/${cg.maxFrases} frases${esc(aviso)}</span>` };
}

// ---------- protocolo ----------

function cgDoServidor(i) {
  return { id: i.id, nome: i.nome, definicao: i.definicao, tipo: i.tipo,
    categorias_txt: (i.categorias || []).map((c) => c.valor + ((c.palavras_chave || []).length ? ` [${c.palavras_chave.join(', ')}]` : '') + (c.definicao ? `: ${c.definicao}` : '')).join('\n'),
    onde_txt: (i.onde_procurar || ['qualquer']).join('; '), palavras_txt: (i.palavras_chave || []).join('; '), obrigatorio: !!i.obrigatorio,
    max_trechos: i.max_trechos || 3, parte_planilha: i.parte_planilha || '' };
}
function cgParaServidor(i) {
  return { id: i.id, nome: i.nome, definicao: i.definicao, tipo: i.tipo, categorias: i.categorias_txt, onde_procurar: i.onde_txt, palavras_chave: i.palavras_txt,
    obrigatorio: i.obrigatorio, max_trechos: Number(i.max_trechos) || 3, parte_planilha: i.parte_planilha || null };
}

async function carregarColeta() {
  if (!slugAtual) return;
  $('#cg-exp-csv').href = cgUrl('protocolo/exportar.csv');
  $('#cg-exp-xlsx').href = cgUrl('protocolo/exportar.xlsx');
  $('#cg-mlr-ref').value = typeof lerPlanilhaColeta === 'function' ? lerPlanilhaColeta() : '';
  try {
    const p = await cgApi(cgUrl('protocolo'));
    cg.regra = p.regra_frases;
    cg.abrev = new Set(p.regra_frases.abreviacoes);
    cg.antesNumero = new Set(p.regra_frases.abreviacoes_antes_de_numero);
    cg.maxFrases = p.regra_frases.max_frases_definicao;
    cg.avisoPalavras = p.regra_frases.aviso_palavras;
    cg.tipos = p.tipos; cg.partes = p.partes_planilha;
    cg.itens = p.itens.map(cgDoServidor); cg.erros = []; cg.versao = p.versao_protocolo; cg.sujo = false;
    const mods = await cgApi(cgUrl('protocolo/modelos'));
    $('#cg-modelo').innerHTML = mods.modelos.map((m) => `<option value="${esc(m.id)}" title="${esc(m.descricao)}">${esc(m.nome)} (${m.itens} itens)</option>`).join('');
    await cgVersoes();
    cgRender();
    cgIndicarVersao();
    cgSub(cg.sub);
  } catch (e) { cgMsg('#cg-msg', e.message, true); }
}

async function cgVersoes() {
  const h = await cgApi(cgUrl('protocolo/historico'));
  $('#cg-versoes').innerHTML = h.versoes.map((v) => `<option value="${v.versao}">v${v.versao}${v.atual ? ' (atual)' : ''} · ${v.itens} itens${v.atualizado_em ? ' · ' + esc(v.atualizado_em.replace('T', ' ')) : ''}</option>`).join('');
  const atual = h.versoes.find((v) => v.atual);
  if (atual) $('#cg-versoes').value = String(atual.versao);
}
function cgIndicarVersao() {
  $('#cg-versao').textContent = (cg.versao ? `protocolo v${cg.versao}` : 'sem protocolo salvo') + (cg.sujo ? ' · alterações não salvas' : '');
}

function cgOpcoesTipo(sel) { return cg.tipos.map((t) => `<option value="${t.id}"${t.id === sel ? ' selected' : ''}>${esc(t.rotulo)}</option>`).join(''); }
function cgOpcoesParte(sel) { return `<option value="">—</option>` + cg.partes.map((p) => `<option value="${p.chave}"${p.chave === sel ? ' selected' : ''}>${esc(p.rotulo)}</option>`).join(''); }

function cgRender() {
  const erros = {};
  for (const e of cg.erros) { const k = (e.linha || 0) - 1; (erros[k] = erros[k] || []).push(e); }
  $('#cg-tab-protocolo tbody').innerHTML = cg.itens.map((it, i) => {
    const cat = it.tipo === 'categoria' || it.tipo === 'multipla';
    const c = cgContador(it.definicao);
    const linha = `<tr data-i="${i}" class="${erros[i] ? 'cg-linha-erro' : ''}">
      <td>${i + 1}</td>
      <td><input data-f="id" value="${esc(it.id)}" size="8" aria-label="id do item ${i + 1}"></td>
      <td><input data-f="nome" value="${esc(it.nome)}" size="22" aria-label="nome do item ${i + 1}"></td>
      <td><textarea data-f="definicao" rows="3" cols="34" aria-label="definição do item ${i + 1}">${esc(it.definicao)}</textarea><div class="cg-cont" data-cont>${c.html}</div></td>
      <td><select data-f="tipo" aria-label="tipo do item ${i + 1}">${cgOpcoesTipo(it.tipo)}</select></td>
      <td>${cat ? `<textarea data-f="categorias_txt" rows="4" cols="34" aria-label="categorias do item ${i + 1}">${esc(it.categorias_txt)}</textarea>` : '<span class="discreto">—</span>'}</td>
      <td><input data-f="onde_txt" value="${esc(it.onde_txt)}" size="16" aria-label="onde procurar do item ${i + 1}"></td>
      <td><textarea data-f="palavras_txt" rows="3" cols="22" aria-label="palavras-chave do item ${i + 1}">${esc(it.palavras_txt)}</textarea></td>
      <td><input type="checkbox" data-f="obrigatorio"${it.obrigatorio ? ' checked' : ''} aria-label="obrigatório"></td>
      <td><input type="number" data-f="max_trechos" min="1" max="10" value="${esc(it.max_trechos)}" style="width:3.5em" aria-label="máximo de trechos"></td>
      <td><select data-f="parte_planilha" aria-label="parte da planilha do corpus">${cgOpcoesParte(it.parte_planilha)}</select></td>
      <td class="cg-acoes"><button type="button" class="sec peq" data-acao="subir" title="subir"${i === 0 ? ' disabled' : ''}>↑</button>
        <button type="button" class="sec peq" data-acao="descer" title="descer"${i === cg.itens.length - 1 ? ' disabled' : ''}>↓</button>
        <button type="button" class="sec peq" data-acao="duplicar" title="duplicar">⧉</button>
        <button type="button" class="sec peq" data-acao="remover" title="remover">✕</button></td></tr>`;
    const msgs = (erros[i] || []).map((e) => `<div class="erro">${esc(e.campo ? e.campo + ': ' : '')}${esc(e.mensagem)}${e.sugestao && e.codigo === 'frases_excedidas'
      ? ` <button type="button" class="sec peq" data-acao="sugestao" data-i="${i}">usar sugestão de corte</button>` : ''}</div>`).join('');
    return linha + (msgs ? `<tr class="cg-linha-erro-msg"><td></td><td colspan="11">${msgs}</td></tr>` : '');
  }).join('') || '<tr><td colspan="12" class="discreto">Protocolo vazio: carregue um modelo, importe um arquivo ou adicione itens.</td></tr>';
  const avisos = cg.erros.length;
  const caixa = $('#cg-erros');
  caixa.hidden = !avisos;
  caixa.textContent = avisos ? `${avisos} problema(s) no protocolo: corrija as linhas destacadas e salve de novo.` : '';
}

function cgNovoItem() {
  let n = cg.itens.length + 1;
  while (cg.itens.some((x) => x.id === `I${String(n).padStart(2, '0')}`)) n += 1;
  return { id: `I${String(n).padStart(2, '0')}`, nome: '', definicao: '', tipo: 'texto', categorias_txt: '', onde_txt: 'qualquer', palavras_txt: '', obrigatorio: false, max_trechos: 3, parte_planilha: '' };
}

function cgMarcarSujo() { cg.sujo = true; cgIndicarVersao(); }

$('#cg-tab-protocolo tbody').addEventListener('input', (ev) => {
  const t = ev.target, tr = t.closest('tr[data-i]');
  if (!tr || !t.dataset.f) return;
  const it = cg.itens[Number(tr.dataset.i)];
  it[t.dataset.f] = t.type === 'checkbox' ? t.checked : t.value;
  if (t.dataset.f === 'definicao') tr.querySelector('[data-cont]').innerHTML = cgContador(t.value).html;
  cgMarcarSujo();
});
$('#cg-tab-protocolo tbody').addEventListener('change', (ev) => {
  const t = ev.target, tr = t.closest('tr[data-i]');
  if (tr && t.dataset.f === 'tipo') { cg.itens[Number(tr.dataset.i)].tipo = t.value; cgMarcarSujo(); cgRender(); }
});
$('#cg-tab-protocolo tbody').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-acao]');
  if (!b) return;
  const tr = b.closest('tr[data-i]');
  const i = tr ? Number(tr.dataset.i) : Number(b.dataset.i);
  const a = b.dataset.acao;
  if (a === 'subir' && i > 0) [cg.itens[i - 1], cg.itens[i]] = [cg.itens[i], cg.itens[i - 1]];
  else if (a === 'descer' && i < cg.itens.length - 1) [cg.itens[i + 1], cg.itens[i]] = [cg.itens[i], cg.itens[i + 1]];
  else if (a === 'remover') cg.itens.splice(i, 1);
  else if (a === 'duplicar') cg.itens.splice(i + 1, 0, { ...cg.itens[i], id: cg.itens[i].id + '_2' });
  else if (a === 'sugestao') {
    const e = cg.erros.find((x) => x.linha === Number(b.dataset.i) + 1 && x.codigo === 'frases_excedidas');
    if (e) cg.itens[Number(b.dataset.i)].definicao = e.sugestao;
    cg.erros = cg.erros.filter((x) => !(x.linha === Number(b.dataset.i) + 1 && x.codigo === 'frases_excedidas'));
  }
  cg.erros = a === 'sugestao' ? cg.erros : [];
  cgMarcarSujo(); cgRender();
});
$('#cg-adicionar').addEventListener('click', () => { cg.itens.push(cgNovoItem()); cgMarcarSujo(); cgRender(); });

async function cgSalvar() {
  cgMsg('#cg-msg', 'Salvando…');
  try {
    const r = await cgApi(cgUrl('protocolo'), cgJson({ itens: cg.itens.map(cgParaServidor) }, 'PUT'));
    cg.itens = r.itens.map(cgDoServidor); cg.erros = []; cg.versao = r.versao_protocolo; cg.sujo = false;
    cgRender(); cgIndicarVersao(); await cgVersoes();
    cgMsg('#cg-msg', (r.alterado ? `Salvo: versão ${r.versao_protocolo}.` : 'Sem alterações: a versão continua a mesma.') + (r.avisos.length ? ` ${r.avisos.length} aviso(s): ${r.avisos[0].mensagem}` : ''));
  } catch (e) {
    cg.erros = e.erros || [];
    cgRender();
    cgMsg('#cg-msg', e.message, true);
  }
}
$('#cg-salvar').addEventListener('click', cgSalvar);

$('#cg-carregar-modelo').addEventListener('click', async () => {
  const id = $('#cg-modelo').value;
  if (!id) return;
  if (cg.itens.length && !confirm('Substituir os itens da tela pelo modelo? (nada é gravado até você salvar)')) return;
  try {
    const r = await cgApi(cgUrl(`protocolo/modelos/${id}/carregar`, { aplicar: 'false', modo: 'substituir' }), { method: 'POST' });
    cg.itens = r.itens.map(cgDoServidor); cg.erros = [];
    cgMarcarSujo(); cgRender();
    cgMsg('#cg-msg', `Modelo "${r.modelo}" carregado na tela (${r.itens.length} itens). Clique em "Salvar protocolo" para gravar.`);
  } catch (e) { cgMsg('#cg-msg', e.message, true); }
});

$('#cg-importar').addEventListener('change', async (ev) => {
  const arq = ev.target.files[0];
  if (!arq) return;
  cgMsg('#cg-msg', 'Importando…');
  try {
    const r = await cgApi(cgUrl('protocolo/importar', { nome: arq.name }), { method: 'POST', body: arq });
    cg.itens = r.itens.map(cgDoServidor); cg.erros = r.erros;
    cgMarcarSujo(); cgRender();
    cgMsg('#cg-msg', `${r.itens.length} item(ns) lidos de ${arq.name} (${r.formato}); ${r.erros.length} erro(s), ${r.avisos.length} aviso(s). ${r.erros.length ? 'Corrija as linhas em vermelho e salve.' : 'Clique em "Salvar protocolo" para gravar.'}`, r.erros.length > 0);
  } catch (e) { cgMsg('#cg-msg', e.message, true); }
  ev.target.value = '';
});

$('#cg-restaurar').addEventListener('click', async () => {
  const v = $('#cg-versoes').value;
  if (!v || !confirm(`Restaurar a versão ${v}? Isso cria uma nova versão com esse conteúdo.`)) return;
  try {
    await cgApi(cgUrl(`protocolo/historico/${v}/restaurar`), { method: 'POST' });
    await carregarColeta();
    cgMsg('#cg-msg', `Versão ${v} restaurada como nova versão.`);
  } catch (e) { cgMsg('#cg-msg', e.message, true); }
});

// ---------- sub-abas ----------

function cgSub(nome) {
  cg.sub = nome;
  document.querySelectorAll('#cg-subabas button').forEach((b) => b.classList.toggle('on', b.dataset.sub === nome));
  document.querySelectorAll('#aba-coleta .cg-sub').forEach((d) => { d.hidden = d.dataset.sub !== nome; });
  if (nome === 'revisar') cgCarregarMatriz().catch((e) => cgMsg('#cg-msg-rev', e.message, true));
  if (nome === 'coletar') cgConsultarProgresso();
}
$('#cg-subabas').addEventListener('click', (ev) => { const b = ev.target.closest('button[data-sub]'); if (b) cgSub(b.dataset.sub); });

// ---------- coleta (17.2) ----------

function cgPararTimer() { if (cg.timer) clearInterval(cg.timer); cg.timer = null; }

function cgMostrarProgresso(p) {
  const barra = $('#cg-barra');
  barra.hidden = !p.run_id;
  const pct = p.total ? Math.min(100, Math.round((p.feitos / p.total) * 100)) : (p.rodando ? 0 : 100);
  barra.setAttribute('aria-valuenow', String(pct));
  barra.firstElementChild.style.width = pct + '%';
  const chips = [`documentos: ${p.feitos}/${p.total == null ? '?' : p.total}`, `calculadas: ${p.calculadas || 0}`, `puladas (sem mudança): ${p.puladas || 0}`, `decididas preservadas: ${p.preservadas || 0}`];
  if (p.llm && p.llm.modo !== 'desligado') chips.push(`LLM: ${p.llm.chamadas} chamada(s), ${p.llm.trechos_verificados} trecho(s) verificados, ${p.llm.descartados} descartados`);
  let extra = '';
  if (p.rodando) extra = `<span class="chip">rodando: ${esc(p.documento_atual || '…')}</span>`;
  else if (p.erro) extra = `<span class="chip erro">falhou: ${esc(p.erro)}</span>`;
  else if (p.resumo) {
    const r = p.resumo;
    extra = `<span class="chip">concluída em ${r.segundos} s</span>` + Object.entries(r.por_status || {}).map(([s, n]) => `<span class="chip">${esc(CG_STATUS[s] || s)}: ${n}</span>`).join('')
      + (r.revisar ? `<span class="chip erro">${r.revisar} célula(s) decididas com evidência a revisar</span>` : '')
      + (r.sem_texto && r.sem_texto.length ? `<span class="chip">${r.sem_texto.length} documento(s) sem texto processado</span>` : '')
      + ((r.erros || []).length ? `<span class="chip erro">${r.erros.length} erro(s) do LLM: ${esc(r.erros[0].erro)}</span>` : '');
  }
  $('#cg-resumo').innerHTML = chips.map((c) => `<span class="chip">${esc(c)}</span>`).join('') + extra;
  $('#cg-executar').disabled = !!p.rodando;
}

async function cgConsultarProgresso() {
  if (!slugAtual) return;
  try {
    const p = await cgApi(cgUrl('progresso'));
    cgMostrarProgresso(p);
    if (p.rodando && !cg.timer) cg.timer = setInterval(cgConsultarProgresso, 1000);
    if (!p.rodando && cg.timer) { cgPararTimer(); cgMsg('#cg-msg-exec', p.erro ? 'A coleta falhou.' : 'Coleta concluída: veja a aba Revisar.', !!p.erro); }
  } catch (e) { cgPararTimer(); cgMsg('#cg-msg-exec', e.message, true); }
}

$('#cg-executar').addEventListener('click', async () => {
  if (cg.sujo && !confirm('Há alterações não salvas no protocolo: a coleta usa o protocolo salvo. Continuar?')) return;
  cgMsg('#cg-msg-exec', 'Iniciando…');
  try {
    await cgApi(cgUrl('executar'), cgJson({ llm: $('#cg-llm').value, forcar: $('#cg-forcar').checked }));
    cgMsg('#cg-msg-exec', 'Coleta em andamento…');
    cgConsultarProgresso();
  } catch (e) { cgMsg('#cg-msg-exec', e.message, true); }
});

// ---------- revisão (17.3) ----------

async function cgCarregarMatriz() {
  const q = { status: $('#cg-f-status').value, item: $('#cg-f-item').value, grupo: $('#cg-f-grupo').value };
  Object.keys(q).forEach((k) => { if (!q[k]) delete q[k]; });
  const m = await cgApi(cgUrl('matriz', q));
  cg.matriz = m;
  const preencher = (id, opcoes, rotulo) => {
    const el = $(id), atual = el.value;
    el.innerHTML = '<option value="">todos</option>' + opcoes.map(([v, r]) => `<option value="${esc(v)}">${esc(r)}</option>`).join('');
    el.value = atual;
  };
  preencher('#cg-f-status', m.status.map((s) => [s, m.rotulo_status[s]]));
  if (!q.item) preencher('#cg-f-item', m.contadores.map((c) => [c.id, `${c.id} ${c.nome}`]));
  preencher('#cg-f-grupo', m.grupos.map((g) => [g, g]));
  $('#cg-tab-contadores').innerHTML = `<thead><tr><th>Item</th><th>Tipo</th><th>Sugerido</th><th>Aceito</th><th>Editado</th><th>Rejeitado</th><th>Não encontrado</th><th>Não se aplica</th><th>Revisão</th><th>Obrigatório sem valor</th></tr></thead><tbody>`
    + m.contadores.map((c) => `<tr><td title="${esc(c.nome)}"><b>${esc(c.id)}</b> ${esc(c.nome)}</td><td>${esc(c.tipo)}</td><td>${c.contagem.sugerido}</td><td>${c.contagem.aceito}</td><td>${c.contagem.editado}</td><td>${c.contagem.rejeitado}</td>
      <td>${c.contagem.nao_encontrado}</td><td>${c.contagem.nao_se_aplica}</td><td>${c.decididos}/${c.total} (${Math.round(c.progresso * 100)}%)</td><td>${c.obrigatorio ? (c.obrigatorio_sem_valor ? `<span class="erro">${c.obrigatorio_sem_valor}</span>` : '0') : '—'}</td></tr>`).join('') + '</tbody>';
  const cab = `<thead><tr><th>Documento</th>${m.itens.map((i) => `<th title="${esc(i.nome)} (${esc(i.tipo)})">${esc(i.id)}<br><button type="button" class="sec peq" data-lote-item="${esc(i.id)}" title="aceitar todos os sugeridos deste item">aceitar col.</button></th>`).join('')}<th></th></tr></thead>`;
  const corpo = m.linhas.map((l) => `<tr><td title="${esc(l.arquivo)}">${esc(l.rotulo)}<br><small class="discreto">${l.decididas}/${l.total}</small></td>`
    + m.itens.map((i) => {
      const c = l.celulas[i.id];
      if (!c || c.oculta) return `<td class="cg-cel co-st-vazio" data-doc="${l.documento_id}" data-item="${esc(i.id)}"><span class="discreto">${c ? '' : '·'}</span></td>`;
      const v = c.valor ? esc(c.valor.length > 28 ? c.valor.slice(0, 27) + '…' : c.valor) : '<span class="discreto">—</span>';
      return `<td class="cg-cel co-st-${esc(c.status)}" data-doc="${l.documento_id}" data-item="${esc(i.id)}" title="${esc(CG_STATUS[c.status])} · ${esc(c.origem || '')}${c.confianca != null ? ' · conf. ' + c.confianca : ''}">${v}${c.revisar ? ' <b class="erro" title="' + esc(c.revisar) + '">!</b>' : ''}${c.pagina != null ? ` <small class="discreto">p.${c.pagina}</small>` : ''}</td>`;
    }).join('') + `<td><button type="button" class="sec peq" data-lote-doc="${l.documento_id}" title="aceitar todos os sugeridos deste documento">aceitar linha</button></td></tr>`).join('');
  $('#cg-matriz').innerHTML = cab + `<tbody>${corpo || `<tr><td colspan="${m.itens.length + 2}" class="discreto">Nenhuma célula: execute a coleta (aba 2) ou ajuste os filtros.</td></tr>`}</tbody>`;
  cgMsg('#cg-msg-rev', `${m.documentos} documento(s) · protocolo v${m.versao_protocolo}`);
}

['#cg-f-status', '#cg-f-item', '#cg-f-grupo'].forEach((s) => $(s).addEventListener('change', () => cgCarregarMatriz().catch((e) => cgMsg('#cg-msg-rev', e.message, true))));
$('#cg-atualizar').addEventListener('click', () => cgCarregarMatriz().catch((e) => cgMsg('#cg-msg-rev', e.message, true)));

async function cgLote(corpo) {
  try {
    const r = await cgApi(cgUrl('decidir-lote'), cgJson(corpo));
    cgMsg('#cg-msg-rev', `${r.aplicadas} célula(s) aceitas; ignoradas: ${r.ignoradas_ambiguas} ambígua(s), ${r.ignoradas_sem_valor} sem valor.`);
    await cgCarregarMatriz();
  } catch (e) { cgMsg('#cg-msg-rev', e.message, true); }
}

async function cgAbrirCelula(doc, item) {
  const r = await cgApi(cgUrl('celula', { documento_id: doc, item }));
  const c = r.celula, it = r.item;
  const trechos = (c.trechos || []).map((t) => `<li><b>${t.pagina != null ? 'p. ' + esc(t.pagina) : 'sem página'}</b> <small class="discreto">seção: ${esc(t.secao || '')}</small><br>${esc(t.texto)}
    ${t.contexto ? `<br><a href="#" data-contexto="${esc(t.contexto)}">ver contexto (KWIC)</a>` : ''}</li>`).join('');
  const alts = (c.alternativas || []).map((a) => `<li>${esc(Array.isArray(a.valor) ? a.valor.join('; ') : a.valor)}${a.unidade ? ' ' + esc(a.unidade) : ''} <small class="discreto">${esc(a.origem || '')}${a.nota != null ? ' · nota ' + a.nota : ''}</small></li>`).join('');
  let entrada;
  if (it.tipo === 'categoria') entrada = `<select id="cg-novo-valor">${it.categorias.map((x) => `<option>${esc(x.valor)}</option>`).join('')}</select>`;
  else if (it.tipo === 'multipla') entrada = it.categorias.map((x) => `<label class="inline check"><input type="checkbox" class="cg-novo-multi" value="${esc(x.valor)}"> ${esc(x.valor)}</label>`).join(' ');
  else if (it.tipo === 'sim_nao') entrada = '<select id="cg-novo-valor"><option>sim</option><option>não</option></select>';
  else entrada = `<input id="cg-novo-valor" size="30" placeholder="${it.tipo === 'numero' ? 'ex.: 312 ou 1.200 respondentes' : it.tipo === 'data' ? 'ex.: 2025 ou 2025-03' : 'texto'}">`;
  $('#cg-detalhe').dataset.doc = doc; $('#cg-detalhe').dataset.item = item;
  $('#cg-detalhe').innerHTML = `<div class="cartao"><h4>${esc(r.rotulo)} · ${esc(it.id)} ${esc(it.nome)} <small class="discreto">(${esc(it.tipo)})</small></h4>
    <p class="discreto">${esc(it.definicao)}</p>
    <p><span class="selo co-st-${esc(c.status)}">${esc(CG_STATUS[c.status])}</span> <b>${esc(r.valor_texto || '—')}</b>${c.unidade ? ' ' + esc(c.unidade) : ''}
      <small class="discreto">origem: ${esc(c.origem || '')} · confiança ${c.confianca != null ? esc(c.confianca) : '—'} · ${esc(c.justificativa || '')}</small>
      ${c.revisar ? `<br><span class="erro">Revisar: ${esc(c.revisar)}</span>` : ''}${c.definicao_mudou ? '<br><span class="avis">A definição do item mudou desde a sua decisão.</span>' : ''}</p>
    ${trechos ? `<ul class="cg-trechos">${trechos}</ul>` : '<p class="discreto">Sem trecho: nada foi encontrado neste documento.</p>'}
    ${alts ? `<h5>Outras possibilidades</h5><ul>${alts}</ul>` : ''}
    <p class="barra"><button type="button" data-decidir="aceitar">Aceitar</button>
      <button type="button" class="sec" data-decidir="rejeitar">Rejeitar</button>
      <button type="button" class="sec" data-decidir="nao_se_aplica">Não se aplica</button>
      ${c.automatico ? '<button type="button" class="sec" data-decidir="desfazer">Desfazer decisão</button>' : ''}</p>
    <p class="barra"><label class="inline">Editar valor ${entrada}</label><button type="button" class="sec" data-decidir="editar">Salvar valor editado</button>
      <label class="inline">Nota <input id="cg-nota" size="30" value="${esc(c.nota || '')}"></label></p>
    <div id="cg-contexto" class="discreto"></div></div>`;
  $('#cg-detalhe').scrollIntoView({ block: 'nearest' });
}

async function cgDecidir(acao) {
  const d = $('#cg-detalhe');
  const corpo = { documento_id: Number(d.dataset.doc), item: d.dataset.item, acao, nota: $('#cg-nota') ? $('#cg-nota').value : null };
  if (acao === 'editar') {
    const multi = [...document.querySelectorAll('.cg-novo-multi:checked')].map((x) => x.value);
    corpo.valor = document.querySelector('.cg-novo-multi') ? multi : ($('#cg-novo-valor') ? $('#cg-novo-valor').value : null);
  }
  try {
    await cgApi(cgUrl('celula/decidir'), cgJson(corpo));
    await cgCarregarMatriz();
    await cgAbrirCelula(d.dataset.doc, d.dataset.item);
  } catch (e) { cgMsg('#cg-msg-rev', e.message, true); }
}

document.addEventListener('click', async (ev) => {
  const t = ev.target;
  if (!t.closest || !t.closest('#aba-coleta')) return;
  if (t.dataset.loteItem) cgLote({ acao: 'aceitar', item: t.dataset.loteItem });
  else if (t.dataset.loteDoc) cgLote({ acao: 'aceitar', documento_id: Number(t.dataset.loteDoc) });
  else if (t.dataset.decidir) cgDecidir(t.dataset.decidir);
  else if (t.dataset.contexto) {
    ev.preventDefault();
    try {
      const c = await cgApi(t.dataset.contexto);
      $('#cg-contexto').innerHTML = `${esc(c.esquerda)} <mark>${esc(c.termo)}</mark> ${esc(c.direita)}<br><b>${esc(c.citacao)}</b>`;
    } catch (e) { cgMsg('#cg-msg-rev', e.message, true); }
  } else {
    const cel = t.closest('td.cg-cel');
    if (cel && cel.dataset.item && !cel.classList.contains('co-st-vazio')) cgAbrirCelula(cel.dataset.doc, cel.dataset.item).catch((e) => cgMsg('#cg-msg-rev', e.message, true));
  }
});

// ---------- exportação e concordância ----------

$('#cg-x-baixar').addEventListener('click', () => {
  if (!slugAtual) return;
  window.location.href = cgUrl('exportar', { formato: $('#cg-x-formato').value, versao: $('#cg-x-versao').value, extensao: $('#cg-x-ext').value });
});

$('#cg-mlr-enviar').addEventListener('click', async () => {
  const ref = $('#cg-mlr-ref').value.trim();
  if (typeof gravarPlanilhaColeta === 'function') gravarPlanilhaColeta(ref);
  cgMsg('#cg-msg-exp', 'Gerando…');
  try {
    const r = await cgApi(cgUrl('exportar/mlr'), cgJson({ planilha_referencia: ref || null, incluir_duplicados: !$('#cg-mlr-omitir').checked }), true);
    const resumo = JSON.parse(r.headers.get('X-Raiox-Resumo') || '{}');
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `coleta_raiox_${slugAtual}.xlsx`; a.click();
    cgMsg('#cg-msg-exp', `${resumo.exportados} trecho(s) exportados; ${resumo.duplicados_na_planilha || 0} já constavam na planilha do usuário.`);
  } catch (e) { cgMsg('#cg-msg-exp', e.message, true); }
});

$('#cg-c-arquivo').addEventListener('change', async (ev) => {
  const arq = ev.target.files[0];
  if (!arq) return;
  try {
    const r = await cgApi(cgUrl('concordancia/segundo-codificador', { nome: arq.name }), { method: 'POST', body: arq });
    $('#cg-c-fonte').value = 'segundo';
    cgMsg('#cg-msg-conc', `Segundo codificador: ${r.documentos_casados} documento(s), ${r.valores} valor(es), itens ${r.itens_reconhecidos.join(', ')}${r.nao_casados.length ? '; não casados: ' + r.nao_casados.slice(0, 3).join(', ') : ''}.`);
  } catch (e) { cgMsg('#cg-msg-conc', e.message, true); }
  ev.target.value = '';
});

const cgNum = (x, n) => (x == null ? '—' : Number(x).toFixed(n || 2).replace('.', ','));
$('#cg-c-calcular').addEventListener('click', async () => {
  cgMsg('#cg-msg-conc', 'Calculando…');
  try {
    const q = { fonte: $('#cg-c-fonte').value };
    if ($('#cg-c-bandas').value.trim()) q.bandas = $('#cg-c-bandas').value.trim();
    const r = await cgApi(cgUrl('concordancia', q));
    $('#cg-tab-conc').innerHTML = '<thead><tr><th>Item</th><th>Tipo</th><th>n</th><th>% concordância</th><th>Kappa (Cohen)</th><th>Alfa (Krippendorff)</th><th>Nota</th></tr></thead><tbody>'
      + r.itens.map((i) => `<tr><td><b>${esc(i.id)}</b> ${esc(i.nome)}</td><td>${esc(i.tipo)}</td><td>${i.n}</td><td>${i.percentual == null ? '—' : cgNum(i.percentual * 100, 0) + '%'}</td>
        <td>${cgNum(i.kappa)}${i.kappa_faixa ? ` <small class="discreto">${esc(i.kappa_faixa)}</small>` : ''}</td><td>${cgNum(i.alfa)}${i.alfa_faixa ? ` <small class="discreto">${esc(i.alfa_faixa)}${i.metrica ? ', ' + esc(i.metrica) : ''}</small>` : ''}</td>
        <td class="discreto">${esc(i.nota || '')}</td></tr>`).join('') + '</tbody>';
    cgMsg('#cg-msg-conc', r.descricao);
  } catch (e) { cgMsg('#cg-msg-conc', e.message, true); }
});
