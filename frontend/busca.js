// 15.12 Similaridade semântica (embeddings via Ollama, painel ao lado da similaridade TF-IDF) e 15.13 "Perguntar ao corpus".
// Usa $, esc, api, fmtNum e slugAtual (app.js). Nada é enviado para fora da máquina nos embeddings (só Ollama local).

const se = { timer: null, status: null };
const pq = { itens: [] };

function seUrl(caminho, q) {
  const s = new URLSearchParams(q || {}).toString();
  return `/api/projetos/${slugAtual}/semantica/${caminho}${s ? '?' + s : ''}`;
}

function seMsg(texto, erro) { const m = $('#se-msg'); m.textContent = texto || ''; m.className = erro ? 'erro' : 'discreto'; }

async function seVerificar() {
  if (!slugAtual) return;
  seMsg('Verificando o Ollama…');
  try {
    const st = await api(seUrl('status'));
    se.status = st;
    const modelos = st.modelos_embedding;
    $('#se-modelo').innerHTML = modelos.map((m) => `<option>${esc(m)}</option>`).join('') || '<option value="">(nenhum modelo de embeddings)</option>';
    const calc = st.calculados[0];
    if (calc && modelos.includes(calc.modelo)) $('#se-modelo').value = calc.modelo;
    $('#se-doc').innerHTML = st.documentos.map((d) => `<option value="${d.id}">${esc(d.rotulo)}</option>`).join('');
    const como = $('#se-como');
    como.hidden = !st.como_habilitar;
    como.textContent = st.como_habilitar ? (st.erro ? st.erro + ' ' : '') + st.como_habilitar : '';
    $('#se-calcular').disabled = !(st.disponivel && modelos.length && st.provedor_ollama);
    if (st.disponivel && modelos.length && !st.provedor_ollama) { como.hidden = false; como.textContent = 'Escolha o provedor Ollama em Configurações para calcular embeddings.'; }
    seMsg(st.disponivel ? `Ollama no ar (${st.modelos.length} modelo(s); ${modelos.length} de embeddings).${calc ? ` Embeddings calculados: ${calc.modelo} (${fmtNum(calc.n)} segmentos, ${calc.dim} dimensões).` : ''}` : 'Ollama indisponível.');
    if (calc) await seMostrar();
    if (st.progresso && st.progresso.rodando) seIniciarSonda();
  } catch (e) { seMsg(e.message, true); }
}

function seRenderProgresso(p) {
  const pct = p.total ? Math.round((100 * p.feitos) / p.total) : 0;
  $('#se-prog').hidden = !(p.rodando || p.finalizado_em || p.erro);
  $('#se-prog-barra').style.width = pct + '%';
  $('#se-prog-txt').textContent = p.rodando ? `Calculando embeddings: ${p.feitos} de ${p.total} segmentos…` : p.erro ? `Parou: ${p.erro}` : p.finalizado_em ? `Concluído: ${p.feitos} segmentos.` : '';
  $('#se-cancelar').hidden = !p.rodando;
  $('#se-calcular').disabled = !!p.rodando || !(se.status && se.status.disponivel && se.status.modelos_embedding.length && se.status.provedor_ollama);
}

function seIniciarSonda() {
  if (se.timer) return;
  se.timer = setInterval(async () => {
    try {
      const p = await api(seUrl('progresso'));
      seRenderProgresso(p);
      if (!p.rodando) { clearInterval(se.timer); se.timer = null; await seVerificar(); }
    } catch { clearInterval(se.timer); se.timer = null; }
  }, 1000);
}

async function seCalcular() {
  const modelo = $('#se-modelo').value;
  if (!modelo) return seMsg('Nenhum modelo de embeddings instalado no Ollama.', true);
  try {
    await api(seUrl('calcular'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ modelo }) });
    seMsg('Calculando no Ollama local…');
    seIniciarSonda();
  } catch (e) { seMsg(e.message, true); }
}

async function seMostrar() {
  const tabela = (el, cab, linhas) => { el.innerHTML = `<thead><tr>${cab.map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${linhas.join('')}</tbody>`; };
  try {
    const doc = $('#se-doc').value;
    if (doc) {
      const v = await api(seUrl('similaridade', { documento_id: doc, k: 10 }));
      tabela($('#tab-se-viz'), ['Documento', 'Cosseno'], v.vizinhos.map((x) => `<tr><td>${esc(x.rotulo)}</td><td>${fmtNum(x.similaridade, 3)}</td></tr>`));
    }
    const g = await api(seUrl('similaridade', { k: 10 }));
    tabela($('#tab-se-pares'), ['Documento A', 'Documento B', 'Cosseno'], g.pares.map((x) => `<tr><td>${esc(x.rotulo_a)}</td><td>${esc(x.rotulo_b)}</td><td>${fmtNum(x.similaridade, 3)}</td></tr>`));
  } catch (e) { seMsg(e.message, true); }
}

$('#se-verificar').addEventListener('click', seVerificar);
$('#se-calcular').addEventListener('click', seCalcular);
$('#se-cancelar').addEventListener('click', async () => { await api(seUrl('cancelar'), { method: 'POST' }).catch(() => {}); });
$('#se-doc').addEventListener('change', seMostrar);

// ---------- 15.13 Perguntar ao corpus ----------

function pqUrl(caminho, q) {
  const s = new URLSearchParams(q || {}).toString();
  return `/api/projetos/${slugAtual}/${caminho}${s ? '?' + s : ''}`;
}

function pqMsg(texto, erro) { const m = $('#pq-msg'); m.textContent = texto || ''; m.className = erro ? 'erro' : 'discreto'; }

function pqDestacar(texto, consulta) {
  const termos = [...new Set(consulta.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter((t) => t.length > 3))];
  let html = esc(texto);
  for (const t of termos) html = html.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'), '<mark>$1</mark>');
  return html;
}

function pqRenderResposta(r, consulta) {
  const alvo = $('#pq-resposta');
  if (!r) { alvo.innerHTML = ''; return; }
  const v = r.verificacao;
  const avisos = r.avisos.map((a) => `<p class="pq-aviso">⚠ ${esc(a)}</p>`).join('');
  alvo.innerHTML = `<div class="pq-resposta ${v.ok ? '' : 'com-aviso'}"><b>Resposta do LLM</b> <span class="discreto">(${esc(r.provedor)} · ${esc(r.modelo || '')}; ${v.ok ? 'conferida: citações, números e trechos batem com os trechos recuperados' : 'NÃO passou na conferência automática'})</span>
    <p>${esc(r.texto)}</p>${avisos}
    <p class="discreto">Citações válidas: ${v.citacoes_validas.length ? v.citacoes_validas.map(esc).join('; ') : 'nenhuma'}. Confira sempre a página no documento.</p></div>`;
}

async function pqBuscar() {
  const pergunta = $('#pq-pergunta').value.trim();
  if (!slugAtual) return;
  if (!pergunta) return pqMsg('Escreva uma pergunta.', true);
  const responder = $('#pq-resp').checked;
  if (responder) {
    const remoto = await api('/api/config/llm').then((c) => ['anthropic', 'openai_compativel'].includes(c.provedor)).catch(() => false);
    if (remoto && !confirm('Os trechos recuperados serão enviados ao provedor remoto configurado, que pode cobrar por token. Continuar?')) return;
  }
  pqMsg(responder ? 'Buscando e gerando a resposta…' : 'Buscando…');
  $('#pq-buscar').disabled = true;
  try {
    const r = await api(pqUrl('perguntar'), { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pergunta, k: +$('#pq-k').value || 8, modo: $('#pq-modo').value, responder }) });
    pqRenderResposta(r.resposta, pergunta);
    $('#pq-itens').innerHTML = r.itens.length ? r.itens.map((t) => `<div class="pq-trecho"><div class="pq-cab"><b>[${t.posicao}] ${esc(t.rotulo)}${t.pagina != null ? `, p. ${t.pagina}` : ' (sem página)'}</b>
      <span class="discreto">${t.bm25 != null ? `BM25 ${fmtNum(t.bm25, 2)}` : ''}${t.cosseno != null ? ` · cosseno ${fmtNum(t.cosseno, 3)}` : ''}${r.modo === 'hibrido' ? ` · RRF ${fmtNum(t.nota, 4)}` : ''}${t.secao ? ` · ${esc(t.secao)}` : ''}${t.tambem_em && t.tambem_em.length ? ` · mesmo texto também em ${t.tambem_em.map((o) => esc(o.rotulo) + (o.pagina != null ? ', p. ' + o.pagina : '')).join('; ')}` : ''}</span></div>
      <div class="pq-texto">${pqDestacar(t.texto, pergunta)}</div></div>`).join('') : '<p class="vazio">Nenhum trecho encontrado para esta pergunta: sem trechos, não há resposta.</p>';
    pqMsg(`${r.itens.length} trecho(s) de ${fmtNum(r.segmentos_no_corpus)} · busca ${r.modo === 'hibrido' ? 'híbrida (BM25 + cosseno por RRF)' : 'lexical (BM25)'}${r.aviso ? ' · ' + r.aviso : ''}`);
    pqCarregarLog();
  } catch (e) { pqMsg(e.message, true); }
  $('#pq-buscar').disabled = false;
}

async function pqCarregarLog() {
  if (!slugAtual) return;
  try {
    const r = await api(pqUrl('perguntar/log', { limite: 10 }));
    $('#pq-log').innerHTML = r.consultas.length ? r.consultas.map((c) => `<div>${esc((c.em || '').replace('T', ' '))} · <a href="#" data-pq-q="${esc(c.pergunta)}">${esc(c.pergunta)}</a> · ${esc(c.modo)}${c.modelo ? ` · ${esc(c.modelo)}` : ''}${c.verificacao_ok === false ? ' · ⚠ não conferida' : ''}</div>`).join('') : 'Nenhuma consulta ainda.';
  } catch { /* sem log */ }
}

function carregarPerguntar() { pqCarregarLog(); }

$('#pq-buscar').addEventListener('click', pqBuscar);
$('#pq-pergunta').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') pqBuscar(); });
$('#pq-log').addEventListener('click', (ev) => { const a = ev.target.closest('[data-pq-q]'); if (a) { ev.preventDefault(); $('#pq-pergunta').value = a.dataset.pqQ; } });
