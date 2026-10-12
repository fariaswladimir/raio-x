// Painel "Classes gramaticais e entidades" (4.5, spaCy opcional) em Análises > Descritivo: frequências só de substantivos,
// adjetivos ou verbos e lista de entidades nomeadas (ORG, PERSON, GPE) com link para o KWIC. Mostra "não instalado" sem spaCy.
// Usa $, esc, api, fmtNum, slugAtual (app.js), rx, rxUrl, docLink, buscarKwic, mostrarSub, SUBS, CARREGADORES (raiox.js).

const cgr = { seq: 0 };

function montarPainelClasses() {
  if ($('#p-classes') || !$('#p-kwic')) return;
  const p = document.createElement('div');
  p.className = 'painel larga'; p.id = 'p-classes'; p.dataset.sub = 'descritivo';
  p.innerHTML = `
    <div class="p-cab"><b>Classes gramaticais e entidades (spaCy)</b> <span class="discreto p-info" id="cg-info"></span>
      <span class="p-ctl"><a class="botao sec peq" id="cg-csv" download="classes_gramaticais.csv" href="#">Classes CSV</a>
        <a class="botao sec peq" id="cg-csv-e" download="entidades.csv" href="#">Entidades CSV</a></span></div>
    <div class="p-corpo livre">
      <p id="cg-status" class="discreto"></p>
      <p id="cg-msg" class="vazio" hidden></p>
      <div id="cg-conteudo">
        <p class="barra">
          <label class="inline">Classes
            <select id="cg-classes"><option value="substantivos">só substantivos</option><option value="adjetivos">só adjetivos</option><option value="verbos">só verbos</option>
              <option value="substantivos,adjetivos">substantivos e adjetivos</option><option value="plenas">substantivos, adjetivos e verbos (formas ativas do IRaMuTeQ)</option></select></label>
          <label class="inline">Tipos de entidade
            <select id="cg-tipos"><option value="ORG,PERSON,GPE">ORG, PERSON, GPE</option><option value="ORG">só ORG</option><option value="PERSON">só PERSON</option><option value="GPE">só GPE</option>
              <option value="ORG,PERSON,GPE,PRODUCT,NORP,LOC,EVENT">mais tipos</option></select></label>
          <button id="cg-calcular" type="button">Atualizar</button>
        </p>
        <div class="sm-grade">
          <div><h5 class="sm-tit">Termos mais frequentes da classe</h5><div class="rolagem alta"><table id="tab-cg-freq"></table></div></div>
          <div><h5 class="sm-tit">Entidades nomeadas <span class="discreto" id="cg-ents-info"></span></h5><div class="rolagem alta"><table id="tab-cg-ents"></table></div></div>
        </div>
        <p class="aviso" id="cg-aviso" hidden></p>
      </div>
      <p class="discreto">Classes UPOS do spaCy (en_core_web_sm, pt_core_news_sm; sem modelo para espanhol). Mesmo universo do painel Frequências (corpo do texto, palavras vazias
        filtradas). Em <code>parametros.json</code>: <code>lematizacao.metodo = "spacy"</code> (padrão: simplemma), <code>reinert.formas_ativas = "classes"</code> e
        <code>termos_compostos.classes</code> restringem a CHD e os termos compostos a essas classes. Instalação: <code>instalar_spacy.bat</code>.</p>
    </div>`;
  $('#p-kwic').parentNode.insertBefore(p, $('#p-kwic').nextSibling);
  $('#cg-calcular').addEventListener('click', carregarClasses);
  for (const id of ['#cg-classes', '#cg-tipos']) $(id).addEventListener('change', carregarClasses);
  $('#tab-cg-ents').addEventListener('click', (ev) => {
    const a = ev.target.closest('a[data-kwic]');
    if (!a) return;
    ev.preventDefault();
    $('#rx-q').value = a.dataset.kwic;
    $('#rx-por').value = 'forma';
    if (typeof mostrarSub === 'function' && rx.sub !== 'descritivo') mostrarSub('descritivo');
    buscarKwic(true);
    const alvo = $('#p-kwic');
    if (alvo && alvo.scrollIntoView) alvo.scrollIntoView({ block: 'nearest' });
  });
}

async function carregarClasses() {
  if (!slugAtual || !$('#p-classes')) return;
  const seq = ++cgr.seq;
  $('#cg-msg').hidden = true;
  let st;
  try { st = await api('/api/spacy/status'); } catch (e) { st = { instalado: false, mensagem: e.message, modelos: {} }; }
  const modelos = Object.entries(st.modelos || {}).map(([i, m]) => `${i}: ${m.instalado ? 'instalado' : 'não instalado'}`).join(' · ');
  $('#cg-status').textContent = st.instalado ? `spaCy ${st.versao} · modelos ${modelos}` : `spaCy não instalado. Opção de lematização "spacy" indisponível. ${st.instalar || ''}`;
  $('#cg-conteudo').hidden = !st.instalado;
  if (!st.instalado) { $('#cg-info').textContent = ''; return; }
  const vazias = $('#rx-vazias') ? $('#rx-vazias').value : 'filtrar';
  const q = { classes: $('#cg-classes').value, por: $('#rx-por').value === 'forma' ? 'forma' : 'lema', vazias, ...rxEscopo() };
  $('#cg-csv').href = rxUrl('classes-gramaticais.csv', q);
  $('#cg-csv-e').href = rxUrl('entidades.csv', { tipos: $('#cg-tipos').value });
  try {
    const [f, e] = await Promise.all([api(rxUrl('classes-gramaticais', { ...q, limite: 100 })), api(rxUrl('entidades', { tipos: $('#cg-tipos').value, limite: 100 }))]);
    if (seq !== cgr.seq) return;
    $('#cg-info').textContent = `(${fmtNum(f.documentos)} documentos com classes; ${fmtNum(f.tipos)} termos)`;
    $('#tab-cg-freq').innerHTML = '<thead><tr><th>#</th><th>Termo</th><th>Classe</th><th>Freq.</th><th>/10k</th><th>Docs</th></tr></thead><tbody>'
      + (f.itens.map((t, i) => `<tr><td>${i + 1}</td><td>${termoHtml(t.termo, q.por)}</td><td>${esc(t.classe)}</td><td class="num">${fmtNum(t.freq)}</td>
        <td class="num">${fmtNum(t.por_10k, 1)}</td><td class="num">${t.docs}</td></tr>`).join('') || '<tr><td colspan="6" class="discreto">Sem dados: execute o pipeline com o spaCy instalado.</td></tr>') + '</tbody>';
    $('#cg-ents-info').textContent = `(${fmtNum(e.total_distintas)} distintas)`;
    $('#tab-cg-ents').innerHTML = '<thead><tr><th>Entidade</th><th>Tipo</th><th>Freq.</th><th>Docs</th><th>Onde (pág.)</th><th>KWIC</th></tr></thead><tbody>'
      + (e.itens.map((x) => `<tr><td>${esc(x.texto)}</td><td>${esc(x.tipo)}</td><td class="num">${fmtNum(x.freq)}</td><td class="num">${x.docs}</td>
        <td>${x.exemplos.map((o) => `${docLink(o)}${o.pagina ? ' p. ' + o.pagina : ''}`).join('; ')}</td>
        <td><a href="#" data-kwic="${esc(x.kwic)}" title="Abrir no KWIC (por forma)">contextos</a></td></tr>`).join('') || '<tr><td colspan="6" class="discreto">Nenhuma entidade.</td></tr>') + '</tbody>';
    $('#cg-aviso').hidden = false;
    $('#cg-aviso').textContent = e.aviso + (f.sem_classes.length ? ` ${f.sem_classes.length} documento(s) sem etiquetagem (idioma sem modelo ou etapa não executada).` : '');
  } catch (err) {
    if (seq !== cgr.seq) return;
    $('#cg-msg').hidden = false; $('#cg-msg').textContent = err.message;
  }
}

montarPainelClasses();
if (typeof SUBS !== 'undefined' && !SUBS.descritivo.includes('classes')) {
  SUBS.descritivo.push('classes');
  CARREGADORES.classes = carregarClasses;
}
