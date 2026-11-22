import {accounts, batchAction, createBatch, refresh, role, setSession, signIn, state} from './state.js';
import {batchRail, esc, field, heading} from './ui.js';
import {firing} from './firing.js';
import {load} from './load.js';
import {review} from './review.js';

const root = document.querySelector('#app');
const pages = {
  firing: ['烧成批次','登记窑次，按烧成周期补录温区和同一台累计表的读数。',firing],
  load: ['负荷分析','校验起止时段，用历史烧成基线估计本周期参考用量。',load],
  review: ['周期复核','交接配方审批和节拍确认，保留原始读数及试算依据。',review]
};
const currentPage = () => location.hash.slice(1) in pages ? location.hash.slice(1) : 'firing';
let poll;
const numeric = new Set(['baseline_version','batch_kg','planned_minutes','peak_c','reading_m3','next_minutes','run_id']);
const timestamps = new Set(['opened_at','closed_at','started_at','ended_at','sampled_at']);

function credentials() {
  root.innerHTML = `<main class="login"><div class="kiln-door" aria-hidden="true"><div class="kiln-mouth"><i></i><i></i><i></i></div><span>K2</span></div>
    <section class="sign-in"><p class="brand-name">澄浦陶瓷</p><h1>窑炉燃气台账</h1><p class="login-sub">查看烧成记录、燃气负荷和下一周期节拍。</p>
    <form data-action="login">${field('工号','username','autocomplete="username"')}${field('密码','password','type="password" autocomplete="current-password"')}<button>进入台账</button></form>
    <div class="demo"><span>演示岗位</span><div>${Object.entries(role).map(([key,name]) => `<button type="button" class="secondary" data-demo="${key}">${name}</button>`).join('')}</div></div>
    <p id="feedback" role="status" aria-live="polite"></p></section></main>`;
}

function render() {
  clearTimeout(poll);
  if (!state.session) { credentials(); return; }
  const key = currentPage();
  const [title, hint, view] = pages[key];
  root.innerHTML = `<header class="top"><div class="identity"><span class="stamp" aria-hidden="true">窑</span><div><b>澄浦陶瓷</b><small>烧成工段 · 燃气台账</small></div></div>
    <nav aria-label="工作台">${Object.entries(pages).map(([route,[label]]) => `<a href="#${route}" ${route === key ? 'aria-current="page"' : ''}>${label}</a>`).join('')}</nav>
    <div class="session"><span>${role[state.session.user.role]}</span><button type="button" data-logout>退出</button></div></header>
    <main class="work"><div>${heading(title,hint)}<div class="workspace">${batchRail()}
    <article class="desk"><p id="feedback" role="status" aria-live="polite"></p>${view(state.batch)}</article></div></div></main>`;
  if (key === 'load' && state.batch?.runs[0]?.status === 'queued') poll = setTimeout(() => reload(), 1200);
}

function feedback(message, kind='error') {
  const el = document.querySelector('#feedback');
  if (el) { el.textContent = message; el.dataset.kind = kind; }
}

async function reload(code) {
  try { await refresh(code); render(); }
  catch (error) { feedback(error.message); }
}

root.addEventListener('click', async (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.demo) {
    const form = root.querySelector('[data-action=login]');
    form.elements.username.value = accounts[button.dataset.demo];
    form.elements.password.value = 'KilnLab!1073';
    form.elements.username.focus();
  }
  if (button.hasAttribute('data-logout')) {
    setSession(null); state.batch = null; location.hash = 'login'; render();
  }
  if (button.dataset.batch) await reload(button.dataset.batch);
  if (button.hasAttribute('data-refresh')) await reload();
});

root.addEventListener('submit', async (event) => {
  const form = event.target;
  if (!form.dataset.action) return;
  event.preventDefault();
  const button = event.submitter;
  if (button) button.disabled = true;
  const raw = Object.fromEntries(new FormData(form));
  const payload = Object.fromEntries(Object.entries(raw).map(([key,value]) => [key,
    numeric.has(key) ? Number(value) : timestamps.has(key) ? `${value}:00+08:00` : value]));
  try {
    const action = form.dataset.action;
    if (action === 'login') {
      setSession(await signIn(payload));
      await refresh(); location.hash = 'firing'; render();
      return;
    }
    const result = action === 'schedule' ? await createBatch(payload) : await batchAction(`/${action}`, payload);
    await refresh(action === 'schedule' ? result.code : state.code);
    render(); feedback('已写入台账', 'success');
  } catch (error) {
    feedback(error.message);
    document.querySelector('#feedback')?.scrollIntoView({block:'nearest'});
  } finally { if (button) button.disabled = false; }
});

window.addEventListener('hashchange', render);
render();
if (state.session) reload();
