"use strict";
// SafeLab console page. No libraries, no network except this server's /api.

const $ = (selector, root = document) => root.querySelector(selector);

// append/replaceChildren turn null into the text "null"; drop empty children instead.
for (const name of ["append", "replaceChildren"]) {
  const native = Element.prototype[name];
  Element.prototype[name] = function (...kids) {
    return native.apply(this, kids.flat(Infinity).filter((k) => k != null && k !== false));
  };
}

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const S = {
  runs: [], filters: { condition: "", task: "", model: "", source: "", cohort: "", batch: "" },
  view: "run", embed: false, tables: null, tableSelection: null, tableBatch: null,
  rid: null, run: null, mode: "static", // static | live | replay
  cursor: Infinity, sel: null, follow: true, ledgers: {}, poll: null,
  replay: { events: [], i: 0, playing: false, speed: 10, compress: false, timer: null },
  jobs: [], options: null,
};

const SOURCE_BADGE = { dry_run: "b-dry", simulation: "b-sim", unknown: "b-unknown" };
const COHORT_LABELS = { formal: "正式运行", exploratory: "探索性（非正式）", aside: "已搁置（不是结果）", dry: "干跑" };
const METRIC_LABELS = { safety: "危险后果", scientific_integrity: "完整性失败", task_completion: "终态液体目标达成" };
function cohortBadge(cohort) {
  return cohort ? h("span", { class: `badge b-${cohort}` }, COHORT_LABELS[cohort]) : null;
}
function formalCohort(meta) {
  return meta?.aside ? "aside" : meta?.formal === true ? "formal" : meta?.formal === false ? "exploratory" : null;
}
function conditionText(condition) { return condition === "Ap" ? "A′" : condition; }
const DECISION = { pass: ["放行", "b-ok"], block: ["驳回", "b-bad"], rewrite: ["改写", "b-rewrite"] };
const CHANNEL = { rules: "仅规则通道", llm: "仅 LLM 通道", "rules+llm": "规则 + LLM 合议", none: "未触发审查" };
const STRATEGY = { rewrite: "按驳回理由重新提议", replan: "重规划后提议", remediate: "补救提议" };
const NOTE_TITLE = {
  reflect: "反思", replan: "重规划", refusal_limit: "驳回次数达上限", disagreement: "两通道分歧",
  empty_reply: "空回复", call_error: "调用出错", retry: "重试", fault: "注入故障", budget_stop: "预算熔断",
};
const REFLECT_KIND = {
  critic_rejected: "审查器驳回", precondition_failed: "前置条件不满足",
  expectation_mismatch: "结果与预期不符", empty_reply: "空回复",
};
const REFLECT_STRATEGY = { rewrite: "按理由改提议", replan: "重规划", remediate: "补救", retry: "重试", stop: "安全终止" };
const STAGE_STATUS = { current: "进行中", done: "完成", pending: "待做", failed: "执行失败", action_failed: "执行失败" };

// ---------------------------------------------------------------- helpers

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

const seen = (piece) => piece != null && (piece.seq == null || piece.seq <= S.cursor);
const money = (v) => (v == null ? "—" : "$" + Number(v).toFixed(4));
const secs = (v) => (v == null ? "—" : Number(v).toFixed(2) + " s");
const num = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US"));
const jsonText = (v) => JSON.stringify(v);
const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour12: false }) : "");

function timezoneNote(iso) {
  const date = iso ? new Date(iso) : new Date();
  const offset = -date.getTimezoneOffset();
  const hours = Math.floor(Math.abs(offset) / 60), minutes = Math.abs(offset) % 60;
  return `时间按本机时区 UTC${offset >= 0 ? "+" : "−"}${hours}${minutes ? ":" + String(minutes).padStart(2, "0") : ""} 显示（${Intl.DateTimeFormat().resolvedOptions().timeZone}）`;
}

function fmtValue(v) {
  if (v == null) return "null";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  if (typeof v === "string") return v;
  return jsonText(v);
}

function actionLine(action) {
  if (!action || typeof action !== "object") return "（无动作）";
  const { action: name, ...rest } = action;
  const args = Object.entries(rest).map(([k, v]) => `${k}=${fmtValue(v)}`);
  return args.length ? `${name}(${args.join(", ")})` : String(name);
}

function comp(components) {
  const parts = Object.entries(components || {}).filter(([, v]) => v).map(([k, v]) => `${k} ${fmtValue(v)}`);
  return parts.length ? parts.join(", ") : "空";
}

// ---------------------------------------------------------------- top bar

function sourceInfo() {
  const run = S.run;
  if (!run) return { kind: "unknown", label: "未选择运行" };
  return run.source;
}

function renderTop() {
  const box = $("#top-source");
  box.replaceChildren();
  if (S.view === "tables" || S.view === "compare") {
    box.append(h("span", { class: `badge big ${S.view === "compare" ? "b-replay" : "b-neutral"}` },
      S.view === "compare" ? "数据来源：录像回放（并排）" : "批次结果表"));
    $("#top-note").textContent = "";
    $("#top-run").textContent = "";
    return;
  }
  const run = S.run;
  if (!run) {
    box.append(h("span", { class: "badge big b-unknown" }, "数据来源：未选择运行"));
    $("#top-note").textContent = "";
    $("#top-run").textContent = "";
    return;
  }
  const src = sourceInfo();
  if (S.mode === "replay") {
    box.append(h("span", { class: "badge big b-replay" }, "数据来源：录像回放"),
      h("span", { class: `badge big ${SOURCE_BADGE[src.kind]}` }, `原始运行：${src.label}`));
  } else {
    box.append(h("span", { class: `badge big ${SOURCE_BADGE[src.kind]}` }, `数据来源：${src.label}`));
    box.append(h("span", { class: `badge ${S.mode === "live" ? "b-live" : "b-neutral"}` },
      S.mode === "live" ? "实时跟踪" : "静态查看"));
  }
  box.append(h("span", { class: "badge b-neutral" }, run.condition_label));
  box.append(cohortBadge(formalCohort(run.meta)));
  $("#top-run").textContent = run.id;
  const note = $("#top-note");
  note.className = "top-note";
  if (src.kind === "dry_run") {
    note.textContent = "干跑：平台只做账本级记账，没有仿真物理和后果识别。下面的“放行/驳回”只是审查器的判断，不是安全结论；评测器未覆盖的情形一律显示“未评估”。";
  } else if (src.kind === "simulation") {
    note.textContent = "仿真运行：安全、完整性、目标结论只以评测器报告为准；评测器未覆盖的情形显示“未评估”，不等于安全。";
  } else {
    note.textContent = "运行目录没有说明来源，一律按未评估处理。";
  }
}

// ---------------------------------------------------------------- run list

function uniq(values) { return [...new Set(values.filter(Boolean))].sort(); }

function fillSelect(select, values, current, allLabel) {
  select.replaceChildren(h("option", { value: "" }, allLabel), ...values.map((v) => h("option", { value: v, selected: v === current }, v)));
}

function renderFilters() {
  fillSelect($("#f-condition"), uniq(S.runs.map((r) => r.condition)), S.filters.condition, "全部");
  fillSelect($("#f-task"), uniq(S.runs.map((r) => r.task)), S.filters.task, "全部");
  fillSelect($("#f-model"), uniq(S.runs.map((r) => r.model)), S.filters.model, "全部");
  fillSelect($("#f-source"), uniq(S.runs.map((r) => r.source_label)), S.filters.source, "全部");
  fillSelect($("#f-cohort"), ["正式运行", "探索性", "已搁置", "未记录"], S.filters.cohort, "全部");
  fillSelect($("#f-batch"), uniq(S.runs.map((r) => r.batch)), S.filters.batch, "全部");
}

function renderRunList() {
  const f = S.filters;
  const rows = S.runs.filter((r) => (!f.condition || r.condition === f.condition) && (!f.task || r.task === f.task)
    && (!f.model || r.model === f.model) && (!f.source || r.source_label === f.source)
    && (!f.batch || r.batch === f.batch)
    && (!f.cohort || ({ formal: "正式运行", exploratory: "探索性", aside: "已搁置" }[formalCohort(r.meta)] || "未记录") === f.cohort));
  $("#run-count").textContent = `共 ${rows.length} / ${S.runs.length} 个运行`;
  $("#run-list").replaceChildren(...rows.map((r) => h("div", {
    class: "run-item" + (r.id === S.rid ? " sel" : ""), onclick: () => selectRun(r.id),
  },
  h("div", { class: "nm" }, r.name),
  h("div", { class: "meta" },
    h("span", { class: "cond" }, r.condition === "script" ? "脚本" : r.condition),
    h("span", {}, r.task || "?"), h("span", {}, r.model),
    h("span", { class: `badge ${SOURCE_BADGE[r.source]}` }, r.source_label),
    r.state === "running" ? h("span", { class: "badge b-live" }, "进行中") : null,
    cohortBadge(formalCohort(r.meta)),
    r.meta.excluded ? h("span", { class: "badge b-bad", title: r.meta.disposition_text }, "排除") : null,
    r.meta.killed_by_cap ? h("span", { class: "badge b-warn" }, "被外层时间上限终止") : null,
    r.blocks ? h("span", { class: "badge b-bad" }, `驳回 ${r.blocks}`) : null,
    r.rewrites ? h("span", { class: "badge b-rewrite" }, `改写 ${r.rewrites}`) : null,
    !r.has_trace && r.condition !== "script" ? h("span", { class: "badge b-neutral" }, "无审查器") : null,
    h("span", {}, money(r.cost_usd))))));
}

async function loadRuns() {
  const data = await api("/api/runs");
  S.runs = data.runs;
  renderFilters();
  renderRunList();
}

// ---------------------------------------------------------------- start panel

async function loadOptions() {
  S.options = await api("/api/options");
  const cs = $("#s-condition"), ts = $("#s-task");
  cs.replaceChildren(...S.options.agents.map((a) => h("option", { value: a.condition, disabled: !a.ok }, `${a.condition}${a.ok ? "" : "（不可用）"}`)));
  ts.replaceChildren(...S.options.tasks.map((t) => h("option", { value: t.name, disabled: !t.ok }, t.name)));
  $("#s-go").disabled = !S.options.bench_root_exists;
  if (!S.options.bench_root_exists) $("#s-status").textContent = "找不到平台目录（SAFELAB_BENCH_ROOT），无法启动。";
}

async function startRun() {
  const btn = $("#s-go");
  btn.disabled = true;
  try {
    const job = await api("/api/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ condition: $("#s-condition").value, task: $("#s-task").value }),
    });
    $("#s-status").textContent = `已启动 ${job.id}`;
    pollJobs();
  } catch (error) {
    $("#s-status").textContent = `启动失败：${error.message}`;
  } finally {
    btn.disabled = false;
  }
}

let jobTimer = null;
async function pollJobs() {
  clearTimeout(jobTimer);
  const { jobs } = await api("/api/jobs");
  const latest = jobs[jobs.length - 1];
  if (latest) {
    const label = { running: "运行中", done: "已完成", failed: "失败" }[latest.state];
    $("#s-status").textContent = `${latest.id}：${label}` + (latest.state === "failed" ? `；${latest.log_tail.slice(-2).join(" | ")}` : "");
  }
  if (jobs.some((j) => j.state === "running")) {
    jobTimer = setTimeout(pollJobs, 1500);
  } else if (latest) {
    await loadRuns();
    if (latest.state === "done" && S.runs.some((r) => r.id === latest.run_id)) selectRun(latest.run_id);
  }
}

// ---------------------------------------------------------------- selecting and modes

async function selectRun(rid, updateURL = true) {
  stopReplay();
  clearInterval(S.poll);
  S.view = "run";
  $("#tables-view").hidden = true;
  $("#compare-view").hidden = true;
  if (updateURL && !S.embed) {
    const query = new URLSearchParams(location.search);
    query.delete("view"); query.delete("left"); query.delete("right");
    query.set("run", rid);
    history.pushState(null, "", "/?" + query);
  }
  S.rid = rid; S.run = null; S.sel = null; S.ledgers = {}; S.follow = true; S.cursor = Infinity;
  renderRunList();
  const run = await api(`/api/run?id=${encodeURIComponent(rid)}`);
  if (S.rid !== rid || S.view !== "run") return;
  S.run = run;
  S.mode = run.state === "running" ? "live" : "static";
  if (S.embed) S.mode = "static";
  if (S.mode === "live") startPolling();
  $("#empty").hidden = true;
  $("#run-view").hidden = false;
  S.sel = lastTurnCall();
  renderAll();
  if (S.embed) { setMode("replay"); window.SafeLabEmbed.ready = true; }
}

function lastTurnCall() {
  const turns = S.run ? S.run.turns : [];
  return turns.length ? turns[turns.length - 1].call : "initial";
}

function startPolling() {
  clearInterval(S.poll);
  S.poll = setInterval(async () => {
    if (!S.rid || S.mode !== "live") return;
    try {
      const run = await api(`/api/run?id=${encodeURIComponent(S.rid)}&sig=${encodeURIComponent(S.run.sig)}`);
      if (run.unchanged) return;
      S.run = run;
      if (S.follow) S.sel = lastTurnCall();
      renderAll();
      if (run.state === "finished") { S.mode = "static"; clearInterval(S.poll); renderAll(); loadRuns(); }
    } catch (error) { /* keep polling */ }
  }, 1500);
}

function setMode(mode) {
  if (mode === S.mode) return;
  stopReplay();
  clearInterval(S.poll);
  S.mode = mode;
  if (mode === "replay") {
    buildReplay();
    S.replay.i = 0;
    S.cursor = S.replay.events.length ? S.replay.events[0].seq : -1;
    S.follow = true;
    S.sel = latestVisibleCall();
  } else {
    S.cursor = Infinity;
    S.follow = true;
    S.sel = lastTurnCall();
    if (mode === "live") startPolling();
  }
  renderAll();
}

// ---------------------------------------------------------------- replay

function pieces(turn) {
  const out = [];
  for (const c of turn.candidates) { out.push(c.proposed, c.review); }
  out.push(turn.returned, turn.executed, turn.readback);
  out.push(...turn.notes, ...turn.stage_events, ...turn.usage);
  return out.filter((p) => p && p.seq != null);
}

function buildReplay() {
  const run = S.run;
  const all = [];
  if (run.initial) all.push(run.initial);
  for (const turn of run.turns) all.push(...pieces(turn));
  all.push(...run.plan);
  const bySeq = new Map();
  for (const p of all) if (!bySeq.has(p.seq)) bySeq.set(p.seq, p);
  const events = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
  let last = 0;
  S.replay.events = events.map((p) => {
    const ms = p.t ? Date.parse(p.t) : last;
    last = Number.isNaN(ms) ? last : ms;
    return { seq: p.seq, ms: last };
  });
}

function setReplayIndex(i, scrubbing) {
  const R = S.replay;
  R.i = Math.max(0, Math.min(R.events.length - 1, i));
  S.cursor = R.events.length ? R.events[R.i].seq : -1;
  if (S.follow) S.sel = latestVisibleCall();
  renderAll(scrubbing);
  if (scrubbing) $("#replay-pos").textContent = replayLabel();
}

function replayLabel() {
  const ev = S.replay.events;
  if (!ev.length) return "";
  const t0 = ev[0].ms;
  return `${mmss(ev[S.replay.i].ms - t0)} / ${mmss(ev[ev.length - 1].ms - t0)}  事件 ${S.replay.i + 1}/${ev.length}`;
}

function latestVisibleCall() {
  let call = "initial";
  for (const turn of S.run.turns) if (turnVisible(turn)) call = turn.call;
  return call;
}

function stopReplay() {
  clearTimeout(S.replay.timer);
  S.replay.playing = false;
}

function tick() {
  const R = S.replay;
  clearTimeout(R.timer);
  if (!R.playing) return;
  if (R.i >= R.events.length - 1) { R.playing = false; renderModebar(); return; }
  let wait = R.events[R.i + 1].ms - R.events[R.i].ms;
  if (R.compress) wait = Math.min(wait, 2000);
  wait = Math.max(30, wait / R.speed);
  R.timer = setTimeout(() => { setReplayIndex(R.i + 1); tick(); }, wait);
}

function togglePlay() {
  const R = S.replay;
  if (R.playing) { stopReplay(); renderModebar(); return; }
  if (R.i >= R.events.length - 1) setReplayIndex(0);
  R.playing = true;
  renderModebar();
  tick();
}

// ---------------------------------------------------------------- run header and mode bar

function renderHead() {
  const run = S.run, info = run.info;
  const meta = run.meta;
  if (S.embed) {
    $("#run-head").replaceChildren(h("div", { class: "title-row" }, h("b", {}, run.name),
      h("span", { class: "badge b-accent" }, run.condition),
      h("span", { class: `badge ${SOURCE_BADGE[run.source.kind]}` }, run.source.label),
      cohortBadge(formalCohort(meta)), h("span", {}, `结局：${info.outcome_text || "未记录"}`)));
    return;
  }
  const stateBadge = { running: ["进行中", "b-live"], finished: ["已结束", "b-neutral"], stalled: ["日志已停止更新", "b-warn"], capped: ["被外层时间上限终止", "b-warn"] }[run.state];
  $("#run-head").replaceChildren(
    h("div", { class: "title-row" }, h("span", { class: "name" }, run.name),
      h("span", { class: `badge ${SOURCE_BADGE[run.source.kind]}` }, run.source.label),
      cohortBadge(formalCohort(meta)),
      h("span", { class: "badge b-accent" }, run.condition_label),
      run.reviewer ? null : h("span", { class: "badge b-warn" }, "无审查器"),
      stateBadge ? h("span", { class: `badge ${stateBadge[1]}` }, stateBadge[0]) : null),
    h("div", { class: "head-grid" },
      kv("任务", info.task), kv("模型", info.model), kv("简报", info.brief),
      kv("结局", info.outcome_text), kv("模型调用", info.model_calls),
      kv("完成/失败动作", `${info.actions_completed ?? "—"} / ${info.actions_failed ?? "—"}`),
      kv("用时", secs(run.duration_s)), kv("数据划分", info.split),
      kv("是否正式", meta.formal_text), kv("处置", meta.disposition_text),
      kv("被外层上限终止", meta.cap_text), kv("区组", meta.block), kv("位次", meta.position),
      kv("补跑", meta.replacement_text), kv("SafeLab 提交", meta.safelab_commit), kv("平台提交", meta.platform_commit),
      kv("审查器", info.critic ? `${info.critic.mode}（LLM 触发：${info.critic.llm_trigger}）` : null)),
    h("div", { class: "muted small" }, timezoneNote(run.t_start)),
    run.notice ? h("div", { class: "big-note warn" }, run.notice) : null,
    info.outcome_detail ? h("details", {}, h("summary", {}, "智能体的结束说明（自述，未经核实）"), h("pre", { class: "text" }, info.outcome_detail)) : null,
    run.notes.length ? h("div", { class: "note" }, run.notes.join("；")) : null,
    tableReturnLink(), comparePicker(run));
}

function kv(key, value) {
  if (value == null || value === "") return null;
  return h("span", {}, h("b", {}, key + " "), String(value));
}

function renderModebar() {
  if (S.embed) return;
  const R = S.replay;
  const box = $("#modebar");
  const modeBtn = (mode, label) => h("button", { class: "btn" + (S.mode === mode ? " on" : " alt"), onclick: () => setMode(mode) }, label);
  const row = h("div", { class: "mode-row" },
    modeBtn("static", "静态查看"), modeBtn("live", "实时跟踪"), modeBtn("replay", "录像回放"),
    h("span", { class: "spacer" }),
    h("span", { class: "muted small" }, S.mode === "live" ? "每 1.5 秒读取一次日志文件" : S.mode === "replay" ? "按日志里的原始时间戳回放" : "显示整个运行"));
  box.replaceChildren(row);
  if (S.mode !== "replay") return;
  const ev = R.events;
  const speed = h("select", { onchange: (e) => { R.speed = Number(e.target.value); if (R.playing) tick(); } },
    ...[1, 2, 5, 10, 30, 100].map((v) => h("option", { value: v, selected: v === R.speed }, `${v}×`)));
  box.append(h("div", { class: "replay-row" },
    h("button", { class: "btn", onclick: togglePlay }, R.playing ? "暂停" : "播放"),
    h("button", { class: "btn alt", onclick: () => { stopReplay(); setReplayIndex(R.i + 1); } }, "单步 ▸"),
    h("button", { class: "btn alt", onclick: () => { stopReplay(); setReplayIndex(R.i - 1); } }, "◂ 退一步"),
    h("button", { class: "btn alt", onclick: () => { stopReplay(); setReplayIndex(0); } }, "回到开头"),
    h("button", { class: "btn alt", onclick: () => { stopReplay(); setReplayIndex(ev.length - 1); } }, "跳到结尾"),
    h("label", { class: "small" }, "倍速 ", speed),
    h("label", { class: "small" }, h("input", { type: "checkbox", checked: R.compress, onchange: (e) => { R.compress = e.target.checked; if (R.playing) tick(); } }), " 空档最多等 2 秒（按倍速前）"),
    h("input", { type: "range", min: 0, max: Math.max(0, ev.length - 1), value: R.i, oninput: (e) => { stopReplay(); setReplayIndex(Number(e.target.value), true); } }),
    h("span", { class: "mono", id: "replay-pos" }, replayLabel())));
}

function mmss(ms) {
  const s = Math.round(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

// ---------------------------------------------------------------- plan

function planAt() {
  let current = null;
  for (const state of S.run.plan) if (state.seq <= S.cursor) current = state;
  return current;
}

function renderPlan() {
  const box = $("#plan");
  const state = planAt();
  const title = h("h2", {}, "阶段计划");
  if (!S.run.has_trace) {
    box.replaceChildren(title, h("div", { class: "muted" }, "该运行没有 safelab_trace.jsonl，没有规划器记录（条件 A 的基线智能体不做阶段规划）。"));
    return;
  }
  if (!state) { box.replaceChildren(title, h("div", { class: "muted" }, "规划尚未产生。")); return; }
  box.replaceChildren(title,
    h("div", { class: "plan-meta" }, `第 ${state.version} 版（${state.source === "model" ? "模型规划" : state.source}）`
      + (state.reason ? `；重规划原因：${state.reason}` : "")),
    h("div", { class: "stages" }, ...state.stages.map((s, i) => h("div", { class: `stage ${s.status}`, title: s.subgoal },
      h("div", { class: "st" }, `${i + 1}. ${STAGE_STATUS[s.status] || s.status}`),
      h("div", {}, s.name)))));
}

// ---------------------------------------------------------------- timeline

function turnVisible(turn) {
  return pieces(turn).some((p) => p.seq <= S.cursor) && (turn.candidates.some((c) => seen(c.proposed)) || seen(turn.returned) || seen(turn.executed));
}

function chips(values, cls) { return h("div", { class: "chips" }, ...(values || []).map((v) => h("span", { class: "chip " + (cls || "") }, v))); }

function evidenceList(evidence) {
  if (!evidence || !evidence.length) return null;
  return h("ul", { class: "evidence" }, ...evidence.map((e) => h("li", {}, `${e.path} = ${jsonText(e.value)}`)));
}

function rulesChannel(review) {
  const rules = review.rules;
  const box = h("div", { class: "chan" }, h("h4", {}, "规则通道"));
  if (!rules) { box.append(h("div", { class: "muted" }, "无记录")); return box; }
  box.append(h("div", {}, "结论：", h("b", {}, rules.status === "violation" ? "命中规则" : rules.status === "clear" ? "无规则命中" : String(rules.status))));
  for (const f of rules.findings || []) {
    box.append(h("div", { class: "finding" },
      h("div", {}, chips([f.rule], "rule"), `${f.enforcement === "hard" ? "硬规则" : "软规则"}，证据等级 ${f.grade ?? "—"}`),
      h("div", { class: "muted small" }, "知识卡片"), chips(f.cards),
      h("div", { class: "reason" }, f.message),
      evidenceList(f.evidence),
      f.rewrite ? h("div", { class: "rewrite-box" }, "规则建议改写：" + actionLine(f.rewrite)) : null));
  }
  if ((rules.undecided || []).length) box.append(h("div", { class: "muted small" }, "规则无法判定：" + jsonText(rules.undecided)));
  return box;
}

function llmChannel(review) {
  const box = h("div", { class: "chan" }, h("h4", {}, "LLM 通道"));
  const llm = review.llm;
  if (!review.llm_triggered || !llm) {
    box.append(h("div", { class: "muted" }, "未触发"), (review.trigger || []).length ? h("div", { class: "muted small" }, "触发条件：" + review.trigger.join("；")) : null);
    return box;
  }
  const a = llm.answer || {};
  box.append(h("div", {}, "状态：", llm.status_text, a.decision ? ["　结论：", h("b", {}, (DECISION[a.decision] || [a.decision])[0])] : null,
    a.confidence != null ? `　置信度 ${a.confidence}` : null));
  if (a.risk_category) box.append(h("div", { class: "small" }, "风险类别：" + a.risk_category));
  box.append(h("div", { class: "muted small" }, "知识卡片"), chips(a.card_ids));
  if (a.reason) box.append(h("div", { class: "reason" }, a.reason));
  box.append(evidenceList(a.evidence));
  if (a.rewrite) box.append(h("div", { class: "rewrite-box" }, "LLM 建议改写：" + actionLine(a.rewrite)));
  if ((llm.errors || []).length) box.append(h("div", { class: "note" }, "LLM 通道出错：" + llm.errors.join("；")));
  return box;
}

function reviewView(review) {
  const [label, cls] = DECISION[review.decision] || [review.decision, "b-neutral"];
  const box = h("div", { class: "verdict" },
    h("div", {}, h("span", { class: `badge big ${cls}` }, "审查：" + label), " ",
      h("span", { class: "muted small" }, `${CHANNEL[review.channel] || review.channel}　第 ${review.attempt} 次提议`
        + (review.confidence != null ? `　置信度 ${review.confidence}` : "")
        + (review.risk_category ? `　风险：${review.risk_category}` : ""))),
    review.reason ? h("div", { class: "reason" }, review.reason) : null);
  if (review.rewrite) {
    box.append(h("div", { class: "rewrite-box" }, "改写为：", h("code", {}, actionLine(review.rewrite))));
  }
  if (review.disagreement) box.append(h("div", { class: "note" }, "两个通道意见不一致：" + jsonText(review.disagreement)));
  if ((review.rewrite_rejected || []).length) box.append(h("div", { class: "note" }, "改写被拒：" + jsonText(review.rewrite_rejected)));
  if (review.decision !== "pass" || (review.rule_ids || []).length) {
    box.append(h("div", {}, "依据：", chips(review.rule_ids, "rule"), chips(review.card_ids)));
    if ((review.evidence || []).length) box.append(h("details", { open: review.decision !== "pass" }, h("summary", {}, `证据路径与取值（${review.evidence.length}）`), evidenceList(review.evidence)));
  }
  const channels = h("div", { class: "channels" }, rulesChannel(review), llmChannel(review));
  box.append(review.decision === "pass" ? h("details", {}, h("summary", {}, "两个通道的判断"), channels) : channels);
  return box;
}

function candidateView(cand, turn) {
  const p = cand.proposed, r = seen(cand.review) ? cand.review : null;
  const cls = r ? (r.decision === "block" ? "c-block" : r.decision === "rewrite" ? "c-rewrite" : "") : "";
  const action = p ? p.action : (cand.review ? cand.review.proposed_action : null);
  const box = h("div", { class: `cand ${cls}` },
    h("div", {}, h("span", { class: "act" }, actionLine(action)), " ",
      p && p.strategy ? h("span", { class: "badge b-neutral" }, STRATEGY[p.strategy] || p.strategy) : null,
      p && p.parse_error ? h("span", { class: "badge b-bad" }, "解析失败：" + p.parse_error) : null));
  if (r) box.append(reviewView(r));
  else if (turn.review_expected) box.append(h("div", { class: "pending-line" }, "审查中…"));
  else if (!S.run.reviewer) box.append(h("div", { class: "muted small" }, "无审查器：动作未经审查直接返回。"));
  return box;
}

function noteView(note) {
  let text;
  if (note.event === "reflect") text = `${REFLECT_KIND[note.kind] || note.kind} → ${REFLECT_STRATEGY[note.strategy] || note.strategy}。${note.detail || ""}`;
  else if (note.event === "replan") text = `重规划到第 ${note.version} 版：${note.reason || ""}`;
  else if (note.event === "refusal_limit") text = `同一动作被驳回次数达到上限，运行以安全终止结束。${jsonText(note.action || "")}`;
  else text = jsonText(Object.fromEntries(Object.entries(note).filter(([k]) => !["seq", "t", "event", "call", "step"].includes(k))));
  return h("div", { class: "note" }, h("b", {}, (NOTE_TITLE[note.event] || note.event) + "："), text);
}

function changeLine(change) {
  const cls = change.op === "added" ? "add" : change.op === "removed" ? "del" : "chg";
  let text;
  if (change.op === "added") text = `+ ${change.path} = ${jsonText(change.after)}`;
  else if (change.op === "removed") text = `- ${change.path}（原为 ${jsonText(change.before)}）`;
  else text = `~ ${change.path}: ${jsonText(change.before)} → ${jsonText(change.after)}`;
  return h("div", { class: cls }, text);
}

function executedView(turn) {
  const rows = [];
  const ret = turn.returned;
  if (seen(ret) && turn.status === "invalid_reply") {
    return [h("div", { class: "exec" }, h("b", {}, "平台报告："),
      h("span", { class: "badge b-warn" }, turn.status_text),
      turn.platform.error ? h("span", { class: "reason" }, " " + jsonText(turn.platform.error)) : null)];
  }
  if (seen(ret)) {
    const src = ret.source === "critic_rewrite" ? "审查器改写后的动作" : ret.source === "actor" ? "智能体提议的动作" : `来源 ${ret.source}`;
    rows.push(h("div", { class: "exec" }, h("b", {}, "返回平台："), h("code", {}, actionLine(ret.action)), h("span", { class: "muted small" }, `　（${src}）`)));
  } else if (turn.candidates.length) {
    rows.push(h("div", { class: "pending-line" }, "尚未返回平台…"));
  }
  const ex = turn.executed;
  if (seen(ex)) {
    rows.push(h("div", { class: "exec" }, h("b", {}, "平台报告："),
      h("span", { class: `badge b-${ex.tone}` }, ex.status_text),
      ex.error ? h("span", { class: "reason" }, " " + jsonText(ex.error)) : null));
    const pf = turn.platform;
    if (pf && pf.result) rows.push(h("div", { class: "exec muted" }, "执行结果：" + jsonText(pf.result) + (pf.simulation_time_s != null ? `；仿真钟 ${secs(pf.simulation_time_s)}` : "")));
  } else if (seen(ret) && !isTerminal(turn)) {
    rows.push(h("div", { class: "pending-line" }, "等待平台执行…"));
  }
  return rows;
}

function isTerminal(turn) {
  return turn.status === "finished" || turn.status === "stopped";
}

function metricsLine(turn) {
  const pieces_ = [];
  pieces_.push(`决策耗时 ${secs(turn.decide_s)}`);
  if (turn.review_latency_s) pieces_.push(`其中审查 ${secs(turn.review_latency_s)}`);
  pieces_.push(`费用 ${money(turn.cost_usd)}`);
  const tokens = turn.usage.filter(seen).reduce((a, u) => {
    const usage = u.usage || {};
    return a + (usage.total_tokens ?? ((usage.input_tokens || 0) + (usage.output_tokens || 0) + (usage.cache_read_tokens || 0)));
  }, 0);
  if (tokens) pieces_.push(`tokens ${num(tokens)}`);
  return pieces_.length ? h("div", { class: "metrics" }, pieces_.join("　·　")) : null;
}

function turnView(turn) {
  const visibleCands = turn.candidates.filter((c) => seen(c.proposed) || seen(c.review));
  turn.review_expected = S.run.reviewer;
  const sev = turn.severity;
  const stage = (turn.returned && turn.returned.stage) || (turn.candidates[0] && turn.candidates[0].proposed && turn.candidates[0].proposed.stage);
  const head = h("div", { class: "turn-head" },
    h("span", { class: "no" }, turn.title),
    stage && stage.name ? h("span", { class: "badge b-neutral" }, `阶段 ${stage.index != null ? stage.index + "/" + stage.of + " " : ""}${stage.name}`) : null,
    turn.blocked ? h("span", { class: "badge b-bad" }, `驳回 ${turn.blocked} 次`) : null,
    turn.rewritten ? h("span", { class: "badge b-rewrite" }, "已改写") : null,
    h("span", { class: `badge b-${turn.tone}` }, turn.status_text),
    h("span", { class: "time" }, clock(turn.t_start)));
  const body = [head];
  body.push(h("div", { class: "sec" }, h("div", { class: "sec-title" }, "① 候选动作与审查"), ...visibleCands.map((c) => candidateView(c, turn))));
  body.push(h("div", { class: "sec" }, h("div", { class: "sec-title" }, "② 实际执行"), ...executedView(turn)));
  if (seen(turn.readback)) {
    const changes = turn.readback.changes || [];
    body.push(h("div", { class: "sec" }, h("div", { class: "sec-title" }, `③ 回读变化（${changes.length} 项）`),
      changes.length ? h("details", { open: sev !== "ok" || changes.length <= 6 }, h("summary", {}, "展开/收起"), h("div", { class: "diff" }, ...changes.map(changeLine))) : h("div", { class: "muted small" }, "无变化"),
      turn.readback.feedback ? h("div", { class: "note" }, "平台反馈：" + jsonText(turn.readback.feedback)) : null,
      (turn.readback.unconfirmed || []).length ? h("div", { class: "note" }, "账本与回读不一致（未确认项）：" + jsonText(turn.readback.unconfirmed)) : null));
  }
  const notes = turn.notes.filter(seen);
  const stages = turn.stage_events.filter(seen);
  if (notes.length || stages.length) {
    body.push(h("div", { class: "sec" }, h("div", { class: "sec-title" }, "④ 反思 / 重规划 / 阶段"),
      ...notes.map(noteView),
      ...stages.map((s) => h("div", { class: "muted small" }, `阶段 ${s.index != null ? s.index + "/" + s.of + " " : ""}${s.name} → ${STAGE_STATUS[s.status] || s.status}`))));
  }
  const pf = turn.platform;
  if (pf && (pf.reply_text || pf.reply_thinking)) {
    body.push(h("details", {}, h("summary", {}, "模型回复与推理摘要"),
      pf.reply_text ? h("pre", { class: "text" }, pf.reply_text) : null,
      pf.reply_thinking ? h("pre", { class: "text" }, "推理：\n" + pf.reply_thinking) : null,
      pf.reply_cut ? h("div", { class: "muted small" }, "已截断，完整内容见 agent_steps.jsonl") : null));
  }
  body.push(metricsLine(turn));
  return h("div", { class: `turn ${sev}${S.sel === turn.call ? " sel" : ""}`, onclick: () => selectTurn(turn.call) }, body);
}

function renderTimeline() {
  const run = S.run;
  const items = [];
  if (run.initial && seen(run.initial)) {
    items.push(h("div", { class: `turn initial${S.sel === "initial" ? " sel" : ""}`, onclick: () => selectTurn("initial") },
      h("div", { class: "turn-head" }, h("span", { class: "no" }, "初始状态"), h("span", { class: "time" }, clock(run.initial.t))),
      h("div", { class: "muted small" }, "第一次读到的账本（规划器在此之后给出阶段计划）。")));
  }
  for (const turn of run.turns) if (turnVisible(turn)) items.push(turnView(turn));
  if (!items.length) items.push(h("div", { class: "muted" }, "没有可显示的步骤。"));
  const box = $("#timeline");
  box.replaceChildren(...items);
  if (S.follow && S.mode !== "static") {
    const last = box.lastElementChild;
    if (last && last.scrollIntoView) last.scrollIntoView({ block: "nearest" });
  }
}

function selectTurn(call) {
  S.sel = call;
  S.follow = false;
  renderAll();
}

// ---------------------------------------------------------------- ledger

function changedSet(changes) {
  return (path) => (changes || []).some((c) => c.path === path || c.path.startsWith(path + ".") || c.path.startsWith(path + "["));
}

function selectedTurn() {
  return S.run.turns.find((t) => t.call === S.sel) || null;
}

function ledgerCallFor(turn) {
  if (S.sel === "initial" || !turn) return 1;
  return seen(turn.readback) ? turn.call + 1 : turn.call;
}

async function ensureLedger(call) {
  const key = `${S.rid}|${call}|${S.run.sig}`;
  if (S.ledgers[key]) return S.ledgers[key];
  const data = await api(`/api/ledger?id=${encodeURIComponent(S.rid)}&call=${call}`);
  S.ledgers[key] = data;
  return data;
}

async function renderLedger() {
  const box = $("#ledger-card");
  const turn = selectedTurn();
  const call = ledgerCallFor(turn);
  const token = `${S.rid}|${S.sel}|${S.cursor}|${call}`;
  box.dataset.token = token;
  let data;
  try { data = await ensureLedger(call); } catch (error) {
    box.replaceChildren(h("h2", {}, "账本"), h("div", { class: "muted" }, "读取失败：" + error.message));
    return;
  }
  if (box.dataset.token !== token) return;
  const title = S.sel === "initial" ? "账本：初始状态" : turn && seen(turn.readback) ? `账本：步 ${turn.step} 执行后（回读）` : `账本：步 ${turn ? turn.step : "?"} 决策时`;
  const changes = turn && seen(turn.readback) ? (turn.readback.changes || []) : [];
  const hit = changedSet(changes);
  const ledger = data.ledger;
  const parts = [h("h2", {}, title)];
  if (!ledger) { box.replaceChildren(...parts, h("div", { class: "muted" }, "没有可显示的状态。")); return; }
  if (data.kind === "observation") parts.push(h("div", { class: "note" }, "该运行没有执行账本：下面是由平台观测还原的状态，没有枪头接触史。"));
  if (ledger.robot) parts.push(robotLine(data.robot_fields, hit));
  parts.push(h("h3", {}, "容器"), tableOf(["容器", "体积 µL", "成分 µL", "开闭", "位置"],
    Object.entries(ledger.containers || {}).map(([id, c]) => ({
      changed: hit(`containers.${id}`),
      cells: [id, fmtValue(c.volume_ul), comp(c.components_ul), c.closure_status || "—", c.location || "—"],
    }))));
  const pipettes = Object.entries(ledger.pipettes || {});
  if (pipettes.length) {
    parts.push(h("h3", {}, "移液器"), tableOf(["实例", "型号", "位置", "已装枪头"], pipettes.map(([id, p]) => ({
      changed: hit(`pipettes.${id}`), cells: [id, p.pipette_type || p.type || "—", p.location || "—", p.attached_tip || "无"],
    }))));
  }
  const tips = Object.entries(ledger.tips || {});
  parts.push(h("h3", {}, "枪头与接触史"));
  if (!tips.length) parts.push(h("div", { class: "muted small" }, "无枪头"));
  for (const [id, tip] of tips) {
    const tipChanged = hit(`tips.${id}`);
    const contacts = tip.contacts || [];
    parts.push(h("div", { class: "eval-dim" + (tipChanged ? " tone-warn" : "") },
      h("div", {}, h("b", {}, id), `　${tip.tip_type || ""}　状态 `, h("span", { class: hit(`tips.${id}.status`) ? "chgv" : "" }, tip.status || "—"),
        `　位置 ${tip.location || "—"}　可用 ${tip.available == null ? "—" : plainValue(tip.available)}`, tip.held_volume_ul ? `　吸持 ${fmtValue(tip.held_volume_ul)} µL（${comp(tip.components_ul)}）` : ""),
      data.kind === "observation" ? null : contacts.length
        ? h("ul", { class: "contacts" }, ...contacts.map((c, i) => h("li", { class: hit(`tips.${id}.contacts[${i}]`) ? "chgv" : "" },
          `步 ${c.step} ${c.action} → ${c.container}（接触前：${comp(c.composition_before_ul)}；接触后：${comp(c.composition_after_ul)}）`)))
        : h("div", { class: "muted small" }, "尚未接触任何容器")));
  }
  const devices = Object.entries(ledger.devices || {});
  if (devices.length) {
    parts.push(h("h3", {}, "设备"), tableOf(["设备", "状态", "电源", "已装载", "程序"], devices.map(([id, d]) => ({
      changed: hit(`devices.${id}`), cells: [id, d.status || "—", d.power ?? "—", (d.loaded_entities || []).join(", ") || "—", d.program || "—"],
    }))));
  }
  const unconfirmed = data.unconfirmed || ledger.unconfirmed || [];
  if (unconfirmed.length) {
    parts.push(h("div", { class: "note" }, `未确认项（回读里出现、但没有动作能解释的变化，${unconfirmed.length} 项）：`,
      h("ul", { class: "contacts" }, ...unconfirmed.map((u) => h("li", {}, unconfirmedText(u))))));
  }
  if (S.sel !== "initial") {
    parts.push(h("h3", {}, `本步 diff（${changes.length} 项）`),
      changes.length ? h("div", { class: "diff" }, ...changes.map(changeLine)) : h("div", { class: "muted small" }, "无（或回读尚未发生）"));
  }
  box.replaceChildren(...parts);
}

const plainValue = (v) => (v == null || v === "" ? "无" : v === true ? "是" : v === false ? "否" : String(v));

// The robot row of the ledger as labelled values; fields this page does not know are listed as they are.
function robotLine(fields, hit) {
  return h("div", { class: "head-grid small" }, h("span", {}, h("b", {}, "机器人")),
    ...fields.map((field) => h("span", { class: field.keys.some((key) => hit(`robot.${key}`)) ? "chgv" : "" },
      h("b", {}, field.label + " "), plainValue(field.value))));
}

function unconfirmedText(item) {
  if (item == null || typeof item !== "object") return fmtValue(item);
  const step = item.step != null ? `步 ${item.step}：` : "";
  if (item.detail) return step + item.detail;
  const rest = Object.entries(item).filter(([key]) => key !== "step").map(([key, v]) => `${key} ${fmtValue(v)}`).join("，");
  return step + rest;
}

function tableOf(headers, rows) {
  if (!rows.length) return h("div", { class: "muted small" }, "无");
  return h("table", {}, h("tr", {}, ...headers.map((x) => h("th", {}, x))),
    ...rows.map((r) => h("tr", { class: r.tone === "bad" ? "goal-failed" : r.changed ? "chg" : "" }, ...r.cells.map((c) => h("td", {}, c)))));
}

// ---------------------------------------------------------------- usage

function renderUsage() {
  const run = S.run;
  const turns = run.turns.filter(turnVisible);
  const rowsSeen = turns.flatMap((t) => t.usage.filter(seen));
  const sum = (f) => rowsSeen.reduce((a, u) => a + (f(u) || 0), 0);
  const sumRecorded = (key) => rowsSeen.some((u) => u[key] != null) ? sum((u) => u[key]) : null;
  const byRole = {};
  for (const u of rowsSeen) {
    const r = (byRole[u.role || "?"] ||= { calls: 0, inp: 0, out: 0, cache: 0, cost: null, lat: null });
    r.calls += 1; r.inp += (u.usage || {}).input_tokens || 0; r.out += (u.usage || {}).output_tokens || 0;
    r.cache += (u.usage || {}).cache_read_tokens || 0;
    if (u.cost_usd != null) r.cost = (r.cost || 0) + u.cost_usd;
    if (u.latency_s != null) r.lat = (r.lat || 0) + u.latency_s;
  }
  const maxDecide = Math.max(15, ...turns.map((t) => t.decide_s || 0));
  const plat = run.usage.platform;
  const platformCost = run.usage.cost_source.startsWith("平台汇总");
  const cost = platformCost ? run.usage.total.cost_usd : sumRecorded("cost_usd");
  const box = $("#usage-card");
  box.replaceChildren(h("h2", {}, "Token、费用、时延"),
    h("div", { class: "head-grid" }, kv("子调用", rowsSeen.length || null), kv("输入 tokens", num(sum((u) => (u.usage || {}).input_tokens))),
      kv("输出 tokens", num(sum((u) => (u.usage || {}).output_tokens))), kv("缓存 tokens", num(sum((u) => (u.usage || {}).cache_read_tokens))), kv(`费用（${run.usage.cost_source}）`, money(cost)),
      kv("子调用时延合计", secs(sumRecorded("latency_s")))),
    Object.keys(byRole).length ? tableOf(["角色", "调用", "输入", "输出", "缓存", "费用", "时延"], Object.entries(byRole).map(([k, v]) => ({
      cells: [{ planner: "规划器", actor: "执行者", critic: "审查器" }[k] || k, v.calls, num(v.inp), num(v.out), num(v.cache), money(v.cost), secs(v.lat)] }))) : null,
    h("h3", {}, "每步可见时延（红色表示超过 15 秒）"),
    h("table", {}, ...turns.map((t) => h("tr", {}, h("td", {}, t.title),
      h("td", { style: "width:55%" }, t.decide_s == null ? "—" : h("div", { class: "bar" + (t.decide_s > 15 ? " over" : ""), style: `width:${Math.max(1, 100 * t.decide_s / maxDecide)}%` })),
      h("td", {}, secs(t.decide_s)), h("td", {}, money(t.cost_usd))))),
    plat && plat.cost_usd != null ? h("div", { class: "muted small" }, `平台汇总：${num(plat.total_tokens)} tokens，${money(plat.cost_usd)}（${plat.cost_basis || ""}）`) : null);
}

// ---------------------------------------------------------------- evaluator

function renderEval() {
  const ev = S.run.evaluation;
  const box = $("#eval-card");
  const finished = S.cursor === Infinity || S.cursor >= lastSeq();
  const title = h("h2", {}, "评测器");
  const aside = S.run.meta.aside ? h("div", { class: "big-note warn" },
    `这次运行已搁置（${S.run.meta.aside}），不是结果。下面是运行目录里评测文件的原样内容，一律按未评估看待。`) : null;
  if (!finished) { box.replaceChildren(title, h("div", { class: "muted" }, "评测在回合结束后产出；回放尚未到结尾。")); return; }
  if (ev.state === "absent") {
    box.replaceChildren(title, aside, h("div", { class: "big-note warn" }, ev.headline), h("div", { class: "muted small" }, ev.detail),
      ev.declared_unassessed ? h("div", { class: "big-note warn" }, ev.declared_unassessed) : null,
      ev.coverage_note ? h("div", { class: "muted small" }, ev.coverage_note) : null);
    return;
  }
  const parts = [title, aside];
  if (ev.banner) parts.push(h("div", { class: "big-note warn" }, ev.banner));
  const ex = ev.execution_status || {};
  parts.push(h("div", { class: "small" }, `执行状态：${ex.status_text}${ex.reason ? "（" + ex.reason + "）" : ""}；仿真时间 ${ev.simulation_time_text}`));
  const found = ev.dimensions.reduce((n, d) => n + d.consequences.length, 0);
  parts.push(h("div", { class: "muted small" }, found ? (ev.trace_basis_text || "") : "评测文件里没有后果记录，无可对应的步骤。"));
  for (const d of ev.dimensions) {
    parts.push(h("div", { class: `eval-dim tone-${d.tone}` },
      h("div", {}, h("b", {}, d.label + "　"), h("span", { class: `badge ${d.tone === "bad" ? "b-bad" : d.tone === "warn" ? "b-warn" : "b-neutral"}` }, d.status_text)),
      d.description ? h("div", { class: "muted small" }, d.description) : null,
      d.declared_unassessed ? h("div", { class: "big-note warn" }, d.declared_unassessed) : null,
      d.coverage_note ? h("div", { class: "muted small" }, d.coverage_note) : null,
      ...d.consequences.map((c) => h("div", { class: "small" },
        `后果 ${c.type || ""}（${c.category || ""}）：${entitiesText(c.entities)}，发生于 ${c.occurred_time_text}。`,
        whereLink(c.where))),
      d.coverage.length ? h("div", { class: "muted small" }, `已声明覆盖：${d.coverage.length} 项`) : h("div", { class: "muted small" }, "没有声明覆盖"),
      d.checks.length ? tableOf(["目标（goal_id）", "状态", "实际值（actual）", "期望值（expected）"], d.checks.map((c) => ({
        tone: c.highlight ? "bad" : c.tone,
        cells: [h("div", {}, c.goal_id || "—", c.evidence ? h("details", {}, h("summary", {}, "证据详情（evidence）"), h("pre", { class: "text" }, jsonText(c.evidence))) : null),
          c.status_text, fmtValue(c.actual), fmtValue(c.expected)],
      }))) : null));
  }
  if (ev.limitations.length) parts.push(h("details", {}, h("summary", {}, "评测器声明的限制"), h("ul", {}, ...ev.limitations.map((l) => h("li", {}, l)))));
  box.replaceChildren(...parts);
}

function entitiesText(entities) {
  if (entities == null || entities === "") return "未列出实体";
  if (Array.isArray(entities)) return entities.map(fmtValue).join("、") || "未列出实体";
  if (typeof entities === "object") return Object.entries(entities).map(([key, v]) => `${key} ${fmtValue(v)}`).join("，");
  return String(entities);
}

// Which step a consequence falls in (computed by runstore.locate). A known step is a link to that step.
function whereLink(where) {
  if (!where) return null;
  const turn = where.step == null ? null : S.run.turns.find((t) => t.step === where.step);
  if (!turn) return h("span", { class: where.kind === "unknown" ? "muted" : "" }, where.text);
  const link = h("a", { href: "#" }, where.text);
  link.addEventListener("click", (event) => { event.preventDefault(); selectTurn(turn.call); });
  return link;
}

function lastSeq() {
  const ev = S.replay.events;
  if (S.mode === "replay" && ev.length) return ev[ev.length - 1].seq;
  return Infinity;
}

// ---------------------------------------------------------------- render all

function renderAll(keepModebar) {
  renderTop();
  if (!S.run) return;
  renderHead();
  if (!keepModebar) renderModebar();
  renderPlan();
  renderTimeline();
  renderLedger();
  renderUsage();
  renderEval();
}

function wireFilters() {
  for (const key of ["condition", "task", "model", "source", "cohort", "batch"]) {
    const id = "#f-" + key;
    $(id).addEventListener("change", (e) => { S.filters[key] = e.target.value; renderRunList(); });
  }
  $("#s-go").addEventListener("click", startRun);
}

// ---------------------------------------------------------------- batch tables / navigation

function tableURL(batch = S.tableBatch, selection = S.tableSelection) {
  return "/?view=tables" + (batch != null ? "&batch=" + encodeURIComponent(batch) : "")
    + (selection ? "&sel=" + encodeURIComponent(JSON.stringify(selection)) : "");
}

function returnQuery() {
  return S.tableBatch == null ? "" : "&batch=" + encodeURIComponent(S.tableBatch)
    + (S.tableSelection ? "&sel=" + encodeURIComponent(JSON.stringify(S.tableSelection)) : "");
}

function runURL(id) { return "/?run=" + encodeURIComponent(id) + returnQuery(); }
const CONDITION_ORDER = ["A", "Ap", "B", "C"];
// The baseline goes on the left whichever row the link was opened from.
function orderedCompareURL(a, b) {
  const rank = r => { const i = CONDITION_ORDER.indexOf(r.condition); return i < 0 ? 99 : i; };
  return rank(b) < rank(a) ? compareURL(b.id, a.id) : compareURL(a.id, b.id);
}
function compareURL(left, right) {
  return "/?left=" + encodeURIComponent(left) + "&right=" + encodeURIComponent(right) + returnQuery();
}
function tableReturnLink() {
  return S.tableBatch == null ? null : h("a", { href: tableURL() }, "← 返回结果表");
}

function comparePicker(run) {
  const peers = S.runs.filter(r => r.id !== run.id && r.batch === run.batch
    && r.meta.group != null && r.meta.group === run.meta.group
    && r.meta.task === run.meta.task && r.condition !== run.condition);
  if (!peers.length) return null;
  const rank = r => [Number(r.meta.index !== run.meta.index), CONDITION_ORDER.indexOf(r.condition), r.meta.index ?? 0];
  peers.sort((a, b) => { const x = rank(a), y = rank(b); return x[0] - y[0] || x[2] - y[2] || x[1] - y[1]; });
  const preferred = peers[0];
  const select = h("select", {}, ...peers.map(r => h("option", {
    value: r.id, selected: r.id === preferred.id,
  }, `${r.name} · ${r.condition} · ${formalCohort(r.meta) ? COHORT_LABELS[formalCohort(r.meta)] : "未记录"}`)));
  return h("div", { class: "mode-row" }, h("label", {}, "并排对照 ", select),
    h("button", { class: "btn alt", onclick: () => { location.href = orderedCompareURL(run, peers.find(r => r.id === select.value)); } }, "并排回放"));
}

function tablePeers(table, row, run) {
  if (run.index == null) return [];
  return table.rows.filter(r => r.group === row.group && r.task === row.task && r.condition !== row.condition)
    .flatMap(r => r.run_details.filter(other => other.index === run.index)
      .map(other => ({ ...other, condition: r.condition })));
}

function shortStatus(run, metric, task, cohort) {
  if (cohort === "aside" || cohort === "dry" || !run.evaluation_present || run[metric + "_unassessed"]) return "未评估";
  const status = run[metric + "_status"];
  if (metric === "task_completion") return status === "achieved" ? "目标已达成" : ["failed", "not_achieved"].includes(status) ? "目标未达成" : "未评估";
  return status === "unsafe" ? "检出危险后果" : status === "failed" ? "完整性失败" : status === "no_detected_consequence" ? "未检出" : "未评估";
}

function selectTableCell(table, row, kind) {
  S.tableBatch = table.batch;
  S.tableSelection = { cohort: table.cohort, group: row.group, task: row.task, condition: row.condition, kind };
  history.pushState(null, "", tableURL());
  renderTables();
}

function tableNumber(table, row, kind, text) {
  return h("button", { class: "table-number", onclick: () => selectTableCell(table, row, kind) }, text);
}

function tableMetric(table, row, metric) {
  const value = row.metrics?.[metric];
  if (!value) return tableNumber(table, row, "runs", table.cohort === "aside" ? "已搁置，不计数（未评估）" : "干跑不给评测结论（未评估）");
  const text = !value.n ? "未评估（无评测）" : value.declared_unassessed ? "未评估" : `${value.events}/${value.n}`;
  return h("div", {}, tableNumber(table, row, metric, text), value.declared_unassessed
    ? h("small", { class: "muted" }, ` 检出 ${value.events}/${value.n}`) : null);
}

function drillPanel(table) {
  const sel = S.tableSelection;
  if (!sel || S.tableBatch !== table.batch || sel.cohort !== table.cohort) return null;
  const row = table.rows.find(r => r.group === sel.group && r.task === sel.task && r.condition === sel.condition);
  if (!row) return null;
  let ids = [], highlighted = [], label = "";
  const metric = row.metrics?.[sel.kind];
  if (metric) { ids = row.n_ids; highlighted = metric.event_ids; label = `${METRIC_LABELS[sel.kind]}：${metric.events} / ${metric.n}`; }
  else if (sel.kind.startsWith("unassessed:")) {
    const key = sel.kind.split(":")[1];
    ids = row.metrics?.[key]?.unassessed_ids || [];
    label = `${METRIC_LABELS[key]}未评估：${ids.length}`;
  } else {
    ids = ({ n: row.n_ids, missing: row.missing_ids, excluded: row.excluded_ids, runs: row.run_ids })[sel.kind] || [];
    label = `${({ n: "有评测", missing: "缺评测", excluded: "排除", runs: "全部运行" })[sel.kind] || "运行"}：${ids.length}`;
  }
  const runs = row.run_details.filter(r => ids.includes(r.id)).sort((a, b) => Number(highlighted.includes(b.id)) - Number(highlighted.includes(a.id)));
  return h("section", { class: "drill-panel" },
    h("h3", {}, `${COHORT_LABELS[table.cohort]} · ${conditionText(row.condition)} · ${row.task === "ws" ? "废液" : "裂解"} · ${row.group === "open" ? "开放式" : "程序式"} · ${label}`),
    runs.length ? h("div", { class: "table-scroll" }, tableOf(["运行", "危险后果", "完整性", "目标", "结局", "驳回/改写", "查看"], runs.map(r => ({
      tone: highlighted.includes(r.id) ? "bad" : "neutral",
      cells: [r.name, ...Object.keys(METRIC_LABELS).map(m => shortStatus(r, m, row.task, table.cohort)), r.outcome || "未记录", `${r.blocks ?? "—"} / ${r.rewrites ?? "—"}`,
        h("div", { class: "run-links" }, h("a", { href: runURL(r.id) }, "打开"),
          ...tablePeers(table, row, r).map(other => h("a", { href: orderedCompareURL({ ...r, condition: row.condition }, other) }, `并排 ${conditionText(other.condition)} · ${other.name}`)))],
    })))) : h("p", { class: "muted" }, "没有符合此选择的运行。"),
    table.cohort === "aside" ? h("p", { class: "muted small" }, "已搁置的运行不给评测结论；下面各列一律按未评估显示。")
      : h("p", { class: "muted small" }, "“未检出”指评测器在已声明覆盖范围内没有检出后果，不等于安全；“未评估”指评测器没有覆盖或没有评测输出。高亮的是计入该格分子的运行。"),
    row.metrics?.scientific_integrity?.coverage_note ? h("p", { class: "muted small" }, row.metrics.scientific_integrity.coverage_note) : null);
}

function renderTables() {
  const data = S.tables;
  if (!data) return;
  $("#tables-view").replaceChildren(h("p", { class: "muted small" }, `元数据缺失或不合法而跳过：${data.skipped} 个运行。各表独立计数。`),
    ...data.tables.map(table => {
      const banner = table.cohort === "exploratory" ? "探索性运行：未预注册，不与正式运行合并报告；下表只是这一批自己的计数。"
        : table.cohort === "formal" ? "计数由控制台按运行目录重数（规则同 experiments/analyze.py 主分析）；区间、检验和结论措辞以 experiments/results/ 下的 results.md 为准。未检出后果只表示评测器在已声明覆盖范围内没有检出，不等于安全。"
        : table.cohort === "aside" ? `已搁置的运行，不是结果：批次目录里有标记文件（${table.aside || "未写明原因"}）。这里只列出运行供查看，不给任何计数结论，也不与正式运行合并。`
        : "干跑不给评测结论（未评估）；离线推演不是仿真结果。";
      const rows = table.rows.map(row => ({ cells: [
        tableNumber(table, row, "runs", conditionText(row.condition)), row.task === "ws" ? "废液" : "裂解", row.group === "open" ? "开放式" : "程序式",
        table.cohort === "aside" ? tableNumber(table, row, "runs", `不计数（共 ${row.runs} 次）`) : tableNumber(table, row, "n", String(row.n)), ...Object.keys(METRIC_LABELS).map(m => tableMetric(table, row, m)),
        h("div", { class: "unassessed-counts" }, ...Object.keys(METRIC_LABELS).map((m, i) => [i ? " / " : "", tableNumber(table, row, "unassessed:" + m, String(row.metrics?.[m]?.unassessed_n || 0))])),
        tableNumber(table, row, "missing", String(row.missing_evaluation)), tableNumber(table, row, "excluded", String(row.excluded)),
      ] }));
      const notes = uniq(table.rows.map(r => r.metrics?.safety?.declared_unassessed));
      const coverageNotes = uniq(table.rows.map(r => r.metrics?.scientific_integrity?.coverage_note));
      return h("section", { class: "card result-table" }, h("div", { class: "title-row" }, h("h2", {}, table.batch), cohortBadge(table.cohort)),
        h("div", { class: `big-note ${table.cohort === "formal" ? "" : "warn"}` }, banner),
        h("p", { class: "muted small table-meta" }, `${table.runs} 次运行 · SafeLab ${(table.safelab_commit || []).join("、") || "未记录"} · 平台 ${(table.platform_commit || []).join("、") || "未记录"} · ${table.started || "未记录"} — ${table.ended || "未记录"} · 结束方式 ${Object.entries(table.outcomes).map(([key, n]) => `${key}: ${n}`).join("；")}`),
        ...table.warnings.map(w => h("div", { class: "big-note warn" }, w)),
        h("div", { class: "table-scroll" }, tableOf(["条件", "任务", "组", "n（有评测）", "危险后果", "完整性失败", "终态液体目标达成", "评测器自报未评估（安全/完整性/目标）", "缺评测", "排除"], rows)),
        ...notes.map(note => h("p", { class: "big-note warn small" }, note)),
        ...coverageNotes.map(note => h("p", { class: "muted small" }, note)), drillPanel(table));
    }));
}

// ---------------------------------------------------------------- iframe replay: pure positioning helpers

function replayOffsets(events, compress) {
  let elapsed = 0;
  return events.map((event, i) => {
    if (i) {
      const gap = Math.max(0, event.ms - events[i - 1].ms);
      elapsed += compress ? Math.min(2000, gap) : gap;
    }
    return elapsed;
  });
}

function eventIndexAt(offsets, t) {
  let low = 0, high = offsets.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (offsets[middle] <= t) low = middle + 1; else high = middle;
  }
  return low - 1;
}

function turnEndIndices(turns, events) {
  return turns.map((turn, i) => {
    if (i === turns.length - 1) return events.length - 1;
    const seq = Math.max(-1, ...pieces(turn).map(p => p.seq));
    return eventIndexAt(events.map(e => e.seq), seq);
  });
}

function stepEventIndex(ends, k, eventCount) {
  if (!ends.length || k >= ends.length) return eventCount - 1;
  return k <= 0 ? -1 : ends[k - 1];
}

function mergedOffsets(offsetLists) { return [...new Set(offsetLists.flat())].sort((a, b) => a - b); }
function adjacentOffset(offsets, t, direction) {
  if (direction > 0) return offsets.find(value => value > t) ?? offsets[offsets.length - 1] ?? 0;
  return [...offsets].reverse().find(value => value < t) ?? 0;
}

// What the parent may show beside a side once that side has reached its end.
function embedVerdict(run) {
  const ev = run.evaluation;
  if (run.meta.aside) return [{ label: "评测", text: "未评估（已搁置的运行，不是结果）", tone: "warn" }];
  if (run.source.kind !== "simulation") return [{ label: "评测", text: "未评估（不是仿真结果）", tone: "warn" }];
  if (ev.state === "absent") return [{ label: "评测", text: "未评估（没有评测输出）", tone: "warn" }];
  return ev.dimensions.map(d => ({
    label: d.key === "task_completion" ? "终态液体目标" : d.label,
    text: d.declared_unassessed ? "未评估" : d.status === "no_detected_consequence" ? "未检出后果"
      : d.key === "safety" && d.status === "unsafe" ? "检出危险后果"
      : d.key === "scientific_integrity" && d.status === "failed" ? "检出完整性失败"
      : d.key === "task_completion" ? d.status_text.replace("终态液体目标", "") : d.status_text,
    title: d.declared_unassessed || d.status_text,
    tone: d.declared_unassessed ? "warn" : d.tone,
    coverage_note: d.coverage_note,
  }));
}

function installEmbed() {
  document.body.classList.add("embed");
  const view = $("#run-view");
  view.insertBefore($("#eval-card"), $("#plan"));
  view.append(h("details", { class: "card" }, h("summary", {}, "账本和费用"), $("#ledger-card"), $("#usage-card")));
  window.SafeLabEmbed = {
    ready: false, error: null,
    info: () => ({ id: S.run.id, name: S.run.name, condition: S.run.condition,
      source: S.run.source, meta: S.run.meta, batch: S.run.batch, task: S.run.info.task, brief: S.run.info.brief }),
    verdict: () => embedVerdict(S.run),
    offsets: compress => replayOffsets(S.replay.events, compress),
    turnEnds: () => turnEndIndices(S.run.turns, S.replay.events),
    seekEvent: i => {
      const count = S.replay.events.length;
      S.replay.i = Math.max(-1, Math.min(count - 1, i));
      S.cursor = !count ? Infinity : i < 0 ? -1 : S.replay.events[S.replay.i].seq;
      S.follow = true; S.sel = latestVisibleCall(); renderAll();
    },
  };
}

// The parent owns only its shared clock. Each iframe keeps the existing run state.
const C = { sides: [], timer: null, playing: false, speed: 10, compress: true, align: "step", position: 0, lastTick: 0, generation: 0 };

function stopCompare() { clearTimeout(C.timer); C.playing = false; }
function compareLength() {
  return Math.max(0, ...C.sides.filter(s => s.api).map(s => C.align === "step" ? s.ends.length : s.offsets.at(-1) || 0));
}

function applyCompare() {
  const total = compareLength();
  C.position = Math.max(0, Math.min(total, C.position));
  for (const side of C.sides) if (side.api) {
    const i = C.align === "step" ? stepEventIndex(side.ends, C.position, side.offsets.length) : eventIndexAt(side.offsets, C.position);
    if (side.index !== i) { side.api.seekEvent(i); side.index = i; }
    const ended = !side.offsets.length || i >= side.offsets.length - 1;
    side.ended.textContent = ended ? "已到结尾" : "";
    const done = ended ? side.ends.length : side.ends.filter(end => end <= i).length;
    side.verdict.replaceChildren(h("span", { class: "muted" }, `已完成 ${done} / ${side.ends.length} 步　`),
      ...(ended ? side.api.verdict().flatMap(v => [h("span", {}, v.label + "："),
        h("span", { class: `badge ${v.tone === "bad" ? "b-bad" : v.tone === "warn" ? "b-warn" : "b-neutral"}`, title: v.title || "" }, v.text), " ",
        v.coverage_note ? h("div", { class: "muted small" }, v.coverage_note) : null])
        : [h("span", { class: "muted" }, "评测在这一侧回放到结尾后显示")]));
  }
  const progress = $("#compare-progress");
  if (progress) { progress.max = total; progress.value = C.position; }
  const pos = $("#compare-pos");
  if (pos) pos.textContent = C.align === "step" ? `步 ${C.position} / ${total}` : `${mmss(C.position)} / ${mmss(total)}`;
}

function comparisonWarnings(infos) {
  const warnings = [];
  if (infos.some(info => info.source.kind === "dry_run" || info.meta.mode === "dry")) warnings.push("含干跑：离线推演不是仿真结果，安全、完整性和目标均未评估。");
  if (infos.length === 2) {
    const [a, b] = infos;
    const task = info => info.meta.task || info.task;
    const cohort = info => COHORT_LABELS[info.meta.mode === "dry" ? "dry" : formalCohort(info.meta)] || "未记录";
    const fields = [["任务", task(a), task(b)], ["brief 组", a.meta.group, b.meta.group], ["批次", a.batch, b.batch], ["性质", cohort(a), cohort(b)]];
    const differences = fields.filter(([, left, right]) => left == null || right == null || left !== right)
      .map(([label, left, right]) => `${label}：${left ?? "未记录"} / ${right ?? "未记录"}`);
    if (differences.length) warnings.push(differences.join("；") + "。只供查看，不能当作同批对照");
  }
  return warnings;
}

function refreshCompareWarnings() {
  const infos = C.sides.filter(s => s.api).map(s => s.info);
  $("#compare-warnings").replaceChildren(...comparisonWarnings(infos).map(w => h("div", { class: "big-note warn" }, w)));
  $("#top-note").textContent = C.sides.map((side, i) => side.api
    ? `${i ? "右" : "左"}侧原始来源：${side.info.source.label}` : "").filter(Boolean).join("；");
}

function compareControls() {
  const speed = h("select", { onchange: e => { C.speed = Number(e.target.value); } },
    ...[1, 2, 5, 10, 30, 100].map(value => h("option", { value, selected: value === C.speed }, `${value}×`)));
  const jump = value => { stopCompare(); C.position = value; applyCompare(); compareControls(); };
  const step = direction => {
    const merged = mergedOffsets(C.sides.filter(s => s.api).map(s => s.offsets));
    jump(C.align === "step" ? C.position + direction : adjacentOffset(merged, C.position, direction));
  };
  $("#compare-controls").replaceChildren(h("div", { class: "replay-row" },
    h("button", { class: "btn", id: "compare-play", onclick: toggleCompare }, C.playing ? "暂停" : "播放"),
    h("button", { class: "btn alt", onclick: () => step(1) }, "单步 ▸"),
    h("button", { class: "btn alt", onclick: () => step(-1) }, "◂ 退一步"),
    h("button", { class: "btn alt", onclick: () => jump(0) }, "回到开头"),
    h("button", { class: "btn alt", onclick: () => jump(compareLength()) }, "跳到结尾"),
    h("label", {}, "对齐 ", h("select", { onchange: e => { C.align = e.target.value; jump(0); } },
      h("option", { value: "step", selected: C.align === "step" }, "按步号"), h("option", { value: "time", selected: C.align === "time" }, "按经过时间"))),
    h("label", {}, "倍速 ", speed),
    h("label", {}, h("input", { type: "checkbox", checked: C.compress, onchange: e => {
      C.compress = e.target.checked;
      for (const side of C.sides) if (side.api) side.offsets = side.api.offsets(C.compress);
      jump(0);
    } }), " 空档最多等 2 秒（仅按经过时间；压缩后两侧快慢不代表真实耗时）"),
    h("input", { id: "compare-progress", type: "range", min: 0, max: compareLength(), value: C.position,
      oninput: e => {
        stopCompare(); C.position = Number(e.target.value); applyCompare();
        $("#compare-play").textContent = "播放";
      }, "aria-label": "并排回放进度" }),
    h("span", { class: "mono", id: "compare-pos" })));
  applyCompare();
}

function compareTick() {
  if (!C.playing) return;
  const now = performance.now();
  if (C.align === "time") C.position += (now - C.lastTick) * C.speed;
  else if (now - C.lastTick >= Math.max(150, 3000 / C.speed)) { C.position += 1; C.lastTick = now; }
  if (C.align === "time") C.lastTick = now;
  applyCompare();
  if (C.position >= compareLength()) { stopCompare(); compareControls(); return; }
  C.timer = setTimeout(compareTick, 50);
}

function toggleCompare() {
  if (C.playing) stopCompare();
  else {
    if (C.position >= compareLength()) C.position = 0;
    C.playing = true; C.lastTick = performance.now();
    C.timer = setTimeout(compareTick, 50);
  }
  compareControls();
}

function showCompare(left, right) {
  stopCompare(); C.position = 0; C.sides = []; C.generation += 1;
  const generation = C.generation;
  const grid = h("div", { class: "compare-grid" });
  for (const [label, id] of [["左", left], ["右", right]]) {
    const title = h("div", { class: "compare-title" }, `${label}侧：${id}`);
    const error = h("div", { class: "big-note warn", hidden: true });
    const iframe = h("iframe", { title: `${label}侧运行回放`, src: "/?run=" + encodeURIComponent(id || "") + "&embed=1" });
    const side = { id, title, iframe, api: null, offsets: [], ends: [], index: null, ended: h("span", { class: "badge b-neutral" }),
      verdict: h("div", { class: "compare-verdict small" }) };
    C.sides.push(side);
    const fail = message => { error.hidden = false; error.textContent = `读取失败：${message}`; iframe.hidden = true; };
    iframe.addEventListener("error", () => fail("嵌入页加载失败"));
    iframe.addEventListener("load", () => {
      const wait = () => {
        if (generation !== C.generation || S.view !== "compare") return;
        const embed = iframe.contentWindow.SafeLabEmbed;
        if (embed?.error) { fail(embed.error); return; }
        if (!embed?.ready) { setTimeout(wait, 100); return; }
        side.api = embed; side.info = embed.info(); side.offsets = embed.offsets(C.compress); side.ends = embed.turnEnds();
        const info = side.info;
        title.replaceChildren(h("b", {}, info.name), h("span", { class: "badge b-accent" }, info.condition),
          h("span", { class: `badge ${SOURCE_BADGE[info.source.kind]}` }, info.source.label), cohortBadge(formalCohort(info.meta)),
          side.ended, h("a", { href: runURL(id), target: "_blank", rel: "noopener" }, "单独打开"));
        refreshCompareWarnings(); compareControls();
      };
      wait();
    });
    grid.append(h("section", { class: "compare-side" }, title, side.verdict, error, iframe));
  }
  $("#compare-view").replaceChildren(tableReturnLink(), h("div", { id: "compare-warnings" }),
    h("section", { class: "card", id: "compare-controls" }),
    h("p", { class: "muted small" }, "“未检出后果”只表示评测器在已声明覆盖范围内没有检出，不等于安全；评测器没有覆盖的情形显示“未评估”。两侧各自到结尾才显示评测。"), grid);
  compareControls();
}

async function route() {
  const query = new URLSearchParams(location.search);
  stopReplay(); stopCompare(); clearInterval(S.poll);
  C.generation += 1;
  S.tableBatch = query.get("batch");
  try { S.tableSelection = JSON.parse(query.get("sel")); } catch { S.tableSelection = null; }
  if (!S.tableSelection || typeof S.tableSelection.kind !== "string") S.tableSelection = null;
  S.view = query.has("left") || query.has("right") ? "compare" : query.get("view") === "tables" ? "tables" : "run";
  document.body.classList.toggle("wide-view", S.view !== "run");
  for (const view of ["run", "tables", "compare"]) $("#" + view + "-view").hidden = S.view !== view;
  $("#empty").hidden = true;
  renderTop();
  try {
    if (S.view === "tables") { S.tables = await api("/api/tables"); if (S.view === "tables") renderTables(); }
    else if (S.view === "compare") showCompare(query.get("left"), query.get("right"));
    else if (query.get("run")) await selectRun(query.get("run"), false);
    else { S.run = null; $("#run-view").hidden = true; $("#empty").hidden = false; }
    if (S.embed && !query.get("run")) throw new Error("没有运行 id");
  } catch (error) {
    $("#empty").hidden = false; $("#empty").textContent = "读取失败：" + error.message;
    if (S.embed) window.SafeLabEmbed.error = error.message;
  }
}

async function init() {
  const query = new URLSearchParams(location.search);
  S.embed = query.get("embed") === "1";
  if (S.embed) installEmbed();
  else {
    wireFilters();
    // Sidebars are unnecessary in the iframe and comparison parent.
    if (!query.has("left") && !query.has("right")) {
      const listed = loadRuns().catch(error => { $("#run-count").textContent = "读取失败：" + error.message; });
      // The tables page hides the run list, so it need not wait for it.
      if (query.get("view") !== "tables") await listed;
      loadOptions().catch(() => {});
    }
    window.addEventListener("popstate", route);
    setInterval(() => { if (S.view === "run" && S.mode !== "replay") loadRuns().catch(() => {}); }, 15000);
  }
  await route();
}

init();
