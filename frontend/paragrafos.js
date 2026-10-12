// Exemplos de parágrafos (Frente 14.2/14.3): modelos por tipo de análise, pré-visualização sem LLM, edição por projeto e,
// só com o LLM ligado em Configurações, "Gerar versão adaptada com LLM" (entra em Comentários como sugestão).
// Usa $, esc, api, fmtNum e slugAtual de app.js.
const pg = { modelos: [], analises: [], campos: {}, llm: false, projeto: null, seq: 0, editando: null };
const PG_TITULO = {
  resumo: 'Resumo do corpus', frequencias: 'Frequências', tendencias: 'Tendências no tempo', kwic: 'Concordância (KWIC)', colocacoes: 'Colocações',
  ngramas: 'N-gramas', keyness: 'Palavras-chave (keyness)', especificidades: 'Especificidades', afc: 'Análise fatorial (AFC)',
  similaridade: 'Similaridade entre documentos', dicionario: 'Dicionário / codebook',
};
const PG_ORIGEM = { padrao: 'padrão', padrao_editado: 'padrão editado neste projeto', projeto: 'do projeto' };

function pgMensagem(texto, erro) {
  const m = $('#pg-msg');
  m.textContent = texto || ''; m.className = erro ? 'erro' : 'discreto';
}

function pgDestacar(texto) {
  return esc(texto).replace(/\{([a-zA-Z0-9_]+)(:[^}]*)?\}/g, (_m, nome, fmt) => `<i>{${nome}${fmt || ''}}</i>`);
}

async function carregarParagrafos() {
  if (!slugAtual) return;
  const seq = ++pg.seq;
  if (pg.projeto !== slugAtual) { pg.projeto = slugAtual; pg.editando = null; }
  try {
    const r = await api(`/api/projetos/${slugAtual}/modelos-paragrafo`);
    if (seq !== pg.seq) return;
    Object.assign(pg, { modelos: r.modelos, analises: r.analises, campos: r.campos, llm: r.llm_habilitado });
    const atual = $('#pg-filtro').value;
    $('#pg-filtro').innerHTML = '<option value="">todas</option>' + r.analises.map((a) => `<option value="${a}">${esc(PG_TITULO[a] || a)}</option>`).join('');
    $('#pg-filtro').value = atual;
    $('#pg-info').textContent = `(${r.modelos.length} modelos · LLM ${r.llm_habilitado ? 'ligado' : 'desligado'})`;
    pgDesenhar();
  } catch (e) {
    pgMensagem(e.message, true);
  }
}

function pgCartao(m) {
  if (pg.editando === m.id) return pgFormulario(m);
  const botoes = [
    `<button type="button" data-pg="previa">Pré-visualizar com os dados do projeto</button>`,
    `<button type="button" class="sec" data-pg="editar">Editar</button>`,
    `<button type="button" class="sec" data-pg="duplicar">Duplicar</button>`,
    m.origem === 'padrao_editado' ? `<button type="button" class="sec" data-pg="restaurar">Restaurar padrão</button>` : '',
    m.origem === 'projeto' ? `<button type="button" class="sec" data-pg="excluir">Excluir</button>` : '',
    pg.llm ? `<button type="button" class="sec" data-pg="gerar" title="Envia métricas e trechos ao provedor configurado">Gerar versão adaptada com LLM</button>` : '',
  ].join('');
  return `<article class="pg-cartao" data-id="${esc(m.id)}">
    <div class="pg-cab"><b>${esc(m.titulo)}</b><span class="badge">${esc(m.estilo)}</span><span class="badge">${esc(m.idioma)}</span>
      <span class="discreto">${esc(PG_ORIGEM[m.origem] || m.origem)}</span></div>
    <div class="pg-modelo">${pgDestacar(m.texto_modelo)}</div>
    ${m.notas ? `<div class="pg-notas"><b>Não afirmar:</b> ${esc(m.notas)}</div>` : ''}
    <div class="cm-acoes">${botoes}</div>
    <div class="pg-saida-area"></div>
  </article>`;
}

function pgDesenhar() {
  const filtro = $('#pg-filtro').value;
  let html = '';
  for (const a of pg.analises) {
    if (filtro && filtro !== a) continue;
    const mm = pg.modelos.filter((m) => m.analise === a);
    if (!mm.length) continue;
    html += `<h4 class="pg-grupo">${esc(PG_TITULO[a] || a)} <span class="discreto">${mm.length} modelo(s)</span></h4>` + mm.map(pgCartao).join('');
  }
  $('#pg-lista').innerHTML = html || '<p class="vazio">Nenhum modelo.</p>';
}

function pgFormulario(m) {
  const novo = m.id === '__novo__';
  const campos = (pg.campos[m.analise] || []).map((c) => `<code data-campo="${esc(c)}" title="Inserir {${esc(c)}}">{${esc(c)}}</code>`).join('');
  return `<article class="pg-cartao" data-id="${esc(m.id)}"><div class="pg-form">
    <label>Título <input data-f="titulo" maxlength="150" value="${esc(m.titulo)}"></label>
    <label>Estilo <input data-f="estilo" list="pg-estilos" maxlength="60" value="${esc(m.estilo)}">
      <datalist id="pg-estilos"><option value="descritivo"><option value="interpretativo cauteloso"><option value="resultado para artigo"></datalist></label>
    <label>Texto do modelo (use os campos abaixo entre chaves)<textarea data-f="texto_modelo" maxlength="4000">${esc(m.texto_modelo)}</textarea></label>
    <div class="pg-campos" aria-label="Campos disponíveis (clique para inserir)">${campos}</div>
    <label>Notas: o que o parágrafo não pode afirmar<textarea data-f="notas" maxlength="2000">${esc(m.notas)}</textarea></label>
    <div class="cm-acoes"><button type="button" data-pg="salvar">Salvar neste projeto</button><button type="button" class="sec" data-pg="cancelar">Cancelar</button></div>
    ${novo ? '' : '<p class="discreto">O modelo padrão não é alterado: a versão editada vale só para este projeto.</p>'}
  </div></article>`;
}

function pgProjetoAtual() {
  return pg.modelos.filter((m) => m.origem !== 'padrao')
    .map(({ id, analise, titulo, estilo, idioma, texto_modelo, notas }) => ({ id, analise, titulo, estilo, idioma, texto_modelo, notas }));
}

async function pgSalvarLista(lista, aviso) {
  const r = await api(`/api/projetos/${slugAtual}/modelos-paragrafo`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ modelos: lista }) });
  pg.modelos = r.modelos; pg.editando = null;
  pgDesenhar();
  pgMensagem(aviso);
}

function pgNovoId(base) {
  const ids = new Set(pg.modelos.map((m) => m.id));
  let n = 2;
  while (ids.has(`${base}-${n}`)) n += 1;
  return `${base}-${n}`.slice(0, 64);
}

function pgRotuloMetrica(v) {
  if (typeof v === 'number') return Number.isInteger(v) ? fmtNum(v) : fmtNum(v, Math.abs(v) < 10 ? 3 : 2);
  return Array.isArray(v) ? `[${v.length} item(ns)]` : String(v);
}

function pgEvidencias(evs) {
  if (!evs || !evs.length) return '';
  return `<details><summary>Trechos de evidência (${evs.length})</summary><ul class="cm-ev">${evs.map((e) =>
    `<li><b>${esc(e.rotulo)}</b> <span class="discreto">p. ${esc(e.pagina)}</span> — “…${esc(e.trecho)}…”</li>`).join('')}</ul></details>`;
}

async function pgPrevia(art, id) {
  const area = art.querySelector('.pg-saida-area');
  area.innerHTML = '<p class="discreto">Calculando com os dados do projeto…</p>';
  try {
    const r = await api(`/api/projetos/${slugAtual}/modelos-paragrafo/${encodeURIComponent(id)}/previa`, { method: 'POST' });
    const usadas = Object.entries(r.metricas_usadas).map(([k, v]) => `<code>${esc(k)}</code> = ${esc(pgRotuloMetrica(v))}`).join(' · ');
    area.innerHTML = `<div class="pg-saida"><div class="discreto">Pré-visualização (sem LLM, determinística)</div>
      <p class="texto">${esc(r.texto)}</p><details><summary>Métricas usadas</summary><p class="cm-met">${usadas || '—'}</p></details>${pgEvidencias(r.evidencias)}</div>`;
  } catch (e) {
    area.innerHTML = `<div class="pg-saida erro">${esc(e.message)}</div>`;
  }
}

function pgPedirInstrucoes(art) {
  art.querySelector('.pg-saida-area').innerHTML = `<div class="pg-saida"><label>Instruções adicionais para o LLM (opcional)
    <input data-f="instr" maxlength="1000" placeholder="ex.: seja breve; destaque o ano de 2025"></label>
    <p class="discreto">O pedido leva o modelo, as métricas e até 5 trechos do projeto ao provedor configurado e fica registrado em saidas/llm_log.jsonl.</p>
    <p><button type="button" data-pg="gerar-ok">Enviar ao LLM</button></p></div>`;
}

async function pgGerar(art, id, botao) {
  const area = art.querySelector('.pg-saida-area');
  const instrucoes = (art.querySelector('[data-f="instr"]') || { value: '' }).value;
  botao.disabled = true;
  area.innerHTML = '<p class="discreto">Gerando com o LLM (pode levar alguns minutos em modelos locais)…</p>';
  try {
    const r = await api(`/api/projetos/${slugAtual}/modelos-paragrafo/${encodeURIComponent(id)}/gerar`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instrucoes: instrucoes.trim() || null }) });
    const v = r.verificacao;
    const problemas = [...v.numeros_nao_encontrados.map((n) => `número ${n}`), ...v.citacoes_invalidas, ...v.trechos_nao_encontrados.map((t) => `trecho “${t}”`)];
    area.innerHTML = `<div class="pg-saida"><div class="discreto">Gerado por ${esc(r.provedor)} · ${esc(r.modelo)} — entrou em <b>Comentários</b> como <b>${esc(r.status)}</b> (origem LLM)</div>
      <p class="texto">${esc(r.texto)}</p>
      <div class="cm-verif ${v.ok ? 'ok' : ''}">${v.ok ? `Conferência automática: ${v.numeros_verificados} número(s) conferidos, sem problemas.` : `Conferência automática encontrou: ${problemas.map(esc).join('; ')}. O comentário ficou em <b>revisar</b>.`}</div>
      <p><button type="button" class="sec" data-pg="ver-comentarios">Ir para Comentários</button></p></div>`;
  } catch (e) {
    area.innerHTML = `<div class="pg-saida erro">${esc(e.message)}</div>`;
  } finally {
    botao.disabled = false;
  }
}

$('#pg-filtro').addEventListener('change', pgDesenhar);

$('#pg-lista').addEventListener('click', async (ev) => {
  const art = ev.target.closest('.pg-cartao');
  if (!art) return;
  const campo = ev.target.closest('[data-campo]');
  if (campo) {
    const ta = art.querySelector('[data-f="texto_modelo"]');
    const i = ta.selectionStart == null ? ta.value.length : ta.selectionStart;
    ta.value = ta.value.slice(0, i) + `{${campo.dataset.campo}}` + ta.value.slice(ta.selectionEnd == null ? i : ta.selectionEnd);
    ta.focus();
    return;
  }
  const botao = ev.target.closest('button[data-pg]');
  if (!botao) return;
  const id = art.dataset.id, m = pg.modelos.find((x) => x.id === id);
  const acao = botao.dataset.pg;
  try {
    if (acao === 'previa') await pgPrevia(art, id);
    else if (acao === 'gerar') pgPedirInstrucoes(art);
    else if (acao === 'gerar-ok') await pgGerar(art, id, botao);
    else if (acao === 'editar') { pg.editando = id; pgDesenhar(); }
    else if (acao === 'cancelar') { pg.editando = null; pgDesenhar(); }
    else if (acao === 'ver-comentarios') { $('#cm-origem').value = 'llm'; $('#cm-status').value = ''; mostrarAba('comentarios'); carregarComentarios(); }
    else if (acao === 'duplicar') {
      const copia = { id: pgNovoId(m.id), analise: m.analise, titulo: `${m.titulo} (cópia)`, estilo: m.estilo, idioma: m.idioma, texto_modelo: m.texto_modelo, notas: m.notas };
      await pgSalvarLista([...pgProjetoAtual(), copia], 'Modelo duplicado neste projeto.');
      pg.editando = copia.id; pgDesenhar();
    } else if (acao === 'restaurar' || acao === 'excluir') {
      const msg = acao === 'restaurar' ? 'Restaurar o modelo padrão (descarta a versão editada deste projeto)?' : 'Excluir este modelo do projeto?';
      if (!window.confirm(msg)) return;
      await pgSalvarLista(pgProjetoAtual().filter((x) => x.id !== id), acao === 'restaurar' ? 'Modelo padrão restaurado.' : 'Modelo excluído.');
    } else if (acao === 'salvar') {
      const f = (n) => art.querySelector(`[data-f="${n}"]`).value;
      const editado = { id, analise: m.analise, titulo: f('titulo').trim(), estilo: f('estilo').trim(), idioma: m.idioma, texto_modelo: f('texto_modelo').trim(), notas: f('notas').trim() };
      await pgSalvarLista([...pgProjetoAtual().filter((x) => x.id !== id), editado], 'Modelo salvo neste projeto.');
    }
  } catch (e) {
    pgMensagem(e.message, true);
  }
});
