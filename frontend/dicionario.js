// Painel "Dicionário (codebook)" (6.4): importar o .xlsx, editar categorias e termos, resultados por grupo/ano/documento,
// mapa de calor e KWIC por categoria. Usa $, esc, api, fmtNum, slugAtual (app.js) e rx, rxUrl, buscarKwic (raiox.js).

const dc = { cats: [], res: null, seq: 0, sujo: false };

function dcMensagem(texto, erro) {
  const m = $('#dc-msg');
  m.textContent = texto || '';
  m.style.color = erro ? 'var(--erro)' : '';
}

function dcErros(e) { // api() lança Error(JSON) quando o detalhe é um objeto
  try { const d = JSON.parse(e.message); if (d && d.erros) return d.erros.join(' | '); } catch { /* texto simples */ }
  return e.message;
}

function paramsDicionario(extra) {
  return { agrupar: $('#dc-agrupar').value, por: $('#dc-por').value, ...extra };
}

// ---------- editor ----------

function renderEditor() {
  const corpo = dc.cats.map((c, i) => `<tr data-i="${i}">
    <td><input class="dc-id" value="${esc(c.id)}" ${c.novo ? '' : 'readonly'} size="8" aria-label="Id da categoria" placeholder="id"></td>
    <td><input class="dc-nome" value="${esc(c.nome)}" size="26" aria-label="Nome da categoria"></td>
    <td><input class="dc-tema" value="${esc(c.tema)}" size="8" aria-label="Tema"></td>
    <td><input class="dc-termos" value="${esc((c.termos || []).join(', '))}" size="40" aria-label="Termos de ${esc(c.id)}" placeholder="ex.: agent*, human oversight"></td>
    <td class="dc-aviso">${(c.termos || []).length ? '' : '<span class="avis">sem termos — preencha</span>'}</td>
    <td><button type="button" class="sec peq dc-rem" title="Remover categoria" aria-label="Remover ${esc(c.id)}">×</button></td></tr>`).join('');
  $('#tab-dc-ed').innerHTML = `<thead><tr><th>Id</th><th>Nome</th><th>Tema</th><th>Termos (separados por vírgula)</th><th></th><th></th></tr></thead><tbody>${corpo ||
    '<tr><td colspan="6" class="discreto">Sem categorias: importe o codebook (.xlsx) ou use "Nova categoria".</td></tr>'}</tbody>`;
  const sem = dc.cats.filter((c) => !(c.termos || []).length).length;
  $('#dc-resumo-ed').textContent = `(${dc.cats.length} categorias${sem ? ` · ${sem} sem termos — preencha` : ''}${dc.sujo ? ' · alterações não salvas' : ''})`;
}

function lerEditor() {
  document.querySelectorAll('#tab-dc-ed tbody tr[data-i]').forEach((tr) => {
    const c = dc.cats[+tr.dataset.i];
    c.id = tr.querySelector('.dc-id').value.trim();
    c.nome = tr.querySelector('.dc-nome').value.trim();
    c.tema = tr.querySelector('.dc-tema').value.trim();
    c.termos = tr.querySelector('.dc-termos').value.split(',').map((t) => t.trim()).filter(Boolean);
  });
}

async function carregarDicionario() {
  if (!slugAtual) return;
  try {
    const d = await api(`/api/projetos/${slugAtual}/dicionario`);
    dc.cats = d.categorias.map((c) => ({ id: c.id, nome: c.nome, tema: c.tema, tema_nome: c.tema_nome, descricao: c.descricao, termos: c.termos }));
    dc.sujo = false;
    dcMensagem('');
    renderEditor();
  } catch (e) {
    dc.cats = [];
    renderEditor();
    dcMensagem(dcErros(e), true);
  }
  carregarResultadosDicionario();
}

async function salvarDicionario() {
  lerEditor();
  try {
    const d = await api(`/api/projetos/${slugAtual}/dicionario`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ categorias: dc.cats.map(({ novo, ...c }) => c) }),
    });
    dc.cats = d.categorias.map((c) => ({ id: c.id, nome: c.nome, tema: c.tema, tema_nome: c.tema_nome, descricao: c.descricao, termos: c.termos }));
    dc.sujo = false;
    renderEditor();
    dcMensagem(`Dicionário salvo: ${d.total} categorias (${d.sem_termos} sem termos). Execute o pipeline para atualizar o instantâneo do laudo.`);
    carregarResultadosDicionario();
  } catch (e) {
    dcMensagem(dcErros(e), true);
  }
}

async function importarCodebook() {
  const arq = $('#dc-arq').files[0];
  if (!arq || !slugAtual) { dcMensagem('Escolha o arquivo .xlsx do codebook primeiro.', true); return; }
  dcMensagem('Importando…');
  try {
    const r = await api(`/api/projetos/${slugAtual}/dicionario/importar-codebook`, { method: 'POST', body: arq });
    const rel = r.relatorio, col = Object.entries(rel.colunas).map(([k, v]) => `${k} ← "${v}"`).join('; ');
    $('#dc-relatorio').hidden = false;
    $('#dc-relatorio').innerHTML = `Aba <b>${esc(rel.aba)}</b>: ${rel.categorias_importadas} categorias (${rel.novas} novas, ${rel.atualizadas} atualizadas). Colunas: ${esc(col)}.` +
      (rel.aviso ? `<br>${esc(rel.aviso)}` : '');
    dcMensagem('');
    await carregarDicionario();
  } catch (e) {
    dcMensagem(dcErros(e), true);
  }
}

// ---------- resultados ----------

function rotuloUnidade(u) { return u.rotulo; }

function celulaComparacao(u) {
  if (u.g2 == null) return '<td></td><td></td>';
  return `<td title="p = ${fmtP(u.p)}">${u.g2 >= 0 ? '+' : '−'}${fmtNum(Math.abs(u.g2), 1)}</td><td>${fmtNum(u.log_ratio, 2)}</td>`;
}

function renderResultadosDicionario() {
  const r = dc.res, tab = $('#tab-dc-res'), heat = $('#tab-dc-heat');
  if (!r) { tab.innerHTML = ''; heat.innerHTML = ''; return; }
  const porUnidade = r.agrupar !== 'documento';
  $('#dc-unid-nome').textContent = r.agrupar;
  const cabUn = porUnidade ? r.unidades.map((u) => `<th colspan="${r.comparacao ? 3 : 1}" class="dc-un" title="${u.documentos} documento(s) · ${fmtNum(u.tokens)} palavras">${esc(rotuloUnidade(u))}</th>`).join('') : '';
  const sub = porUnidade ? r.unidades.map(() => `<th>/10k</th>${r.comparacao ? '<th title="G² (sinal + = mais frequente na unidade que no resto)">G²</th><th title="Log Ratio (Hardie 2014)">LR</th>' : ''}`).join('') : '';
  const linhas = r.categorias.map((c) => `<tr class="dc-cat" data-id="${esc(c.id)}" title="Abrir os padrões nos contextos (KWIC)">
      <td><b>${esc(c.id)}</b></td><td>${esc(c.nome)}</td><td>${esc(c.tema)}</td><td>${fmtNum(c.total)}</td><td>${fmtNum(c.por_10k, 1)}</td><td>${c.docs}/${r.documentos}</td>
      <td class="dc-top">${c.termos_top.slice(0, 4).map((t) => `${esc(t.termo)} (${fmtNum(t.freq)})`).join(', ')}</td>
      ${porUnidade ? c.unidades.map((u) => `<td>${fmtNum(u.por_10k, 1)}</td>${r.comparacao ? celulaComparacao(u) : ''}`).join('') : ''}</tr>`).join('');
  tab.innerHTML = `<thead><tr><th rowspan="2">Categoria</th><th rowspan="2">Nome</th><th rowspan="2">Tema</th><th rowspan="2">Ocorr.</th><th rowspan="2">/10k</th>
    <th rowspan="2" title="Documentos com ao menos uma ocorrência">Docs</th><th rowspan="2">Termos mais casados</th>${cabUn}</tr><tr>${sub}</tr></thead>
    <tbody>${linhas || '<tr><td colspan="7" class="discreto">Nenhuma categoria com termos.</td></tr>'}</tbody>`;

  const cabH = r.unidades.map((u) => `<th title="${esc(u.rotulo)} · ${fmtNum(u.tokens)} palavras">${esc(u.rotulo.length > 18 ? u.rotulo.slice(0, 17) + '…' : u.rotulo)}</th>`).join('');
  const linhasH = r.categorias.map((c) => {
    const max = Math.max(...c.unidades.map((u) => u.por_10k), 0.0001);
    return `<tr class="dc-cat" data-id="${esc(c.id)}"><th class="dc-h-cat" title="${esc(c.nome)}">${esc(c.id)} <span class="discreto">${esc(c.nome.length > 28 ? c.nome.slice(0, 27) + '…' : c.nome)}</span></th>` +
      c.unidades.map((u) => `<td class="heat-c" style="background:color-mix(in srgb, var(--c1) ${(u.por_10k / max * 70).toFixed(0)}%, transparent)" title="${esc(c.id)} · ${esc(u.rotulo)}: ${fmtNum(u.n)} ocorr. · ${fmtNum(u.por_10k, 1)} /10k · ${u.docs}/${u.documentos} doc.">${fmtNum(u.por_10k, 1)}</td>`).join('') + '</tr>';
  }).join('');
  heat.innerHTML = `<thead><tr><th>Categoria</th>${cabH}</tr></thead><tbody>${linhasH || `<tr><td colspan="${r.unidades.length + 1}" class="discreto">Nenhuma categoria com termos.</td></tr>`}</tbody>`;
}

async function carregarResultadosDicionario() {
  if (!slugAtual || !rx.resumo) return;
  const seq = ++dc.seq;
  $('#dc-csv').href = rxUrl('dicionario.csv', paramsDicionario());
  const vazio = $('#dc-vazio');
  try {
    const r = await api(rxUrl('dicionario', paramsDicionario()));
    if (seq !== dc.seq) return;
    dc.res = r;
    vazio.hidden = r.categorias.length > 0;
    vazio.textContent = 'Nenhuma categoria com termos: importe o codebook e preencha os termos (ou escreva-os acima) para ver as contagens.';
    $('#dc-info').textContent = `(${r.categorias.length} categorias com termos${r.sem_termos.length ? ` · ${r.sem_termos.length} sem termos — preencha` : ''} · ${r.documentos} doc. · ${fmtNum(r.tokens)} palavras)`;
    renderResultadosDicionario();
  } catch (e) {
    if (seq !== dc.seq) return;
    dc.res = null;
    vazio.hidden = false;
    vazio.textContent = dcErros(e);
    $('#dc-info').textContent = '';
    renderResultadosDicionario();
  }
}

function limparDicionario() {
  dc.res = null; dc.cats = [];
  for (const id of ['#tab-dc-ed', '#tab-dc-res', '#tab-dc-heat']) $(id).innerHTML = '';
  $('#dc-info').textContent = '';
  $('#dc-resumo-ed').textContent = '';
}

// Clicar numa categoria abre os padrões dela no KWIC (palavras com curinga e frases entre aspas, na mesma unidade).
function abrirCategoriaNoKwic(id) {
  const c = dc.res && dc.res.categorias.find((x) => x.id === id);
  if (!c) return;
  $('#rx-q').value = c.consulta_kwic;
  const por = dc.res.por;
  if ($('#rx-por').value !== por) { $('#rx-por').value = por; $('#rx-por').dispatchEvent(new Event('change')); } else buscarKwic(true);
  $('#p-kwic').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

$('#p-dic').addEventListener('click', (ev) => {
  const rem = ev.target.closest('.dc-rem');
  if (rem) {
    lerEditor();
    dc.cats.splice(+rem.closest('tr').dataset.i, 1);
    dc.sujo = true; renderEditor();
    return;
  }
  const tr = ev.target.closest('tr.dc-cat');
  if (tr) abrirCategoriaNoKwic(tr.dataset.id);
});
$('#tab-dc-ed').addEventListener('input', () => { dc.sujo = true; $('#dc-resumo-ed').textContent = `(${dc.cats.length} categorias · alterações não salvas)`; });
$('#dc-nova').addEventListener('click', () => {
  lerEditor();
  dc.cats.push({ id: '', nome: '', tema: '', tema_nome: '', descricao: '', termos: [], novo: true });
  dc.sujo = true; renderEditor();
  const ids = document.querySelectorAll('#tab-dc-ed .dc-id');
  ids[ids.length - 1].focus();
});
$('#dc-salvar').addEventListener('click', salvarDicionario);
$('#dc-importar').addEventListener('click', importarCodebook);
$('#dc-atualizar').addEventListener('click', carregarResultadosDicionario);
for (const id of ['#dc-agrupar', '#dc-por']) $(id).addEventListener('change', carregarResultadosDicionario);
