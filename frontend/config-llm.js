// Configurações (Frente 14.1): provedor de LLM, modelo, chave de API (nunca em claro) e chave geral "Permitir geração com LLM".
// Usa $, esc, api de app.js. A chave só viaja no PUT; a API devolve só a máscara ("••••1234").
const cf = { cfg: null };
const CF_PROVEDORES = ['nenhum', 'ollama', 'anthropic', 'openai_compativel'];

function cfMensagem(texto, erro) {
  const m = $('#cf-msg');
  m.textContent = texto || '';
  m.className = erro ? 'erro' : 'discreto';
}

function cfProvedorEscolhido() {
  const r = document.querySelector('input[name="cf-prov"]:checked');
  return r ? r.value : 'nenhum';
}

function cfMostrarPainel() {
  const p = cfProvedorEscolhido();
  for (const nome of CF_PROVEDORES) {
    const el = document.getElementById(`cf-p-${nome}`);
    if (el) el.hidden = nome !== p;
  }
}

function cfRender(cfg) {
  cf.cfg = cfg;
  // 11.2: no modo offline os provedores remotos ficam bloqueados (o Ollama local segue permitido).
  document.querySelectorAll('input[name="cf-prov"]').forEach((r) => {
    if (r.value === 'anthropic' || r.value === 'openai_compativel') { r.disabled = !!cfg.modo_offline; r.title = cfg.modo_offline ? 'Modo offline: provedor remoto desativado' : ''; }
  });
  const avisoOff = $('#cf-offline');
  if (avisoOff) { avisoOff.hidden = !cfg.modo_offline; avisoOff.textContent = cfg.aviso_offline || ''; }
  $('#cf-hab').checked = !!cfg.habilitado;
  document.querySelectorAll('input[name="cf-prov"]').forEach((r) => { r.checked = r.value === cfg.provedor; });
  $('#cf-ol-url').value = cfg.ollama.base_url || '';
  $('#cf-ol-modelo').value = cfg.ollama.modelo || '';
  $('#cf-an-modelo').innerHTML = cfg.modelos_anthropic.map((m) => `<option value="${esc(m)}">${esc(m)}${m === 'claude-opus-5-5' ? ' (padrão)' : ''}</option>`).join('');
  $('#cf-an-modelo').value = cfg.anthropic.modelo;
  $('#cf-an-esforco').value = cfg.anthropic.esforco;
  $('#cf-oa-url').value = cfg.openai_compativel.base_url || '';
  $('#cf-oa-modelo').value = cfg.openai_compativel.modelo || '';
  for (const [campo, prov, rotulo] of [['#cf-an-chave', 'anthropic', '#cf-an-guardada'], ['#cf-oa-chave', 'openai_compativel', '#cf-oa-guardada']]) {
    $(campo).value = ''; $(campo).type = 'password';
    const mascara = cfg.chaves[prov];
    $(rotulo).textContent = mascara ? `Chave guardada: ${mascara}. Deixe o campo vazio para mantê-la.` : 'Nenhuma chave guardada.';
  }
  document.querySelectorAll('[data-mostrar]').forEach((b) => { b.textContent = 'mostrar'; });
  const aviso = $('#cf-cofre');
  aviso.hidden = cfg.armazenamento_chave === 'keyring';
  if (!aviso.hidden) {
    aviso.textContent = 'Atenção: o cofre de credenciais do Windows (keyring) não está disponível. A chave será guardada em um arquivo local em %APPDATA%\\RaioX\\segredos.json, fora dos projetos, mas sem criptografia.';
  }
  cfMostrarPainel();
}

async function cfCarregar() {
  try { cfRender(await api('/api/config/llm')); cfMensagem(''); } catch (e) { cfMensagem(e.message, true); }
}

function cfCorpo() {
  const corpo = {
    habilitado: $('#cf-hab').checked, provedor: cfProvedorEscolhido(),
    ollama: { base_url: $('#cf-ol-url').value.trim(), modelo: $('#cf-ol-modelo').value.trim() },
    anthropic: { modelo: $('#cf-an-modelo').value, esforco: $('#cf-an-esforco').value },
    openai_compativel: { base_url: $('#cf-oa-url').value.trim(), modelo: $('#cf-oa-modelo').value.trim() },
    chaves: {},
  };
  if ($('#cf-an-chave').value.trim()) corpo.chaves.anthropic = $('#cf-an-chave').value;
  if ($('#cf-oa-chave').value.trim()) corpo.chaves.openai_compativel = $('#cf-oa-chave').value;
  return corpo;
}

async function cfSalvar(silencioso) {
  const cfg = await api('/api/config/llm', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfCorpo()) });
  cfRender(cfg);
  if (!silencioso) cfMensagem('Configuração salva.');
  return cfg;
}

$('#cf-cartoes').addEventListener('change', cfMostrarPainel);

$('#cf-salvar').addEventListener('click', async () => {
  try { await cfSalvar(); } catch (e) { cfMensagem(e.message, true); }
});

$('#cf-testar').addEventListener('click', async () => {
  const botao = $('#cf-testar');
  botao.disabled = true;
  cfMensagem('Salvando e testando…');
  try {
    await cfSalvar(true);
    const r = await api('/api/config/llm/testar', { method: 'POST' });
    if (r.modelos) {
      $('#cf-ol-lista').innerHTML = r.modelos.map((m) => `<option value="${esc(m)}"></option>`).join('');
      if (!$('#cf-ol-modelo').value && r.modelos.length) $('#cf-ol-modelo').value = r.modelos[0];
    }
    const modelos = r.modelos && r.modelos.length ? ` Modelos instalados: ${r.modelos.join(', ')}.` : '';
    cfMensagem(`${r.ok ? 'Ok' : 'Falhou'}: ${r.mensagem}${modelos} (${r.latencia_ms} ms)`, !r.ok);
  } catch (e) {
    cfMensagem(e.message, true);
  } finally {
    botao.disabled = false;
  }
});

$('#vista-config').addEventListener('click', async (ev) => {
  const mostrar = ev.target.closest('[data-mostrar]');
  if (mostrar) {
    const campo = document.getElementById(mostrar.dataset.mostrar);
    campo.type = campo.type === 'password' ? 'text' : 'password';
    mostrar.textContent = campo.type === 'password' ? 'mostrar' : 'ocultar';
    return;
  }
  const remover = ev.target.closest('[data-remover]');
  if (remover) {
    try {
      const cfg = await api('/api/config/llm', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ remover_chaves: [remover.dataset.remover] }) });
      cfRender(cfg);
      cfMensagem('Chave removida.');
    } catch (e) { cfMensagem(e.message, true); }
  }
});
