// Interface (Frentes 1-10): dados de projetos e documentos. Navegação e execução: navegacao.js; análises: raiox.js/analises.js.
const $ = (s) => document.querySelector(s);
let slugAtual = null;

function esc(t) {
  const d = document.createElement('div');
  d.textContent = t == null ? '' : String(t);
  return d.innerHTML;
}

async function api(caminho, opcoes) {
  const r = await fetch(caminho, opcoes);
  const corpo = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = corpo.detail;
    throw new Error(typeof d === 'string' ? d : JSON.stringify(d || corpo) || r.statusText);
  }
  return corpo;
}

function mensagem(texto, erro) {
  const m = $('#msg');
  m.textContent = texto;
  m.className = erro ? 'erro' : '';
}

async function carregarProjetos() {
  const lista = await api('/api/projetos');
  const tb = $('#tab-projetos tbody');
  tb.innerHTML = lista.length ? '' : '<tr><td colspan="7" class="discreto">Nenhum projeto ainda: preencha o formulário acima.</td></tr>';
  for (const p of lista) {
    const tr = document.createElement('tr');
    tr.dataset.slug = p.slug;
    tr.innerHTML = `<td><b class="nome-proj">${esc(p.nome)}</b><br><span class="discreto">${esc(p.slug)}</span></td>
      <td>${esc(p.pasta_origem)}</td><td>v${esc(p.versao_parametros)}</td>
      <td data-col="docs" class="discreto">…</td><td data-col="pend" class="discreto">…</td><td data-col="run" class="discreto">…</td>
      <td class="acoes"><button data-abrir="${esc(p.slug)}" data-aba="geral">Abrir</button>
          <button class="sec" data-abrir="${esc(p.slug)}" data-aba="executar">Executar</button></td>`;
    tb.appendChild(tr);
    resumoDoProjeto(p.slug, tr);
  }
}

// Documentos, pendências e estado da última execução de cada projeto (preenchidos sem bloquear a lista).
async function resumoDoProjeto(slug, tr) {
  const cel = (c) => tr.querySelector(`[data-col="${c}"]`);
  try {
    const [docs, pend, prog] = await Promise.all([
      api(`/api/projetos/${slug}/documentos`), api(`/api/projetos/${slug}/pendencias`), api(`/api/projetos/${slug}/progresso`)]);
    const cont = {};
    docs.forEach((d) => { cont[d.status] = (cont[d.status] || 0) + 1; });
    cel('docs').className = ''; cel('pend').className = pend.length ? 'avis' : '';
    cel('docs').textContent = docs.length ? `${docs.length}` : 'nenhum (execute)';
    cel('docs').title = Object.entries(cont).map(([k, v]) => `${k}: ${v}`).join(' · ');
    cel('pend').textContent = pend.length;
    const r = cel('run');
    r.className = prog.rodando ? 'st-alterado' : '';
    r.textContent = prog.rodando ? `rodando (${prog.etapa_atual || '…'})` : (prog.finalizado_em ? 'concluída nesta sessão' : '—');
  } catch (e) {
    cel('docs').textContent = '—'; cel('pend').textContent = '—'; cel('run').textContent = e.message;
  }
}

const ROTULO_REFERENCIAS = {
  titulo: ['✓', 'Referências detectadas pelo título'],
  heuristica: ['~', 'Referências detectadas por heurística (conferir)'],
  nenhum: ['✗', 'Referências não detectadas'],
};

function simboloReferencias(metodo) {
  const r = ROTULO_REFERENCIAS[metodo];
  return r ? `<span title="${esc(r[1])}" class="ref-${esc(metodo)}">${r[0]}</span>` : '—';
}

let docSecoes = null;

function fecharSecoes() {
  docSecoes = null;
  $('#painel-secoes').hidden = true;
  $('#sec-texto').hidden = true;
}

async function abrirSecoes(id, nome) {
  docSecoes = id;
  $('#sec-doc').textContent = nome;
  $('#sec-texto').hidden = true;
  $('#painel-secoes').hidden = false;
  try {
    const r = await api(`/api/projetos/${slugAtual}/documentos/${id}/secoes`);
    const e = r.estatisticas;
    $('#sec-resumo').textContent =
      `Referências: ${e.metodo_deteccao} · palavras: ${e.palavras_total} no total, ${e.palavras_corpo} no corpo, ` +
      `${e.palavras_referencias} em referências · removidos: ${e.urls_removidas} URL/e-mail, ` +
      `${e.hifenizacoes_corrigidas} hifenizações, ${e.linhas_repetidas_removidas} linhas repetidas`;
    $('#tab-secoes tbody').innerHTML = r.secoes.map((s) => {
      const pags = s.pagina_inicio == null ? '—' : (s.pagina_fim != null && s.pagina_fim !== s.pagina_inicio ? `${s.pagina_inicio}–${s.pagina_fim}` : s.pagina_inicio);
      return `<tr><td>${esc(s.tipo)}</td><td>${esc(s.titulo || '(sem título — detectada por heurística)')}</td>
        <td>${esc(pags)}</td><td>${esc(s.palavras)}</td><td class="${s.incluir ? 'st-ok' : 'st-pulado'}">${s.incluir ? 'sim' : 'não'}</td></tr>`;
    }).join('') || '<tr><td colspan="5" class="discreto">Sem seções.</td></tr>';
  } catch (e) {
    $('#sec-resumo').textContent = '';
    $('#tab-secoes tbody').innerHTML = `<tr><td colspan="5" class="discreto">${esc(e.message)}</td></tr>`;
  }
}

const fmtNum = (x, d = 0) => Number(x).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });

async function carregarVocabulario() {
  if (!slugAtual) return;
  const corpo = $('#tab-voc tbody');
  const doc = $('#voc-doc').value;
  const q = new URLSearchParams({ por: $('#voc-por').value, vazias: $('#voc-vazias').value, limite: $('#voc-limite').value });
  if (doc) q.set('documento_id', doc);
  try {
    const r = await api(`/api/projetos/${slugAtual}/vocabulario?${q}`);
    $('#voc-resumo').textContent = `(${fmtNum(r.tipos)} termos · ${fmtNum(r.tokens)} palavras contadas · ${r.documentos} doc.)`;
    corpo.innerHTML = r.itens.map((t, i) =>
      `<tr><td>${i + 1}</td><td>${esc(t.termo)}</td><td>${fmtNum(t.freq)}</td><td>${fmtNum(t.por_10k, 1)}</td><td>${t.docs}</td></tr>`
    ).join('') || '<tr><td colspan="5" class="discreto">Sem termos.</td></tr>';
  } catch (e) {
    $('#voc-resumo').textContent = '';
    corpo.innerHTML = `<tr><td colspan="5" class="discreto">${esc(e.message)}</td></tr>`;
  }
}

for (const id of ['#voc-por', '#voc-vazias', '#voc-doc', '#voc-limite']) $(id).addEventListener('change', carregarVocabulario);

function campoEditavel(d, campo, classe) {
  return `<input class="${classe || ''}" data-doc="${d.id}" data-campo="${campo}" value="${esc(d[campo] ?? '')}"
    ${campo === 'grupo' ? 'list="lista-grupos"' : ''} ${campo === 'ano' ? 'inputmode="numeric"' : ''}>`;
}

// Ações por pendência: OCR por documento (2.6) e "excluir da análise" (reversível, 2.5).
function acoesDaPendencia(p) {
  const b = [];
  if (p.pode_ocr && p.ocr !== true) {
    b.push(`<button class="sec" data-acao="ocr" data-doc="${p.id}" title="Reconverte só este documento com OCR de página inteira e roda o pipeline">Reconverter com OCR</button>`);
  } else if (p.pode_ocr) {
    b.push('<span class="discreto">OCR já aplicado: o texto continua ausente</span>');
  } else if (p.ocr === true) {
    b.push(`<button class="sec" data-acao="ocr-off" data-doc="${p.id}" title="Volta a seguir o parâmetro conversao.ocr do projeto">Desfazer OCR</button>`);
  }
  b.push(p.excluido
    ? `<button class="sec" data-acao="reincluir" data-doc="${p.id}">Reincluir na análise</button>`
    : `<button class="sec" data-acao="excluir" data-doc="${p.id}" title="Tira o documento das análises sem apagar nada; dá para reincluir">Excluir da análise</button>`);
  return b.join(' ');
}

async function abrirProjeto(slug, nome) {
  slugAtual = slug;
  if (nome || !$('#det-nome').textContent) $('#det-nome').textContent = nome || slug;
  const [docs, execs, grupos, pend] = await Promise.all([
    api(`/api/projetos/${slug}/documentos`),
    api(`/api/projetos/${slug}/execucoes?limite=30`),
    api(`/api/projetos/${slug}/grupos`),
    api(`/api/projetos/${slug}/pendencias`),
  ]);
  const cont = {};
  docs.forEach((d) => { cont[d.status] = (cont[d.status] || 0) + 1; });
  $('#det-resumo').textContent = `(${docs.length}) ` + Object.entries(cont).map(([k, v]) => `${k}: ${v}`).join(' · ');
  $('#det-grupos').textContent = 'Grupos: ' + (grupos.map((g) => `${g.grupo || 'sem grupo'} (${g.documentos})`).join(' · ') || '—');
  $('#lista-grupos').innerHTML = grupos.filter((g) => g.grupo).map((g) => `<option value="${esc(g.grupo)}">`).join('');
  $('#tab-docs tbody').innerHTML = docs.map((d) =>
    `<tr title="${esc([...d.problemas, ...d.avisos].join(' | '))}"><td><a href="#" class="doc-link" data-secoes="${d.id}" data-nome="${esc(d.arquivo)}">${esc(d.arquivo)}</a></td>
     <td>${campoEditavel(d, 'grupo')}</td><td>${campoEditavel(d, 'id_estudo')}</td>
     <td>${campoEditavel(d, 'ano', 'ano')}</td><td>${campoEditavel(d, 'autor')}</td>
     <td class="st-${esc(d.status)}">${esc(d.excluido ? d.status + ' · excluído' : d.status)}${d.ocr === true ? ' · OCR' : ''}</td><td>${esc(d.paginas)}</td><td>${esc(d.idioma)}</td>
     <td>${simboloReferencias(d.referencias)}</td><td>${d.pct_corpo == null ? '—' : esc(d.pct_corpo) + '%'}</td></tr>`).join('');
  fecharSecoes();
  const escolhido = $('#voc-doc').value;
  $('#voc-doc').innerHTML = '<option value="">corpus inteiro</option>' +
    docs.filter((d) => d.status !== 'com_problema' && d.status !== 'removido' && !d.excluido)
      .map((d) => `<option value="${d.id}">${esc(d.arquivo.slice(0, 60))}</option>`).join('');
  if ([...$('#voc-doc').options].some((o) => o.value === escolhido)) $('#voc-doc').value = escolhido;
  carregarVocabulario();
  if (typeof carregarRaioX === 'function') carregarRaioX();
  if (typeof carregarComentarios === 'function') carregarComentarios();
  $('#det-pend').textContent = `(${pend.length})`;
  $('#tab-pend tbody').innerHTML = pend.length
    ? pend.map((p) =>
      `<tr><td>${esc(p.arquivo)}</td><td class="st-${esc(p.status)}">${esc(p.status)}</td>
       <td class="prob">${p.problemas.map(esc).join('<br>')}</td><td class="avis">${p.avisos.map(esc).join('<br>')}</td>
       <td class="acoes">${acoesDaPendencia(p)}</td></tr>`).join('')
    : '<tr><td colspan="5" class="discreto">Nenhuma pendência.</td></tr>';
  $('#tab-exec tbody').innerHTML = execs.map((e) =>
    `<tr><td>${e.id}</td><td>${esc(e.etapa)}</td><td>${esc((e.iniciado_em || '').replace('T', ' ').slice(0, 19))}</td>
     <td class="st-${esc(e.status)}">${esc(e.status)}</td><td>${esc(e.mensagem)}</td></tr>`).join('');
}

// Edição inline: ao sair do campo, envia só o que mudou (PATCH parcial).
$('#tab-docs').addEventListener('change', async (ev) => {
  const campo = ev.target.closest('input[data-doc]');
  if (!campo || !slugAtual) return;
  const valor = campo.value.trim();
  const nomeCampo = campo.dataset.campo;
  const corpo = { [nomeCampo]: nomeCampo === 'ano' ? (valor === '' ? null : Number(valor)) : (valor || null) };
  const marcar = (classe) => { campo.className = campo.className.replace(/ ?(salvo|falhou)/g, '') + ' ' + classe; };
  try {
    const d = await api(`/api/projetos/${slugAtual}/documentos/${campo.dataset.doc}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corpo),
    });
    campo.value = d[nomeCampo] ?? '';
    marcar('salvo');
    mensagem('Metadados salvos.');
  } catch (e) {
    marcar('falhou');
    mensagem(e.message, true);
  }
});

$('#tab-pend').addEventListener('click', async (ev) => {
  const bt = ev.target.closest('button[data-acao]');
  if (!bt || !slugAtual) return;
  const slug = slugAtual, acao = bt.dataset.acao;
  const corpo = { ocr: { ocr: true }, 'ocr-off': { ocr: null }, excluir: { excluido: true }, reincluir: { excluido: false } }[acao];
  bt.disabled = true;
  try {
    await api(`/api/projetos/${slug}/documentos/${bt.dataset.doc}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo),
    });
    if (acao === 'ocr' || acao === 'ocr-off') {
      mensagem('Documento marcado para reconversão: executando o pipeline (o OCR pode levar alguns minutos).');
      if (typeof mostrarAba === 'function') mostrarAba('executar');
      $('#ex-btn').click();
    } else {
      mensagem(acao === 'excluir' ? 'Documento excluído da análise: execute o pipeline para atualizar os resultados.'
        : 'Documento reincluído: execute o pipeline para atualizar os resultados.');
      await abrirProjeto(slug);
    }
  } catch (e) {
    mensagem(e.message, true);
    bt.disabled = false;
  }
});

$('#tab-docs').addEventListener('click', (ev) => {
  const a = ev.target.closest('a[data-secoes]');
  if (!a) return;
  ev.preventDefault();
  abrirSecoes(a.dataset.secoes, a.dataset.nome);
});

$('#sec-fechar').addEventListener('click', fecharSecoes);

$('#sec-ver-texto').addEventListener('click', async () => {
  if (docSecoes == null || !slugAtual) return;
  const pre = $('#sec-texto');
  try {
    const r = await fetch(`/api/projetos/${slugAtual}/documentos/${docSecoes}/texto?incluir=${$('#sec-modo').value}`);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    pre.textContent = await r.text();
    pre.hidden = false;
  } catch (e) {
    mensagem(e.message, true);
  }
});

$('#btn-csv').addEventListener('click', async () => {
  const arq = $('#arq-csv').files[0];
  if (!arq || !slugAtual) return mensagem('Escolha um arquivo documentos.csv primeiro.', true);
  try {
    const r = await api(`/api/projetos/${slugAtual}/documentos-csv`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv' },
      body: await arq.arrayBuffer(),
    });
    const faltam = r.sem_arquivo.length ? ` Sem arquivo correspondente: ${r.sem_arquivo.join(', ')}.` : '';
    mensagem(`CSV aplicado: ${r.aplicadas} de ${r.linhas} linha(s).${faltam}`, r.sem_arquivo.length > 0);
    await abrirProjeto(slugAtual);
  } catch (e) {
    mensagem(e.message, true);
  }
});

$('#form-projeto').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const nome = $('#nome').value.trim(), pasta = $('#pasta').value.trim().replace(/^"|"$/g, '');
  $('#erro-nome').textContent = !nome ? 'Informe o nome do projeto.' : (/[a-z0-9]/i.test(nome.normalize('NFD')) ? '' : 'O nome precisa ter letras ou números.');
  $('#erro-pasta').textContent = !pasta ? 'Informe o caminho da pasta de artigos.' : '';
  if ($('#erro-nome').textContent || $('#erro-pasta').textContent) return mensagem('Corrija os campos destacados.', true);
  const botao = ev.target.querySelector('button[type=submit]');
  botao.disabled = true;
  try {
    const p = await api('/api/projetos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome, pasta_origem: pasta }),
    });
    mensagem(`Projeto "${p.nome}" criado. Abra-o e execute o pipeline.`);
    ev.target.reset();
    await carregarProjetos();
  } catch (e) {
    // O servidor responde 400 (pasta inexistente / nome inválido) ou 409 (projeto já existe) com a explicação.
    if (/pasta/i.test(e.message)) $('#erro-pasta').textContent = e.message;
    else if (/projeto|nome/i.test(e.message)) $('#erro-nome').textContent = e.message;
    mensagem(e.message, true);
  } finally {
    botao.disabled = false;
  }
});

api('/api').then((i) => { $('#versao').textContent = `${i.sistema} ${i.versao}`; }).catch(() => {});
