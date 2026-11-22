import {state} from './state.js';
import {amount, badge, clock, empty, esc, table, ticket} from './ui.js';
import {readingTrace} from './firing.js';

const showLoad = (result) => {
  const span = Math.max(result.expected_m3, result.actual_m3, 1) * 1.12;
  return `<figure class="gas-comparison"><figcaption>本周期燃气量 <span>m³</span></figcaption>
    <div class="gas-row"><span>模型参考</span><i style="width:${100 * Math.max(0, result.expected_m3) / span}%"></i><b>${amount(result.expected_m3)}</b></div>
    <div class="gas-row actual"><span>表计实测</span><i style="width:${100 * result.actual_m3 / span}%"></i><b>${amount(result.actual_m3)}</b></div>
    <div class="delta"><span>实测 − 参考</span><b>${result.delta_m3 > 0 ? '+' : ''}${amount(result.delta_m3)} m³</b></div></figure>`;
};

export function load(batch) {
  if (!batch) return empty('先在烧成批次登记窑次。');
  const run = batch.runs[0];
  const operator = state.session.user.role === 'operator';
  const supervisor = state.session.user.role === 'supervisor';
  let body;
  if (run?.status === 'ready') {
    const r = run.result;
    body = `<div class="analysis-grid">${showLoad(r)}<section class="model"><h4>弹性网络校验</h4><dl>
      <dt>留出集 MAE</dt><dd>${amount(r.mae_m3)} m³</dd><dt>训练 / 留出</dt><dd>${r.train_count} / ${r.holdout_count}</dd>
      <dt>交叉验证</dt><dd>${r.cv_folds} 折</dd><dt>α / L1 比例</dt><dd>${r.alpha.toFixed(5)} / ${r.l1_ratio}</dd>
      <dt>随机种子</dt><dd>${r.seed}</dd></dl><p>MAE 来自合成历史批次。配方版本与节拍签核在周期复核中登记。</p></section></div>
      <details class="edit"><summary>模型特征与缩放后系数</summary>${table(['特征','本次输入','缩放后系数'],
        Object.entries(r.features).map(([key,value]) => [esc(key), amount(value), amount(r.coefs_scaled[key])]))}
        <p class="digest">训练集 SHA-256 <code>${esc(r.training_sha256)}</code></p></details>${readingTrace(run)}`;
  } else if (run?.status === 'queued') {
    body = `<p class="empty">试算 #${run.id} 已排队，页面会更新结果。</p><button type="button" data-refresh class="secondary">刷新试算状态</button>`;
  } else if (run?.status === 'failed') {
    body = `<p class="empty">试算 #${run.id} 失败（${esc(run.error)}）。主管可按原快照重试。</p>${supervisor ? `<form data-action="runs/${run.id}/retry"><button>按原快照重试</button></form>` : ''}${readingTrace(run)}`;
  } else {
    body = `<div class="coverage"><div><b>温区</b><span>${batch.curves.length} / 3 阶段</span><p>升温、保温、冷却必须连续覆盖烧成周期。</p></div>
      <div><b>累计表</b><span>${batch.meters.length} 条读数</span><p>进窑、出窑必须有记录，间隔不得超过三小时。</p></div></div>
      <p class="muted">待校验周期 ${clock(batch.opened_at)}–${clock(batch.closed_at)}。提交后冻结原始台账。</p>
      ${operator ? '<form data-action="runs"><button>校验并提交试算</button></form>' : ''}`;
  }
  return `${ticket(batch)}<section class="board"><div class="section-title"><h3>周期负荷参考</h3>${run ? badge(run.status, {ready:'试算完成',failed:'试算失败',queued:'队列等待'}[run.status]) : ''}</div>${body}</section>`;
}
