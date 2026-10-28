(() => {
  const D = window.SITE_DATA;
  const app = document.getElementById('app');

  const STATUS = {
    kept:        { label: 'Изпълнено',            icon: '✓', hint: 'Има данни, че обещаното е направено (при обещание „няма да…“ – не е нарушено до момента).' },
    partial:     { label: 'Частично изпълнено',   icon: '◐', hint: 'Част от обещаното е направена, друга част – не.' },
    in_progress: { label: 'В процес',             icon: '…', hint: 'Има конкретни стъпки, но не е завършено.' },
    broken:      { label: 'Нарушено',             icon: '✕', hint: 'Източниците показват, че е изоставено или противоречи на обещаното.' },
    reversed:    { label: 'Обърната позиция',     icon: '↺', hint: 'Политикът публично е променил позицията си.' },
    no_power:    { label: 'Без власт да го изпълни', icon: '∅', hint: 'Изпълнението не зависи от политика: напр. опозиция без мнозинство или въпрос извън президентските правомощия. Не е нито заслуга, нито провал.' },
    too_early:   { label: 'Рано е за оценка',     icon: '⏳', hint: 'Времето за изпълнение още не е настъпило.' },
    unclear:     { label: 'Няма достатъчно данни', icon: '?', hint: 'Обещанието е твърде общо или не открихме надеждни данни.' },
  };
  const ORDER = Object.keys(STATUS);
  const REL = { delivers: 'Изпълнение', progress: 'Стъпка напред', obstacle: 'Пречка или критика', abandoned: 'Отказ',
    reversal: 'Смяна на позицията', context: 'Контекст' };
  const TOPIC = { prices: 'Цени', justice: 'Правосъдие', corruption: 'Корупция', eu_funds: 'Европейски средства',
    eu_nato: 'ЕС и НАТО', budget: 'Бюджет', euro: 'Евро', tax: 'Данъци', energy: 'Енергетика', governance: 'Управление',
    security: 'Сигурност', foreign: 'Външна политика', social: 'Социална политика', other: 'Друго' };
  const MONTHS = ['януари', 'февруари', 'март', 'април', 'май', 'юни', 'юли', 'август', 'септември', 'октомври', 'ноември', 'декември'];

  const people = Object.fromEntries(D.politicians.map(p => [p.id, p]));
  const state = { status: null, q: '', showAuto: true };

  // ---------- helpers
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'href') el.setAttribute('href', safeUrl(v));
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'style') el.setAttribute('style', v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u) ? u : '#'; }
  function ext(href, text) { return h('a', { href, target: '_blank', rel: 'noopener noreferrer' }, text, ' ↗'); }
  function fmtDate(d) {
    if (!d) return 'дата неизвестна';
    const [y, m, day] = d.split('-').map(Number);
    if (!m) return String(y);
    if (!day) return `${MONTHS[m - 1]} ${y}`;
    return `${day} ${MONTHS[m - 1]} ${y}`;
  }
  function fmtStamp(iso) {
    if (!iso) return '–';
    const d = new Date(iso);
    return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
  function daysUntil(iso) {
    const t = new Date(iso + 'T23:59:59'); return Math.ceil((t - new Date()) / 86400000);
  }
  function plural(n, one, many) { return n === 1 ? one : many; }
  function pill(status) {
    const s = STATUS[status] || STATUS.unclear;
    return h('span', { class: 'pill', style: `--c:var(--s-${status in STATUS ? status : 'unclear'})`, title: s.hint }, h('span', { 'aria-hidden': 'true' }, s.icon), s.label);
  }
  function bar(counts) {
    const label = ORDER.filter(s => counts[s]).map(s => `${STATUS[s].label}: ${counts[s]}`).join(', ') || 'няма обещания';
    return h('div', { class: 'bar', role: 'img', 'aria-label': label },
      ORDER.filter(s => counts[s]).map(s => h('i', { style: `flex:${counts[s]};--c:var(--s-${s})`, title: `${STATUS[s].label}: ${counts[s]}` })));
  }

  // ---------- views
  function personCard(p, current) {
    return h('li', null, h('a', { class: 'person', href: `#/p/${p.id}`, 'aria-current': current ? 'page' : null },
      h('h3', null, p.name),
      h('div', { class: 'sub' }, p.seats != null ? `${p.party_short} · ${p.seats} места` : p.party_short),
      bar(p.counts),
      h('div', { class: 'n' }, p.promise_count ? `${p.promise_count} ${plural(p.promise_count, 'обещание', 'обещания')} в базата` : 'Още няма проверими обещания в базата')));
  }

  function evidenceItem(e) {
    const auto = e.origin === 'auto';
    return h('li', { class: `rel-${e.relation}` },
      h('div', { class: 'rel' }, REL[e.relation] || e.relation, ' · ', fmtDate(e.date), ' · ', e.publisher,
        auto ? ` · автоматично (ИИ, увереност ${Math.round((e.confidence || 0) * 100)}%)` : ' · ръчно проучено'),
      h('div', null, ext(e.url, e.title)),
      e.note ? h('div', { class: 'note' }, e.note) : null,
      e.guard ? h('div', { class: 'note' }, `Моделът го е определил като „${REL[e.model_relation] || e.model_relation}“, но е понижено до „контекст“: ${e.guard}.`) : null,
      e.quote ? h('div', { class: 'quote' }, `„${e.quote}“`) : null);
  }

  function promiseCard(pr, open) {
    const p = people[pr.politician];
    const auto = pr.origin === 'auto';
    const weight = { delivers: 0, abandoned: 0, reversal: 0, obstacle: 1, progress: 1, context: 2 };
    const evid = [...pr.evidence].sort((a, b) => (weight[a.relation] - weight[b.relation]) || (b.date || '').localeCompare(a.date || ''));
    const SHOW = 8;
    const evList = evid.length ? (() => {
      const ul = h('ul', { class: 'ev' }, evid.slice(0, SHOW).map(evidenceItem));
      if (evid.length > SHOW) {
        const more = h('button', { class: 'chip', onclick: () => { more.remove(); ul.append(...evid.slice(SHOW).map(evidenceItem)); } }, `Покажи още ${evid.length - SHOW}`);
        return h('div', null, ul, h('p', null, more));
      }
      return ul;
    })() : h('p', { class: 'meta' }, 'Все още няма събрани доказателства.');
    const dueEl = pr.due ? (() => {
      const n = daysUntil(pr.due);
      const txt = n < 0 ? `срокът изтече на ${fmtDate(pr.due)}` : n === 0 ? `срок: днес` : `срок: ${fmtDate(pr.due)} (след ${n} ${plural(n, 'ден', 'дни')})`;
      return h('span', { class: 'due' + (n < 0 ? ' late' : '') }, ' · ', txt);
    })() : null;
    const history = pr.status_history.length ? h('div', { class: 'why' }, h('strong', null, 'История на оценката: '),
      pr.status_history.map(x => `${fmtDate(x.date)}: ${STATUS[x.from]?.label} → ${STATUS[x.to]?.label}`).join('; ')) : null;
    return h('li', null, h('article', { class: 'card' + (auto ? ' auto' : ''), id: `promise-${pr.id}` },
      h('div', { class: 'head' }, pill(pr.status), h('span', { class: 'who' }, p.name), `(${p.party_short})`,
        h('span', null, '· ' + fmtDate(pr.said_on)),
        pr.topic ? h('span', { class: 'tag' }, TOPIC[pr.topic] || pr.topic) : null,
        auto ? h('span', { class: 'tag auto', title: 'Намерено автоматично от заглавие в новините; не е проверявано ръчно.' }, 'автоматично открито') : null),
      h('p', { class: 'txt' }, pr.text),
      h('div', { class: 'meta' }, 'Източник: ', ext(pr.source.url, `${pr.source.publisher}`), dueEl),
      h('details', open ? { open: true } : null,
        h('summary', null, `Защо тази оценка · ${evid.length} ${plural(evid.length, 'доказателство', 'доказателства')}`),
        h('p', { class: 'why' }, pr.status_reason),
        h('p', { class: 'meta' }, pr.status_origin === 'auto' ? `Оценка от автоматичната система, ${fmtDate(pr.status_updated)}.` : `Първоначална оценка по посочените източници, ${fmtDate(pr.status_updated)}; системата може да я промени при нови данни.`),
        pr.quote ? h('div', { class: 'quote' }, `„${pr.quote}“`, pr.quote_lang === 'en' ? ' (цитат от източника, на английски)' : '') : null,
        pr.context ? h('p', { class: 'meta' }, pr.context) : null,
        history,
        evList)));
  }

  function matches(pr) {
    if (state.status && pr.status !== state.status) return false;
    if (!state.showAuto && pr.origin === 'auto') return false;
    if (state.q) {
      const hay = (pr.text + ' ' + people[pr.politician].name + ' ' + (TOPIC[pr.topic] || '')).toLowerCase();
      if (!hay.includes(state.q.toLowerCase())) return false;
    }
    return true;
  }

  function homeView(pid) {
    const pol = pid ? people[pid] : null;
    const all = D.promises.filter(p => !pid || p.politician === pid);
    const view = h('div');
    const add = (...kids) => view.append(...kids.filter(Boolean));
    add(
      pol ? h('p', { class: 'crumb' }, h('a', { href: '#/' }, '← Всички политици')) : null,
      h('h1', null, pol ? pol.name : 'Обещано и направено'),
      pol ? h('p', { class: 'lede' }, `${pol.role} · ${pol.party}`) :
        h('p', { class: 'lede' }, 'Какво обещават водещите български политици – и какво се случва после. Към всяко твърдение има линк към източник. Системата събира новини всяка седмица и ги оценява автоматично с изкуствен интелект.'),
      pol ? h('div', { class: 'bio' }, pol.bio, ' ', h('span', { class: 'meta' }, 'Източници: ', pol.bio_sources.map((s, i) => [i ? ', ' : '', ext(s.url, s.publisher)]))) :
        h('div', { class: 'callout' }, h('strong', null, 'Честно за ограниченията. '),
          'Оценките не са проверявани от човек и може да са грешни. Всяка оценка е свързана с източници, които можете да отворите. Едни и същи правила важат за всички политици. Опозицията често е „без власт да изпълни“ – това не е провал. ',
          h('a', { href: '#/method' }, 'Как работи системата →')));
    if (!pol) add(h('ul', { class: 'people' }, D.politicians.map(p => personCard(p, false))));

    const counts = Object.fromEntries(ORDER.map(s => [s, all.filter(p => p.status === s).length]));
    const chips = h('div', { class: 'filters' },
      h('button', { class: 'chip', 'aria-pressed': String(!state.status), onclick: () => { state.status = null; draw(); } }, 'Всички', h('small', null, all.length)),
      ORDER.filter(s => counts[s]).map(s => h('button', { class: 'chip', 'aria-pressed': String(state.status === s), onclick: () => { state.status = state.status === s ? null : s; draw(); } },
        STATUS[s].label, h('small', null, counts[s]))));
    const search = h('input', { type: 'search', placeholder: 'Търсене в обещанията…', 'aria-label': 'Търсене', value: state.q });
    search.addEventListener('input', () => { state.q = search.value; renderList(); });
    const auto = h('input', { type: 'checkbox' }); auto.checked = state.showAuto;
    auto.addEventListener('change', () => { state.showAuto = auto.checked; renderList(); });
    const holder = h('ul', { class: 'list' });
    add(h('h2', null, pol ? 'Обещания' : 'Всички обещания'), chips,
      h('div', { class: 'filters' }, search, h('label', { class: 'chk' }, auto, 'Показвай автоматично открити')), holder);

    function renderList() {
      const list = all.filter(matches);
      holder.replaceChildren(...(list.length ? list.map(p => promiseCard(p, false)) :
        [h('li', { class: 'empty' }, all.length ? 'Няма обещания по тези филтри.' : 'Все още не сме намерили проверими, конкретни обещания с надежден източник. Системата продължава да търси всеки ден.')]));
    }
    renderList();
    return view;
  }

  function promiseView(id) {
    const pr = D.promises.find(p => p.id === id);
    if (!pr) return h('div', null, h('h1', null, 'Не е намерено'), h('p', null, h('a', { href: '#/' }, '← Към всички обещания')));
    return h('div', null, h('p', { class: 'crumb' }, h('a', { href: `#/p/${pr.politician}` }, `← ${people[pr.politician].name}`)),
      h('ul', { class: 'list' }, promiseCard(pr, true)));
  }

  function methodView() {
    const sc = D.stats;
    return h('div', { class: 'prose' },
      h('h1', null, 'Как работи'),
      h('p', { class: 'lede' }, 'Накратко: събираме публични новини, местният изкуствен интелект ги съпоставя с обещанията, а фиксирани правила решават кога оценката се променя. Няма редактор, който да одобрява – затова има предпазни механизми и ясно маркиране на всичко автоматично.'),
      h('h2', null, 'Какво броим за „обещание“'),
      h('p', null, 'Конкретно, проверимо поемане на ангажимент от политик („ще внесем бюджета до края на месеца“). Не броим мнения, критики, прогнози и общи лозунги – освен когато ги показваме с оценка „няма достатъчно данни“.'),
      h('h2', null, 'Оценките'),
      h('table', null, h('tbody', null, ORDER.map(s => h('tr', null, h('td', null, pill(s)), h('td', null, STATUS[s].hint))))),
      h('p', { class: 'meta' }, '„Без власт да го изпълни“ е умишлено отделна категория: честната оценка на президент или на опозиция не може да е „нарушено“ за нещо, което не зависи от тях.'),
      h('h2', null, 'Откъде идват данните'),
      h('ul', null,
        h('li', null, 'Първоначалният списък с обещания е събран и оценен ръчно от Claude (ИИ) по цитираните публикации към 28 октомври 2026 г. Всеки запис има линк към източника.'),
        h('li', null, 'Всяка седмица системата чете заглавия от Капитал, Дневник, Медиапул, Sofia Globe и от търсения в Google News (там попадат и БТА, БНР, bTV и други). Пази се само заглавие, кратко резюме, линк, издание и дата – не целият текст.'),
        h('li', null, 'Парламентарни гласувания, Държавен вестник и официалните сайтове на институциите още не са свързани – това е следваща стъпка.')),
      h('h2', null, 'Как ИИ участва и какви са предпазните механизми'),
      h('ol', null,
        h('li', null, 'Модел за векторно сходство (bge-m3) избира кои заглавия може да са свързани с кое обещание.'),
        h('li', null, `Езиков модел (реално използвани до момента: ${(D.judge_models || []).map(m => m === 'external-agent' ? 'външен агент (напр. Claude)' : m).join(', ') || 'още няма'}) чете заглавието и определя отношението му към обещанието: изпълнение, стъпка напред, пречка, отказ, смяна на позицията, контекст.`),
        h('li', null, 'Моделът трябва да върне дословен цитат от заглавието. Ако цитатът не се намира в текста, оценката се изхвърля. Така се ограничава измислянето.'),
        h('li', null, 'Изявления, обвинения и мнения на политици (особено на опоненти) се водят само „контекст“ – не са доказателство за пречка или нарушение. Постове в социални мрежи не се броят за източник.'),
        h('li', null, 'Слаби оценки (под 60% увереност) се изхвърлят. За промяна на статус се изискват поне 75% увереност и поне 2 независими издания (3 – за „изпълнено“, „нарушено“ и „обърната позиция“).'),
        h('li', null, 'Статусът се променя най-много веднъж седмично и само по фиксирани правила – не по преценка на модела.'),
        h('li', null, 'Новите обещания, открити автоматично, са в пунктирана рамка, с оценка „няма достатъчно данни“ и текст, който е самото заглавие – моделът не го пренаписва.')),
      h('h2', null, 'Какво може да се обърка'),
      h('ul', null,
        h('li', null, 'Малкият локален модел разбира български по-зле от големите. Очаквайте грешни връзки между новини и обещания; цитатът и линкът са там, за да ги хванете.'),
        h('li', null, 'Заглавията не са цялата статия. Заглавие като „Радев: ще...“ може да не отразява нюансите.'),
        h('li', null, 'Покритието е неравно: при Радев има повече обещания, защото управлява (има какво да се провери) и защото първо проучихме него. За други политици е намерен малък брой проверими обещания – не защото не обещават, а защото още не сме ги намерили. Това не е позиция на сайта.'),
        h('li', null, 'Някои справки в първоначалните данни идват от вторични източници (напр. Уикипедия, коментари), което е отбелязано при съответните записи.')),
      h('h2', null, 'Състояние на системата'),
      h('ul', null,
        h('li', null, `Заглавия в базата: ${sc.news_items}`),
        h('li', null, `Автоматично прикачени доказателства: ${sc.auto_evidence}`),
        h('li', null, `Автоматично открити обещания: ${sc.auto_promises}`),
        h('li', null, `Автоматични промени на оценки: ${sc.status_changes}`),
        h('li', null, `Последно обновяване: ${fmtStamp(D.generated)}`)));
  }

  // ---------- routing
  function draw() {
    const hash = location.hash || '#/';
    const [, route, arg] = hash.split('/');
    document.querySelectorAll('nav a').forEach(a => {
      const on = (a.dataset.nav === 'method') === (route === 'method');
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    let view;
    if (route === 'method') { document.title = 'Как работи – Обещано и направено'; view = methodView(); }
    else if (route === 'promise') { view = promiseView(decodeURIComponent(arg || '')); document.title = 'Обещание – Обещано и направено'; }
    else if (route === 'p' && people[arg]) { view = homeView(arg); document.title = `${people[arg].name} – Обещано и направено`; }
    else { view = homeView(null); document.title = 'Обещано и направено'; }
    app.replaceChildren(view);
  }
  window.addEventListener('hashchange', () => { state.status = null; state.q = ''; draw(); window.scrollTo(0, 0); });
  document.getElementById('foot-updated').textContent = `Последно автоматично обновяване: ${fmtStamp(D.generated)}.`;
  draw();
})();
