// Sub-aba "Classificação" da aba Codificação (15.11): classificação zero-shot/few-shot por LLM nos rótulos do dicionário
// (ou numa lista), revisão item a item e concordância com os rótulos humanos. Reaproveita de codificacao.js: cdUrl-like,
// renderConfusao e ic. Usa $, esc, api, fmtNum e slugAtual (app.js).

const cl = { timer: null, pagina: 0, porPagina: 100, dicionario: [] };

function clUrl(caminho, q) {
  const s = new URLSearchParams(q || {}).toString();
  return `/api/projetos/${slugAtual}/classificacao${caminho ? '/' + caminho : ''}${s ? '?' + s : ''}`;
}

function clMsg(id, texto, erro) {
  const m = $(id);
  m.textContent = texto || '';
  m.className = erro ? 'erro' : 'discreto';
}

function clMostrarAba(aba) {
  const classif = aba === 'classificacao';
  document.querySelectorAll('#cl-subabas button').forEach((b) => {
    b.classList.toggle('on', b.dataset.clAba === aba);
    b.setAttribute('aria-selected', b.dataset.clAba === aba ? 'true' : 'false');
  });
  $('#aba-codificacao').classList.toggle('cl-ativo', classif);  // o CSS esconde o resto da aba sem mexer no atributo hidden dos blocos
  $('#cl-painel').hidden = !classif;
  if (classif) clCarregar();
}

function clCorpo() {
  const c = { origem: $('#cl-origem').value, modo: $('#cl-modo').value, k: +$('#cl-k').value || 3, multirrotulo: $('#cl-multi').checked,
    limite: +$('#cl-limite').value || null };
  if ($('#cl-fonte').value === 'lista') c.rotulos = $('#cl-lista').value;
  return c;
}

function clCustoHtml(c) {
  if (!c) return '';
  if (!c.preco_conhecido) return esc(c.nota || '');
  const brl = (x) => 'US$ ' + fmtNum(x, 2);
  const cache = c.cache_aplicavel
    ? `${brl(c.custo_com_cache_usd)} com cache de prompt (−${fmtNum(c.economia_pct, 0)}%; ~${fmtNum(c.tokens_cache_leitura || 0)} tokens lidos do cache a preço reduzido)`
    : 'cache de prompt não se aplica (prefixo abaixo do mínimo do modelo)';
  return `Custo estimado (${esc(c.modelo)}): ${brl(c.custo_sem_cache_usd)} sem cache · ${cache}. Prefixo ~${fmtNum(c.prefixo_tokens)} tokens. ${esc(c.nota || '')}`;
}

async function clEstimar() {
  if (!slugAtual) return;
  try {
    const e = await api(clUrl('estimativa'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(clCorpo()) });
    const prov = { nenhum: 'nenhum', ollama: 'Ollama (local)', anthropic: 'Anthropic (remoto)', openai_compativel: 'compatível com OpenAI (remoto)' }[e.provedor] || e.provedor;
    $('#cl-estimativa').innerHTML = `${fmtNum(e.unidades)} unidade(s) · ${e.rotulos} rótulo(s)${e.exemplos ? ` · ${e.exemplos} exemplo(s) humanos (fora da avaliação)` : ''} · ~${fmtNum(e.tokens_entrada_aprox)} tokens de entrada e ~${fmtNum(e.tokens_saida_aprox)} de saída · provedor: <b>${esc(prov)}</b>${e.habilitado ? '' : ' · <b class="erro">LLM desligado em Configurações</b>'}`;
    $('#cl-custo').innerHTML = clCustoHtml(e.custo);
    $('#cl-aviso-remoto').hidden = !e.remoto;
    $('#cl-rodar').disabled = !e.habilitado || !e.unidades;
    clMsg('#cl-msg', '');
  } catch (e) { $('#cl-estimativa').textContent = ''; $('#cl-custo').textContent = ''; clMsg('#cl-msg', e.message, true); $('#cl-rodar').disabled = true; }
}

function clRenderProgresso(p) {
  const pct = p.total ? Math.round((100 * p.feitos) / p.total) : 0;
  $('#cl-prog').hidden = !(p.rodando || p.finalizado_em || p.erro);
  $('#cl-prog-barra').style.width = pct + '%';
  $('#cl-prog-barra').className = p.erros ? 'com-erro' : '';
  $('#cl-prog-txt').textContent = p.rodando ? `Classificando: ${p.feitos} de ${p.total} (${p.erros} erro(s))…` :
    p.erro ? `Parou: ${p.erro}` : p.finalizado_em ? `Concluído: ${p.feitos} de ${p.total}, ${p.erros} erro(s)${p.cancelado ? ' (cancelado)' : ''}${p.ultimo_erro ? ` · último erro: ${p.ultimo_erro}` : ''}.` : '';
  $('#cl-cancelar').hidden = !p.rodando;
  $('#cl-rodar').disabled = !!p.rodando;
}

async function clSondar() {
  try {
    const p = await api(clUrl('progresso'));
    clRenderProgresso(p);
    if (!p.rodando) { clearInterval(cl.timer); cl.timer = null; await Promise.all([clEstimar(), clCarregarItens()]); }
    else if (p.feitos % 10 === 0) clCarregarItens();
  } catch { clearInterval(cl.timer); cl.timer = null; }
}

async function clRodar() {
  if (!$('#cl-aviso-remoto').hidden && !confirm('As unidades e os rótulos serão enviados ao provedor remoto configurado, que pode cobrar por token. Continuar?')) return;
  if (!confirm('Uma nova classificação substitui o resultado atual (e as revisões feitas). Continuar?')) return;
  clMsg('#cl-msg', '');
  try {
    await api(clUrl('executar'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(clCorpo()) });
    if (!cl.timer) cl.timer = setInterval(clSondar, 1000);
    clSondar();
  } catch (e) { clMsg('#cl-msg', e.message, true); }
}

function clRotulosHtml(t) {
  if (t.status === 'erro') return '<span class="erro">erro</span>';
  return (t.rotulos || []).map((r) => `<span class="cl-rot">${esc(r)}</span>`).join('') || '—';
}

function clRevisaoHtml(t) {
  if (t.status !== 'classificado') return '';
  return `<span class="cl-rev"><button type="button" class="sec peq ${t.revisao === 'aceito' ? 'on-ok' : ''}" data-cl-rev="aceito" data-id="${t.id}" title="Aceitar">✓</button>` +
    `<button type="button" class="sec peq ${t.revisao === 'rejeitado' ? 'on-no' : ''}" data-cl-rev="rejeitado" data-id="${t.id}" title="Rejeitar">✗</button></span>`;
}

async function clCarregarItens() {
  if (!slugAtual) return;
  const q = { filtro: $('#cl-filtro').value, offset: cl.pagina * cl.porPagina, limit: cl.porPagina };
  const rot = $('#cl-rotulo').value.trim(), busca = $('#cl-busca').value.trim();
  if (rot) q.rotulo = rot;
  if (busca) q.busca = busca;
  $('#cl-csv').href = clUrl('itens.csv', { filtro: q.filtro, ...(rot ? { rotulo: rot } : {}), ...(busca ? { busca } : {}) });
  try {
    const r = await api(clUrl('itens', q));
    const c = r.contagens;
    $('#cl-contagem').innerHTML = [['total', 'itens'], ['classificado', 'classificados'], ['pendente_revisao', 'a revisar'], ['aceito', 'aceitos'], ['rejeitado', 'rejeitados'],
      ['concordam', 'concordam com o humano'], ['discordam', 'discordam'], ['erro', 'com erro'], ['exemplo', 'exemplos']].map(([k, rotulo]) => `<span class="chip">${fmtNum(c[k])} ${rotulo}</span>`).join('');
    $('#cl-tab tbody').innerHTML = r.itens.length ? r.itens.map((t) => `<tr class="${t.revisao === 'rejeitado' ? 'cl-rejeitado' : t.revisao === 'aceito' ? 'cl-aceito' : ''} ${t.concorda === false ? 'cd-dif' : t.concorda ? 'cd-ok' : ''}">
      <td>${esc(t.documento || t.ref)}${t.pagina != null ? `, p. ${t.pagina}` : ''}<br><span class="discreto">${esc(t.origem)} ${esc(t.ref)}</span></td>
      <td class="cl-texto">${esc(t.texto.length > 420 ? t.texto.slice(0, 420) + '…' : t.texto)}</td>
      <td>${clRotulosHtml(t)}</td><td><b>${esc(t.rotulo_humano || '—')}</b>${t.status === 'exemplo' ? ' <span class="discreto">(exemplo)</span>' : ''}</td>
      <td>${t.confianca != null ? fmtNum(t.confianca, 2) : ''}</td><td class="cd-just">${esc(t.justificativa || '')}</td><td>${clRevisaoHtml(t)}</td></tr>`).join('')
      : '<tr><td colspan="7" class="discreto">Nenhum item neste filtro.</td></tr>';
    const paginas = Math.max(1, Math.ceil(r.n / cl.porPagina));
    $('#cl-pag').textContent = `${fmtNum(r.n)} item(ns) · página ${cl.pagina + 1} de ${paginas}`;
    $('#cl-ant').disabled = cl.pagina === 0;
    $('#cl-prox').disabled = cl.pagina + 1 >= paginas;
    if (r.config && !cl.configAplicada) {
      cl.configAplicada = true;
      $('#cl-modo').value = r.config.modo || 'zero_shot';
      $('#cl-multi').checked = !!r.config.multirrotulo; if (r.config.k) $('#cl-k').value = r.config.k;
      clAtualizarModo();
    }
  } catch (e) { clMsg('#cl-msg', e.message, true); }
}

async function clRevisar(id, revisao) {
  try { await api(clUrl(`itens/${id}/revisao`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revisao }) }); await clCarregarItens(); }
  catch (e) { clMsg('#cl-msg', e.message, true); }
}

async function clCalcular() {
  clMsg('#cl-msg-conc', 'Calculando (bootstrap)…');
  try {
    const r = await api(clUrl('concordancia', { bootstrap: +$('#cl-boot').value || 0, somente: $('#cl-somente').value }));
    const k = r.kappa, a = r.alfa;
    $('#cl-conc').innerHTML = `<div class="cd-estat">
      <div class="cd-num"><span class="discreto">Concordância simples</span><b>${fmtNum(100 * r.percentual, 1)}%</b><span class="discreto">${fmtNum(r.n_pares)} pares (${fmtNum(r.n_itens)} itens${r.modo ? `; ${r.modo === 'few_shot' ? 'few-shot' : 'zero-shot'}` : ''})</span></div>
      <div class="cd-num"><span class="discreto">Kappa de Cohen</span><b>${k.kappa == null ? '—' : fmtNum(k.kappa, 3)}</b><span class="discreto">IC 95% ${ic(k.ic95)}${k.bootstrap ? ` · bootstrap ${ic(k.bootstrap.ic95)}` : ''}<br>${esc(k.faixa || k.nota || '')}</span></div>
      <div class="cd-num"><span class="discreto">Alfa de Krippendorff</span><b>${a.alfa == null ? '—' : fmtNum(a.alfa, 3)}</b><span class="discreto">${esc(a.faixa || a.nota || '')}</span></div></div>
      <p class="discreto">${esc(r.nota)}</p>
      <div class="rolagem"><table class="tp-tab"><thead><tr><th>Rótulo</th><th>humano</th><th>LLM</th><th>acertos</th><th>kappa (1 × resto)</th><th>precisão</th><th>revocação</th><th>F1</th></tr></thead>
      <tbody>${r.por_codigo.map((c) => `<tr><td>${esc(c.codigo)}</td><td>${c.suporte_humano}</td><td>${c.atribuidos_llm}</td><td>${c.vp}</td><td>${c.kappa == null ? '—' : fmtNum(c.kappa, 3)}</td>
        <td>${c.precisao == null ? '—' : fmtNum(c.precisao, 2)}</td><td>${c.revocacao == null ? '—' : fmtNum(c.revocacao, 2)}</td><td>${c.f1 == null ? '—' : fmtNum(c.f1, 2)}</td></tr>`).join('')}</tbody></table></div>
      <h5 class="sm-tit">Matriz de confusão</h5><div class="rolagem alta">${renderConfusao(r.confusao)}</div>`;
    clMsg('#cl-msg-conc', '');
  } catch (e) { $('#cl-conc').innerHTML = ''; clMsg('#cl-msg-conc', e.message, true); }
}

function clAtualizarModo() {
  $('#cl-k-rot').hidden = $('#cl-modo').value !== 'few_shot';
  $('#cl-lista').hidden = $('#cl-fonte').value !== 'lista';
}

async function clCarregar() {
  if (!slugAtual) return;
  cl.pagina = 0;
  cl.configAplicada = false;
  try {
    const r = await api(clUrl('rotulos'));
    cl.dicionario = r.dicionario;
    $('#cl-info-rot').textContent = r.dicionario.length ? `${r.dicionario.length} código(s) no dicionário do projeto.` : 'O dicionário do projeto está vazio: importe o codebook (aba Codificação) ou use uma lista própria.';
    if (!r.dicionario.length) { $('#cl-fonte').value = 'lista'; }
  } catch (e) { clMsg('#cl-msg', e.message, true); }
  clAtualizarModo();
  await Promise.all([clEstimar(), clCarregarItens()]);
  try { const p = await api(clUrl('progresso')); clRenderProgresso(p); if (p.rodando && !cl.timer) cl.timer = setInterval(clSondar, 1000); } catch { /* sem progresso */ }
}

$('#cl-subabas').addEventListener('click', (ev) => { const b = ev.target.closest('[data-cl-aba]'); if (b) clMostrarAba(b.dataset.clAba); });
for (const id of ['#cl-origem', '#cl-modo', '#cl-fonte', '#cl-multi']) $(id).addEventListener('change', () => { clAtualizarModo(); clEstimar(); });
for (const id of ['#cl-k', '#cl-limite', '#cl-lista']) $(id).addEventListener('change', clEstimar);
$('#cl-estimar').addEventListener('click', clEstimar);
$('#cl-rodar').addEventListener('click', clRodar);
$('#cl-cancelar').addEventListener('click', async () => { await api(clUrl('cancelar'), { method: 'POST' }).catch(() => {}); });
$('#cl-limpar').addEventListener('click', async () => {
  if (!confirm('Apagar os resultados da classificação e as revisões?')) return;
  try { await api(clUrl(''), { method: 'DELETE' }); await Promise.all([clEstimar(), clCarregarItens()]); } catch (e) { clMsg('#cl-msg', e.message, true); }
});
$('#cl-filtro').addEventListener('change', () => { cl.pagina = 0; clCarregarItens(); });
for (const id of ['#cl-rotulo', '#cl-busca']) $(id).addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { cl.pagina = 0; clCarregarItens(); } });
$('#cl-ant').addEventListener('click', () => { cl.pagina = Math.max(0, cl.pagina - 1); clCarregarItens(); });
$('#cl-prox').addEventListener('click', () => { cl.pagina += 1; clCarregarItens(); });
$('#cl-calc').addEventListener('click', clCalcular);
$('#cl-aceitar-lote').addEventListener('click', async () => {
  const min = +$('#cl-confmin').value;
  if (!confirm(`Aceitar todos os itens classificados com confiança ≥ ${min}?`)) return;
  try { const r = await api(clUrl('revisar-lote'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revisao: 'aceito', confianca_minima: min }) }); clMsg('#cl-msg', `${r.alterados} item(ns) aceito(s).`); await clCarregarItens(); }
  catch (e) { clMsg('#cl-msg', e.message, true); }
});
$('#cl-tab').addEventListener('click', (ev) => {
  const b = ev.target.closest('[data-cl-rev]');
  if (!b) return;
  const ja = b.classList.contains('on-ok') || b.classList.contains('on-no');
  clRevisar(+b.dataset.id, ja ? 'pendente' : b.dataset.clRev);
});
