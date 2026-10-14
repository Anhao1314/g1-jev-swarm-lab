'use strict';
const $ = id => document.getElementById(id);
const labels = {stand: '站立', walk_forward: '前进', stop: '停止'};
const number = (value, digits=3) => Number.isFinite(value) ? value.toFixed(digits) : '未记录';
async function load() {
  $('result').hidden = true;
  $('video').pause(); $('video').removeAttribute('src'); $('video').load();
  $('error').textContent = '正在核验封存证据…';
  try {
    const response = await fetch('/api/result', {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.reason || data.error);
    $('instruction').textContent = data.instruction;
    $('verdict').textContent = data.result.mission_success === true ? '这次任务已完成' : '这次任务未完整成功';
    $('counts').textContent = `${data.physics_steps} 个真实物理步 · ${data.policy_calls} 次原策略推理 · ${data.media.frames} 帧已封存回放`;
    $('nodes').replaceChildren();
    for (const node of data.result.nodes) {
      const m = node.metrics || {};
      const card = document.createElement('article');
      const title = document.createElement('h3');
      title.textContent = `${labels[m.skill] || m.skill || node.node_id} · ${m.skill_status || '未记录'}`;
      const detail = document.createElement('p');
      detail.textContent = `${number(m.simulation_time_s, 2)} s · 物理 ${m.physical_success === true ? '通过' : m.physical_success === false ? '失败' : '未记录'} · 末速度 ${number(m.final_speed_mps)} m/s`;
      card.append(title, detail);
      if (m.skill === 'walk_forward') {
        const local = document.createElement('p');
        local.textContent = `局部前进 ${number(m.final_forward_progress_m, 4)} m；横向误差 ${number(m.final_lateral_drift_m, 4)} m；航向误差 ${number(m.final_heading_error_deg)}°`;
        card.append(local);
      }
      $('nodes').append(card);
    }
    const stop = data.result.nodes.find(n => n.metrics?.skill === 'stop')?.metrics || {};
    $('stop').textContent = `Stop 末瞬时速度 ${number(stop.final_speed_mps, 4)} m/s；该阶段累计路径 ${number(stop.path_length_m, 4)} m。`;
    $('authority').textContent = `授权已消费。来源保证：${data.authority.assurance}。历史账号来源不等于生产身份认证；本页不验证新授权。`;
    const comment = new URL(data.authority.comment_url);
    if (comment.origin !== 'https://github.com') throw new Error('授权来源 URL 不符合预期');
    $('comment').href = comment.href;
    $('provenance').textContent = JSON.stringify({request_id: data.request_id, run_id: data.run_id, ...data.provenance, video_sha256: data.media.sha256, language_runtime: data.authority.language_runtime, d011: data.authority.d011}, null, 2);
    $('video').src = data.media.url;
    $('result').hidden = false;
    $('error').textContent = '来源与原始记录校验通过 · 当前仅展示已封存结果';
  } catch (error) {
    $('error').textContent = '证据校验失败，停止展示：' + error.message;
  }
}
$('refresh').addEventListener('click', load);
$('video').addEventListener('error', () => { $('error').textContent = '回放读取失败，请重新核验证据；未触发新执行。'; });
load();
