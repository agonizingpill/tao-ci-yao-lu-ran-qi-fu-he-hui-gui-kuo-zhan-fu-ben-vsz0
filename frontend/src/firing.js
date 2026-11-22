import {phase, state} from './state.js';
import {amount, clock, date, empty, esc, field, heatBand, localInput, table, ticket} from './ui.js';

function intake(batch) {
  const canRecord = state.session.user.role === 'operator' && !batch.runs.length;
  const unused = Object.keys(phase).filter(key => !batch.curves.some(curve => curve.phase === key));
  const start = localInput(batch.opened_at);
  const end = localInput(batch.closed_at);
  return `<section class="board"><h3>温区与燃气抄表</h3>${heatBand(batch)}
    <div class="measurement"><section><h4>温区记录 <span>${batch.curves.length} / 3</span></h4>
    ${batch.curves.length ? table(['阶段 / 时段','峰值','来源'],batch.curves.map(c => [
      `<b>${phase[c.phase]}</b><br><small>${clock(c.started_at)}–${clock(c.ended_at)}</small>`, `${amount(c.peak_c)} °C`,
      `${esc(c.source_file)}${canRecord ? `<details class="withdraw"><summary>撤销</summary><form data-action="curve/${c.phase}/withdraw">${field('撤销原因','description','minlength="4" maxlength="400"')}<button class="secondary">确认撤销</button></form></details>` : ''}`
    ])) : empty('依序登记升温、保温和冷却三段。')}
    ${canRecord && unused.length ? `<details class="edit" ${unused.length === 1 ? 'open' : ''}><summary>补登温区</summary>
     <form data-action="curve" class="form-grid"><label>阶段<select name="phase">${unused.map(key => `<option value="${key}">${phase[key]}</option>`).join('')}</select></label>
      ${field('峰值 °C','peak_c','type="number" min="20" max="1500" step="0.01"')}
      ${field('开始','started_at',`type="datetime-local" min="${start}" max="${end}"`)}
      ${field('结束','ended_at',`type="datetime-local" min="${start}" max="${end}"`)}
      ${field('热电偶来源文件','source_file',`value="${esc(batch.code)}-TC.csv" maxlength="80"`)}<button>保存温区</button></form></details>` : ''}
    </section><section><h4>累计表读数 <span>${batch.meters.length} 条</span></h4>
    ${batch.meters.length ? table(['时间','累计 m³','表号 / 来源'], batch.meters.map(m => [clock(m.sampled_at), amount(m.reading_m3),
      `${esc(m.meter_serial)}<br><small>${esc(m.source_file)}</small>`])) : empty('登记进窑、出窑及间隔不超过三小时的累计读数。')}
    ${canRecord ? `<details class="edit" open><summary>补登抄表</summary><form data-action="meter" class="form-grid">
      ${field('抄表时间','sampled_at',`type="datetime-local" min="${start}" max="${end}"`)}
      ${field('累计读数 m³','reading_m3','type="number" min="0" step="0.001"')}
      ${field('仪表编号','meter_serial',`value="${esc(batch.meters[0]?.meter_serial || '')}" maxlength="80"`)}
      ${field('燃气来源文件','source_file',`value="${esc(batch.code)}-GAS.csv" maxlength="80"`)}<button>保存抄表</button></form></details>` : ''}
    </section></div></section>`;
}

function schedule() {
  return `<details class="board schedule"><summary>安排新窑次</summary><form data-action="schedule" class="form-grid schedule-form">
     ${field('批次号','code','pattern="[A-Z0-9][A-Z0-9\\-]{1,30}" placeholder="K2-1122-D"')}
     ${field('窑炉','kiln','maxlength="80" placeholder="K2 辊道窑"')}
     ${field('基础配方','recipe','maxlength="80" placeholder="釉面砖 Y17"')}
     ${field('版本','baseline_version','type="number" min="1" max="10000" value="3"')}
     ${field('装载量 kg','batch_kg','type="number" min="0.01" max="100000" step="0.01"')}
     ${field('计划节拍 分钟','planned_minutes','type="number" min="30" max="1440" value="480"')}
     ${field('进窑','opened_at','type="datetime-local"')}${field('出窑','closed_at','type="datetime-local"')}<button>登记排程</button>
    </form></details>`;
}

export function firing(batch) {
  return `${state.session.user.role === 'operator' ? schedule() : ''}${batch ? ticket(batch) + intake(batch) : empty('当前没有烧成批次。')}`;
}

export function readingTrace(run) {
  return `<details class="edit"><summary>追溯试算 #${run.id} 的原始读数</summary><p class="digest">输入 SHA-256 <code>${esc(run.input_hash)}</code></p>
    ${table(['温区','起止','峰值','记录来源'],run.input_snapshot.curve.map(c => [phase[c.phase],`${date(c.started_at)} – ${clock(c.ended_at)}`,amount(c.peak_c),esc(c.source_file)]))}
    ${table(['抄表时点','表号','累计 m³','记录来源'],run.input_snapshot.meter.map(m => [date(m.sampled_at),esc(m.meter_serial),amount(m.reading_m3),esc(m.source_file)]))}</details>`;
}
