/* Read-only task preview. No execution or authorization endpoint exists here. */
"use strict";

const SKILLS = {stand: "站立", walk_forward: "前进", turn: "转向", stop: "停止"};
const COMPILER_TEXT = {
  SUCCESS: "受控中文已解析为明确的任务步骤。编译成功不代表获准执行。",
  AMBIGUOUS: "指令仍有歧义，请明确动作、距离、角度或时长后重新提交。",
  UNSUPPORTED: "该表达或动作不在当前受控中文能力范围内。",
  MALFORMED: "无法形成有效任务，请使用明确的动作、数值和顺序。"
};
const REASONS = {
  LANGUAGE_RUNTIME_BLOCKED: "Language Runtime 尚未获准连接执行入口。",
  D011_BLOCKED: "D011 门禁仍为 BLOCKED。",
  OWNER_AUTHORIZATION_ABSENT: "未提供本次任务的独立 Owner 执行授权。",
  LIVE_STATE_NOT_OBSERVED: "尚未观察并评估当前机器人物理状态。"
};

function text(value) { return value === null || value === undefined ? "—" : String(value); }
function stepTitle(step) {
  const p = step.parameters || {};
  const label = SKILLS[step.skill] || text(step.skill);
  if (p.distance_m !== undefined) return `${label} ${p.distance_m} 米`;
  if (p.angle_deg !== undefined) return `${label} ${p.angle_deg}°`;
  if (p.duration_s !== undefined) return `${label} ${p.duration_s} 秒`;
  return label;
}
function reasonText(code) { return REASONS[code] ? `${REASONS[code]} (${code})` : text(code); }
function requestPath(id) { return `/api/requests/${encodeURIComponent(id)}`; }

function createState() {
  return {
    revision: 0, contract: null,
    edit() { this.revision += 1; this.contract = null; },
    begin() { this.revision += 1; return this.revision; },
    accept(revision, contract) {
      if (revision !== this.revision) return false;
      this.contract = contract;
      return true;
    }
  };
}

function boot(doc = document, fetcher = fetch) {
  const $ = (id) => doc.getElementById(id);
  const state = createState();
  const input = $("instruction");
  let pending = false;
  function node(tag, content, className) {
    const e = doc.createElement(tag);
    if (content !== undefined) e.textContent = text(content);
    if (className) e.className = className;
    return e;
  }
  function busy(value) {
    pending = value;
    $("submit-request").disabled = value;
    doc.querySelector(".result").setAttribute("aria-busy", String(value));
  }
  function reset(message = "等待一条新指令") {
    $("contract-content").hidden = true;
    $("empty-state").hidden = false;
    $("result-subtitle").textContent = message;
    $("result-tag").textContent = "未生成";
    $("result-tag").className = "tag neutral";
    $("binding-check-result").textContent = "";
    $("error").hidden = true;
    $("download-contract").removeAttribute("href");
    $("physics-count").textContent = "0";
    $("policy-count").textContent = "0";
    $("execution-status").textContent = "NOT_EXECUTED";
  }
  function edited() {
    state.edit();
    $("character-count").textContent = `${input.value.length} / 512`;
    reset("指令已编辑，请重新生成任务契约");
  }
  input.addEventListener("input", edited);
  doc.querySelectorAll("[data-example]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.example;
      edited();
      input.focus();
    });
  });
  function showError(error) {
    $("error").textContent = error.message || "请求失败，请检查本地服务。";
    $("error").hidden = false;
  }
  async function jsonRequest(url, payload) {
    const response = await fetcher(url, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload), cache: "no-store"
    });
    let body;
    try { body = await response.json(); } catch (_) { throw new Error(`服务未返回有效 JSON（HTTP ${response.status}）。`); }
    if (!response.ok) throw new Error(`请求被拒绝（HTTP ${response.status}）：${text(body.error_message || body.error || body.reason || "请检查输入或来源绑定")}`);
    return body;
  }
  function render(contract) {
    $("empty-state").hidden = true;
    $("contract-content").hidden = false;
    $("result-subtitle").textContent = `请求 ${text(contract.request_id)}`;
    $("result-tag").textContent = contract.authorization?.decision === "DENY" ? "执行被拒绝" : text(contract.authorization?.decision);
    $("result-tag").className = "tag blocked";
    $("submitted-text").textContent = contract.source?.text || "";
    const compiler = contract.compiler || {};
    const capability = contract.capability || {};
    const auth = contract.authorization || {};
    const execution = contract.execution || {};
    const stages = [
      ["语言理解", compiler.status, compiler.status === "SUCCESS"],
      ["能力检查", capability.status || "NOT_EVALUATED", capability.status === "GROUNDED"],
      ["请求绑定", contract.binding?.request_sha256 ? "BOUND" : "NOT_BOUND", Boolean(contract.binding?.request_sha256)],
      ["执行授权", auth.decision || "UNKNOWN", false]
    ];
    $("pipeline").replaceChildren(...stages.map(([label, status, good]) => {
      const li = node("li", undefined, good ? "good" : "warn");
      li.append(node("strong", label), node("small", status));
      return li;
    }));
    $("compiler-message").hidden = false;
    $("compiler-message").textContent = compiler.error_message || COMPILER_TEXT[compiler.status] || `语言处理状态：${text(compiler.status)}`;
    const steps = contract.mission?.steps || [];
    const checks = capability.results || [];
    $("mission-steps").replaceChildren(...steps.map((step, index) => {
      const check = checks.find((item) => item.step_id === step.id) || {};
      const article = node("article", undefined, "mission-step");
      const top = node("div", undefined, "mission-top");
      top.append(node("span", `${String(index + 1).padStart(2, "0")}  ${stepTitle(step)}`, "mission-title"), node("span", check.status || "NOT_EVALUATED", "small mono"));
      article.append(top);
      if (check.reason) article.append(node("div", check.reason, "mission-detail"));
      article.append(node("div", `步骤 ${text(step.id)} · 模式 ${text(check.execution_mode)} · 风险 ${text(check.risk)}`, "mission-detail"));
      if (check.evidence_ref) article.append(node("div", `能力依据：${typeof check.evidence_ref === "string" ? check.evidence_ref : JSON.stringify(check.evidence_ref)}`, "mission-detail mono"));
      return article;
    }));
    if (!steps.length) $("mission-steps").append(node("p", "未生成可审查的 Mission。请先修改指令。", "muted small"));
    $("authorization-summary").textContent = auth.decision === "DENY"
      ? "这条指令尚不能进入真实执行。界面操作与任务预览不会改变执行授权。"
      : `服务器返回授权判断：${text(auth.decision)}。本界面没有执行功能。`;
    $("authorization-reasons").replaceChildren(...(auth.reasons || []).map((code) => node("li", reasonText(code))));
    $("gate-labels").replaceChildren(...[
      ["Language Runtime", auth.language_runtime], ["D011", auth.d011],
      ["Owner", auth.owner_authorization], ["实时状态", auth.state_assessment]
    ].map(([label, value]) => node("span", `${label}: ${text(value)}`)));
    $("physics-count").textContent = text(execution.physics_steps);
    $("policy-count").textContent = text(execution.policy_calls);
    $("execution-status").textContent = text(execution.status);
    $("download-contract").href = requestPath(contract.request_id);
    $("check-binding").disabled = false;
    $("binding-check-result").textContent = "";
    $("identity").replaceChildren(...[
      ["请求 ID", contract.request_id], ["创建时间", contract.created_at],
      ["指令 SHA256", contract.source?.sha256], ["Mission SHA256", contract.binding?.mission_sha256],
      ["请求 SHA256", contract.binding?.request_sha256], ["契约 SHA256", contract.contract_sha256]
    ].flatMap(([key, value]) => [node("dt", key), node("dd", value)]));
    $("contract-json").textContent = JSON.stringify(contract, null, 2);
  }
  $("request-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (pending || !input.value.trim()) return;
    const revision = state.begin();
    const submitted = input.value;
    reset("正在理解指令与检查任务契约…");
    busy(true);
    try {
      const contract = await jsonRequest("/api/requests", {text: submitted});
      if (state.accept(revision, contract)) render(contract);
    } catch (error) { if (state.revision === revision) showError(error); }
    finally { busy(false); }
  });
  $("check-binding").addEventListener("click", async () => {
    const contract = state.contract;
    if (!contract) return;
    const revision = state.revision;
    $("check-binding").disabled = true;
    $("binding-check-result").textContent = "正在核验已保存的任务契约…";
    try {
      const result = await jsonRequest(`${requestPath(contract.request_id)}/check`, {contract_sha256: contract.contract_sha256});
      if (state.revision !== revision) return;
      $("binding-check-result").textContent = `绑定核验：${result.binding_valid === true ? "一致" : "不一致"} · 授权判断：${text(result.decision)}。核验不授予执行权限。`;
    } catch (error) {
      if (state.revision === revision) $("binding-check-result").textContent = `绑定核验失败：${error.message}`;
    } finally { if (state.revision === revision) $("check-binding").disabled = false; }
  });
  return state;
}

if (typeof module !== "undefined" && module.exports) module.exports = {createState, stepTitle, requestPath, reasonText, boot};
if (typeof document !== "undefined") boot();
