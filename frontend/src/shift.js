import {listPrograms, listShifts, openProgram, openShift, planShift, releaseReservation, shiftDetail, state} from './state.js';
import {amount, badge, date, empty, esc, field, table} from './ui.js';

const shiftState = {shifts: [], detail: null, programs: [], message: '', kind: 'success', lastPlan: null};

export function shiftFeedback(message, kind='error') {
  shiftState.message = message;
  shiftState.kind = kind;
}

async function loadView() {
  [shiftState.shifts, shiftState.programs] = await Promise.all([listShifts(), listPrograms()]);
  const current = shiftState.detail?.id ?? shiftState.shifts[0]?.id;
  shiftState.detail = current ? await shiftDetail(current) : null;
}

function quotaBar(detail) {
  const used = Number(detail.reserved_m3);
  const quota = Number(detail.quota_m3);
  const pct = Math.min(100, 100 * used / Math.max(quota, 0.001));
  return `<div class="quota-card"><div class="quota-head"><b>${esc(detail.name)}</b>
      <span>${date(detail.started_at)} – ${date(detail.ended_at)}</span></div>
    <div class="quota-track" role="img" aria-label="已预留占额度比例"><i style="width:${pct.toFixed(2)}%"></i></div>
    <div class="quota-numbers"><span>额度 ${amount(detail.quota_m3)} m³</span>
      <span>已预留 ${amount(detail.reserved_m3)} m³</span><strong>余量 ${amount(detail.remaining_m3)} m³</strong></div></div>`;
}

function reservations(detail) {
  if (!detail.reservations.length) return empty('该班次尚未排上窑次。');
  const operator = state.session.user.role === 'operator';
  return table(['窑次', '窑炉 / 配方', '装载量 kg', '预留气量 m³', '估算口径', operator ? '退回占额' : ''],
    detail.reservations.map(r => [
      `<b>${esc(r.batch_code)}</b>`,
      `${esc(r.kiln)}<br><small>${esc(r.recipe)} V${r.baseline_version} · ${r.planned_minutes} 分钟</small>`,
      amount(r.batch_kg),
      `<strong>${amount(r.reserved_m3)}</strong>`,
      `计划装载与温程<br><small>${esc(r.estimate_snapshot.model_revision)}</small>`,
      operator ? `<form data-action="shift-release" data-shift="${r.shift_id}" data-code="${esc(r.batch_code)}">
        <button type="submit" class="secondary">退回</button></form>` : '']));
}

function estimateEvidence() {
  const plan = shiftState.lastPlan;
  if (!plan) return '';
  const rows = Object.entries(plan.estimates).map(([code, snap]) => {
    const placed = plan.placed_codes.includes(code);
    return [`<b>${esc(code)}</b> ${badge(placed ? 'ready' : 'failed', placed ? '排上' : '落选')}`,
      amount(snap.cycle.batch_kg), amount(snap.expected_m3),
      Object.entries(snap.features).map(([key, value]) => `${esc(key)} ${amount(value)}`).join('<br>')];
  });
  return `<details class="board" open><summary>本次排单的回归估算与组合依据（请求键 ${esc(plan.request_key || '')}）</summary>
    ${table(['窑次', '装载 kg', '估算 m³', '回归特征'], rows)}
    <p class="digest">合计排上 ${plan.placed_codes.length} 个窑次 · ${amount(plan.placed_total_m3)} m³ ·
    ${amount(plan.placed_total_kg)} kg。落选：${plan.rejected.map(r => esc(r.code)).join('、') || '无'}</p></details>`;
}

function shiftForms() {
  if (state.session.user.role !== 'operator') return '';
  return `<div class="shift-forms"><details class="board"><summary>开设限气班次</summary>
    <form data-action="shift-open" class="form-grid">
      ${field('班次名称', 'name', 'placeholder="1122 早班限气" maxlength="80"')}
      ${field('燃气额度 m³', 'quota_m3', 'type="number" min="0.001" step="0.001"')}
      ${field('开始', 'started_at', 'type="datetime-local"')}${field('结束', 'ended_at', 'type="datetime-local"')}
      <button>登记班次额度</button></form></details>
    <details class="board"><summary>登记配方计划温程</summary>
    <form data-action="program-open" class="form-grid">
      ${field('配方', 'recipe', 'placeholder="釉面砖 Y17" maxlength="80"')}
      ${field('配方版本', 'version', 'type="number" min="1" value="3"')}
      ${field('升温峰值 °C', 'ramp_peak_c', 'type="number" min="20" max="1500" step="0.01" value="1050"')}
      ${field('保温峰值 °C', 'soak_peak_c', 'type="number" min="20" max="1500" step="0.01" value="1180"')}
      ${field('冷却峰值 °C', 'cool_peak_c', 'type="number" min="20" max="1500" step="0.01" value="1000"')}
      ${field('升温时长占比', 'ramp_share', 'type="number" min="0.05" max="0.9" step="0.0001" value="0.375"')}
      ${field('保温时长占比', 'soak_share', 'type="number" min="0.05" max="0.9" step="0.0001" value="0.25"')}
      <button>保存计划温程</button></form>
    <p class="muted">冷却段占比自动取剩余比例；估算按计划节拍拆分三段时长后做回归。</p></details></div>`;
}

function planPanel(detail) {
  if (state.session.user.role !== 'operator') {
    return `<section class="board"><h3>排单组合</h3>${empty('仅烧成班长可发起限气排单。')}</section>`;
  }
  return `<section class="board"><h3>在剩余额度内重算最优组合</h3>
    <p class="muted">每次确认使用唯一请求键，网络重试不会重复扣气；排单失败自动退回占额。余量变化后再次确认会按最新余量重算。</p>
    <form data-action="shift-plan" data-shift="${detail.id}" class="plan-action">
      <button type="submit">按计划装载与温程排单</button></form>
    ${shiftState.message ? `<p class="plan-message" data-kind="${shiftState.kind}">${esc(shiftState.message)}</p>` : ''}
    ${estimateEvidence()}</section>`;
}

export async function shift() {
  try {
    await loadView();
  } catch (error) {
    return empty(error.message);
  }
  if (!shiftState.shifts.length) {
    return `<section class="board"><h3>限气班次</h3>${empty('还没有限气班次，请先开设班次并登记燃气额度。')}</section>${shiftForms()}`;
  }
  const detail = shiftState.detail;
  const rail = `<aside class="batch-rail shift-rail"><h2>限气班次</h2><div>${shiftState.shifts.map(s => `
    <button class="batch-pick ${detail?.id === s.id ? 'selected' : ''}" data-shift-pick="${s.id}" aria-pressed="${detail?.id === s.id}">
      <strong>${esc(s.name)}</strong>${badge(s.reserved_m3 >= s.quota_m3 ? 'confirmed' : 'recording',
        s.reserved_m3 >= s.quota_m3 ? '额度用尽' : '有余量')}
      <span>${date(s.started_at).slice(5)} · 已排 ${s.reserved_batches} 窑次</span></button>`).join('')}</div></aside>`;
  return `<div class="workspace">${rail}<div class="shift-desk">
    <section class="board">${quotaBar(detail)}<h3 style="margin-top:1rem">已排窑次与预留气量</h3>${reservations(detail)}</section>
    ${planPanel(detail)}
    <section class="board"><h3>可用计划温程（${shiftState.programs.length}）</h3>
    ${shiftState.programs.length ? table(['配方', '版本', '三段峰值 °C', '升温/保温/冷却占比'],
      shiftState.programs.map(p => [esc(p.recipe), `V${p.version}`,
        `${amount(p.ramp_peak_c)} / ${amount(p.soak_peak_c)} / ${amount(p.cool_peak_c)}`,
        `${p.ramp_share} / ${p.soak_share} / ${(1 - Number(p.ramp_share) - Number(p.soak_share)).toFixed(4)}`]))
      : empty('尚无计划温程，班长先登记后才能估算排单。')}</section>
    ${shiftForms()}</div></div>`;
}

export async function handleShiftAction(action, form, dataset) {
  shiftState.message = '';
  if (action === 'shift-open') {
    await openShift(form);
    shiftState.message = '限气班次已开设';
  } else if (action === 'program-open') {
    await openProgram(form);
    shiftState.message = '计划温程已保存';
  } else if (action === 'shift-plan') {
    const requestKey = `REQ-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 8).toUpperCase()}`;
    const result = await planShift(Number(dataset.shift), {request_key: requestKey});
    shiftState.lastPlan = {...result, request_key: requestKey};
    shiftState.kind = 'success';
    shiftState.message = `已排上 ${result.placed_codes.length} 个窑次，预留 ${amount(result.placed_total_m3)} m³`;
  } else if (action === 'shift-release') {
    await releaseReservation(Number(dataset.shift), dataset.code);
    shiftState.kind = 'success';
    shiftState.message = `窑次 ${dataset.code} 的占额已退回`;
  }
}

export function selectShift(shiftId) {
  shiftState.message = '';
  shiftState.lastPlan = null;
  return shiftDetail(shiftId).then(detail => { shiftState.detail = detail; });
}
