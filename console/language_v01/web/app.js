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
function preparationPayload(contract) { return {contract_sha256: contract.contract_sha256}; }
function executionView(snapshot, contract, preparation) {
  if (!snapshot || snapshot.request_id !== contract?.request_id ||
      !preparation?.preparation_sha256 || snapshot.preparation_sha256 !== preparation.preparation_sha256) {
    throw new Error("执行响应与当前请求或准备清单不匹配。");
  }
  const labels = {
    AWAITING_OWNER: "等待本次 Owner 授权 · 尚无执行画面",
    RUNNING: "本次采集正在运行 · 尚未得到最终任务结果",
    REFUSED_FAILED_OR_PARTIAL: "本次入口拒绝、失败或未完成 · 请查看原始结果",
    CAPTURE_FINISHED: "本次采集已结束 · 任务是否成功以原始结果为准",
    SYNTHETIC_TEST_ONLY: "非物理测试替身回执 · 没有机器人运动画面"
  };
  if (!Object.hasOwn(labels, snapshot.status)) throw new Error("未知执行状态，无法确认本次执行。");
  if (![null, "NEW_MUJOCO_CAPTURE", "SYNTHETIC_NONPHYSICAL_BACKEND"].includes(snapshot.kind)) {
    throw new Error("未知采集来源，无法确认本次执行。");
  }
  if (snapshot.status === "AWAITING_OWNER" && (snapshot.run_id !== null || snapshot.kind !== null || snapshot.media !== null)) {
    throw new Error("等待授权的响应含有不一致的执行信息。");
  }
  const count = (value) => Number.isSafeInteger(value) && value >= 0 ? String(value) : "UNKNOWN";
  let media = null;
  if (snapshot.media !== null && snapshot.media !== undefined) {
    if (snapshot.kind !== "NEW_MUJOCO_CAPTURE" || !snapshot.run_id ||
        snapshot.media.kind !== "NEW_RUN_STATE_PLAYBACK" ||
        snapshot.media.url !== `${requestPath(contract.request_id)}/media` ||
        !/^[a-f0-9]{64}$/.test(snapshot.media.sha256 || "") ||
        !/^[a-f0-9]{64}$/.test(snapshot.media.source_pose_sha256 || "")) {
      throw new Error("运动画面缺少本次真实采集绑定，拒绝展示。");
    }
    media = snapshot.media;
  }
  const synthetic = snapshot.kind === "SYNTHETIC_NONPHYSICAL_BACKEND";
  return {
    status: snapshot.status, title: synthetic ? "非物理测试替身回执 · 没有机器人运动画面" : labels[snapshot.status],
    physics: count(snapshot.physics_steps), policy: count(snapshot.policy_calls), media,
    runId: snapshot.run_id || "尚未创建", result: snapshot.result ?? null
  };
}

function createState() {
  return {
    revision: 0, contract: null, preparation: null, execution: null,
    edit() { this.revision += 1; this.contract = null; this.preparation = null; this.execution = null; },
    begin() { this.revision += 1; this.contract = null; this.preparation = null; this.execution = null; return this.revision; },
    accept(revision, contract) {
      if (revision !== this.revision) return false;
      this.contract = contract;
      return true;
    },
    acceptPreparation(revision, contractHash, preparation) {
      if (revision !== this.revision || !this.contract || this.contract.contract_sha256 !== contractHash) return false;
      this.preparation = preparation;
      this.execution = null;
      return true;
    },
    acceptExecution(revision, snapshot) {
      if (revision !== this.revision || !this.contract || !this.preparation) return false;
      const view = executionView(snapshot, this.contract, this.preparation);
      this.execution = snapshot;
      return view;
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
    $("preparation-content").hidden = true;
    $("preparation-status").textContent = "";
    $("download-preparation").removeAttribute("href");
    $("prepare-request").disabled = true;
    $("physics-count").textContent = "0";
    $("policy-count").textContent = "0";
    $("execution-status").textContent = "NOT_EXECUTED";
    clearExecution();
    $("observe-execution").disabled = true;
  }
  function clearExecution() {
    $("execution-title").textContent = "当前没有新指令的执行画面";
    $("execution-observation").textContent = "";
    $("execution-result").hidden = true;
    $("execution-result").textContent = "";
    $("execution-media").hidden = true;
    const video = $("execution-video");
    video.pause();
    video.removeAttribute("src");
    video.load();
    $("execution-media-caption").textContent = "";
    $("execution-media-provenance").textContent = "";
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
    if (!response.ok) throw new Error(`请求被拒绝（HTTP ${response.status}）：${text(body.error_message || body.error_code || body.error || body.reason || "请检查输入或来源绑定")}`);
    return body;
  }
  async function executionRequest(id) {
    const response = await fetcher(`${requestPath(id)}/execution`, {method: "GET", cache: "no-store"});
    let body;
    try { body = await response.json(); } catch (_) { throw new Error(`执行状态不是有效 JSON（HTTP ${response.status}）。`); }
    if (!response.ok) throw new Error(`执行状态读取失败（HTTP ${response.status}）：${text(body.error_message || body.error_code || body.error || "UNKNOWN")}`);
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
    $("prepare-request").disabled = compiler.status !== "SUCCESS" || !contract.mission;
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
  $("prepare-request").addEventListener("click", async () => {
    const contract = state.contract;
    if (!contract || $("prepare-request").disabled) return;
    const revision = state.revision;
    $("prepare-request").disabled = true;
    $("observe-execution").disabled = true;
    clearExecution();
    $("preparation-content").hidden = true;
    $("download-preparation").removeAttribute("href");
    state.preparation = null;
    $("preparation-status").textContent = "正在生成独立审查清单；不会启动仿真…";
    try {
      const response = await jsonRequest(`${requestPath(contract.request_id)}/prepare`, preparationPayload(contract));
      const preparation = response.preparation || response;
      if (!state.acceptPreparation(revision, contract.contract_sha256, preparation)) return;
      $("preparation-content").hidden = false;
      $("preparation-status").textContent = "准备清单已生成 · 等待独立审查与 Owner 授权";
      $("preparation-identity").replaceChildren(...[
        ["准备 ID", preparation.preparation_id], ["准备 SHA256", preparation.preparation_sha256],
        ["执行源码", preparation.C_exec], ["Readiness SHA256", preparation.readiness_sha256],
        ["协议 SHA256", preparation.protocol_sha256]
      ].flatMap(([key, value]) => [node("dt", key), node("dd", value)]));
      const budget = preparation.budget || {};
      $("preparation-budget").textContent = `冻结预算：最多 ${text(budget.native_steps)} 物理步 · ${text(budget.wall_s)} 秒 · 外部截止 ${text(budget.outer_cutoff_s)} 秒 · seed ${text(budget.seed)} · ${text(budget.attempts)} 次执行。准备清单不启动采集；实际消耗请查看本次执行状态。`;
      const gates = preparation.gates || {};
      $("preparation-gates").replaceChildren(...[
        ["独立 Release", gates.narrow_language_release], ["Owner", gates.owner],
        ["实时状态", gates.live_state], ["Language Runtime", gates.language_runtime], ["D011", gates.d011]
      ].map(([label, value]) => node("span", `${label}: ${text(value)}`)));
      const execution = preparation.execution || {};
      $("preparation-execution").textContent = `准备时记录：${text(execution.status)} · 物理步 ${text(execution.physics_steps)} · 策略调用 ${text(execution.policy_calls)}`;
      $("download-preparation").href = `${requestPath(contract.request_id)}/preparation`;
      $("observe-execution").disabled = false;
    } catch (error) {
      if (state.revision === revision) $("preparation-status").textContent = `准备被拒绝：${error.message}`;
    } finally { if (state.revision === revision) $("prepare-request").disabled = false; }
  });
  $("observe-execution").addEventListener("click", async () => {
    const contract = state.contract;
    if (!contract || !state.preparation) return;
    const revision = state.revision;
    $("observe-execution").disabled = true;
    clearExecution();
    $("physics-count").textContent = "UNKNOWN";
    $("policy-count").textContent = "UNKNOWN";
    $("execution-status").textContent = "UNKNOWN";
    $("execution-observation").textContent = "正在读取本次执行回执；此操作不会发起执行…";
    try {
      const snapshot = await executionRequest(contract.request_id);
      const view = state.acceptExecution(revision, snapshot);
      if (!view) return;
      $("execution-title").textContent = view.title;
      $("execution-status").textContent = view.status;
      $("physics-count").textContent = view.physics;
      $("policy-count").textContent = view.policy;
      $("execution-observation").textContent = `运行 ID：${view.runId}`;
      if (view.result !== null) {
        $("execution-result").hidden = false;
        $("execution-result").textContent = JSON.stringify(view.result, null, 2);
      }
      if (view.media) {
        $("execution-media").hidden = false;
        $("execution-video").src = view.media.url;
        $("execution-media-caption").textContent = "本次真实采集的状态回放；不是实时机器人画面。";
        $("execution-media-provenance").textContent = `视频 SHA256 ${view.media.sha256} · 原始位姿 SHA256 ${view.media.source_pose_sha256}`;
      }
    } catch (error) {
      if (state.revision === revision) $("execution-observation").textContent = `本次执行状态无法确认：${error.message}`;
    } finally { if (state.revision === revision) $("observe-execution").disabled = false; }
  });
  return state;
}

if (typeof module !== "undefined" && module.exports) module.exports = {createState, stepTitle, requestPath, preparationPayload, reasonText, executionView, boot};
if (typeof document !== "undefined") boot();
