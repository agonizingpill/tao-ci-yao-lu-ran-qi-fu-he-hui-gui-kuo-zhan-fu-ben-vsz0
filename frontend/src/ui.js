import {batchStatus, phase, state} from './state.js';

export const esc = (value='') => String(value ?? '').replace(/[&<>"']/g, symbol => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[symbol]));
const displayTime = new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai', dateStyle:'short', timeStyle:'short'});
export const date = (value) => displayTime.format(new Date(value));
export const clock = (value) => date(value).slice(-5);
export const localInput = (value) => date(value).replace(' ', 'T');
export const amount = (value) => Number(value).toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 3});
export const badge = (value, text=batchStatus[value]) => `<span class="status ${esc(value)}">${esc(text)}</span>`;
export const empty = (text) => `<p class="empty">${esc(text)}</p>`;
export const field = (label, name, attrs='') => `<label>${label}<input name="${name}" ${attrs} required></label>`;

export function heading(title, hint) {
  return `<div class="page-heading"><h1>${title}</h1><p>${hint}</p></div>`;
}

export function batchRail() {
  return `<aside class="batch-rail"><h2>窑次</h2><div>${state.batches.map(batch => `
    <button class="batch-pick ${state.code === batch.code ? 'selected' : ''}" data-batch="${esc(batch.code)}" aria-pressed="${state.code === batch.code}">
      <strong>${esc(batch.code)}</strong>${badge(batch.status)}<span>${esc(batch.kiln)} · ${date(batch.opened_at).slice(5)}</span>
    </button>`).join('') || empty('登记烧成批次以建立台账。')}</div></aside>`;
}

export function ticket(batch) {
  return `<header class="ticket"><div><p>${esc(batch.kiln)} / ${esc(batch.recipe)} V${batch.baseline_version}</p><h2>${esc(batch.code)}</h2></div>
    <div class="ticket-terms"><span>${date(batch.opened_at)} – ${clock(batch.closed_at)}</span><span>${amount(batch.batch_kg)} kg · 原节拍 ${batch.planned_minutes} 分钟</span></div>${badge(batch.status)}</header>`;
}

export function heatBand(batch) {
  const start = +new Date(batch.opened_at), length = +new Date(batch.closed_at) - start;
  return `<div class="heat-band" role="img" aria-label="进窑至出窑的温区记录，空白表示阶段缺失">
      ${batch.curves.map(c => `<div class="heat-segment ${esc(c.phase)}" style="left:${100*(+new Date(c.started_at)-start)/length}%;width:${100*(+new Date(c.ended_at)-+new Date(c.started_at))/length}%">
      <span>${phase[c.phase]}</span><strong>${Math.round(c.peak_c)}<small> °C</small></strong></div>`).join('')}</div>
    <div class="time-scale"><span>${clock(batch.opened_at)} 进窑</span><span>${clock(batch.closed_at)} 出窑</span></div>`;
}

export function table(headers, rows) {
  return `<div class="table-scroll"><table><thead><tr>${headers.map(h => `<th scope="col">${h}</th>`).join('')}</tr></thead>
  <tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
