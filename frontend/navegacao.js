// Navegação (Frente 10.1): vista "Projetos" x projeto aberto com abas, execução em segundo plano com progresso
// (polling de 1 s em /progresso) e lembrança do último projeto/aba no localStorage.
// Usa $, esc, api, mensagem, fmtNum, carregarProjetos, abrirProjeto (app.js) e redesenharPaineis (analises.js).

const ABAS = ['geral', 'executar', 'analises', 'comentarios', 'codificacao', 'perguntar', 'corpus', 'coleta', 'paragrafos', 'laudo'];
const CHAVE_PROJETO = 'raiox.projeto', CHAVE_ABA = 'raiox.aba', CHAVE_VISTA = 'raiox.vista';

function lembrar(chave, valor) {
  try { if (valor == null) localStorage.removeItem(chave); else localStorage.setItem(chave, valor); } catch { /* sem armazenamento: segue sem lembrar */ }
}
function lerLembrado(chave) {
  try { return localStorage.getItem(chave); } catch { return null; }
}

let abaAtual = 'geral';

function mostrarVista(vista) {
  const projeto = vista === 'projeto', config = vista === 'config';
  $('#vista-projetos').hidden = projeto || config;
  $('#vista-projeto').hidden = !projeto;
  $('#vista-config').hidden = !config;
  $('#nav-abas').hidden = !projeto;
  $('#nav-projeto').hidden = !projeto;
  document.querySelectorAll('#nav-principal .nav-item').forEach((b) => b.classList.toggle('on', b.dataset.vista === vista));
  lembrar(CHAVE_VISTA, config ? 'projetos' : vista);
  if (!projeto) pararPolling();
  if (config) cfCarregar();
  else if (!projeto) carregarProjetos().catch((e) => mensagem(e.message, true));
}

function mostrarAba(aba) {
  if (!ABAS.includes(aba)) aba = 'geral';
  abaAtual = aba;
  document.querySelectorAll('#nav-abas button').forEach((b) => {
    b.classList.toggle('on', b.dataset.aba === aba);
    b.setAttribute('aria-current', b.dataset.aba === aba ? 'page' : 'false');
  });
  for (const a of ABAS) $(`#aba-${a}`).hidden = a !== aba;
  lembrar(CHAVE_ABA, aba);
  if (aba === 'analises') requestAnimationFrame(() => redesenharPaineis());
  if (aba === 'paragrafos') carregarParagrafos();
  if (aba === 'codificacao' && typeof carregarCodificacao === 'function') carregarCodificacao();
  if (aba === 'perguntar' && typeof carregarPerguntar === 'function') carregarPerguntar();
  if (aba === 'corpus' && typeof carregarCorpus === 'function') carregarCorpus();
  if (aba === 'coleta' && typeof carregarColeta === 'function') carregarColeta();
}

async function entrarNoProjeto(slug, nome, aba) {
  $('#det-nome').textContent = nome || slug;
  lembrar(CHAVE_PROJETO, slug);
  mostrarVista('projeto');
  mostrarAba(aba || lerLembrado(CHAVE_ABA) || 'geral');
  zerarProgresso();
  await abrirProjeto(slug, nome);
  consultarProgresso(slug);
  if (abaAtual === 'analises') requestAnimationFrame(() => redesenharPaineis());
  if (abaAtual === 'paragrafos') carregarParagrafos();
  if (abaAtual === 'codificacao' && typeof carregarCodificacao === 'function') carregarCodificacao();
  if (abaAtual === 'corpus' && typeof carregarCorpus === 'function') carregarCorpus();
  if (abaAtual === 'coleta' && typeof carregarColeta === 'function') carregarColeta();
}

$('#nav-principal').addEventListener('click', (ev) => {
  const b = ev.target.closest('[data-vista]');
  if (b) mostrarVista(b.dataset.vista);
});
$('#nav-abas').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-aba]');
  if (b) mostrarAba(b.dataset.aba);
});
$('#tab-projetos').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-abrir]');
  if (!b) return;
  const nome = b.closest('tr').querySelector('.nome-proj').textContent;
  entrarNoProjeto(b.dataset.abrir, nome, b.dataset.aba).catch((e) => mensagem(e.message, true));
});

// ---------- execução e progresso ----------

const prog = { slug: null, timer: null, errosVistos: -1, ultimo: null };

function pararPolling() {
  if (prog.timer) clearInterval(prog.timer);
  prog.timer = null;
}

function zerarProgresso() {
  pararPolling();
  prog.slug = null; prog.errosVistos = -1; prog.ultimo = null;
  $('#ex-etapas').innerHTML = '';
  $('#ex-status').textContent = '';
  $('#ex-erros-bloco').hidden = true;
  $('#ex-btn').disabled = false;
  $('#aba-run').hidden = true;
}

function duracao(ini, fim) {
  if (!ini) return '';
  const s = Math.max(0, Math.round(((fim ? new Date(fim + 'Z') : new Date()) - new Date(ini + 'Z')) / 1000));
  return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
}

const ROTULO_STATUS = { pendente: 'aguardando', rodando: 'rodando', concluida: 'concluída', com_erros: 'com erros' };

function renderProgresso(p) {
  prog.ultimo = p;
  $('#aba-run').hidden = !p.rodando;
  $('#ex-btn').disabled = p.rodando;
  $('#ex-etapas').innerHTML = p.etapas.map((e) => {
    const total = e.total, pct = e.status === 'concluida' || e.status === 'com_erros' ? 100
      : (total ? Math.min(100, Math.round((e.feitos / total) * 100)) : 0);
    const contagem = e.status === 'pendente' ? '' : `${fmtNum(e.feitos)}${total != null ? ' / ' + fmtNum(total) : ''} · ${fmtNum(e.pulados)} pulado(s) · ${fmtNum(e.erros)} erro(s)`;
    return `<div class="etapa st-${esc(e.status)}${p.etapa_atual === e.nome ? ' atual' : ''}">
      <span class="e-nome">${esc(e.nome)} <span class="discreto">${esc(e.escopo)}</span></span>
      <div class="barra-prog" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="Progresso da etapa ${esc(e.nome)}"><i class="${e.erros ? 'com-erro' : ''}" style="width:${pct}%"></i></div>
      <span class="e-cont">${contagem}</span><span class="e-st">${esc(ROTULO_STATUS[e.status] || e.status)}</span></div>`;
  }).join('');
  if (p.rodando) {
    $('#ex-status').textContent = `Rodando: etapa ${p.etapa_atual || '…'} · ${duracao(p.iniciado_em)}`;
  } else if (p.erro) {
    $('#ex-status').textContent = `A execução falhou: ${p.erro}`;
  } else if (p.finalizado_em) {
    const n = p.resumo ? p.resumo.erros : 0;
    $('#ex-status').textContent = `Concluída em ${duracao(p.iniciado_em, p.finalizado_em)}: ${n} erro(s).` +
      (p.resumo ? ' Documentos: ' + Object.entries(p.resumo.documentos).map(([k, v]) => `${k} ${v}`).join(' · ') : '');
  } else {
    $('#ex-status').textContent = 'Nenhuma execução nesta sessão do servidor (o histórico está em "Execuções recentes").';
  }
  const erros = p.etapas.reduce((s, e) => s + e.erros, 0);
  if (erros !== prog.errosVistos) { prog.errosVistos = erros; listarErros(p, erros); }
  else if (p.erro) listarErros(p, erros);
}

async function listarErros(p, n) {
  const bloco = $('#ex-erros-bloco'), lista = $('#ex-erros');
  const fatal = p.erro ? [`A execução parou: ${p.erro}`] : [];
  if (!n && !fatal.length) { bloco.hidden = true; return; }
  let msgs = [];
  try {
    const execs = await api(`/api/projetos/${prog.slug}/execucoes?limite=500`);
    const desde = (p.iniciado_em || '').slice(0, 19);
    msgs = execs.filter((e) => e.status === 'erro' && (e.iniciado_em || '').slice(0, 19) >= desde)
      .map((e) => `[${e.etapa}] ${e.mensagem || ''}`);
  } catch (e) { msgs = [e.message]; }
  bloco.hidden = false;
  $('#ex-erros-n').textContent = `(${n})`;
  lista.innerHTML = [...fatal, ...msgs].map((m) => `<li>${esc(m)}</li>`).join('');
}

async function consultarProgresso(slug) {
  try {
    const p = await api(`/api/projetos/${slug}/progresso`);
    if (slug !== slugAtual) return;
    prog.slug = slug;
    renderProgresso(p);
    if (p.rodando && !prog.timer) prog.timer = setInterval(() => sondar(slug), 1000);
  } catch (e) {
    $('#ex-status').textContent = e.message;
  }
}

async function sondar(slug) {
  if (slug !== slugAtual) return pararPolling();
  try {
    const p = await api(`/api/projetos/${slug}/progresso`);
    renderProgresso(p);
    if (!p.rodando) {
      pararPolling();
      await abrirProjeto(slug); // recarrega documentos, execuções, análises e comentários
      if (abaAtual === 'analises') requestAnimationFrame(() => redesenharPaineis());
    }
  } catch (e) {
    pararPolling();
    $('#ex-status').textContent = e.message;
  }
}

$('#ex-btn').addEventListener('click', async () => {
  if (!slugAtual) return;
  const slug = slugAtual;
  $('#ex-btn').disabled = true;
  prog.errosVistos = -1;
  try {
    await api(`/api/projetos/${slug}/executar`, { method: 'POST' });
  } catch (e) {
    // 409: já havia uma execução em andamento; só passa a acompanhá-la.
    $('#ex-status').textContent = e.message;
  }
  prog.slug = slug;
  await consultarProgresso(slug);
  if (prog.ultimo && !prog.ultimo.rodando) await abrirProjeto(slug); // terminou antes do primeiro sondar
});

// ---------- início: reabre o último projeto/aba ----------

(async () => {
  let lista = [];
  try { lista = await api('/api/projetos'); } catch (e) { return mensagem(e.message, true); }
  await carregarProjetos().catch((e) => mensagem(e.message, true));
  const slug = lerLembrado(CHAVE_PROJETO);
  const p = lista.find((x) => x.slug === slug);
  if (p && lerLembrado(CHAVE_VISTA) === 'projeto') await entrarNoProjeto(p.slug, p.nome, lerLembrado(CHAVE_ABA));
  else mostrarVista('projetos');
})();
