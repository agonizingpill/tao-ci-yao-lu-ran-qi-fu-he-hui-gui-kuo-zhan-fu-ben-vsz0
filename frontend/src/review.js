import {recipeStatus, state} from './state.js';
import {badge, date, empty, esc, field, table, ticket} from './ui.js';
import {readingTrace} from './firing.js';

const events = {firing_scheduled:'登记排程', curve_recorded:'登记温区', curve_withdrawn:'撤销温区', meter_recorded:'登记抄表',
  load_queued:'提交试算', load_ready:'试算完成', load_failed:'试算失败', load_requeued:'重试试算', recipe_proposed:'提报配方',
  recipe_approved:'批准配方', recipe_rejected:'退回配方', cycle_proposed:'提出节拍方案', cycle_confirmed:'确认周期', rule_blocked:'规则拦截'};

function recipeDesk(batch, operator, supervisor, closed) {
  return `<section class="board"><h3>配方变更</h3>${batch.recipes.map(change => `<article class="recipe-line"><div><b>V${change.version}</b> ${badge(change.status,recipeStatus[change.status])}</div>
    <p>${esc(change.description)}</p><small>提报 ${esc(change.submitted_by)}${change.reviewed_by ? ` · 审批 ${esc(change.reviewed_by)} · ${esc(change.note)}` : ''}</small>
    ${supervisor && !closed && change.status === 'pending' ? `<form data-action="recipes/${change.id}/decision" class="form-grid">
      <label>决定<select name="decision"><option value="approved">批准</option><option value="rejected">退回</option></select></label>
      ${field('审批依据','note','minlength="4" maxlength="400"')}<button>登记审批</button></form>` : ''}</article>`).join('') || empty('当前采用基础配方，可提报新的材料或釉料调整。')}
    ${operator && !closed && batch.recipes[0]?.status !== 'pending' ? `<form data-action="recipes" class="form-grid recipe-form">${field('变更说明','description','minlength="4" maxlength="400"')}<button>提报配方</button></form>` : ''}</section>`;
}

function confirmationDesk(batch, run, operator, supervisor, closed) {
  const plan = batch.review;
  return `<section class="board"><h3>下一周期节拍</h3>${plan ? `<div class="plan"><div><strong>${plan.next_minutes}</strong> 分钟 <span>原节拍 ${batch.planned_minutes} 分钟</span></div>
      <p>${esc(plan.rationale)}</p><small>${plan.attribution === 'recipe' ? '关联获批配方' : '只记录观测差异'} · 试算 #${plan.run_id} · 提报 ${esc(plan.proposed_by)}</small>
      ${plan.confirmed_by ? `<p class="confirmed-by">${esc(plan.confirmed_by)} 已确认 · ${date(plan.confirmed_at)}</p>` : ''}</div>` : empty('试算完成后，烧成班长可提出下一周期节拍。')}
    ${operator && run && !closed ? `<form data-action="review" class="review-form">
      <input type="hidden" name="run_id" value="${run.id}"><div class="form-grid">
      ${field('新节拍 分钟','next_minutes',`type="number" min="30" max="1440" value="${plan?.next_minutes || batch.planned_minutes}"`)}
      <label>记录口径<select name="attribution"><option value="observed">只记录观测差异</option><option value="recipe" ${plan?.attribution === 'recipe' ? 'selected' : ''}>关联获批配方</option></select></label></div>
      ${field('复核依据','rationale',`value="${esc(plan?.rationale || '')}" minlength="4" maxlength="400"`)}<button>提交节拍方案</button></form>` : ''}
    ${supervisor && plan && !closed ? '<form data-action="review/confirm"><button>确认周期</button></form>' : ''}
    ${run ? readingTrace(run) : ''}</section>`;
}

export function review(batch) {
  if (!batch) return empty('先登记需要复核的窑次。');
  const {role} = state.session.user;
  const run = batch.runs.find(item => item.id === batch.review?.run_id) || batch.runs.find(item => item.status === 'ready');
  return `${ticket(batch)}<div class="review-grid">${recipeDesk(batch, role === 'operator', role === 'supervisor', batch.status === 'confirmed')}
    ${confirmationDesk(batch, run, role === 'operator', role === 'supervisor', batch.status === 'confirmed')}</div>
    <details class="board audit"><summary>交接轨迹 · ${batch.audit.length} 条</summary>
    ${batch.audit.length ? table(['时间','岗位工号','动作','依据'],batch.audit.map(entry => [date(entry.happened_at), esc(entry.actor),
      events[entry.event] || esc(entry.event), esc(entry.detail.reason || entry.detail.note || entry.detail.source || entry.detail.rationale || entry.detail.run_id || '')])) : empty('业务操作与规则拦截会自动记入台账。')}</details>`;
}
