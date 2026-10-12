// Tela de metodologia: catálogo de análises (método + referências) vindo de /api/metodologia.
// Independente do app principal (não usa app.js); lembra só o formato e o último projeto no localStorage.

const $ = (s, r = document) => r.querySelector(s);
const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const semAcento = (t) => String(t ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

const NOTA_CONFERIR = 'conferir antes de citar';
const estado = {
  catalogo: [], familias: [], formato: 'abnt', refs: {}, // refs: chave -> {texto, html, nota}
  projeto: '', uso: null, // uso: id -> análise marcada
};

function lembrar(chave, valor) { try { if (valor) localStorage.setItem(chave, valor); else localStorage.removeItem(chave); } catch { /* sem armazenamento */ } }
function lerLembrado(chave) { try { return localStorage.getItem(chave); } catch { return null; } }

function mensagem(texto, erro = false) {
  const m = $('#msg');
  m.textContent = texto || '';
  m.className = erro ? 'erro' : '';
}

async function api(caminho) {
  const r = await fetch(caminho);
  if (!r.ok) {
    let detalhe = r.statusText;
    try { detalhe = (await r.json()).detail || detalhe; } catch { /* corpo não é JSON */ }
    throw new Error(`${r.status}: ${detalhe}`);
  }
  return r.json();
}

function fmtValor(v) {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'sim' : 'não';
  if (Array.isArray(v)) return v.length ? v.map(fmtValor).join(', ') : '(vazio)';
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k}: ${fmtValor(x)}`).join('; ');
  return String(v);
}

// ---------------------------------------------------------------- cópia
async function copiar(texto, botao) {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(texto);
    else throw new Error('sem clipboard');
  } catch {
    const ta = document.createElement('textarea');
    ta.value = texto; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } finally { ta.remove(); }
  }
  if (botao) {
    const antes = botao.textContent;
    botao.textContent = 'copiado';
    setTimeout(() => { botao.textContent = antes; }, 1400);
  }
}

// ---------------------------------------------------------------- dados
async function carregarReferencias() {
  const r = await api(`/api/metodologia/referencias?formato=${estado.formato}`);
  estado.refs = {};
  r.referencias.forEach((x, i) => { estado.refs[x.chave] = { ...x, ordem: i }; });
}

async function carregarCatalogo() {
  const r = await api('/api/metodologia');
  estado.catalogo = r.analises;
  estado.familias = r.familias;
}

async function carregarProjetos() {
  let lista = [];
  try { lista = await api('/api/projetos'); } catch { return; }
  const sel = $('#projeto');
  lista.forEach((p) => {
    const o = document.createElement('option');
    o.value = p.slug; o.textContent = p.nome || p.slug;
    sel.appendChild(o);
  });
  const lembrado = lerLembrado('raiox.projeto');
  if (lembrado && lista.some((p) => p.slug === lembrado)) { sel.value = lembrado; await escolherProjeto(lembrado); }
}

async function escolherProjeto(slug) {
  estado.projeto = slug;
  estado.uso = null;
  $('#rotulo-so-usadas').hidden = !slug;
  if (!slug) { $('#so-usadas').checked = false; return; }
  try {
    const r = await api(`/api/projetos/${encodeURIComponent(slug)}/metodologia`);
    estado.uso = Object.fromEntries(r.analises.map((a) => [a.id, a]));
    mensagem(`Projeto "${slug}": ${r.usadas.length} de ${r.total} análises usadas (marcadas com ●).`);
  } catch (e) {
    mensagem(`Não foi possível ler o projeto: ${e.message}`, true);
  }
}

// ---------------------------------------------------------------- filtros
function visiveis() {
  const q = semAcento($('#busca').value.trim());
  const status = $('#filtro-status').value;
  const soUsadas = $('#so-usadas').checked && estado.uso;
  return estado.catalogo.filter((a) => {
    if (status && a.status !== status) return false;
    if (soUsadas && !(estado.uso[a.id] && estado.uso[a.id].usada_no_projeto)) return false;
    if (!q) return true;
    return semAcento(textoBusca(a)).includes(q);
  });
}

function textoBusca(a) {
  if (a._busca) return a._busca;
  const refs = a.referencias.map((r) => `${r.autores.join(' ')} ${r.ano} ${r.titulo} ${r.veiculo || ''}`).join(' ');
  const params = a.parametros_padrao.map((p) => `${p.nome} ${p.valor}`).join(' ');
  a._busca = [a.nome, a.id, a.familia, a.o_que_mede, a.metrica, a.formula, a.equivale_a, a.nao_e_igual_a, a.eap_id, params, refs].join(' ');
  return a._busca;
}

// ---------------------------------------------------------------- render
function chipStatus(a) { return `<span class="chip ${esc(a.status)}">${esc(a.status)}</span>`; }
function usada(a) { return !!(estado.uso && estado.uso[a.id] && estado.uso[a.id].usada_no_projeto); }

function renderIndice(lista) {
  const porFamilia = new Map();
  lista.forEach((a) => { if (!porFamilia.has(a.familia)) porFamilia.set(a.familia, []); porFamilia.get(a.familia).push(a); });
  let html = '';
  estado.familias.forEach((f) => {
    const itens = porFamilia.get(f);
    if (!itens) return;
    html += `<h3>${esc(f)}</h3>`;
    itens.forEach((a) => {
      html += `<a href="#a-${esc(a.id)}" data-id="${esc(a.id)}" class="${usada(a) ? 'usada' : ''}"><span class="nome">${esc(a.nome)}</span>${chipStatus(a)}<span class="chip eap">EAP ${esc(a.eap_id)}</span></a>`;
    });
  });
  $('#indice').innerHTML = html || '<p class="met-vazio">Nenhuma análise.</p>';
}

function parametrosHtml(a) {
  const uso = estado.uso && estado.uso[a.id];
  const linhas = a.parametros_padrao.map((p, i) => {
    let valor = esc(fmtValor(p.valor));
    const doProjeto = uso && uso.parametros_padrao[i];
    if (doProjeto && 'valor_projeto' in doProjeto) {
      const dif = doProjeto.difere_do_padrao;
      valor += ` <span class="proj">· projeto: ${esc(fmtValor(doProjeto.valor_projeto))}</span>${dif ? ' <span class="dif">(difere do padrão)</span>' : ''}`;
    }
    return `<tr><td>${esc(p.nome)}</td><td>${valor}</td></tr>`;
  }).join('');
  return `<table class="met-param"><tbody>${linhas}</tbody></table>`;
}

function refsOrdenadas(a) {
  return [...a.referencias].sort((x, y) => (estado.refs[x.chave]?.ordem ?? 0) - (estado.refs[y.chave]?.ordem ?? 0));
}

function referenciaHtml(r) {
  const f = estado.refs[r.chave];
  if (!f) return '';
  const corpo = estado.formato === 'bibtex' ? `<pre>${esc(f.texto)}</pre>` : `<span>${f.html}</span>`;
  const notas = [];
  if (r.nota) {
    if (r.nota === NOTA_CONFERIR) notas.push(`<span class="nota">${esc(NOTA_CONFERIR)}</span>`);
    else notas.push(`<span class="nota-livre">Nota: ${esc(r.nota)}</span>`);
  }
  return `<li class="met-ref" data-chave="${esc(r.chave)}"><div class="txt">${corpo}${notas.join('')}</div><button type="button" class="sec" data-copiar="${esc(r.chave)}">copiar</button></li>`;
}

function cartaoHtml(a) {
  const uso = usada(a);
  const refs = refsOrdenadas(a);
  const modulo = a.modulo ? `<code>${esc(a.modulo)}</code>` : '<span class="met-vazio">ainda sem módulo</span>';
  const formula = a.formula ? `<code class="met-formula">${esc(a.formula)}</code>` : '';
  return `<section class="met-cartao${uso ? ' usada' : ''}" id="a-${esc(a.id)}" data-id="${esc(a.id)}">
    <header>
      <h2>${esc(a.nome)}</h2>
      ${chipStatus(a)}<span class="chip eap">EAP ${esc(a.eap_id)}</span>${uso ? '<span class="chip usada" title="' + esc((estado.uso[a.id].evidencia_de_uso || []).join('; ')) + '">usada neste projeto</span>' : ''}
    </header>
    <p class="discreto" style="margin:0 0 8px">${esc(a.familia)}</p>
    <dl>
      <dt>O que mede</dt><dd>${esc(a.o_que_mede)}</dd>
      <dt>Métrica</dt><dd>${esc(a.metrica)}${formula}</dd>
      <dt>Parâmetros</dt><dd>${parametrosHtml(a)}</dd>
      <dt>Equivale a</dt><dd>${esc(a.equivale_a)}</dd>
      <dt>Não é igual a</dt><dd>${esc(a.nao_e_igual_a)}</dd>
      <dt>Cuidados</dt><dd><ul>${a.cuidados.map((c) => `<li>${esc(c)}</li>`).join('')}</ul></dd>
      <dt>Módulo</dt><dd>${modulo}</dd>
    </dl>
    <div class="met-refs">
      <h3>Referências (${refs.length})${refs.length ? `<button type="button" class="sec" data-copiar-todas="${esc(a.id)}">copiar todas desta análise</button>` : ''}</h3>
      ${refs.length ? `<ol>${refs.map(referenciaHtml).join('')}</ol>` : '<p class="met-vazio">Sem referências no catálogo para esta análise.</p>'}
    </div>
  </section>`;
}

function renderizar() {
  const lista = visiveis();
  renderIndice(lista);
  $('#cartoes').innerHTML = lista.length ? lista.map(cartaoHtml).join('') : '<div class="met-nenhum">Nenhuma análise encontrada para esse filtro.</div>';
  const total = estado.catalogo.length;
  $('#contagem').textContent = `${lista.length} de ${total} análises`;
}

// ---------------------------------------------------------------- eventos
function atualizarDownloads() {
  const txt = estado.formato === 'apa' ? 'apa' : 'abnt';
  const a = $('#baixar-txt');
  a.href = `/api/metodologia/referencias.txt?formato=${txt}`;
  a.textContent = `Baixar todas (.txt, ${txt.toUpperCase()})`;
}

async function trocarFormato(formato) {
  estado.formato = formato;
  lembrar('raiox.metodologia.formato', formato);
  document.querySelectorAll('#formatos button').forEach((b) => {
    const on = b.dataset.formato === formato;
    b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on));
  });
  atualizarDownloads();
  try { await carregarReferencias(); renderizar(); } catch (e) { mensagem(e.message, true); }
}

$('#formatos').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-formato]');
  if (b) trocarFormato(b.dataset.formato);
});
$('#busca').addEventListener('input', renderizar);
$('#filtro-status').addEventListener('change', renderizar);
$('#so-usadas').addEventListener('change', renderizar);
$('#imprimir').addEventListener('click', () => window.print());
$('#projeto').addEventListener('change', async (ev) => {
  lembrar('raiox.projeto', ev.target.value || null);
  mensagem('');
  await escolherProjeto(ev.target.value);
  renderizar();
});

$('#cartoes').addEventListener('click', (ev) => {
  const um = ev.target.closest('button[data-copiar]');
  if (um) { copiar(estado.refs[um.dataset.copiar].texto, um); return; }
  const todas = ev.target.closest('button[data-copiar-todas]');
  if (todas) {
    const a = estado.catalogo.find((x) => x.id === todas.dataset.copiarTodas);
    copiar(refsOrdenadas(a).map((r) => estado.refs[r.chave].texto).join('\n\n'), todas);
  }
});

$('#indice').addEventListener('click', (ev) => {
  const link = ev.target.closest('a[data-id]');
  if (!link) return;
  ev.preventDefault();
  const alvo = document.getElementById(`a-${link.dataset.id}`);
  if (alvo) {
    alvo.scrollIntoView({ behavior: 'smooth', block: 'start' });
    history.replaceState(null, '', `#a-${link.dataset.id}`);
    document.querySelectorAll('#indice a.atual').forEach((x) => x.classList.remove('atual'));
    link.classList.add('atual');
    if (window.matchMedia('(max-width: 900px)').matches) $('#indice-det').open = false;
  }
});

async function iniciar() {
  const guardado = lerLembrado('raiox.metodologia.formato');
  if (['abnt', 'apa', 'bibtex'].includes(guardado)) estado.formato = guardado;
  if (window.matchMedia('(max-width: 900px)').matches) $('#indice-det').open = false;
  try {
    await Promise.all([carregarCatalogo(), carregarReferencias()]);
  } catch (e) {
    mensagem(`Não foi possível carregar o catálogo: ${e.message}`, true);
    return;
  }
  await carregarProjetos();
  await trocarFormato(estado.formato);
  if (location.hash.startsWith('#a-')) {
    const alvo = document.getElementById(location.hash.slice(1));
    if (alvo) alvo.scrollIntoView();
  }
}
iniciar();
