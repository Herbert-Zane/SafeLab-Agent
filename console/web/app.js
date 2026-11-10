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
  runs: [], filters: { condition: "", task: "", model: "", source: "" },
  rid: null, run: null, mode: "static", // static | live | replay
  cursor: Infinity, sel: null, follow: true, ledgers: {}, poll: null,
  replay: { events: [], i: 0, playing: false, speed: 10, compress: false, timer: null },
  jobs: [], options: null,
};

const SOURCE_BADGE = { dry_run: "b-dry", simulation: "b-sim", unknown: "b-unknown" };
const DECISION = { pass: ["放行", "b-ok"], block: ["驳回", "b-bad"], rewrite: ["改写", "b-rewrite"] };
const CHANNEL = { rules: "仅规则通道", llm: "仅 LLM 通道", "rules+llm": "规则 + LLM 合议", none: "未触发审查" };
const STRATEGY = { rewrite: "按驳回理由重新提议", replan: "重规划后提议", remediate: "补救提议" };
const STATUS = {
  complete: ["已执行", "b-ok"], finished: ["结束（finish）", "b-accent"],
  stopped: ["审查器终止", "b-bad"], awaiting: ["等待执行", "b-neutral"],
  no_action: ["无动作", "b-neutral"],
};
const NOTE_TITLE = {
  reflect: "反思", replan: "重规划", refusal_limit: "驳回次数达上限", disagreement: "两通道分歧",
  empty_reply: "空回复", call_error: "调用出错", retry: "重试", fault: "注入故障", budget_stop: "预算熔断",
};
const REFLECT_KIND = {
  critic_rejected: "审查器驳回", precondition_failed: "前置条件不满足",
  expectation_mismatch: "结果与预期不符", empty_reply: "空回复",
};
const REFLECT_STRATEGY = { rewrite: "按理由改提议", replan: "重规划", remediate: "补救", retry: "重试", stop: "安全终止" };
const STAGE_STATUS = { current: "进行中", done: "完成", pending: "待做", failed: "失败" };

// ---------------------------------------------------------------- helpers

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

const seen = (piece) => piece != null && (piece.seq == null || piece.seq <= S.cursor);
const money = (v) => (v == null ? "—" : "$" + Number(v).toFixed(4));
const secs = (v) => (v == null ? "—" : Number(v).toFixed(1) + " s");
const num = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US"));
const jsonText = (v) => JSON.stringify(v);
const clock = (iso) => (iso ? iso.slice(11, 19) : "");

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
}

function renderRunList() {
  const f = S.filters;
  const rows = S.runs.filter((r) => (!f.condition || r.condition === f.condition) && (!f.task || r.task === f.task)
    && (!f.model || r.model === f.model) && (!f.source || r.source_label === f.source));
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

async function selectRun(rid) {
  stopReplay();
  clearInterval(S.poll);
  S.rid = rid; S.run = null; S.sel = null; S.ledgers = {}; S.follow = true; S.cursor = Infinity;
  renderRunList();
  const run = await api(`/api/run?id=${encodeURIComponent(rid)}`);
  S.run = run;
  S.mode = run.state === "running" ? "live" : "static";
  if (S.mode === "live") startPolling();
  $("#empty").hidden = true;
  $("#run-view").hidden = false;
  S.sel = lastTurnCall();
  renderAll();
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
  const stateBadge = { running: ["进行中", "b-live"], finished: ["已结束", "b-neutral"], stalled: ["日志已停止更新", "b-warn"] }[run.state];
  $("#run-head").replaceChildren(
    h("div", { class: "title-row" }, h("span", { class: "name" }, run.name),
      h("span", { class: `badge ${SOURCE_BADGE[run.source.kind]}` }, run.source.label),
      h("span", { class: "badge b-accent" }, run.condition_label),
      run.reviewer ? null : h("span", { class: "badge b-warn" }, "无审查器"),
      stateBadge ? h("span", { class: `badge ${stateBadge[1]}` }, stateBadge[0]) : null),
    h("div", { class: "head-grid" },
      kv("任务", info.task), kv("模型", info.model), kv("简报", info.brief),
      kv("结局", info.outcome), kv("模型调用", info.model_calls),
      kv("完成/失败动作", `${info.actions_completed ?? "—"} / ${info.actions_failed ?? "—"}`),
      kv("用时", secs(run.duration_s)), kv("数据划分", info.split),
      kv("审查器", info.critic ? `${info.critic.mode}（LLM 触发：${info.critic.llm_trigger}）` : null)),
    info.outcome_detail ? h("details", {}, h("summary", {}, "智能体的结束说明（自述，未经核实）"), h("pre", { class: "text" }, info.outcome_detail)) : null,
    run.notes.length ? h("div", { class: "note" }, run.notes.join("；")) : null);
}

function kv(key, value) {
  if (value == null || value === "") return null;
  return h("span", {}, h("b", {}, key + " "), String(value));
}

function renderModebar() {
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
  box.append(h("div", {}, "状态：", llm.status, a.decision ? ["　结论：", h("b", {}, (DECISION[a.decision] || [a.decision])[0])] : null,
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
  if (seen(ret)) {
    const src = ret.source === "critic_rewrite" ? "审查器改写后的动作" : ret.source === "actor" ? "智能体提议的动作" : `来源 ${ret.source}`;
    rows.push(h("div", { class: "exec" }, h("b", {}, "返回平台："), h("code", {}, actionLine(ret.action)), h("span", { class: "muted small" }, `　（${src}）`)));
  } else if (turn.candidates.length) {
    rows.push(h("div", { class: "pending-line" }, "尚未返回平台…"));
  }
  const ex = turn.executed;
  if (seen(ex)) {
    rows.push(h("div", { class: "exec" }, h("b", {}, "平台报告："),
      h("span", { class: `badge ${ex.status === "complete" ? "b-ok" : "b-bad"}` }, ex.status === "complete" ? "已执行" : ex.status),
      ex.error ? h("span", { class: "reason" }, " " + jsonText(ex.error)) : null));
    const pf = turn.platform;
    if (pf && pf.result) rows.push(h("div", { class: "exec muted" }, "执行结果：" + jsonText(pf.result) + (pf.simulation_time_s != null ? `；仿真钟 ${pf.simulation_time_s} s` : "")));
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
  if (turn.decide_s != null) pieces_.push(`决策耗时 ${secs(turn.decide_s)}`);
  if (turn.review_latency_s) pieces_.push(`其中审查 ${secs(turn.review_latency_s)}`);
  if (turn.cost_usd) pieces_.push(`费用 ${money(turn.cost_usd)}`);
  const tokens = turn.usage.filter(seen).reduce((a, u) => a + ((u.usage || {}).input_tokens || 0) + ((u.usage || {}).output_tokens || 0), 0);
  if (tokens) pieces_.push(`tokens ${num(tokens)}`);
  return pieces_.length ? h("div", { class: "metrics" }, pieces_.join("　·　")) : null;
}

function turnView(turn) {
  const visibleCands = turn.candidates.filter((c) => seen(c.proposed) || seen(c.review));
  turn.review_expected = S.run.reviewer;
  const sev = turn.severity;
  const badge = STATUS[turn.status] || [turn.status, "b-neutral"];
  const stage = (turn.returned && turn.returned.stage) || (turn.candidates[0] && turn.candidates[0].proposed && turn.candidates[0].proposed.stage);
  const head = h("div", { class: "turn-head" },
    h("span", { class: "no" }, `步 ${turn.step}`),
    stage && stage.name ? h("span", { class: "badge b-neutral" }, `阶段 ${stage.index != null ? stage.index + "/" + stage.of + " " : ""}${stage.name}`) : null,
    turn.blocked ? h("span", { class: "badge b-bad" }, `驳回 ${turn.blocked} 次`) : null,
    turn.rewritten ? h("span", { class: "badge b-rewrite" }, "已改写") : null,
    h("span", { class: `badge ${badge[1]}` }, badge[0]),
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
  if (ledger.robot) parts.push(robotLine(ledger.robot, hit));
  parts.push(h("h3", {}, "容器"), tableOf(["容器", "体积 µL", "成分 µL", "开闭", "位置"],
    Object.entries(ledger.containers || {}).map(([id, c]) => ({
      changed: hit(`containers.${id}`),
      cells: [id, fmtValue(c.volume_ul), comp(c.components_ul), c.closure_status || "—", c.location || "—"],
    }))));
  const tips = Object.entries(ledger.tips || {});
  parts.push(h("h3", {}, "枪头与接触史"));
  if (!tips.length) parts.push(h("div", { class: "muted small" }, "无枪头"));
  for (const [id, tip] of tips) {
    const tipChanged = hit(`tips.${id}`);
    const contacts = tip.contacts || [];
    parts.push(h("div", { class: "eval-dim" + (tipChanged ? " tone-warn" : "") },
      h("div", {}, h("b", {}, id), `　${tip.tip_type || ""}　状态 `, h("span", { class: hit(`tips.${id}.status`) ? "chgv" : "" }, tip.status || "—"),
        `　位置 ${tip.location || "—"}`, tip.held_volume_ul ? `　吸持 ${fmtValue(tip.held_volume_ul)} µL（${comp(tip.components_ul)}）` : ""),
      data.kind === "observation" ? null : contacts.length
        ? h("ul", { class: "contacts" }, ...contacts.map((c, i) => h("li", { class: hit(`tips.${id}.contacts[${i}]`) ? "chgv" : "" },
          `步 ${c.step} ${c.action} → ${c.container}（接触前：${comp(c.composition_before_ul)}；接触后：${comp(c.composition_after_ul)}）`)))
        : h("div", { class: "muted small" }, "尚未接触任何容器")));
  }
  const devices = Object.entries(ledger.devices || {});
  if (devices.length) {
    parts.push(h("h3", {}, "设备"), tableOf(["设备", "状态", "已装载", "程序"], devices.map(([id, d]) => ({
      changed: hit(`devices.${id}`), cells: [id, d.status || "—", (d.loaded_entities || []).join(", ") || "—", d.program || "—"],
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

const ROBOT_FIELDS = { held_object: "手持", attached_tip: "已装枪头", pipette_type: "移液器规格", tool_held: "手中有工具" };
const plainValue = (v) => (v == null || v === "" ? "无" : v === true ? "是" : v === false ? "否" : String(v));

// The robot row of the ledger as labelled values; fields this page does not know are listed as they are.
function robotLine(robot, hit) {
  const known = Object.entries(ROBOT_FIELDS).filter(([key]) => key in robot || key !== "tool_held").map(([key, label]) =>
    h("span", { class: hit(`robot.${key}`) ? "chgv" : "" }, h("b", {}, label + " "), plainValue(robot[key])));
  const rest = Object.entries(robot).filter(([key, v]) => !(key in ROBOT_FIELDS) && v != null && v !== "")
    .map(([key, v]) => h("span", { class: hit(`robot.${key}`) ? "chgv" : "" }, h("b", {}, key + " "), fmtValue(v)));
  return h("div", { class: "head-grid small" }, h("span", {}, h("b", {}, "机器人")), ...known, ...rest);
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
    ...rows.map((r) => h("tr", { class: r.changed ? "chg" : "" }, ...r.cells.map((c) => h("td", {}, c)))));
}

// ---------------------------------------------------------------- usage

function renderUsage() {
  const run = S.run;
  const turns = run.turns.filter(turnVisible);
  const rowsSeen = turns.flatMap((t) => t.usage.filter(seen));
  const sum = (f) => rowsSeen.reduce((a, u) => a + (f(u) || 0), 0);
  const byRole = {};
  for (const u of rowsSeen) {
    const r = (byRole[u.role || "?"] ||= { calls: 0, inp: 0, out: 0, cost: 0, lat: 0 });
    r.calls += 1; r.inp += (u.usage || {}).input_tokens || 0; r.out += (u.usage || {}).output_tokens || 0;
    r.cost += u.cost_usd || 0; r.lat += u.latency_s || 0;
  }
  const maxDecide = Math.max(15, ...turns.map((t) => t.decide_s || 0));
  const plat = run.usage.platform;
  const box = $("#usage-card");
  box.replaceChildren(h("h2", {}, "Token、费用、时延"),
    h("div", { class: "head-grid" }, kv("子调用", rowsSeen.length || null), kv("输入 tokens", num(sum((u) => (u.usage || {}).input_tokens))),
      kv("输出 tokens", num(sum((u) => (u.usage || {}).output_tokens))), kv("费用（按列表价估算）", money(sum((u) => u.cost_usd))),
      kv("子调用时延合计", secs(sum((u) => u.latency_s)))),
    Object.keys(byRole).length ? tableOf(["角色", "调用", "输入", "输出", "费用", "时延"], Object.entries(byRole).map(([k, v]) => ({
      cells: [{ planner: "规划器", actor: "执行者", critic: "审查器" }[k] || k, v.calls, num(v.inp), num(v.out), money(v.cost), secs(v.lat)] }))) : null,
    h("h3", {}, "每步可见时延（红色表示超过 15 秒）"),
    h("table", {}, ...turns.map((t) => h("tr", {}, h("td", {}, `步 ${t.step}`),
      h("td", { style: "width:55%" }, h("div", { class: "bar" + ((t.decide_s || 0) > 15 ? " over" : ""), style: `width:${Math.max(1, 100 * (t.decide_s || 0) / maxDecide)}%` })),
      h("td", {}, secs(t.decide_s)), h("td", {}, money(t.cost_usd))))),
    plat && plat.cost_usd != null ? h("div", { class: "muted small" }, `平台汇总：${num(plat.total_tokens)} tokens，${money(plat.cost_usd)}（${plat.cost_basis || ""}）`) : null);
}

// ---------------------------------------------------------------- evaluator

function renderEval() {
  const ev = S.run.evaluation;
  const box = $("#eval-card");
  const finished = S.cursor === Infinity || S.cursor >= lastSeq();
  const title = h("h2", {}, "评测器");
  if (!finished) { box.replaceChildren(title, h("div", { class: "muted" }, "评测在回合结束后产出；回放尚未到结尾。")); return; }
  if (ev.state === "absent") {
    box.replaceChildren(title, h("div", { class: "big-note warn" }, ev.headline), h("div", { class: "muted small" }, ev.detail));
    return;
  }
  const parts = [title];
  if (ev.banner) parts.push(h("div", { class: "big-note warn" }, ev.banner));
  const ex = ev.execution_status || {};
  parts.push(h("div", { class: "small" }, `执行状态：${ex.status || "—"}${ex.reason ? "（" + ex.reason + "）" : ""}；仿真时间 ${ev.simulation_time_s ?? "—"} s`));
  const found = ev.dimensions.reduce((n, d) => n + d.consequences.length, 0);
  parts.push(h("div", { class: "muted small" }, found ? (ev.trace_basis_text || "") : "评测文件里没有后果记录，无可对应的步骤。"));
  for (const d of ev.dimensions) {
    parts.push(h("div", { class: `eval-dim tone-${d.tone}` },
      h("div", {}, h("b", {}, d.label + "　"), h("span", { class: `badge ${d.tone === "bad" ? "b-bad" : d.tone === "warn" ? "b-warn" : "b-neutral"}` }, d.status_text)),
      ...d.consequences.map((c) => h("div", { class: "small" },
        `后果 ${c.type || ""}（${c.category || ""}）：${entitiesText(c.entities)}，发生于 ${c.occurred_time_s ?? "?"} s。`,
        whereLink(c.where))),
      d.coverage.length ? h("div", { class: "muted small" }, `已声明覆盖：${d.coverage.length} 项`) : h("div", { class: "muted small" }, "没有声明覆盖"),
      ...d.checks.map((c) => h("div", { class: "small" }, `目标检查：${jsonText(c)}`))));
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
  for (const [id, key] of [["#f-condition", "condition"], ["#f-task", "task"], ["#f-model", "model"], ["#f-source", "source"]]) {
    $(id).addEventListener("change", (e) => { S.filters[key] = e.target.value; renderRunList(); });
  }
  $("#s-go").addEventListener("click", startRun);
}

async function init() {
  wireFilters();
  renderTop();
  try {
    await loadRuns();
    await loadOptions();
    const wanted = new URLSearchParams(location.search).get("run");
    if (wanted) selectRun(wanted);
  } catch (error) {
    $("#run-count").textContent = "读取失败：" + error.message;
  }
  setInterval(() => { if (!S.run || S.mode !== "replay") loadRuns().catch(() => {}); }, 15000);
}

init();
