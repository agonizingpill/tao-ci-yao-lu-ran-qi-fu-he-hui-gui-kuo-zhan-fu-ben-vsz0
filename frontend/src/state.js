export const role = {operator: '烧成班长', supervisor: '工艺主管', viewer: '能源查阅'};
export const phase = {ramp: '升温', soak: '保温', cool: '冷却'};
export const batchStatus = {scheduled: '已排程', recording: '采集中', analyzed: '已试算', confirmed: '周期已确认'};
export const recipeStatus = {pending: '待审批', approved: '已批准', rejected: '已退回'};
export const accounts = {operator: 'firing', supervisor: 'chief', viewer: 'energy'};
export const state = {session: JSON.parse(sessionStorage.getItem('kiln.session') || 'null'), batches: [], batch: null, code: sessionStorage.getItem('kiln.code')};

export function setSession(session) {
  state.session = session;
  if (session) sessionStorage.setItem('kiln.session', JSON.stringify(session));
  else sessionStorage.removeItem('kiln.session');
}

async function request(path, method='GET', value) {
  const response = await fetch(`/api${path}`, {method, headers: {
    'Content-Type': 'application/json', ...(state.session && {Authorization: `Bearer ${state.session.token}`})
  }, body: value === undefined ? undefined : JSON.stringify(value)});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') {
      setSession(null);
      location.hash = 'login';
    }
    throw new Error(data.detail || '请求失败，请刷新后重试');
  }
  return data;
}

export const signIn = (form) => request('/login', 'POST', form);
export const batchAction = (path, form) => request(`/batches/${encodeURIComponent(state.code)}${path}`, 'POST', form);
export const createBatch = (form) => request('/batches', 'POST', form);
export async function refresh(code=state.code) {
  const batches = await request('/batches');
  const selected = batches.some((batch) => batch.code === code) ? code : batches[0]?.code;
  const batch = selected ? await request(`/batches/${encodeURIComponent(selected)}`) : null;
  Object.assign(state, {batches, batch, code: selected});
  if (selected) sessionStorage.setItem('kiln.code', selected);
}
