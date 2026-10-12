// Aba "Codificação" (15.1): importa a planilha de trechos codificados por humanos, roda o LLM como SEGUNDO
// codificador (às cegas) e mostra a concordância (percentual, kappa de Cohen, alfa de Krippendorff, por código e
// matriz de confusão). Usa $, esc, api, fmtNum e slugAtual (app.js).

const cd = { arquivo: null, insp: null, timer: null, filtro: 'todos', pagina: 0, porPagina: 100, conc: null };
const PAPEIS_CD = { texto: 'Trecho (original)', codigo: 'Código humano', tema: 'Tema', traducao: 'Tradução', registro: 'ID do registro',
  fonte: 'Fonte / documento', fonte_rotulo: 'Fonte (autor, ano)', pagina: 'Página', secao: 'Seção' };

function cdUrl(caminho, q) {
  const s = new URLSearchParams(q || {}).toString();
  return `/api/projetos/${slugAtual}/codificacao/${caminho}${s ? '?' + s : ''}`;
}

function cdMsg(id, texto, erro) {
  const m = $(id);
  m.textContent = texto || '';
  m.className = erro ? 'erro' : 'discreto';
}

// ---------- importação ----------

function abaInspecionada() {
  const nome = $('#cd-aba').value;
  return (cd.insp && cd.insp.abas.find((a) => a.aba === nome)) || (cd.insp && cd.insp.abas[0]);
}

function renderMapeamento() {
  const a = abaInspecionada();
  if (!a) { $('#cd-mapa').innerHTML = ''; return; }
  $('#cd-mapa').innerHTML = Object.entries(PAPEIS_CD).map(([p, rot]) => `<label class="inline">${esc(rot)}
    <select data-papel="${p}"><option value="">(nenhuma)</option>${a.cabecalho.map((c) => `<option${a.colunas[p] === c ? ' selected' : ''}>${esc(c)}</option>`).join('')}</select></label>`).join('');
}

async function inspecionarPlanilha() {
  cd.arquivo = $('#cd-arquivo').files[0] || null;
  if (!cd.arquivo || !slugAtual) return;
  cdMsg('#cd-msg-imp', 'Lendo a planilha…');
  try {
    cd.insp = await api(cdUrl('inspecionar'), { method: 'POST', body: cd.arquivo });
    $('#cd-aba').innerHTML = cd.insp.abas.map((a) => `<option value="${esc(a.aba)}"${a.aba === cd.insp.sugerida ? ' selected' : ''}>${esc(a.aba)} (${a.trechos} trechos, ${a.com_codigo} com código)</option>`).join('') +
      (cd.insp.abas.length > 1 ? '<option value="*">todas as abas reconhecidas</option>' : '');
    $('#cd-imp-opcoes').hidden = false;
    renderMapeamento();
    cdMsg('#cd-msg-imp', `${cd.insp.abas.length} aba(s) com trecho e código reconhecidos (de ${cd.insp.todas_as_abas.length}). Confira o mapeamento e importe.`);
  } catch (e) { cdMsg('#cd-msg-imp', e.message, true); }
}

function mapeamentoEscolhido() {
  const a = abaInspecionada(), m = {};
  document.querySelectorAll('#cd-mapa select').forEach((s) => {
    if ((a.colunas[s.dataset.papel] || '') !== s.value) m[s.dataset.papel] = s.value;
  });
  return Object.keys(m).length ? m : null;
}

async function importarPlanilha() {
  if (!cd.arquivo) return cdMsg('#cd-msg-imp', 'Escolha o arquivo .xlsx primeiro.', true);
  const q = { modo: $('#cd-modo').value, aba: $('#cd-aba').value };
  const m = mapeamentoEscolhido();
  if (m) q.mapeamento = JSON.stringify(m);
  if ($('#cd-codebook').checked) q.codebook = 'true';
  cdMsg('#cd-msg-imp', 'Importando…');
  try {
    const r = await api(cdUrl('importar', q), { method: 'POST', body: cd.arquivo });
    const cb = r.codebook ? (r.codebook.importado ? ` Codebook: ${r.codebook.categorias_importadas} códigos no dicionário do projeto.` : ` Codebook não importado: ${r.codebook.motivo}.`) : '';
    $('#cd-relatorio').hidden = false;
    $('#cd-relatorio').innerHTML = `<b>${fmtNum(r.trechos_importados)}</b> trechos importados de ${r.abas_importadas.map(esc).join(', ')} (${fmtNum(r.codigos_distintos)} códigos distintos; ${fmtNum(r.sem_codigo_humano)} sem código humano; ${fmtNum(r.repetidos_pulados)} repetidos pulados).
      Fontes: ${r.fontes_casadas} de ${r.fontes} casadas com documentos do corpus (${r.pct_com_documento ?? 0}% dos trechos)${r.fontes_sem_documento.length ? `; sem documento: ${r.fontes_sem_documento.slice(0, 15).map(esc).join(', ')}${r.fontes_sem_documento.length > 15 ? '…' : ''}` : ''}.${esc(cb)}`;
    cdMsg('#cd-msg-imp', '');
    await Promise.all([carregarEstimativa(), carregarTrechos()]);
  } catch (e) { cdMsg('#cd-msg-imp', e.message, true); }
}

// ---------- codificação pelo LLM ----------

async function carregarEstimativa() {
  try {
    const e = await api(cdUrl('estimativa'));
    const prov = { nenhum: 'nenhum', ollama: 'Ollama (local)', anthropic: 'Anthropic (remoto)', openai_compativel: 'compatível com OpenAI (remoto)' }[e.provedor] || e.provedor;
    $('#cd-estimativa').innerHTML = `${fmtNum(e.trechos)} trecho(s) a codificar · codebook com ${e.categorias} código(s) · ~${fmtNum(e.tokens_entrada_aprox)} tokens de entrada e ~${fmtNum(e.tokens_saida_aprox)} de saída · provedor: <b>${esc(prov)}</b>${e.habilitado ? '' : ' · <b class="erro">LLM desligado em Configurações</b>'}${e.custo && typeof clCustoHtml === 'function' ? '<br>' + clCustoHtml(e.custo) : ''}`;
    $('#cd-aviso-remoto').hidden = !e.remoto;
    $('#cd-rodar').disabled = !e.habilitado || !e.trechos || !e.categorias;
  } catch (e) { $('#cd-estimativa').textContent = e.message; }
}

function renderProgressoCd(p) {
  const pct = p.total ? Math.round((100 * p.feitos) / p.total) : 0;
  $('#cd-prog').hidden = !(p.rodando || p.finalizado_em || p.erro);
  $('#cd-prog-barra').style.width = pct + '%';
  $('#cd-prog-barra').className = p.erros ? 'com-erro' : '';
  $('#cd-prog-txt').textContent = p.rodando ? `Codificando: ${p.feitos} de ${p.total} (${p.erros} erro(s))…` :
    p.erro ? `Parou: ${p.erro}` : p.finalizado_em ? `Concluído: ${p.feitos} de ${p.total}, ${p.erros} erro(s)${p.cancelado ? ' (cancelado)' : ''}${p.ultimo_erro ? ` · último erro: ${p.ultimo_erro}` : ''}.` : '';
  $('#cd-cancelar').hidden = !p.rodando;
  $('#cd-rodar').disabled = !!p.rodando;
}

async function sondarCd() {
  try {
    const p = await api(cdUrl('progresso'));
    renderProgressoCd(p);
    if (!p.rodando) {
      clearInterval(cd.timer); cd.timer = null;
      await Promise.all([carregarEstimativa(), carregarTrechos()]);
    } else if (p.feitos % 10 === 0) carregarTrechos();
  } catch (e) { clearInterval(cd.timer); cd.timer = null; }
}

async function rodarLlm() {
  const lim = +$('#cd-limite').value || null;
  const remoto = !$('#cd-aviso-remoto').hidden;
  if (remoto && !confirm('Os trechos e o codebook serão enviados ao provedor remoto configurado, que pode cobrar por token. Continuar?')) return;
  cdMsg('#cd-msg-llm', '');
  try {
    await api(cdUrl('codificar'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limite: lim, apenas_pendentes: true }) });
    if (!cd.timer) cd.timer = setInterval(sondarCd, 1000);
    sondarCd();
  } catch (e) { cdMsg('#cd-msg-llm', e.message, true); }
}

// ---------- trechos ----------

async function carregarTrechos() {
  if (!slugAtual) return;
  const q = { filtro: $('#cd-filtro').value, offset: cd.pagina * cd.porPagina, limit: cd.porPagina };
  const cod = $('#cd-codigo').value.trim(), busca = $('#cd-busca').value.trim();
  if (cod) q.codigo = cod;
  if (busca) q.busca = busca;
  $('#cd-csv').href = cdUrl('trechos.csv', { filtro: q.filtro, ...(cod ? { codigo: cod } : {}), ...(busca ? { busca } : {}) });
  try {
    const r = await api(cdUrl('trechos', q));
    const c = r.contagens;
    $('#cd-contagem').innerHTML = [['total', 'trechos'], ['codificado', 'codificados pelo LLM'], ['pendente', 'pendentes'], ['erro', 'com erro'],
      ['concordam', 'concordam'], ['discordam', 'discordam'], ['com_documento', 'com documento']].map(([k, rot]) => `<span class="chip">${fmtNum(c[k])} ${rot}</span>`).join('');
    const tb = $('#cd-tab tbody');
    tb.innerHTML = r.itens.length ? r.itens.map((t) => `<tr class="${t.concorda === false ? 'cd-dif' : t.concorda ? 'cd-ok' : ''}">
      <td>${esc(t.registro || t.id)}</td><td>${esc(t.documento || t.fonte_rotulo || t.fonte || '')}${t.pagina != null ? `, p. ${t.pagina}` : ''}</td>
      <td class="cd-texto" title="${esc(t.traducao || '')}">${esc(t.texto)}</td><td><b>${esc(t.codigo_humano || '—')}</b></td>
      <td><b>${esc(t.codigo_llm || (t.status === 'erro' ? 'erro' : '—'))}</b></td><td>${t.confianca != null ? fmtNum(t.confianca, 2) : ''}</td>
      <td class="cd-just">${esc(t.justificativa_llm || '')}</td></tr>`).join('') : '<tr><td colspan="7" class="discreto">Nenhum trecho neste filtro.</td></tr>';
    const paginas = Math.max(1, Math.ceil(r.n / cd.porPagina));
    $('#cd-pag').textContent = `${fmtNum(r.n)} trecho(s) · página ${cd.pagina + 1} de ${paginas}`;
    $('#cd-ant').disabled = cd.pagina === 0;
    $('#cd-prox').disabled = cd.pagina + 1 >= paginas;
  } catch (e) { cdMsg('#cd-msg-llm', e.message, true); }
}

// ---------- concordância ----------

function ic(x) { return x ? `[${fmtNum(x[0], 3)}; ${fmtNum(x[1], 3)}]` : '—'; }

function renderConfusao(m) {
  const max = Math.max(...m.matriz.flat(), 1);
  return `<table class="tp-tab cd-conf"><thead><tr><th>humano ↓ · LLM →</th>${m.categorias.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>
    ${m.matriz.map((linha, i) => `<tr><th>${esc(m.categorias[i])}</th>${linha.map((v, j) => `<td class="tp-cel" style="background:color-mix(in srgb, ${i === j ? 'var(--ok)' : 'var(--erro)'} ${v ? Math.round(15 + 85 * v / max) : 0}%, transparent)" title="humano ${esc(m.categorias[i])} × LLM ${esc(m.categorias[j])}: ${v}">${v || ''}</td>`).join('')}</tr>`).join('')}
  </tbody></table>`;
}

async function calcularConcordancia() {
  const nivel = $('#cd-nivel').value;
  cdMsg('#cd-msg-conc', 'Calculando (bootstrap)…');
  $('#cd-conc-csv').href = cdUrl('concordancia.csv', { nivel });
  try {
    const r = await api(cdUrl('concordancia', { nivel, bootstrap: +$('#cd-boot').value || 0 }));
    cd.conc = r;
    const k = r.kappa, a = r.alfa;
    $('#cd-conc').innerHTML = `<div class="cd-estat">
      <div class="cd-num"><span class="discreto">Concordância simples</span><b>${fmtNum(100 * r.percentual, 1)}%</b><span class="discreto">${fmtNum(r.n_pares)} pares; ${fmtNum(r.faltantes_llm)} sem resposta válida do LLM</span></div>
      <div class="cd-num"><span class="discreto">Kappa de Cohen</span><b>${k.kappa == null ? '—' : fmtNum(k.kappa, 3)}</b><span class="discreto">IC 95% assintótico ${ic(k.ic95)}${k.bootstrap ? ` · bootstrap ${ic(k.bootstrap.ic95)}` : ''}<br>${esc(k.faixa || k.nota || '')} (Landis &amp; Koch)</span></div>
      <div class="cd-num"><span class="discreto">Alfa de Krippendorff (nominal)</span><b>${a.alfa == null ? '—' : fmtNum(a.alfa, 3)}</b><span class="discreto">${a.bootstrap ? `IC 95% bootstrap ${ic(a.bootstrap.ic95)} · P(α &lt; 0,667) = ${fmtNum(a.bootstrap.p_abaixo_0667, 3)}<br>` : ''}${esc(a.faixa || a.nota || '')}</span></div>
    </div>
    <h5 class="sm-tit">Por ${nivel === 'tema' ? 'tema' : 'código'} (LLM contra o humano)</h5>
    <div class="rolagem"><table class="tp-tab"><thead><tr><th>${nivel === 'tema' ? 'Tema' : 'Código'}</th><th>humano</th><th>LLM</th><th>acertos</th><th>kappa (1 × resto)</th><th>precisão</th><th>revocação</th><th>F1</th></tr></thead>
    <tbody>${r.por_codigo.map((c) => `<tr><td><a href="#" data-cd-cod="${esc(c.codigo)}">${esc(c.codigo)}</a></td><td>${c.suporte_humano}</td><td>${c.atribuidos_llm}</td><td>${c.vp}</td>
      <td>${c.kappa == null ? '—' : fmtNum(c.kappa, 3)}</td><td>${c.precisao == null ? '—' : fmtNum(c.precisao, 2)}</td><td>${c.revocacao == null ? '—' : fmtNum(c.revocacao, 2)}</td><td>${c.f1 == null ? '—' : fmtNum(c.f1, 2)}</td></tr>`).join('')}</tbody></table></div>
    <h5 class="sm-tit">Matriz de confusão</h5><div class="rolagem alta">${renderConfusao(r.confusao)}</div>`;
    cdMsg('#cd-msg-conc', '');
  } catch (e) { $('#cd-conc').innerHTML = ''; cdMsg('#cd-msg-conc', e.message, true); }
}

async function carregarCodificacao() {
  if (!slugAtual) return;
  cd.pagina = 0;
  await Promise.all([carregarEstimativa(), carregarTrechos()]);
  try { const p = await api(cdUrl('progresso')); renderProgressoCd(p); if (p.rodando && !cd.timer) cd.timer = setInterval(sondarCd, 1000); } catch { /* sem progresso */ }
}

$('#cd-arquivo').addEventListener('change', inspecionarPlanilha);
$('#cd-aba').addEventListener('change', renderMapeamento);
$('#cd-importar').addEventListener('click', importarPlanilha);
$('#cd-rodar').addEventListener('click', rodarLlm);
$('#cd-cancelar').addEventListener('click', async () => { await api(cdUrl('cancelar'), { method: 'POST' }).catch(() => {}); });
$('#cd-limpar').addEventListener('click', async () => {
  if (!confirm('Apagar a codificação do LLM de todos os trechos? A codificação humana fica.')) return;
  try { await api(cdUrl('limpar-llm'), { method: 'POST' }); await Promise.all([carregarEstimativa(), carregarTrechos()]); } catch (e) { cdMsg('#cd-msg-llm', e.message, true); }
});
for (const id of ['#cd-filtro']) $(id).addEventListener('change', () => { cd.pagina = 0; carregarTrechos(); });
for (const id of ['#cd-codigo', '#cd-busca']) $(id).addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { cd.pagina = 0; carregarTrechos(); } });
$('#cd-ant').addEventListener('click', () => { cd.pagina = Math.max(0, cd.pagina - 1); carregarTrechos(); });
$('#cd-prox').addEventListener('click', () => { cd.pagina += 1; carregarTrechos(); });
$('#cd-calc').addEventListener('click', calcularConcordancia);
$('#cd-conc').addEventListener('click', (ev) => {
  const a = ev.target.closest('[data-cd-cod]');
  if (!a) return;
  ev.preventDefault();
  if ($('#cd-nivel').value === 'codigo') { $('#cd-codigo').value = a.dataset.cdCod; $('#cd-filtro').value = 'discordam'; cd.pagina = 0; carregarTrechos(); }
});
