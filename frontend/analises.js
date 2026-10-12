// Painéis de análise (Frente 10.2): Cirrus (nuvem em canvas, layout em espiral do protótipo voyant-local),
// abas internas dos painéis e redesenho ao redimensionar. Os demais painéis (termos, tendências, colocações,
// resumo, KWIC, keyness) estão em raiox.js e compartilham a seleção de termos (rx.termos / escolherTermo).
// Usa $, esc, fmtNum de app.js e rx, escolherTermo, desenharGrafico, desenharRede de raiox.js.

let caixasCirrus = [];

function cssVar(nome) {
  return getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
}

function desenharCirrus() {
  const cv = $('#cirrus'), wrap = $('#cirrus-wrap');
  if (!cv || !wrap) return;
  const W = wrap.clientWidth, H = wrap.clientHeight;
  if (!W || !H) return; // painel oculto (aba não aberta): redesenha ao mostrar
  const dpr = window.devicePixelRatio || 1;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  caixasCirrus = [];
  const itens = rx.freq ? rx.freq.itens.slice(0, +$('#cirrus-n').value) : [];
  if (!itens.length) {
    ctx.fillStyle = cssVar('--suave'); ctx.font = '13px system-ui, sans-serif'; ctx.textBaseline = 'top';
    ctx.fillText(rx.resumo ? 'Sem termos neste escopo.' : 'Execute o pipeline para ver a nuvem de palavras.', 12, 12);
    return;
  }
  const max = itens[0].freq, min = itens[itens.length - 1].freq;
  const fmax = Math.max(20, Math.min(W, H) / 5.5), fmin = 10;
  const paleta = [1, 2, 3, 4, 5, 6].map((i) => cssVar('--c' + i));
  const fam = 'system-ui, "Segoe UI", sans-serif';
  ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
  itens.forEach((it, k) => {
    const size = fmin + (fmax - fmin) * Math.sqrt((it.freq - min) / ((max - min) || 1));
    ctx.font = `600 ${size}px ${fam}`;
    const w = ctx.measureText(it.termo).width, h = size;
    for (let s = 0; s < 6000; s++) { // espiral a partir do centro, como no protótipo
      const a = s * 0.12, r = 1.1 * a;
      const x = W / 2 + r * Math.cos(a) * 1.5 - w / 2, y = H / 2 + r * Math.sin(a) - h / 2;
      if (x < 2 || y < 2 || x + w > W - 2 || y + h > H - 2) { if (r > Math.max(W, H)) break; continue; }
      if (caixasCirrus.some((b) => x < b.x + b.w + 3 && x + w + 3 > b.x && y < b.y + b.h + 1 && y + h + 1 > b.y)) continue;
      caixasCirrus.push({ it, x, y, w, h, size, cor: paleta[k % 6] });
      break;
    }
  });
  for (const b of caixasCirrus) {
    const sel = rx.termos.indexOf(b.it.termo);
    if (sel >= 0) { ctx.fillStyle = cssVar('--marca'); ctx.fillRect(b.x - 3, b.y, b.w + 6, b.h); }
    ctx.font = `600 ${b.size}px ${fam}`;
    ctx.fillStyle = sel >= 0 ? cssVar('--c' + ((sel % 6) + 1)) : b.cor;
    ctx.fillText(b.it.termo, b.x, b.y + b.h / 2);
  }
}

function caixaDoCirrus(ev) {
  const r = $('#cirrus').getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
  return caixasCirrus.find((b) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h);
}

$('#cirrus').addEventListener('click', (ev) => {
  const b = caixaDoCirrus(ev);
  if (b) escolherTermo(b.it.termo, ev.ctrlKey || ev.shiftKey || ev.metaKey);
});
$('#cirrus').addEventListener('mousemove', (ev) => {
  const b = caixaDoCirrus(ev), dica = $('#cirrus-dica');
  $('#cirrus').style.cursor = b ? 'pointer' : 'default';
  if (!b) { dica.hidden = true; return; }
  dica.hidden = false;
  dica.innerHTML = `<b>${esc(b.it.termo)}</b><br>${fmtNum(b.it.freq)} ocorrências · ${fmtNum(b.it.por_10k, 1)} por 10 mil · ${b.it.docs} doc.`;
  dica.style.left = Math.min(ev.clientX + 14, window.innerWidth - 270) + 'px';
  dica.style.top = Math.min(ev.clientY + 14, window.innerHeight - 70) + 'px';
});
$('#cirrus').addEventListener('mouseleave', () => { $('#cirrus-dica').hidden = true; });
$('#cirrus-n').addEventListener('input', desenharCirrus);

// ---------- abas internas dos painéis (Cirrus/Termos, Links/Colocações, Resumo/Documentos) ----------

function redesenharPaineis() {
  desenharCirrus();
  if (typeof desenharGrafico === 'function') desenharGrafico();
  if (typeof desenharRede === 'function') desenharRede();
}

document.querySelectorAll('.abas-p').forEach((grupo) => {
  grupo.addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-vista]');
    if (!b) return;
    const painel = grupo.closest('.painel');
    grupo.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
    painel.querySelectorAll('.vista').forEach((v) => v.classList.toggle('on', v.id === b.dataset.vista));
    painel.querySelectorAll('.p-ctl[data-para]').forEach((c) => { c.hidden = c.dataset.para !== b.dataset.vista; });
    redesenharPaineis();
  });
});

let timerPaineis = null;
if (window.ResizeObserver) {
  new ResizeObserver(() => { clearTimeout(timerPaineis); timerPaineis = setTimeout(redesenharPaineis, 150); }).observe($('.grade-an'));
}
