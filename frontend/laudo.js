// Laudo e exportação (entregáveis 9.1 e 9.2): gerar o laudo HTML, abrir, baixar CSV e o pacote .zip.
// Usa $, esc, api e slugAtual de app.js (carregado antes). Recarrega junto com os comentários (ver o final do arquivo).
const CSVS = ['documentos', 'frequencias', 'keyness', 'colocacoes', 'comentarios', 'evidencias'];

async function carregarLaudo() {
  if (!slugAtual) return;
  const slug = slugAtual;
  try {
    const [resumo, info] = await Promise.all([
      api(`/api/projetos/${slug}/comentarios/resumo`),
      api(`/api/projetos/${slug}/laudo/info`),
    ]);
    if (slug !== slugAtual) return;
    const s = resumo.por_status || {};
    const aceitos = (s.aceito || 0) + (s.editado || 0);
    const pend = (s.sugerido || 0) + (s.revisar || 0);
    $('#ld-contagem').innerHTML =
      `<span class="chip"><b>${aceitos}</b> aceito(s)/editado(s): entram no laudo</span>` +
      `<span class="chip"><b>${pend}</b> aguardando revisão: ficam de fora</span>` +
      `<span class="chip">${(s.rejeitado || 0)} rejeitado(s) · ${(s.obsoleto || 0)} obsoleto(s)</span>`;
    const abrir = $('#ld-abrir');
    abrir.hidden = !info.existe;
    abrir.href = `/api/projetos/${slug}/laudo`;
    const dx = $('#ld-docx');
    dx.hidden = !(info.existe && info.docx);
    dx.href = `/api/projetos/${slug}/laudo/docx`;
    $('#ld-info').textContent = info.existe
      ? `(último: ${(info.gerado_em || '').replace('T', ' ')} UTC, ${Math.round(info.tamanho_bytes / 1024)} KB)` : '(ainda não gerado)';
    $('#ld-csvs').innerHTML = CSVS.map((n) =>
      `<a class="botao sec" download="${n}.csv" href="/api/projetos/${slug}/exportar/${n}.csv">${n}.csv</a>`).join(' ');
  } catch (e) {
    $('#ld-msg').textContent = e.message;
  }
}

$('#ld-gerar').addEventListener('click', async () => {
  if (!slugAtual) return;
  const b = $('#ld-gerar');
  b.disabled = true;
  $('#ld-msg').textContent = 'Gerando…';
  try {
    const r = await api(`/api/projetos/${slugAtual}/laudo`, { method: 'POST' });
    const falhas = (r.checagem && r.checagem.falhas) || [];
    $('#ld-msg').textContent = `Laudo gerado (HTML e .docx): ${r.aceitos} comentário(s) incluído(s); ${r.pendentes} pendente(s) de fora.` +
      (falhas.length ? ` ${falhas.length} reprovado(s) na checagem de evidência voltaram para revisar.` : '');
    await carregarLaudo();
  } catch (e) {
    $('#ld-msg').textContent = e.message;
  } finally {
    b.disabled = false;
  }
});

$('#ld-pacote').addEventListener('click', async () => {
  if (!slugAtual) return;
  const b = $('#ld-pacote');
  b.disabled = true;
  $('#ld-msg').textContent = 'Montando o pacote…';
  try {
    const r = await fetch(`/api/projetos/${slugAtual}/exportar/pacote.zip`, { method: 'POST' });
    if (!r.ok) throw new Error(((await r.json().catch(() => ({}))).detail) || r.statusText);
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = `${slugAtual}-pacote.zip`;
    a.click();
    URL.revokeObjectURL(url);
    $('#ld-msg').textContent = 'Pacote baixado (também gravado em saidas/pacote.zip).';
    await carregarLaudo();
  } catch (e) {
    $('#ld-msg').textContent = e.message;
  } finally {
    b.disabled = false;
  }
});

// Atualiza as contagens sempre que a revisão de comentários é recarregada (aceitar, editar, rejeitar...).
if (typeof carregarComentarios === 'function') {
  const _carregarComentarios = carregarComentarios;
  carregarComentarios = async function () {
    await _carregarComentarios.apply(this, arguments);
    carregarLaudo();
  };
}

// 9.4 Texto de Métodos
function mtParametros() { return `idioma=${$('#mt-idioma').value}&estilo=${$('#mt-estilo').value}`; }
$('#mt-gerar').addEventListener('click', async () => {
  if (!slugAtual) return;
  $('#mt-msg').textContent = 'Gerando…';
  try {
    const base = `/api/projetos/${slugAtual}/metodos-texto?${mtParametros()}`;
    const r = await api(base);
    const area = $('#mt-texto');
    area.value = r.texto; area.hidden = false;
    $('#mt-copiar').hidden = false;
    $('#mt-md').hidden = false; $('#mt-md').href = `${base}&formato=md`;
    $('#mt-docx').hidden = false; $('#mt-docx').href = `${base}&formato=docx`;
    $('#mt-msg').textContent = `${r.paragrafos.length} parágrafos, ${r.referencias.length} referências.`;
  } catch (e) {
    $('#mt-msg').textContent = e.message;
  }
});
$('#mt-copiar').addEventListener('click', async () => {
  $('#mt-msg').textContent = (await copiar($('#mt-texto').value)) ? 'Copiado ✓' : 'Não foi possível copiar';
});
