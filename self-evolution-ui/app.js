const state = {
  token: "",
  presets: [],
  runtime: null,
  liveReadiness: null,
  readinessLoading: false,
  scenario: null,
  run: null,
  page: "process",
  selectedEventId: null,
  inspectorPinned: false,
  selectedTestId: null,
  testFilter: "all",
  testSearch: "",
  pollTimer: null,
  elapsedTimer: null,
  pollErrors: 0,
  graphSequence: 0,
  recoveryOfRunId: null,
};

const demoProfiles = {
  quick: {
    preset: "demo",
    workers: 2,
    model: "deepseek/deepseek-v4-pro",
    tests: 6,
    label: "короткое демо",
  },
  full: {
    preset: "full",
    workers: 4,
    model: "deepseek/deepseek-v4-pro",
    tests: 26,
    label: "полную проверку",
  },
};

const ui = {
  pageTabs: [...document.querySelectorAll("[data-page]")],
  pages: [...document.querySelectorAll("[data-page-panel]")],
  ouroborosMark: document.getElementById("ouroboros-mark"),
  runtimeName: document.getElementById("runtime-name"),
  runtimeModel: document.getElementById("runtime-model"),
  headerRunState: document.getElementById("header-run-state"),
  headerRunId: document.getElementById("header-run-id"),
  headerElapsed: document.getElementById("header-elapsed"),
  miniStatus: document.getElementById("mini-status"),
  miniMode: document.getElementById("mini-mode"),
  miniPhase: document.getElementById("mini-phase"),
  miniElapsed: document.getElementById("mini-elapsed"),
  miniArchitecture: document.getElementById("mini-architecture"),
  miniRules: document.getElementById("mini-rules"),
  miniGate: document.getElementById("mini-gate"),
  miniLatestEvent: document.getElementById("mini-latest-event"),
  agentsTabCount: document.getElementById("agents-tab-count"),
  testsTabLabel: document.getElementById("tests-tab-label"),
  testsTabCount: document.getElementById("tests-tab-count"),
  demoProfileRadios: [...document.querySelectorAll("input[name='demo-profile']")],
  demoProfileOptions: [...document.querySelectorAll("[data-demo-profile-option]")],
  preset: document.getElementById("preset-select"),
  seed: document.getElementById("seed-input"),
  workers: document.getElementById("workers-select"),
  execution: document.getElementById("execution-select"),
  model: document.getElementById("model-select"),
  modelPicker: document.getElementById("model-picker"),
  modelHint: document.getElementById("model-hint"),
  executionRadios: [...document.querySelectorAll("input[name='execution-mode']")],
  executionOptions: [...document.querySelectorAll("[data-execution-option]")],
  generate: document.getElementById("generate-button"),
  runButton: document.getElementById("run-button"),
  runButtonLabel: document.getElementById("run-button-label"),
  paidWrap: document.getElementById("paid-confirmation-wrap"),
  paid: document.getElementById("paid-confirmation"),
  liveReadiness: document.getElementById("live-readiness"),
  liveReadinessStatus: document.getElementById("live-readiness-status"),
  liveReadinessGrid: document.getElementById("live-readiness-grid"),
  liveReadinessReason: document.getElementById("live-readiness-reason"),
  refreshReadinessButton: document.getElementById("refresh-readiness-button"),
  launchTitle: document.getElementById("launch-title"),
  launchDetail: document.getElementById("launch-detail"),
  scenarioState: document.getElementById("scenario-state"),
  statusIndicator: document.getElementById("status-indicator"),
  statusText: document.getElementById("status-text"),
  statusDetail: document.getElementById("status-detail"),
  failureRecovery: document.getElementById("failure-recovery"),
  failureRecoveryTitle: document.getElementById("failure-recovery-title"),
  failureRecoveryCopy: document.getElementById("failure-recovery-copy"),
  failureErrorCode: document.getElementById("failure-error-code"),
  recoveryLocalButton: document.getElementById("recovery-local-button"),
  scenarioPreview: document.getElementById("scenario-preview"),
  scenarioTitle: document.getElementById("scenario-preview-title"),
  scenarioId: document.getElementById("scenario-id"),
  scenarioSummary: document.getElementById("scenario-summary"),
  scenarioStats: document.getElementById("scenario-stats"),
  scenarioChecks: document.getElementById("scenario-checks"),
  progressValue: document.getElementById("progress-value"),
  progressBar: document.getElementById("progress-bar"),
  phaseValue: document.getElementById("phase-value"),
  phaseDescription: document.getElementById("phase-description"),
  phaseTrack: document.getElementById("phase-track"),
  architectureCheckpoints: document.getElementById("architecture-checkpoints"),
  liveProcess: document.getElementById("live-process"),
  liveEvidence: document.getElementById("live-evidence"),
  liveEvidenceMeta: document.getElementById("live-evidence-meta"),
  liveTaskList: document.getElementById("live-task-list"),
  watchLinks: [...document.querySelectorAll("[data-watch-page]")],
  laneScale: document.getElementById("lane-scale"),
  swimlanes: document.getElementById("swimlanes"),
  liveGraph: document.getElementById("live-graph"),
  graphCaption: document.getElementById("graph-caption"),
  inspectorBody: document.getElementById("event-inspector-body"),
  eventCount: document.getElementById("event-count"),
  eventLog: document.getElementById("event-log"),
  parallelismValue: document.getElementById("parallelism-value"),
  orchestrationDag: document.getElementById("orchestration-dag"),
  agentsSummary: document.getElementById("agents-summary"),
  agentGrid: document.getElementById("agent-grid"),
  testsTitle: document.getElementById("tests-title"),
  testsProgress: document.getElementById("tests-progress"),
  testFilters: [...document.querySelectorAll("[data-test-filter]")],
  testSearch: document.getElementById("test-search"),
  testStatusBar: document.getElementById("test-status-bar"),
  testTableBody: document.getElementById("test-table-body"),
  testDetail: document.getElementById("test-detail"),
  architectureComparison: document.getElementById("architecture-comparison"),
  architectureChangeStatus: document.getElementById("architecture-change-status"),
  architectureDiffWrap: document.getElementById("architecture-diff-wrap"),
  architectureDiff: document.getElementById("architecture-diff"),
  causalChain: document.getElementById("causal-chain"),
  ruleChangeStatus: document.getElementById("rule-change-status"),
  ruleChangeBody: document.getElementById("rule-change-body"),
  gateSummary: document.getElementById("gate-summary"),
  resultMode: document.getElementById("result-mode"),
  resultEngine: document.getElementById("result-engine"),
  exportReportButton: document.getElementById("export-report-button"),
  artifactCount: document.getElementById("artifact-count"),
  artifactList: document.getElementById("artifact-list"),
};

const phaseDefinitions = [
  { id: "generated", label: "Данные" },
  { id: "planning", label: "План" },
  { id: "reviewing", label: "Parallel review" },
  { id: "remediating", label: "Remediation" },
  { id: "testing", label: "Test shards" },
  { id: "rereview", label: "Re-review" },
  { id: "gating", label: "Gate" },
];

const phaseAliases = {
  idle: -1,
  generated: 0,
  generation: 0,
  generating: 0,
  planning: 1,
  planned: 1,
  fan_out: 2,
  baseline_tests: 2,
  reviewing: 2,
  review: 2,
  parallel_review: 2,
  remediating: 3,
  remediation: 3,
  patching: 3,
  evolving_rules: 3,
  testing: 4,
  tests: 4,
  candidate_tests: 4,
  fitness: 4,
  rereview: 5,
  re_review: 5,
  verifying: 5,
  gating: 6,
  gate: 6,
};

const friendlyErrors = {
  paid_run_confirmation_required: "Подтверди платные live-вызовы OpenRouter.",
  run_already_active: "Один E2E уже выполняется. Интерфейс продолжит следить за ним.",
  scenario_not_found: "Сценарий не найден. Сгенерируй его заново.",
  scenario_invalid: "Сценарий не прошёл проверку входных данных.",
  openrouter_not_configured: "OpenRouter не настроен для live-запуска.",
  profile_not_running: "Изолированный Ouroboros profile не запущен. Запусти профиль и повтори preflight.",
  profile_not_ready: "Ouroboros profile не готов к Live-запуску.",
  live_preflight_failed: "Live preflight не прошёл; платный запуск заблокирован.",
  live_preflight_not_run: "Live preflight ещё не выполнен.",
  preflight_model_mismatch: "Профиль настроен на другую модель; синхронизируй его и повтори preflight.",
  profile_model_switch_failed: "Не удалось переключить Ouroboros на выбранную модель.",
  mcp_tools_not_ready: "AGA MCP gateway не видит все 4 review и 2 remediation tools.",
  runtime_version_mismatch: "Версия Ouroboros runtime не совпадает с pinned-версией.",
  budget_api_unavailable: "Сеть/VPN не даёт проверить OpenRouter budget.",
  network_not_ready: "Сеть/VPN не готова к OpenRouter.",
  remaining_budget_below_minimum: "Для live-запуска недостаточно бюджета OpenRouter.",
  invalid_aga_receipt: "Live review не вернул полный trusted AGA receipt. Архитектурная ветка остановлена безопасно; правила и уже завершённые тесты сохранены. Тот же сценарий можно повторить локально бесплатно.",
  mcp_tool_service_error: "Модель передала сервису некорректные технические данные. Архитектура не считается изменённой; новый запуск автоматически исправляет одиночную ошибку копирования digest.",
  run_failed: "E2E завершился с ошибкой.",
  model_not_supported: "Эта модель не входит в разрешённый список Ouroboros.",
};

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function svgElement(name, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function safeObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asText(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return fallback;
  }
}

function compactText(value, maximum = 90) {
  const text = asText(value);
  return text.length > maximum ? `${text.slice(0, maximum - 1)}…` : text;
}

function normalizedStatus(value) {
  return String(value || "idle")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function terminalState(run) {
  if (!run) return null;
  const status = normalizedStatus(run.state);
  if (["succeeded", "success", "completed", "complete", "passed"].includes(status)) return "succeeded";
  if (["failed", "error", "cancelled", "canceled"].includes(status)) return "failed";
  if (["queued", "running", "starting", "in_progress"].includes(status)) return null;
  const terminalEvent = [...safeArray(run.events)].reverse().find((event) => {
    const identity = normalizedStatus(`${event.kind || ""}_${event.id || ""}`);
    return ["run_completed", "run_succeeded", "run_failed", "run_cancelled"].some((kind) => identity.includes(kind));
  });
  if (terminalEvent) {
    return normalizedStatus(`${terminalEvent.kind || ""}_${terminalEvent.id || ""}`).includes("fail") ? "failed" : "succeeded";
  }
  if (Number.isFinite(run.finished_at_unix_ms)) {
    const gate = safeObject(run.result).gate;
    const gateState = normalizedStatus(safeObject(gate).status || safeObject(gate).verdict);
    return gateState.includes("fail") || safeObject(gate).passed === false ? "failed" : "succeeded";
  }
  return null;
}

function runIsActive() {
  if (!state.run || terminalState(state.run)) return false;
  return ["queued", "running", "starting", "in_progress"].includes(normalizedStatus(state.run.state));
}

function formatMoney(value, { showZero = true } = {}) {
  const number = Number(value);
  if (!Number.isFinite(number) || (!showZero && number <= 0)) return "—";
  return `$${number.toFixed(4)}`;
}

function formatDuration(milliseconds) {
  const number = Number(milliseconds);
  if (!Number.isFinite(number) || number < 0) return "—";
  if (number < 1000) return `${Math.round(number)} ms`;
  const totalSeconds = Math.floor(number / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function formatClock(milliseconds) {
  const number = Math.max(0, Number(milliseconds) || 0);
  const totalSeconds = Math.floor(number / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatTimestamp(milliseconds) {
  const number = Number(milliseconds);
  if (!Number.isFinite(number)) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(number));
}

function summaryText(summary) {
  if (typeof summary === "string") return summary;
  const object = safeObject(summary);
  return object.description || object.title || object.text || object.scenario || "Синтетическая модель готова к E2E-проверке.";
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    headers["X-AGA-UI-Token"] = state.token;
  }
  const response = await fetch(path, { ...options, headers });
  let payload;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = { code: "invalid_server_response" };
  }
  if (!response.ok) {
    const error = new Error(payload.code || "request_failed");
    error.code = payload.code || "request_failed";
    throw error;
  }
  return payload;
}

function setPage(page) {
  state.page = page;
  ui.pageTabs.forEach((tab) => {
    const active = tab.dataset.page === page;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  ui.pages.forEach((panel) => panel.classList.toggle("is-active", panel.dataset.pagePanel === page));
}

function setStatus(kind, title, detail = "") {
  ui.statusIndicator.className = `status-indicator is-${kind}`;
  ui.statusText.textContent = title;
  ui.statusDetail.textContent = detail;
}

function normalizedPresets(payload) {
  if (Array.isArray(payload)) {
    return payload.map((preset, index) => {
      if (typeof preset === "string") return { id: preset, label: preset };
      const object = safeObject(preset);
      const id = object.id || object.preset || object.value || `preset-${index + 1}`;
      return { id: String(id), label: String(object.label || object.title || object.name || id), description: object.description || "" };
    });
  }
  return Object.entries(safeObject(payload)).map(([id, preset]) => {
    const object = safeObject(preset);
    return { id, label: String(object.label || object.title || object.name || id), description: object.description || "" };
  });
}

function renderPresetOptions() {
  ui.preset.replaceChildren();
  const presets = state.presets.length ? state.presets : [{ id: "antifraud-migration", label: "Миграция antifraud-платформы" }];
  presets.forEach((preset) => {
    const option = document.createElement("option");
    option.value = preset.id;
    option.textContent = preset.label;
    ui.preset.append(option);
  });
}

function renderRuntime() {
  const runtime = safeObject(state.runtime);
  const recorded = state.run?.recorded_evidence === true;
  const local = !recorded && (state.run ? state.run.execution === "local" : ui.execution.value !== "live");
  ui.runtimeName.textContent = recorded ? "Recorded evidence" : local ? "AGA deterministic" : runtime.name || runtime.runtime || "Ouroboros";
  if (recorded) {
    const source = String(state.run.source_execution || state.run.execution || "run").toUpperCase();
    ui.runtimeModel.textContent = `${source} evidence · новых model calls нет`;
    return;
  }
  if (local) {
    ui.runtimeModel.textContent = "LOCAL · без model calls · $0";
    return;
  }
  const model = state.run
    ? state.run.execution === "live"
      ? state.run.model_id || runtime.model || "model —"
      : "без model calls"
    : runtime.model || runtime.model_id || "model —";
  const provider = runtime.provider || "runtime";
  const runtimeVersion = runtime.version || runtime.ouroboros_version;
  const version = runtimeVersion ? ` · ${runtimeVersion}` : "";
  ui.runtimeModel.textContent = `${model} · ${provider}${version}`;
}

function renderModelOptions() {
  const runtime = safeObject(state.runtime);
  const models = safeArray(runtime.models);
  const previous = ui.model.value || state.run?.model_id || runtime.model || "deepseek/deepseek-v4-pro";
  ui.model.replaceChildren();
  (models.length ? models : [
    { id: "deepseek/deepseek-v4-pro", label: "DeepSeek V4 Pro" },
    { id: "moonshotai/kimi-k3", label: "Kimi K3" },
  ]).forEach((model) => {
    const option = document.createElement("option");
    option.value = String(model.id || "");
    option.textContent = `${model.label || model.id} · ${model.id}`;
    ui.model.append(option);
  });
  const values = [...ui.model.options].map((option) => option.value);
  ui.model.value = values.includes(previous) ? previous : values[0];
}

function selectedDemoProfile() {
  const value = ui.demoProfileRadios.find((radio) => radio.checked)?.value;
  return value === "full" ? "full" : "quick";
}

function applyDemoProfile({ clearScenario = true } = {}) {
  if (runIsActive()) return;
  const profileId = selectedDemoProfile();
  const profile = demoProfiles[profileId];
  ui.demoProfileRadios.forEach((radio) => { radio.checked = radio.value === profileId; });
  ui.demoProfileOptions.forEach((option) => option.classList.toggle("is-selected", option.dataset.demoProfileOption === profileId));
  if ([...ui.preset.options].some((option) => option.value === profile.preset)) ui.preset.value = profile.preset;
  if ([...ui.workers.options].some((option) => Number(option.value) === profile.workers)) ui.workers.value = String(profile.workers);
  if ([...ui.model.options].some((option) => option.value === profile.model)) ui.model.value = profile.model;
  ui.execution.value = "live";
  state.liveReadiness = null;
  ui.paid.checked = false;
  if (clearScenario) {
    resetRunState();
    state.scenario = null;
    state.selectedTestId = null;
  }
}

function renderWorkerOptions() {
  const supported = safeArray(safeObject(state.runtime).parallel_workers)
    .map(Number)
    .filter((value) => Number.isInteger(value) && value >= 1);
  const values = supported.length ? supported : [2, 3, 4];
  const previous = Number(ui.workers.value);
  ui.workers.replaceChildren();
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = String(value);
    ui.workers.append(option);
  });
  ui.workers.value = String(values.includes(previous) ? previous : Math.max(...values));
}

function currentElapsedMilliseconds() {
  const run = state.run;
  if (!run || !Number.isFinite(run.started_at_unix_ms)) return 0;
  const end = Number.isFinite(run.finished_at_unix_ms) ? run.finished_at_unix_ms : Date.now();
  return Math.max(0, end - run.started_at_unix_ms);
}

function renderHeader() {
  const terminal = terminalState(state.run);
  const rawStatus = terminal || (state.run ? normalizedStatus(state.run.state) : state.scenario ? "generated" : "idle");
  ui.headerRunState.textContent = rawStatus.toUpperCase().replaceAll("_", " ");
  ui.headerRunState.className = `state-badge is-${rawStatus}`;
  ui.headerRunId.textContent = state.run?.run_id ? `run ${state.run.run_id}` : "run —";
  ui.headerElapsed.textContent = formatClock(currentElapsedMilliseconds());
  ui.ouroborosMark.classList.toggle("is-running", runIsActive());
}

function runDisplayMode() {
  if (state.run?.recorded_evidence === true) return "RECORDED EVIDENCE";
  if (state.run?.display_mode) return String(state.run.display_mode);
  return (state.run?.execution || ui.execution.value) === "live" ? "LIVE" : "LOCAL";
}

function renderMiniStatus() {
  const run = state.run;
  ui.miniStatus.classList.toggle("is-hidden", !run);
  if (!run) return;
  const events = safeArray(run.events);
  const identities = events.map((event) => normalizedStatus(event.id));
  const terminal = terminalState(run);
  const failureComponent = String(safeObject(run.failure).component || "");
  const architectureDone = identities.some((id) => id.includes("rereview") && (id.includes("passed") || id.includes("completed")));
  const rulesDone = currentTests().length > 0 && currentTests().every((test) => safeObject(test.candidate).passed === true);
  const gateDone = identities.some((id) => id.includes("gate_passed"));
  const branch = (done, failed) => done ? "PASSED" : failed ? "FAILED" : runIsActive() ? "RUNNING" : "WAITING";
  ui.miniMode.textContent = runDisplayMode();
  ui.miniMode.className = `mode-badge ${run.recorded_evidence ? "is-recorded" : run.execution === "live" ? "is-paid" : "is-recommended"}`;
  ui.miniPhase.textContent = terminal === "failed" ? "failed" : terminal === "succeeded" ? "completed" : String(run.phase || run.state || "queued").replaceAll("_", " ");
  ui.miniElapsed.textContent = formatClock(currentElapsedMilliseconds());
  ui.miniArchitecture.textContent = branch(architectureDone, terminal === "failed" && failureComponent === "architecture");
  ui.miniRules.textContent = branch(rulesDone, terminal === "failed" && failureComponent === "rules");
  ui.miniGate.textContent = branch(gateDone, terminal === "failed");
  const latest = events[events.length - 1];
  ui.miniLatestEvent.textContent = latest?.label || (run.recorded_evidence ? "Загружен проверенный public summary" : "Ожидаю первое событие");
}

function startElapsedClock() {
  if (state.elapsedTimer) window.clearInterval(state.elapsedTimer);
  state.elapsedTimer = window.setInterval(() => {
    renderHeader();
    renderMiniStatus();
  }, 1000);
}

function phaseIndex() {
  if (terminalState(state.run) === "succeeded") return phaseDefinitions.length;
  if (terminalState(state.run) === "failed") {
    const failureStage = normalizedStatus(safeObject(state.run?.failure).stage);
    if (state.run?.error_code === "invalid_aga_receipt" || failureStage.includes("review_before")) return 2;
  }
  const phase = normalizedStatus(state.run?.phase || (state.scenario ? "generated" : "idle"));
  if (Object.hasOwn(phaseAliases, phase)) return phaseAliases[phase];
  for (const [alias, index] of Object.entries(phaseAliases)) {
    if (phase.includes(alias)) return index;
  }
  if (state.run) {
    const eventEstimate = Math.floor(safeArray(state.run.events).length / 4) + 1;
    return Math.max(0, Math.min(phaseDefinitions.length - 1, eventEstimate));
  }
  return state.scenario ? 0 : -1;
}

function normalizedProgress() {
  if (terminalState(state.run) === "succeeded") return 1;
  const progress = state.run?.progress;
  const progressObject = safeObject(progress);
  const percent = Number(progressObject.percent);
  let raw = Number.isFinite(percent) ? percent / 100 : Number.NaN;
  if (!Number.isFinite(raw)) {
    const done = Number(progressObject.done);
    const total = Number(progressObject.total);
    if (Number.isFinite(done) && Number.isFinite(total) && total > 0) raw = done / total;
  }
  if (!Number.isFinite(raw)) {
    raw = Number(progress);
    if (Number.isFinite(raw) && raw > 1) raw /= 100;
  }
  if (!Number.isFinite(raw)) return state.run ? Math.max(0, (phaseIndex() + 0.15) / phaseDefinitions.length) : 0;
  return Math.max(0, Math.min(1, raw));
}

function renderPhaseTrack() {
  const current = phaseIndex();
  const terminal = terminalState(state.run);
  ui.phaseTrack.replaceChildren();
  phaseDefinitions.forEach((phase, index) => {
    const item = element("li", "phase-step");
    if (terminal === "succeeded" || index < current) item.classList.add("is-complete");
    if (!terminal && index === current) item.classList.add("is-active");
    if (terminal === "failed" && index === current) item.classList.add("is-failed");
    const dot = element("span", "phase-dot", terminal === "succeeded" || index < current ? "✓" : String(index + 1));
    item.append(dot, element("span", "", phase.label));
    ui.phaseTrack.append(item);
  });
}

function renderArchitectureCheckpoints() {
  const events = safeArray(state.run?.events);
  const matches = (identities, operations = []) => [...events].reverse().find((event) => {
    const identity = normalizedStatus(`${event.id || ""}_${event.kind || ""}`);
    const operation = normalizedStatus(safeObject(event.graph_delta).operation);
    return identities.some((candidate) => identity.includes(normalizedStatus(candidate))) || operations.includes(operation);
  });
  const findingProof = matches(["finding.detected", "finding_detected"], ["finding"]);
  const definitions = [
    {
      id: "architecture",
      label: "Архитектура",
      subtitle: state.run?.execution === "live" ? `Ouroboros · ${state.run.model_id || ui.model.value}` : "Локальный SEAF-контур",
      steps: [
        { id: "finding", label: findingProof ? "SEAF-004 найден" : "Проверка SEAF-004", waiting: "review", proof: findingProof },
        { id: "reroute", label: "Поток reroute", waiting: "patch", proof: matches(["patch.created", "remediation", "reroute"], ["reroute", "patch", "remediation", "update_edge"]) },
        { id: "rereview", label: "Re-review: 0 blockers", waiting: "re-review", proof: matches(["rereview.passed", "rereview_completed", "re.review.passed"], ["rereview", "verify", "healthy"]) },
      ],
    },
    {
      id: "rules",
      label: "Правила",
      subtitle: "Loop A · precedent → candidate",
      steps: [
        { id: "baseline", label: "Baseline: найден false positive", waiting: "baseline", proof: matches(["baseline.worker", "rules.evolution.started"]) },
        { id: "mutation", label: "PRIN-002 уточнён", waiting: "mutation", proof: matches(["rules.mutation.created", "rule.mutation.created", "rules.evolution.completed"]) },
        { id: "fitness", label: "26 candidate-тестов", waiting: "fitness", proof: currentTests().length > 0 && currentTests().every((test) => safeObject(test.candidate).passed === true) ? { label: "Все candidate-тесты прошли" } : null },
      ],
    },
    {
      id: "gate",
      label: "Safety gate",
      subtitle: "Сводит обе ветки",
      steps: [
        { id: "gate", label: "Кандидат готов человеку", waiting: "ждёт обе ветки", proof: matches(["gate.passed", "gate_passed", "run.completed"]) },
      ],
    },
  ];
  const terminal = terminalState(state.run);
  ui.architectureCheckpoints.replaceChildren();
  definitions.forEach((definition) => {
    const complete = definition.steps.every((step) => step.proof);
    const failureComponent = String(safeObject(state.run?.failure).component || "");
    const branchFailed = terminal === "failed" && (definition.id === failureComponent || (definition.id === "gate" && !failureComponent));
    const status = complete ? "complete" : branchFailed ? "failed" : runIsActive() ? "active" : "waiting";
    const item = element("li", `architecture-checkpoint evolution-lane is-${status}`);
    item.dataset.checkpoint = definition.id;
    item.dataset.status = status;
    const header = element("div", "evolution-lane-header");
    const title = element("div");
    title.append(element("strong", "", definition.label), element("span", "", definition.subtitle));
    header.append(title, element("span", "checkpoint-status", status === "complete" ? "ГОТОВО" : status === "active" ? "В РАБОТЕ" : status === "failed" ? "FAILED" : "ЖДЁТ"));
    const steps = element("ol", "evolution-lane-steps");
    let priorComplete = true;
    definition.steps.forEach((step) => {
      let stepStatus = step.proof ? "complete" : "waiting";
      if (!step.proof && priorComplete && status === "active") stepStatus = "active";
      if (!step.proof && priorComplete && status === "failed") stepStatus = "failed";
      const row = element("li", `is-${stepStatus}`);
      row.append(element("span", "evolution-step-mark", stepStatus === "complete" ? "✓" : stepStatus === "failed" ? "!" : ""), element("span", "", step.label));
      steps.append(row);
      priorComplete = priorComplete && Boolean(step.proof);
    });
    item.append(header, steps);
    ui.architectureCheckpoints.append(item);
  });
}

function liveTaskEvidence() {
  const architecture = safeObject(safeObject(finalResult()).architecture_evolution);
  const completed = safeArray(architecture.task_steps);
  if (completed.length === 3) return completed;
  const events = safeArray(state.run?.events);
  const definitions = [
    { stage: "review", matches: ["finding_detected", "ouroboros_finding"] },
    { stage: "remediation", matches: ["patch_created", "ouroboros_patch"] },
    { stage: "re-review", matches: ["rereview_passed", "rereview_completed"] },
  ];
  return definitions.map((definition) => {
    const event = [...events].reverse().find((candidate) => {
      const identity = normalizedStatus(candidate.id);
      return definition.matches.some((part) => identity.includes(part));
    });
    const data = safeObject(event?.data);
    const tools = [...safeArray(data.receipts)];
    if (event?.tool && !tools.includes(event.tool)) tools.push(event.tool);
    return {
      stage: definition.stage,
      task_id: event?.task_id,
      tools,
      cost_usd: data.cost_usd,
      receipt_verified: data.receipt_verified === true,
      status: event?.status || (event ? "completed" : "waiting"),
    };
  });
}

function renderLiveEvidence() {
  const liveSource = state.run?.execution === "live" || (state.run?.recorded_evidence && state.run?.source_execution === "live");
  ui.liveEvidence.classList.toggle("is-hidden", !liveSource);
  if (!liveSource) return;
  const steps = liveTaskEvidence();
  const result = finalResult();
  const summary = safeObject(result.summary);
  const actualCost = Number(state.run?.cost_usd ?? summary.actual_cost_usd);
  const costText = Number.isFinite(actualCost) && actualCost > 0
    ? formatMoney(actualCost, { showZero: false })
    : terminalState(state.run)
      ? "actual cost unavailable"
      : "стоимость появится по receipts";
  ui.liveEvidenceMeta.textContent = `${state.run?.provider || "OpenRouter"} · ${state.run?.model_id || "model —"} · ${costText} · merge: ${summary.merge_performed === false ? "false" : "not performed"}`;
  ui.liveTaskList.replaceChildren();
  steps.forEach((step, index) => {
    const item = element("li", "live-task");
    const top = element("div", "live-task-top");
    const verified = step.receipt_verified === true;
    top.append(
      element("strong", "", `${index + 1}. ${step.stage || ["review", "remediation", "re-review"][index]}`),
      element("span", "", verified ? "RECEIPT VERIFIED" : step.task_id ? "VERIFYING" : "WAITING"),
    );
    item.append(top, element("code", "", step.task_id ? `task ${step.task_id}` : "task ID ожидается"));
    const tools = element("div", "live-task-tools");
    const toolNames = safeArray(step.tools);
    if (toolNames.length) toolNames.forEach((tool) => tools.append(element("span", "", tool)));
    else tools.append(element("span", "", "MCP tools ожидаются"));
    item.append(tools);
    const taskCost = Number(step.cost_usd);
    item.append(element("span", "live-task-cost", Number.isFinite(taskCost) && taskCost > 0 ? `actual ${formatMoney(taskCost, { showZero: false })}` : "actual cost —"));
    ui.liveTaskList.append(item);
  });
}

function renderProgress() {
  const progress = normalizedProgress();
  const terminal = terminalState(state.run);
  const current = phaseIndex();
  const eventIdentity = safeArray(state.run?.events).map((event) => normalizedStatus(event.id || ""));
  const architectureReady = eventIdentity.some((id) => id.includes("rereview") && (id.includes("passed") || id.includes("completed")));
  const rulesReady = eventIdentity.some((id) => id.includes("rules_mutation_created")) && currentTests().length > 0 && currentTests().every((test) => safeObject(test.candidate).passed === true);
  const gateReady = eventIdentity.some((id) => id.includes("gate_passed"));
  const readyBranches = [architectureReady, rulesReady, gateReady].filter(Boolean).length;
  ui.progressValue.textContent = `${readyBranches}/3`;
  ui.progressBar.style.width = `${Math.round(progress * 100)}%`;
  ui.phaseValue.textContent = terminal === "failed" ? "остановлено" : terminal === "succeeded" ? "контуры готовы" : "контуров готовы";
  if (!state.run) {
    ui.phaseDescription.textContent = state.scenario
      ? "План готов. После запуска swimlanes будут заполняться фактическими events."
      : "После запуска здесь появятся только фактически начавшиеся и завершившиеся действия.";
  } else if (terminal === "succeeded") {
    ui.phaseDescription.textContent = "E2E завершён: все события, тесты, изменения и gate зафиксированы.";
  } else if (terminal === "failed") {
    ui.phaseDescription.textContent = "E2E остановился. Последнее фактическое событие и причина сохранены ниже.";
  } else {
    ui.phaseDescription.textContent = `${safeArray(state.run.events).length} событий получено · ${safeArray(state.run.agents).filter((agent) => normalizedStatus(agent.status) === "running").length} исполнителей сейчас работают.`;
  }
  renderPhaseTrack();
}

function renderRunStatus() {
  const terminal = terminalState(state.run);
  if (!state.scenario && !state.run) {
    setStatus("idle", "Готово к запуску", "Главная кнопка сама создаст данные и запустит весь E2E");
    return;
  }
  if (!state.run) {
    setStatus("generated", "Сценарий готов", `${safeArray(state.scenario.tests).length} тестов · ${state.scenario.parallel_workers || ui.workers.value} параллельных workers`);
    return;
  }
  if (state.run.recorded_evidence === true) {
    const source = String(state.run.source_execution || state.run.execution || "run").toUpperCase();
    setStatus(
      terminal === "failed" ? "failed" : "generated",
      `RECORDED EVIDENCE · ${source}`,
      terminal === "failed"
        ? `Загружен failed run · code: ${state.run.error_code || "run_failed"}`
        : "Public summary прошёл schema и SHA-256; новых model calls не было",
    );
    return;
  }
  if (terminal === "succeeded") {
    const gate = safeObject(safeObject(state.run.result).gate);
    setStatus("succeeded", "Полный E2E завершён", gate.summary || gate.detail || "Gate пройден; результаты и артефакты готовы к просмотру");
    return;
  }
  if (terminal === "failed") {
    const detail = state.run.error_code || safeObject(safeObject(state.run.result).gate).reason || "Открой последнее событие для деталей";
    setStatus("failed", "E2E завершился с ошибкой", friendlyErrors[detail] || detail);
    return;
  }
  const phase = state.run.phase || state.run.state || "running";
  setStatus("running", `E2E выполняется · ${String(phase).replaceAll("_", " ")}`, `${safeArray(state.run.events).length} фактических событий · ${Math.round(normalizedProgress() * 100)}%`);
}

function renderFailureRecovery() {
  const failed = terminalState(state.run) === "failed";
  ui.failureRecovery.classList.toggle("is-hidden", !failed);
  if (!failed) return;
  const errorCode = state.run?.error_code || "run_failed";
  ui.failureErrorCode.textContent = errorCode;
  const wasLive = state.run?.execution === "live" || errorCode === "invalid_aga_receipt";
  if (errorCode === "invalid_aga_receipt") {
    const passedCandidate = safeArray(state.run?.tests).filter((test) => safeObject(test.candidate).passed === true).length;
    const testsTotal = safeArray(state.run?.tests).length;
    const stage = safeObject(state.run?.failure).stage || "review_before";
    const cost = Number(state.run?.cost_usd || 0);
    ui.failureRecoveryTitle.textContent = `Архитектурная ветка остановилась на ${stage}`;
    ui.failureRecoveryCopy.textContent = `Trusted receipt не прошёл защитный контракт. Следующие архитектурные шаги не считаются выполненными. Сохранено${testsTotal ? `: candidate-тесты ${passedCandidate}/${testsTotal}` : ""}${cost > 0 ? ` · стоимость $${cost.toFixed(4)}` : ""}.`;
  } else {
    ui.failureRecoveryTitle.textContent = wasLive ? "Live-запуск остановлен" : "E2E остановлен";
    ui.failureRecoveryCopy.textContent = `${friendlyErrors[errorCode] || errorCode}. Сценарий сохранён, его можно сразу повторить локально.`;
  }
  ui.recoveryLocalButton.textContent = "▶ Повторить тот же сценарий бесплатно";
}

function selectedLiveIsReady() {
  const readiness = safeObject(state.liveReadiness);
  return readiness.status === "ready" && readiness.model === ui.model.value;
}

function renderLiveReadiness() {
  const live = ui.execution.value === "live";
  ui.liveReadiness.classList.toggle("is-hidden", !live);
  if (!live) return;
  const readiness = safeObject(state.liveReadiness);
  const loading = state.readinessLoading;
  const ready = selectedLiveIsReady();
  const status = loading ? "checking" : ready ? "ready" : "failed";
  ui.liveReadiness.classList.toggle("is-ready", ready);
  ui.liveReadiness.classList.toggle("is-failed", !loading && !ready);
  ui.liveReadinessStatus.textContent = loading ? "CHECKING" : ready ? "READY" : "BLOCKED";
  ui.liveReadinessStatus.className = `state-badge is-${loading ? "running" : ready ? "succeeded" : "failed"}`;
  const tools = safeObject(readiness.tools);
  const review = safeObject(tools.review);
  const remediation = safeObject(tools.remediation);
  const duration = safeObject(readiness.estimated_duration_seconds);
  const estimate = safeObject(readiness.estimated_cost_usd);
  const network = safeObject(readiness.network);
  const items = [
    ["Runtime", readiness.runtime_version || "6.64.1"],
    ["Provider / model", `${readiness.provider || "OpenRouter"} · ${readiness.model || ui.model.value}`],
    ["Profile", loading ? "checking…" : readiness.profile_status || "unknown"],
    ["MCP gateway", loading ? "checking…" : readiness.mcp_gateway || "not checked"],
    ["Review tools", `${Number(review.ready || 0)}/${Number(review.required || 4)}`],
    ["Remediation tools", `${Number(remediation.ready || 0)}/${Number(remediation.required || 2)}`],
    ["Hard budget cap", `$${Number(readiness.hard_budget_cap_usd || 50).toFixed(2)} · run stop $${Number(readiness.run_stop_threshold_usd || 40).toFixed(2)}`],
    ["Classification", readiness.classification || "synthetic-public"],
    ["Estimate", `${Number(duration.min || 180) / 60}–${Number(duration.max || 600) / 60} min · $${Number(estimate.min || .05).toFixed(2)}–$${Number(estimate.max || .5).toFixed(2)}`],
    ["VPN / network", loading ? "checking…" : network.status === "ready" ? "READY · provider reachable" : "NOT READY"],
  ];
  ui.liveReadinessGrid.replaceChildren();
  items.forEach(([label, value]) => {
    const item = element("div", "readiness-item");
    item.append(element("span", "", label), element("strong", "", value));
    ui.liveReadinessGrid.append(item);
  });
  const code = readiness.code || "live_preflight_not_run";
  ui.liveReadinessReason.textContent = loading
    ? "Проверяю profile, gateway, 6 AGA tools, hard cap и связь с OpenRouter; секреты не возвращаются."
    : ready
      ? "Preflight пройден: provider reachable, receipts и budget будут проверяться fail-closed. VPN details скрыты."
      : `${friendlyErrors[code] || code} · code: ${code}`;
  ui.refreshReadinessButton.disabled = loading || runIsActive();
}

async function refreshLiveReadiness(force = false) {
  if (runIsActive() || ui.execution.value !== "live") return;
  state.readinessLoading = true;
  state.liveReadiness = null;
  renderLiveReadiness();
  renderControls();
  try {
    state.liveReadiness = await request("/api/v2/live-readiness", {
      method: "POST",
      body: JSON.stringify({ model_id: ui.model.value, force }),
    });
  } catch (error) {
    state.liveReadiness = { status: "failed", code: error.code || "live_preflight_failed", model: ui.model.value };
  } finally {
    state.readinessLoading = false;
    renderLiveReadiness();
    renderControls();
  }
}

function setControlsDisabled(disabled) {
  ui.generate.disabled = disabled;
  ui.preset.disabled = disabled;
  ui.seed.disabled = disabled;
  ui.workers.disabled = disabled;
  ui.execution.disabled = disabled;
  ui.model.disabled = disabled;
  ui.executionRadios.forEach((radio) => { radio.disabled = disabled; });
  ui.demoProfileRadios.forEach((radio) => { radio.disabled = disabled; });
  ui.runButton.disabled = disabled;
  ui.refreshReadinessButton.disabled = disabled || state.readinessLoading;
  ui.recoveryLocalButton.disabled = disabled || !state.scenario;
}

function syncExecutionControls() {
  const execution = ui.execution.value === "live" ? "live" : "local";
  const profile = demoProfiles[selectedDemoProfile()];
  const testCount = state.scenario?.preset === ui.preset.value
    ? safeArray(state.scenario.tests).length
    : profile.tests;
  ui.execution.value = execution;
  ui.executionRadios.forEach((radio) => { radio.checked = radio.value === execution; });
  ui.executionOptions.forEach((option) => option.classList.toggle("is-selected", option.dataset.executionOption === execution));
  ui.paidWrap.classList.toggle("is-hidden", execution !== "live");
  ui.modelPicker.classList.toggle("is-local", execution !== "live");
  ui.modelHint.textContent = execution === "live" ? "review → remediation → re-review" : "Локальный режим модель не вызывает";
  ui.launchDetail.textContent = execution === "live"
    ? `Три Live-задачи Ouroboros/OpenRouter · ${testCount} тестов · unified gate.`
    : `Deterministic review, remediation и ${testCount} тестов.`;
  if (execution !== "live") ui.paid.checked = false;
  renderRuntime();
  renderLiveReadiness();
}

function renderControls() {
  const active = runIsActive();
  setControlsDisabled(active);
  syncExecutionControls();
  if (!active && ui.execution.value === "live") {
    ui.runButton.disabled = !selectedLiveIsReady() || !ui.paid.checked;
  }
  if (active) {
    ui.runButtonLabel.textContent = `E2E выполняется · ${Math.round(normalizedProgress() * 100)}%`;
  } else if (terminalState(state.run) && ui.execution.value === "live") {
    ui.runButtonLabel.textContent = `Повторить Live E2E · ${ui.model.selectedOptions[0]?.textContent?.split(" · ")[0] || "модель"}`;
  } else if (terminalState(state.run)) {
    ui.runButtonLabel.textContent = "Запустить тот же E2E локально · $0";
  } else {
    ui.runButtonLabel.textContent = ui.execution.value === "live"
      ? `Запустить ${demoProfiles[selectedDemoProfile()].label}`
      : `Запустить ${demoProfiles[selectedDemoProfile()].label} локально`;
  }
}

function agentPlan() {
  const raw = state.scenario?.agent_plan;
  if (Array.isArray(raw)) return raw;
  const object = safeObject(raw);
  if (Array.isArray(object.agents)) return object.agents.filter((agent) => agent && typeof agent === "object" && !Array.isArray(agent));
  if (Array.isArray(object.workers)) return object.workers.filter((agent) => agent && typeof agent === "object" && !Array.isArray(agent));
  return [];
}

function plannedStages() {
  return safeArray(safeObject(state.scenario?.agent_plan).stages).filter((stage) => typeof stage === "string" && stage);
}

function renderScenario() {
  const scenario = state.scenario;
  if (!scenario) {
    ui.scenarioPreview.classList.add("is-empty");
    ui.scenarioTitle.textContent = "Модель появится здесь";
    ui.scenarioId.textContent = "scenario —";
    ui.scenarioSummary.textContent = "Нажми «Сгенерировать модель». Ты увидишь размер графа, список проверок и план параллельных исполнителей до запуска.";
    ui.scenarioStats.classList.add("is-hidden");
    ui.scenarioStats.replaceChildren();
    ui.scenarioChecks.replaceChildren();
    ui.scenarioState.textContent = "Сценарий ещё не создан";
    ui.scenarioState.classList.remove("is-failed", "is-succeeded");
    return;
  }
  const graph = safeObject(scenario.graph);
  const tests = safeArray(scenario.tests);
  const plan = agentPlan();
  const terminal = terminalState(state.run);
  ui.scenarioPreview.classList.remove("is-empty");
  ui.scenarioTitle.textContent = scenario.preset_label || scenario.title || scenario.preset || "Сложная синтетическая модель";
  ui.scenarioId.textContent = scenario.scenario_id || "scenario —";
  ui.scenarioSummary.textContent = scenario.description || summaryText(scenario.summary);
  ui.scenarioState.textContent = runIsActive()
    ? "E2E выполняется"
    : state.run?.recorded_evidence
      ? `RECORDED EVIDENCE · ${String(state.run.source_execution || state.run.execution || "run").toUpperCase()}`
    : terminal === "failed"
      ? "Прогон завершён с ошибкой"
      : terminal
        ? "Прогон успешно завершён"
        : "Входы готовы · ответы скрыты";
  ui.scenarioState.classList.toggle("is-failed", terminal === "failed");
  ui.scenarioState.classList.toggle("is-succeeded", terminal === "succeeded");
  ui.scenarioStats.classList.remove("is-hidden");
  ui.scenarioStats.replaceChildren();
  [
    ["Компоненты", safeArray(graph.nodes).length],
    ["Связи", safeArray(graph.edges).length],
    ["Тесты", tests.length],
    ["Workers", scenario.parallel_workers || plan.length],
  ].forEach(([label, value]) => {
    const item = element("div", "stat-item");
    item.append(element("span", "", label), element("strong", "", String(value)));
    ui.scenarioStats.append(item);
  });
  ui.scenarioChecks.replaceChildren();
  tests.slice(0, 9).forEach((test) => ui.scenarioChecks.append(element("span", "check-chip", `${test.id || "test"} · ${compactText(test.title || test.scenario, 42)}`)));
  if (tests.length > 9) ui.scenarioChecks.append(element("span", "check-chip", `+ ещё ${tests.length - 9}`));
}

function currentAgents() {
  const actual = safeArray(state.run?.agents);
  if (actual.length) return actual;
  return agentPlan().map((agent, index) => ({
    ...safeObject(agent),
    id: safeObject(agent).id || `planned-${index + 1}`,
    name: safeObject(agent).name || safeObject(agent).label || `Worker ${index + 1}`,
    status: "planned",
  }));
}

function agentTypeLabel(type) {
  const normalized = normalizedStatus(type);
  if (normalized.includes("ouro") || normalized.includes("llm") || normalized.includes("model")) return "LLM · Ouroboros";
  if (normalized.includes("orchestrator")) return "E2E Orchestrator";
  if (normalized.includes("gate")) return "Deterministic · Gate";
  if (normalized.includes("test") || normalized.includes("fitness")) return "Deterministic · Test worker";
  return type ? String(type) : "Deterministic worker";
}

function eventForAgent(event, agent) {
  return event.actor_id === agent.id || event.agent_id === agent.id || event.worker_id === agent.id;
}

function eventTimeBounds(events) {
  const timestamps = events.map((event) => Number(event.timestamp_unix_ms)).filter(Number.isFinite);
  const start = Number.isFinite(state.run?.started_at_unix_ms) ? state.run.started_at_unix_ms : Math.min(...timestamps);
  const end = Number.isFinite(state.run?.finished_at_unix_ms) ? state.run.finished_at_unix_ms : Math.max(Date.now(), ...timestamps);
  if (!Number.isFinite(start)) return { start: Date.now(), end: Date.now() + 1000 };
  return { start, end: Math.max(start + 1000, end) };
}

function selectEvent(eventId, pin = true) {
  state.selectedEventId = eventId;
  state.inspectorPinned = pin;
  renderEventInspector();
  renderEventLog();
}

function renderSwimlanes() {
  const agents = currentAgents();
  const events = safeArray(state.run?.events);
  ui.swimlanes.replaceChildren();
  if (!agents.length) {
    const stages = plannedStages();
    const message = state.scenario
      ? `План: ${stages.length ? stages.join(" → ") : "fan-out после запуска"}. Реальные agent lanes появятся только после создания run.`
      : "Сначала сгенерируй сценарий: здесь появится план, а после запуска — реальные task и tool events.";
    ui.swimlanes.append(element("div", "empty-state", message));
    ui.laneScale.textContent = "единая временная шкала";
    return;
  }
  const planned = !state.run;
  const bounds = eventTimeBounds(events);
  ui.laneScale.textContent = planned ? "пунктир = запланировано" : `${formatTimestamp(bounds.start)} → ${formatTimestamp(bounds.end)}`;
  agents.forEach((agent) => {
    const row = element("div", "swimlane");
    const actor = element("div", "lane-actor");
    actor.append(element("strong", "", agent.name || agent.label || agent.id), element("span", "", `${agentTypeLabel(agent.type)} · ${normalizedStatus(agent.status)}`));
    const track = element("div", `lane-track${planned ? " is-planned" : ""}`);
    events.filter((event) => eventForAgent(event, agent)).forEach((event) => {
      const timestamp = Number(event.timestamp_unix_ms);
      const ratio = Number.isFinite(timestamp) ? (timestamp - bounds.start) / (bounds.end - bounds.start) : 0;
      const marker = element("button", `lane-event is-${normalizedStatus(event.status || "completed")}`);
      marker.type = "button";
      marker.style.left = `${Math.max(2, Math.min(98, ratio * 100))}%`;
      marker.setAttribute("aria-label", event.label || event.kind || "Событие");
      marker.addEventListener("click", () => selectEvent(event.id || String(event.seq)));
      track.append(marker);
    });
    const duration = Number(agent.duration_ms);
    const durationText = planned ? "план" : Number.isFinite(duration) ? formatDuration(duration) : normalizedStatus(agent.status) === "running" ? "live" : "—";
    row.append(actor, track, element("div", "lane-duration", durationText));
    ui.swimlanes.append(row);
  });
}

function cloneGraph(value) {
  const graph = safeObject(value);
  return {
    nodes: safeArray(graph.nodes).map((node) => ({ ...safeObject(node) })),
    edges: safeArray(graph.edges).map((edge) => ({ ...safeObject(edge) })),
  };
}

function neutralInputGraph(value) {
  const graph = cloneGraph(value);
  graph.edges.forEach((edge) => {
    edge._visual = "neutral";
    edge._active = false;
    edge.finding = null;
    edge.health = "neutral";
    edge.status = "neutral";
  });
  return graph;
}

function deltaOperation(delta, event) {
  return normalizedStatus(delta.action || delta.operation || delta.op || delta.kind || event?.kind || event?.id);
}

function applySingleGraphDelta(graph, rawDelta, event) {
  const delta = safeObject(rawDelta);
  if (delta.graph || (Array.isArray(delta.nodes) && Array.isArray(delta.edges))) {
    const snapshot = cloneGraph(delta.graph || delta);
    graph.nodes = snapshot.nodes;
    graph.edges = snapshot.edges;
    return;
  }
  const operation = deltaOperation(delta, event);
  const edgeData = safeObject(delta.edge);
  const after = safeObject(delta.after);
  const edgeId = delta.edge_id || edgeData.id || after.id || delta.id;
  let edge = graph.edges.find((item) => item.id === edgeId);
  if (!edge && delta.from && (delta.to || delta.new_to)) {
    edge = graph.edges.find((item) => item.from === delta.from && item.to === (delta.old_to || delta.to));
  }
  if (!edge && graph.edges.length === 1 && edgeId) edge = graph.edges[0];
  if (!edge) return;

  if (operation.includes("finding") || operation.includes("detect") || operation.includes("block") || operation.includes("highlight")) {
    edge._visual = "blocked";
    const eventRule = String(event?.label || event?.detail || "").match(/[A-Z]+-[0-9]{3}/)?.[0];
    edge.finding = delta.finding || delta.rule_id || safeObject(delta.finding).rule_id || event?.rule_id || eventRule || "finding";
  }
  if (operation.includes("patch") || operation.includes("rerout") || operation.includes("remedi") || operation.includes("candidate") || operation.includes("update_edge")) {
    edge.from = after.from || edgeData.from || delta.new_from || delta.from || edge.from;
    edge.to = after.to || edgeData.to || delta.new_to || delta.to || edge.to;
    edge._visual = "candidate";
    edge.finding = null;
  }
  if (operation.includes("healthy") || operation.includes("verify") || operation.includes("rereview") || operation.includes("approve") || operation.includes("validate")) {
    edge._visual = "healthy";
    edge.finding = null;
  }
  edge._active = true;
}

function applyGraphDelta(graph, rawDelta, event) {
  if (Array.isArray(rawDelta)) rawDelta.forEach((delta) => applySingleGraphDelta(graph, delta, event));
  else if (rawDelta) applySingleGraphDelta(graph, rawDelta, event);
}

function currentGraph() {
  const base = neutralInputGraph(state.scenario?.graph);
  if (!state.run) return base;
  const terminal = terminalState(state.run);
  const resultGraph = safeObject(safeObject(state.run.result).graph);
  if (terminal && safeObject(resultGraph.after).nodes) return cloneGraph(resultGraph.after);
  safeArray(state.run.events).forEach((event) => {
    graphClearActive(base);
    applyGraphDelta(base, event.graph_delta, event);
  });
  return base;
}

function graphClearActive(graph) {
  graph.edges.forEach((edge) => { edge._active = false; });
}

function graphNodePositions(nodes, width, height) {
  const count = Math.max(1, nodes.length);
  const columns = Math.min(6, Math.max(2, Math.ceil(Math.sqrt(count * 1.75))));
  const rows = Math.ceil(count / columns);
  const nodeWidth = count > 18 ? 112 : 126;
  const nodeHeight = 46;
  const xGap = (width - 48 - nodeWidth) / Math.max(1, columns - 1);
  const yGap = (height - 44 - nodeHeight) / Math.max(1, rows - 1);
  const positions = new Map();
  nodes.forEach((node, index) => {
    const row = Math.floor(index / columns);
    const column = index % columns;
    const rowCount = Math.min(columns, count - row * columns);
    const rowOffset = rowCount < columns ? ((columns - rowCount) * xGap) / 2 : 0;
    positions.set(node.id, { x: 24 + rowOffset + column * xGap, y: 22 + row * yGap, width: nodeWidth, height: nodeHeight });
  });
  return positions;
}

function edgeVisualState(edge, reveal = true) {
  if (!reveal) return "neutral";
  const explicit = normalizedStatus(edge._visual || edge.health || edge.status);
  if (explicit.includes("block") || explicit.includes("fail") || edge.finding) return "blocked";
  if (explicit.includes("candidate") || explicit.includes("patch") || explicit.includes("pending")) return "candidate";
  if (explicit.includes("healthy") || explicit.includes("pass") || explicit.includes("approve") || explicit.includes("verified")) return "healthy";
  return "neutral";
}

function renderGraphTo(container, graphValue, options = {}) {
  const graph = cloneGraph(graphValue);
  if (!graph.nodes.length) {
    container.replaceChildren(element("div", "empty-state", options.empty || "Нет данных графа"));
    return;
  }
  const compact = Boolean(options.compact);
  const width = compact ? 680 : 900;
  const height = compact ? 280 : 390;
  const positions = graphNodePositions(graph.nodes, width, height);
  state.graphSequence += 1;
  const markerId = `graph-arrow-${state.graphSequence}`;
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": options.label || "Граф архитектуры" });
  const title = svgElement("title");
  title.textContent = options.label || "Граф архитектуры";
  const defs = svgElement("defs");
  const marker = svgElement("marker", { id: markerId, markerWidth: 8, markerHeight: 8, refX: 7, refY: 3, orient: "auto", markerUnits: "strokeWidth" });
  marker.append(svgElement("path", { d: "M0,0 L0,6 L8,3 z", fill: "context-stroke" }));
  defs.append(marker);
  svg.append(title, defs);

  graph.edges.forEach((edge, index) => {
    const from = positions.get(edge.from || edge.source);
    const to = positions.get(edge.to || edge.target);
    if (!from || !to) return;
    const x1 = from.x + from.width / 2;
    const y1 = from.y + from.height / 2;
    const x2 = to.x + to.width / 2;
    const y2 = to.y + to.height / 2;
    const curve = Math.max(24, Math.min(90, Math.abs(x2 - x1) * .22 + (index % 3) * 10));
    const direction = x2 >= x1 ? 1 : -1;
    const pathData = `M ${x1} ${y1} C ${x1 + curve * direction} ${y1}, ${x2 - curve * direction} ${y2}, ${x2} ${y2}`;
    const visual = edgeVisualState(edge, options.reveal !== false);
    const path = svgElement("path", { d: pathData, class: `graph-edge is-${visual}${edge._active ? " is-active" : ""}`, "marker-end": `url(#${markerId})` });
    svg.append(path);
    const label = svgElement("text", { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 5, class: "edge-label", "text-anchor": "middle" });
    const stateLabel = visual === "blocked" ? edge.finding || "finding" : visual === "candidate" ? "candidate patch" : visual === "healthy" ? "verified" : edge.label || edge.id || "flow";
    label.textContent = compactText(stateLabel, 28);
    svg.append(label);
  });

  const affectedNodes = new Set();
  graph.edges.filter((edge) => edgeVisualState(edge, options.reveal !== false) !== "neutral").forEach((edge) => {
    affectedNodes.add(edge.from || edge.source);
    affectedNodes.add(edge.to || edge.target);
  });
  graph.nodes.forEach((node) => {
    const position = positions.get(node.id);
    const classes = ["graph-node"];
    if (affectedNodes.has(node.id)) classes.push("is-affected");
    if (options.reveal !== false && affectedNodes.has(node.id) && normalizedStatus(node.target_status).includes("eliminate")) classes.push("is-eliminate");
    const group = svgElement("g", { class: classes.join(" "), transform: `translate(${position.x} ${position.y})` });
    group.append(svgElement("rect", { width: position.width, height: position.height, rx: 9 }));
    const label = svgElement("text", { x: 10, y: 20 });
    label.textContent = compactText(node.label || node.name || node.id, 20);
    const meta = svgElement("text", { x: 10, y: 35, class: "node-meta" });
    meta.textContent = compactText(node.kind || node.type || node.target_status || node.id, 25);
    group.append(label, meta);
    svg.append(group);
  });
  container.replaceChildren(svg);
}

function latestGraphEvent() {
  return [...safeArray(state.run?.events)].reverse().find((event) => event.graph_delta);
}

function renderLiveGraph() {
  if (!state.scenario) {
    ui.liveGraph.replaceChildren(element("div", "empty-state", "Нет сгенерированного графа"));
    ui.graphCaption.textContent = "Красные findings появятся только после события проверки.";
    return;
  }
  const graphEvent = latestGraphEvent();
  renderGraphTo(ui.liveGraph, currentGraph(), { reveal: Boolean(state.run), label: "Текущее состояние синтетической архитектуры" });
  if (!state.run) ui.graphCaption.textContent = "Это входная модель. Все связи нейтральны: проверка ещё не запускалась.";
  else if (terminalState(state.run) === "succeeded") ui.graphCaption.textContent = "Финальное состояние после patch, повторной проверки и gate.";
  else if (graphEvent) ui.graphCaption.textContent = graphEvent.detail || graphEvent.label || "Применено фактическое изменение графа.";
  else ui.graphCaption.textContent = "Review выполняется. Пока finding не получен, граф остаётся нейтральным.";
}

function renderEventInspector() {
  const events = safeArray(state.run?.events);
  const selected = events.find((event) => (event.id || String(event.seq)) === state.selectedEventId);
  ui.inspectorBody.replaceChildren();
  if (!selected) {
    ui.inspectorBody.append(element("div", "empty-state", state.run ? "Ожидаю первое фактическое событие." : "Запусти E2E и выбери событие на временной шкале."));
    return;
  }
  const agent = currentAgents().find((item) => item.id === selected.actor_id);
  const header = element("div", "inspector-event-header");
  const badge = element("span", `test-state is-${normalizedStatus(selected.status || "completed")}`, normalizedStatus(selected.status || "completed"));
  header.append(badge, element("h3", "", selected.label || selected.kind || "Событие"), element("p", "", selected.detail || "Детали не переданы"));
  const grid = element("div", "inspector-grid");
  [
    ["Исполнитель", agent?.name || selected.actor_id],
    ["Тип", agentTypeLabel(agent?.type)],
    ["Tool", selected.tool],
    ["Task ID", selected.task_id],
    ["Время", formatTimestamp(selected.timestamp_unix_ms)],
    ["Event", selected.kind || selected.id],
  ].forEach(([label, value]) => {
    const field = element("div", "inspector-field");
    field.append(element("span", "", label), element(label === "Task ID" || label === "Event" ? "code" : "strong", "", asText(value)));
    grid.append(field);
  });
  ui.inspectorBody.append(header, grid);
  const testIds = safeArray(selected.test_ids);
  if (testIds.length) {
    const tests = element("div", "inspector-tests");
    tests.append(element("span", "", "Затронутые тесты"));
    const row = element("div", "mini-chip-row");
    testIds.forEach((id) => row.append(element("span", "mini-chip", id)));
    tests.append(row);
    ui.inspectorBody.append(tests);
  }
  const payload = safeObject(selected.data);
  if (Object.keys(payload).length) {
    const details = element("div", "inspector-payload-wrap");
    details.append(
      element("span", "inspector-payload-label", "Фактический payload"),
      element("pre", "inspector-payload", asText(payload)),
    );
    ui.inspectorBody.append(details);
  }
}

function renderEventLog() {
  const events = safeArray(state.run?.events);
  ui.eventLog.replaceChildren();
  ui.eventCount.textContent = `${events.length} ${events.length === 1 ? "событие" : events.length > 1 && events.length < 5 ? "события" : "событий"}`;
  if (!events.length) {
    ui.eventLog.append(element("li", "empty-state", "Событий пока нет"));
    return;
  }
  events.forEach((event, index) => {
    const item = element("li", "event-item");
    const button = element("button", `event-button${(event.id || String(event.seq)) === state.selectedEventId ? " is-selected" : ""}`);
    button.type = "button";
    const top = element("div", "event-topline");
    top.append(element("span", "event-seq", String(event.seq || index + 1).padStart(2, "0")), element("span", "event-time", formatTimestamp(event.timestamp_unix_ms)));
    button.append(top, element("h3", "", event.label || event.kind || "Событие"), element("p", "", event.detail || event.actor_id || ""));
    button.addEventListener("click", () => selectEvent(event.id || String(event.seq)));
    item.append(button);
    ui.eventLog.append(item);
  });
}

function inferAgentStage(agent) {
  const explicit = normalizedStatus(agent.stage || agent.phase || agent.group);
  if (explicit) return explicit;
  const identifier = normalizedStatus(agent.id);
  if (identifier === "orchestrator") return "planning";
  if (identifier === "architecture" || identifier === "workspace_validator") return "reviewing";
  if (identifier === "rule_evolver") return "remediating";
  if (identifier.includes("worker")) return "testing";
  if (identifier === "gate") return "gating";
  const text = normalizedStatus(`${agent.name || ""}_${agent.type || ""}_${agent.current_action || ""}`);
  if (text.includes("gate")) return "gating";
  if (text.includes("rereview") || text.includes("re_review") || text.includes("verify")) return "rereview";
  if (text.includes("test") || text.includes("fitness") || text.includes("golden")) return "testing";
  if (text.includes("remedi") || text.includes("patch") || text.includes("candidate") || text.includes("evolv") || text.includes("rule")) return "remediating";
  if (text.includes("review") || text.includes("ouro")) return "reviewing";
  return "planning";
}

function renderOrchestration() {
  const agents = currentAgents();
  ui.orchestrationDag.replaceChildren();
  ui.parallelismValue.textContent = `${state.scenario?.parallel_workers || 0} параллельно`;
  if (!agents.length) {
    const stages = plannedStages();
    if (stages.length) {
      const labels = { generate: "Generate", baseline: "Baseline shards", evolve: "Evolve rules + architecture", candidate: "Candidate shards", gate: "Unified gate" };
      stages.forEach((stage) => {
        const wrapper = element("div", "dag-stage");
        wrapper.append(element("div", "dag-stage-label", stage), element("div", "dag-node", labels[stage] || stage));
        ui.orchestrationDag.append(wrapper);
      });
    } else {
      ui.orchestrationDag.append(element("div", "empty-state", "План агентов появится после генерации сценария."));
    }
    return;
  }
  const groups = new Map();
  agents.forEach((agent) => {
    const stage = inferAgentStage(agent);
    if (!groups.has(stage)) groups.set(stage, []);
    groups.get(stage).push(agent);
  });
  const ordered = phaseDefinitions.map((phase) => phase.id).filter((phase) => groups.has(phase));
  [...groups.keys()].forEach((stage) => { if (!ordered.includes(stage)) ordered.push(stage); });
  ordered.forEach((stage) => {
    const wrapper = element("div", "dag-stage");
    const definition = phaseDefinitions.find((phase) => phase.id === stage);
    wrapper.append(element("div", "dag-stage-label", definition?.label || stage));
    groups.get(stage).forEach((agent) => wrapper.append(element("div", `dag-node is-${normalizedStatus(agent.status || "planned")}`, agent.name || agent.label || agent.id)));
    ui.orchestrationDag.append(wrapper);
  });
}

function renderAgents() {
  const agents = currentAgents();
  const actualAgents = safeArray(state.run?.agents);
  ui.agentsTabCount.textContent = String(agents.length);
  ui.agentGrid.replaceChildren();
  const activeCount = actualAgents.filter((agent) => normalizedStatus(agent.status) === "running").length;
  ui.agentsSummary.textContent = state.run ? `${activeCount} active · ${actualAgents.length} total` : `${agents.length} planned`;
  if (!agents.length) {
    ui.agentGrid.append(element("div", "empty-state", "Исполнителей пока нет."));
    renderOrchestration();
    return;
  }
  agents.forEach((agent) => {
    const card = element("article", "agent-card");
    const top = element("div", "agent-card-top");
    const identity = element("div");
    identity.append(element("h3", "", agent.name || agent.label || agent.id), element("div", "agent-type", agentTypeLabel(agent.type)));
    top.append(identity, element("span", `agent-status is-${normalizedStatus(agent.status || "planned")}`));
    const hidePendingGlobalPass = runIsActive() && agent.id === "gate" && normalizedStatus(agent.current_action).includes("pass");
    const visibleAction = hidePendingGlobalPass ? "Локальные проверки сведены; ожидается terminal event" : agent.current_action;
    const action = element("div", "agent-action", visibleAction || (state.run ? "Ожидает фактическую задачу" : "Будет назначен после запуска"));
    const metrics = element("div", "agent-metrics");
    [
      ["STATUS", normalizedStatus(agent.status || "planned")],
      ["DURATION", Number.isFinite(Number(agent.duration_ms)) ? formatDuration(agent.duration_ms) : "—"],
      ["COST", formatMoney(agent.cost_usd, { showZero: state.run?.execution !== "live" })],
    ].forEach(([label, value]) => {
      const metric = element("div");
      metric.append(element("span", "", label), element("strong", "", value));
      metrics.append(metric);
    });
    card.append(top, action, metrics);
    const tools = safeArray(agent.tools);
    if (tools.length) {
      const list = element("div", "agent-tools");
      tools.forEach((tool) => list.append(element("span", "mini-chip", tool)));
      card.append(list);
    }
    ui.agentGrid.append(card);
  });
  renderOrchestration();
}

function currentTests() {
  const planned = safeArray(state.scenario?.tests);
  const actual = safeArray(state.run?.tests);
  if (!actual.length) return planned.map((test) => ({ ...safeObject(test) }));
  const actualById = new Map(actual.map((test) => [test.id, test]));
  const merged = planned.map((test) => ({ ...safeObject(test), ...safeObject(actualById.get(test.id)) }));
  actual.forEach((test) => { if (!planned.some((plannedTest) => plannedTest.id === test.id)) merged.push({ ...safeObject(test) }); });
  return merged;
}

function testStatus(test) {
  const explicit = normalizedStatus(test.status);
  if (explicit && explicit !== "idle") return explicit;
  if (test.candidate !== undefined && test.candidate !== null) {
    const candidate = safeObject(test.candidate);
    if (candidate.passed === false || normalizedStatus(candidate.status).includes("fail")) return "failed";
    return "passed";
  }
  return state.run ? "pending" : "not_run";
}

function testChanged(test) {
  if (!test.baseline || !test.candidate) return false;
  const signature = (value) => {
    const result = safeObject(value);
    return JSON.stringify({
      passed: result.passed,
      outcome: result.actual_outcome,
      findings: safeArray(result.actual_findings).map((finding) => `${finding.rule_id}:${finding.severity}`).sort(),
      suppressed: safeArray(result.suppressed).map((finding) => `${finding.rule_id}:${finding.exception}`).sort(),
    });
  };
  return signature(test.baseline) !== signature(test.candidate);
}

function testMatchesFilter(test) {
  const status = testStatus(test);
  if (state.testFilter === "failed" && !status.includes("fail")) return false;
  if (state.testFilter === "passed" && !["passed", "success", "completed"].some((value) => status.includes(value))) return false;
  if (state.testFilter === "changed" && !testChanged(test) && !status.includes("changed")) return false;
  const query = state.testSearch.trim().toLowerCase();
  if (!query) return true;
  const haystack = [test.id, test.title, test.scenario, test.expected, ...safeArray(test.changed_files), ...safeArray(test.input_artifacts)].map(asText).join(" ").toLowerCase();
  return haystack.includes(query);
}

function formatOutcome(value) {
  if (value === undefined || value === null) return "не запускался";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "pass" : "fail";
  const object = safeObject(value);
  if (typeof object.passed === "boolean") return `${object.passed ? "PASS" : "MISMATCH"} · ${object.actual_outcome || "no outcome"}`;
  return object.label || object.verdict || object.status || object.outcome || object.actual_outcome || object.actual || compactText(value, 72);
}

function formatExpected(value) {
  const expected = safeObject(value);
  if (!Object.keys(expected).length) return compactText(value, 72);
  const rules = safeArray(expected.findings).map((finding) => finding.rule_id).filter(Boolean);
  return `${expected.outcome || "outcome —"}${rules.length ? ` · ${rules.join(", ")}` : " · no findings"}`;
}

function formatInputArtifacts(value) {
  const artifacts = safeArray(value);
  if (!artifacts.length) return "—";
  return artifacts.map((artifact) => {
    if (typeof artifact === "string") return artifact;
    const object = safeObject(artifact);
    return `${object.path || "artifact"}${object.preview ? `\n${object.preview}` : ""}`;
  }).join("\n\n");
}

function renderTestDetail(test) {
  ui.testDetail.replaceChildren();
  if (!test) {
    ui.testDetail.classList.add("is-hidden");
    return;
  }
  ui.testDetail.classList.remove("is-hidden");
  const header = element("div", "test-detail-header");
  const title = element("div");
  title.append(element("h3", "", `${test.id || "test"} · ${test.title || "Без названия"}`), element("p", "", test.scenario || "Описание сценария не передано"));
  header.append(title, element("span", `test-state is-${testStatus(test)}`, testStatus(test)));
  const columns = element("div", "detail-columns");
  [
    ["Ожидается", test.expected],
    ["Baseline actual", test.baseline === undefined ? "Появится после baseline run" : test.baseline],
    ["Candidate actual", test.candidate === undefined ? "Появится после candidate run" : test.candidate],
    ["Изменённые файлы", safeArray(test.changed_files).join("\n") || "—"],
    ["Входные артефакты", formatInputArtifacts(test.input_artifacts)],
    ["Worker", test.worker_id || "ещё не назначен"],
  ].forEach(([label, value]) => {
    const block = element("div", "detail-block");
    block.append(element("span", "", label), element("pre", "", asText(value)));
    columns.append(block);
  });
  ui.testDetail.append(header, columns);
}

function renderTestStatusSummary(tests) {
  const counts = { passed: 0, failed: 0, running: 0, pending: 0 };
  tests.forEach((test) => {
    const status = testStatus(test);
    if (["passed", "success", "completed"].some((value) => status.includes(value)) && !status.includes("baseline")) counts.passed += 1;
    else if (status.includes("fail")) counts.failed += 1;
    else if (status.includes("running")) counts.running += 1;
    else counts.pending += 1;
  });
  ui.testStatusBar.replaceChildren();
  [["passed", "Прошли"], ["failed", "Упали"], ["running", "В работе"], ["pending", "Ожидают"]].forEach(([status, label]) => {
    const pill = element("span", `test-status-pill is-${status}`);
    pill.append(element("i"), element("span", "", `${label}: ${counts[status]}`));
    ui.testStatusBar.append(pill);
  });
  const completed = counts.passed + counts.failed;
  ui.testsProgress.replaceChildren(element("strong", "", `${completed} / ${tests.length}`), element("span", "", "выполнено"));
}

function renderTests() {
  const tests = currentTests();
  ui.testsTabCount.textContent = String(tests.length);
  ui.testsTabLabel.textContent = tests.length === 26 ? "26 тестов" : "Тесты";
  ui.testsTitle.textContent = tests.length ? `Test explorer · ${tests.length} проверок` : "Какие проверки выполняются";
  renderTestStatusSummary(tests);
  const filtered = tests.filter(testMatchesFilter);
  ui.testTableBody.replaceChildren();
  if (!filtered.length) {
    const row = element("tr");
    const cell = element("td", "empty-cell", tests.length ? "По текущему фильтру ничего не найдено." : "Сгенерируй сценарий, чтобы увидеть тест-план.");
    cell.colSpan = 6;
    row.append(cell);
    ui.testTableBody.append(row);
  } else {
    filtered.forEach((test) => {
      const row = element("tr", test.id === state.selectedTestId ? "is-selected" : "");
      row.dataset.testId = test.id || "";
      const nameCell = element("td", "test-name");
      const selectButton = element("button", "test-name-button");
      selectButton.type = "button";
      selectButton.append(element("strong", "", test.title || test.id || "Тест"), element("span", "", test.id || "—"));
      selectButton.addEventListener("click", () => {
        state.selectedTestId = test.id;
        renderTests();
      });
      nameCell.append(selectButton);
      const expected = element("td", "result-cell", compactText(formatExpected(test.expected), 72));
      const baseline = element("td", "result-cell", compactText(formatOutcome(test.baseline), 72));
      const candidate = element("td", "result-cell", compactText(formatOutcome(test.candidate), 72));
      const worker = element("td", "", test.worker_id || "—");
      const statusCell = element("td");
      statusCell.append(element("span", `test-state is-${testStatus(test)}`, testStatus(test).replaceAll("_", " ")));
      row.append(nameCell, expected, baseline, candidate, worker, statusCell);
      ui.testTableBody.append(row);
    });
  }
  const selected = tests.find((test) => test.id === state.selectedTestId);
  renderTestDetail(selected);
}

function diffLines(evolution) {
  const object = safeObject(evolution);
  const change = safeObject(object.change);
  const mutation = safeObject(object.mutation);
  if (safeArray(change.diff_lines).length) return change.diff_lines;
  if (safeArray(mutation.diff_lines).length) return mutation.diff_lines;
  const patchDiff = safeObject(object.patch).diff;
  if (typeof patchDiff === "string" && patchDiff) {
    return patchDiff.split("\n").map((text) => ({
      text,
      kind: text.startsWith("+++") || text.startsWith("---") ? "file" : text.startsWith("@@") ? "hunk" : text.startsWith("+") ? "add" : text.startsWith("-") ? "remove" : "context",
    }));
  }
  return [];
}

function renderDiff(target, lines) {
  target.replaceChildren();
  safeArray(lines).forEach((line) => {
    const object = typeof line === "string" ? { text: line, kind: line.startsWith("+") ? "add" : line.startsWith("-") ? "remove" : "context" } : safeObject(line);
    const row = element("span", `diff-${normalizedStatus(object.kind || "context")}`, object.text || "");
    target.append(row);
  });
}

function finalResult() {
  return terminalState(state.run) ? safeObject(state.run?.result) : {};
}

function resultArchitecture() {
  return safeObject(finalResult().architecture_evolution);
}

function resultRule() {
  return safeObject(finalResult().rule_evolution);
}

function decorateFinalGraph(graphValue, deltas, stage) {
  const graph = cloneGraph(graphValue);
  safeArray(deltas).forEach((delta) => {
    const object = safeObject(delta);
    const edge = graph.edges.find((item) => item.id === object.edge_id);
    if (!edge) return;
    edge._visual = stage === "before" ? "blocked" : "healthy";
    edge.finding = stage === "before" ? object.rule_id || "finding" : null;
  });
  return graph;
}

function renderArchitectureChanges() {
  ui.architectureComparison.replaceChildren();
  ui.architectureDiffWrap.classList.add("is-hidden");
  const result = finalResult();
  const resultGraph = safeObject(result.graph);
  const architecture = resultArchitecture();
  const eventsWithDelta = safeArray(state.run?.events).filter((event) => event.graph_delta);
  const finalDeltas = safeArray(resultGraph.deltas);
  const terminal = terminalState(state.run);
  let before = safeObject(resultGraph.before).nodes
    ? decorateFinalGraph(resultGraph.before, finalDeltas, "before")
    : safeObject(architecture.before).nodes ? architecture.before : neutralInputGraph(state.scenario?.graph);
  let after = safeObject(resultGraph.after).nodes
    ? decorateFinalGraph(resultGraph.after, finalDeltas, "after")
    : safeObject(architecture.after).nodes ? architecture.after : eventsWithDelta.length ? currentGraph() : null;
  if (!state.run || (!after && !eventsWithDelta.length)) {
    ui.architectureComparison.append(element("div", "empty-state", "Сравнение появится после фактической проверки и изменения."));
    ui.architectureChangeStatus.textContent = "ещё не проверено";
    return;
  }
  const comparisonBefore = element("div", "comparison-panel");
  const beforeHeading = element("h3");
  beforeHeading.append(element("span", "", "ВХОД"), element("span", "", `${safeArray(safeObject(before).edges).length} flows`));
  const beforeGraph = element("div", "comparison-graph");
  renderGraphTo(beforeGraph, before, { compact: true, reveal: Boolean(terminal || eventsWithDelta.length), label: "Архитектура до изменения" });
  comparisonBefore.append(beforeHeading, beforeGraph);
  const comparisonAfter = element("div", "comparison-panel");
  const afterHeading = element("h3");
  afterHeading.append(
    element("span", "", terminal === "succeeded" ? "ПОСЛЕ GATE" : terminal === "failed" ? "ОСТАНОВЛЕНО ДО GATE" : "ТЕКУЩЕЕ СОСТОЯНИЕ"),
    element("span", "", `${eventsWithDelta.length} graph deltas`),
  );
  const afterGraph = element("div", "comparison-graph");
  renderGraphTo(afterGraph, after || currentGraph(), { compact: true, reveal: true, label: "Архитектура после изменения" });
  comparisonAfter.append(afterHeading, afterGraph);
  ui.architectureComparison.append(comparisonBefore, comparisonAfter);
  ui.architectureChangeStatus.textContent = terminal === "succeeded"
    ? "проверено gate"
    : terminal === "failed"
      ? `gate не пройден · ${eventsWithDelta.length} graph deltas`
      : `${eventsWithDelta.length} фактических изменений`;
  const lines = diffLines(architecture);
  if (lines.length) {
    ui.architectureDiffWrap.classList.remove("is-hidden");
    renderDiff(ui.architectureDiff, lines);
  }
}

function causalEvents() {
  const keywords = ["finding", "detect", "review", "patch", "remedi", "candidate", "test", "rule", "gate", "complete"];
  return safeArray(state.run?.events).filter((event) => {
    const kind = normalizedStatus(`${event.kind || ""}_${event.id || ""}`);
    return keywords.some((keyword) => kind.includes(keyword));
  });
}

function renderCausalChain() {
  const events = causalEvents();
  ui.causalChain.replaceChildren();
  if (!events.length) {
    ui.causalChain.append(element("li", "empty-state", "Нет фактических изменений."));
    return;
  }
  events.forEach((event, index) => {
    const item = element("li", "causal-item");
    item.append(element("span", "causal-index", String(index + 1)), element("h3", "", event.label || event.kind), element("p", "", event.detail || `${event.actor_id || "worker"} · ${normalizedStatus(event.status)}`));
    ui.causalChain.append(item);
  });
}

function metricValue(object, keys) {
  for (const key of keys) if (object[key] !== undefined) return object[key];
  return "—";
}

function renderRuleChanges() {
  ui.ruleChangeBody.replaceChildren();
  const rule = resultRule();
  const mutation = safeObject(rule.mutation);
  if (!Object.keys(rule).length) {
    const ruleEvents = safeArray(state.run?.events).filter((event) => normalizedStatus(`${event.kind || ""}_${event.id || ""}_${event.actor_id || ""}`).includes("rule"));
    if (ruleEvents.length) {
      ui.ruleChangeStatus.textContent = "в процессе";
      const list = element("ol", "causal-chain");
      ruleEvents.forEach((event, index) => {
        const item = element("li", "causal-item");
        item.append(element("span", "causal-index", String(index + 1)), element("h3", "", event.label || event.kind), element("p", "", event.detail || ""));
        list.append(item);
      });
      ui.ruleChangeBody.append(list);
    } else {
      ui.ruleChangeStatus.textContent = "ожидание";
      ui.ruleChangeBody.append(element("div", "empty-state", "Rule diff и метрики появятся после мутации и тестов."));
    }
    return;
  }
  const tests = safeObject(rule.tests);
  const before = safeObject(tests.before);
  const after = safeObject(tests.after);
  ui.ruleChangeStatus.textContent = rule.status || (tests.gate_passed ? "gate passed" : "готово");
  const summary = element("div", "rule-summary");
  [
    ["Правило", mutation.target_rule || mutation.rule_id || "—"],
    ["Precision", `${asText(metricValue(before, ["precision"]))} → ${asText(metricValue(after, ["precision"]))}`],
    ["Weighted cost", `${asText(metricValue(before, ["weighted_cost"]))} → ${asText(metricValue(after, ["weighted_cost"]))}`],
  ].forEach(([label, value]) => {
    const item = element("div");
    item.append(element("span", "", label), element("strong", "", value));
    summary.append(item);
  });
  ui.ruleChangeBody.append(summary);
  const lines = diffLines(rule);
  if (lines.length) {
    const diff = element("pre", "code-diff");
    renderDiff(diff, lines);
    ui.ruleChangeBody.append(diff);
  }
}

function renderChanges() {
  renderArchitectureChanges();
  renderCausalChain();
  renderRuleChanges();
}

function normalizedArtifacts() {
  const raw = finalResult().artifacts;
  if (Array.isArray(raw)) return raw.map((artifact, index) => typeof artifact === "string" ? { name: artifact, path: artifact } : { id: `artifact-${index + 1}`, ...safeObject(artifact) });
  return Object.entries(safeObject(raw)).map(([id, artifact]) => typeof artifact === "string" ? { id, name: id, path: artifact } : { id, ...safeObject(artifact) });
}

function gatePassed(gate) {
  if (gate.passed === true) return true;
  const status = normalizedStatus(gate.status || gate.verdict || gate.outcome);
  return ["passed", "pass", "approve", "approved", "succeeded", "success"].includes(status);
}

function renderArtifacts() {
  const result = finalResult();
  const gate = safeObject(result.gate);
  const resultSummary = safeObject(result.summary);
  const artifacts = normalizedArtifacts();
  ui.gateSummary.replaceChildren();
  ui.gateSummary.classList.toggle("is-final", Boolean(Object.keys(result).length));
  ui.artifactList.replaceChildren();
  ui.resultMode.textContent = runDisplayMode();
  ui.resultMode.className = `mode-badge ${state.run?.recorded_evidence ? "is-recorded" : state.run?.execution === "live" ? "is-paid" : "is-recommended"}`;
  ui.exportReportButton.disabled = !state.run?.run_id || !terminalState(state.run);
  ui.artifactCount.textContent = `${artifacts.length} ${artifacts.length === 1 ? "файл" : artifacts.length > 1 && artifacts.length < 5 ? "файла" : "файлов"}`;
  if (!Object.keys(result).length) {
    const terminal = terminalState(state.run);
    ui.resultEngine.textContent = state.run?.recorded_evidence
      ? terminal === "failed"
        ? `Recorded evidence проверено; run остановлен до итогового gate · code: ${state.run.error_code || "run_failed"}`
        : "Recorded evidence проверено; итоговый result отсутствует."
      : "Итоговый architecture engine появится после gate.";
    const active = runIsActive();
    ui.gateSummary.append(element("div", "panel empty-state", active ? "Итоговый gate ещё не зафиксирован. PASS/FAIL появится только после terminal event." : "Gate ещё не запускался."));
    ui.artifactList.append(element("div", "empty-state", active
      ? "Артефакты собираются, но итоговый manifest скрыт до завершения run."
      : terminal === "failed"
        ? "Run завершился до финального artifact manifest; failed event и точный сценарий сохранены в recorded evidence."
        : "После E2E здесь будут scenario, events, findings, patch, test report, gate report и candidate manifest."));
    return;
  }
  const tests = currentTests();
  const passedTests = Number.isFinite(Number(resultSummary.candidate_passed))
    ? Number(resultSummary.candidate_passed)
    : tests.filter((test) => safeObject(test.candidate).passed === true).length;
  const totalTests = Number.isFinite(Number(resultSummary.tests)) ? Number(resultSummary.tests) : tests.length;
  const changed = safeArray(resultSummary.behavior_changed);
  const checks = safeArray(gate.checks);
  const architectureClosed = checks.some((check) => check.id === "architecture_closed" && check.passed === true)
    || safeObject(safeObject(result.architecture_evolution).gate).passed === true;
  ui.resultEngine.textContent = `Architecture engine: ${resultSummary.architecture_engine || "—"}${state.run?.execution === "live" && Number(state.run?.cost_usd) > 0 ? ` · actual cost ${formatMoney(state.run.cost_usd, { showZero: false })}` : ""} · ${state.run?.recorded_evidence ? "это проверенное recorded evidence, новых model calls нет" : "fresh run"}`;
  [
    ["Gate", gatePassed(gate) ? "PASSED" : normalizedStatus(gate.status || gate.verdict || "FAILED"), gatePassed(gate) ? "is-passed" : "is-failed"],
    ["Architecture finding", architectureClosed ? "CLOSED" : "OPEN", architectureClosed ? "is-passed" : "is-failed"],
    ["Candidate tests", `${passedTests}/${totalTests}`, passedTests === totalTests ? "is-passed" : "is-failed"],
    ["Behavior changed only", changed.length ? changed.join(", ") : "none", changed.length === 1 && changed[0] === "pr-15" ? "is-passed" : ""],
    ["Human review", resultSummary.human_review_required === true ? "REQUIRED" : "NOT REQUIRED", ""],
    ["Merge performed", String(resultSummary.merge_performed === true), resultSummary.merge_performed === false ? "is-passed" : "is-failed"],
    ["Artifacts", String(artifacts.length), artifacts.length === 9 ? "is-passed" : ""],
  ].forEach(([label, value, className]) => {
    const card = element("div", `gate-card ${className}`.trim());
    card.append(element("span", "", label), element("strong", "", value));
    ui.gateSummary.append(card);
  });
  if (checks.length) {
    const checkPanel = element("div", "gate-checks");
    checkPanel.append(element("strong", "", "Что именно пропустил unified gate"));
    const list = element("div", "gate-check-list");
    checks.forEach((check) => {
      const item = element("span", `gate-check is-${check.passed ? "passed" : "failed"}`);
      item.append(element("i"), element("span", "", check.label || check.id || "gate check"));
      list.append(item);
    });
    checkPanel.append(list);
    ui.gateSummary.append(checkPanel);
  }
  if (!artifacts.length) {
    ui.artifactList.append(element("div", "empty-state", "Backend завершил run, но не передал manifest артефактов."));
    return;
  }
  artifacts.forEach((artifact) => {
    const row = element("div", "artifact-row");
    const icon = element("span", "artifact-icon", "⌁");
    const identity = element("div", "artifact-name");
    identity.append(element("strong", "", artifact.name || artifact.label || artifact.id || artifact.path || "artifact"), element("span", "", artifact.kind || artifact.type || "evidence"));
    const meta = element("div", "artifact-meta", artifact.path || artifact.uri || artifact.description || "local artifact");
    const checksum = element("code", "artifact-checksum", artifact.sha256 || artifact.checksum || artifact.commit || "checksum —");
    row.append(icon, identity, meta, checksum);
    ui.artifactList.append(row);
  });
}

function renderCounters() {
  const tests = currentTests();
  ui.testsTabCount.textContent = String(tests.length);
  ui.agentsTabCount.textContent = String(currentAgents().length);
}

function ensureLatestEventSelection() {
  const events = safeArray(state.run?.events);
  if (!events.length) {
    state.selectedEventId = null;
    return;
  }
  if (!state.inspectorPinned || !events.some((event) => (event.id || String(event.seq)) === state.selectedEventId)) {
    const latest = events[events.length - 1];
    state.selectedEventId = latest.id || String(latest.seq);
  }
}

function renderAll() {
  ensureLatestEventSelection();
  renderRuntime();
  renderHeader();
  renderMiniStatus();
  renderControls();
  renderRunStatus();
  renderFailureRecovery();
  renderScenario();
  renderProgress();
  renderArchitectureCheckpoints();
  renderLiveEvidence();
  renderSwimlanes();
  renderLiveGraph();
  renderEventInspector();
  renderEventLog();
  renderAgents();
  renderTests();
  renderChanges();
  renderArtifacts();
  renderCounters();
}

function resetRunState() {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
  state.run = null;
  state.selectedEventId = null;
  state.inspectorPinned = false;
  state.selectedTestId = null;
  state.pollErrors = 0;
  state.recoveryOfRunId = null;
}

async function generateScenario() {
  if (runIsActive()) return null;
  const seed = ui.seed.value.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(seed)) {
    setStatus("error", "Seed некорректен", "Используй латиницу, цифры, точку, дефис или подчёркивание — максимум 64 символа");
    return null;
  }
  setControlsDisabled(true);
  setStatus("running", "Генерирую новую синтетическую модель…", "Результаты проверок ещё не существуют");
  try {
    const payload = await request("/api/v2/scenarios", {
      method: "POST",
      body: JSON.stringify({
        preset: ui.preset.value,
        seed,
        parallel_workers: Number(ui.workers.value),
      }),
    });
    resetRunState();
    state.scenario = payload.scenario;
    state.selectedTestId = safeArray(state.scenario?.tests)[0]?.id || null;
    renderAll();
    setStatus("generated", "Синтетическая модель готова", `${safeArray(state.scenario?.tests).length} тестов видны заранее; finding и pass пока отсутствуют`);
    return state.scenario;
  } catch (error) {
    setStatus("error", "Не удалось сгенерировать модель", friendlyErrors[error.code] || error.code || "request_failed");
    return null;
  } finally {
    renderControls();
  }
}

function restoreAfterTerminal() {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
  setControlsDisabled(false);
  renderAll();
}

async function startRun() {
  if (runIsActive()) return;
  if (
    !state.scenario
    || state.scenario.preset !== ui.preset.value
    || Number(state.scenario.parallel_workers) !== Number(ui.workers.value)
  ) {
    const generated = await generateScenario();
    if (!generated) return;
  }
  const execution = ui.execution.value;
  if (execution === "live" && !selectedLiveIsReady()) {
    const code = safeObject(state.liveReadiness).code || "live_preflight_not_run";
    setStatus("error", "Live preflight не пройден", friendlyErrors[code] || code);
    return;
  }
  if (execution === "live" && !ui.paid.checked) {
    setStatus("error", "Нужно подтверждение", friendlyErrors.paid_run_confirmation_required);
    return;
  }
  state.selectedEventId = null;
  state.inspectorPinned = false;
  state.pollErrors = 0;
  setControlsDisabled(true);
  ui.runButtonLabel.textContent = "E2E запускается…";
  setStatus("running", "Оркестратор запускает полный E2E…", `${state.scenario.parallel_workers || ui.workers.value} workers будут работать параллельно`);
  try {
    const run = await request("/api/v2/runs", {
      method: "POST",
      body: JSON.stringify({
        scenario_id: state.scenario.scenario_id,
        execution,
        model_id: ui.model.value,
        confirm_paid_run: execution === "live" && ui.paid.checked,
        recovery_of_run_id: execution === "local" ? state.recoveryOfRunId : null,
      }),
    });
    state.run = run;
    state.recoveryOfRunId = null;
    if (run.scenario) state.scenario = run.scenario;
    renderAll();
    window.requestAnimationFrame(() => {
      ui.liveProcess.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "start",
      });
    });
    if (terminalState(run)) restoreAfterTerminal();
    else schedulePoll(run.run_id, 250);
  } catch (error) {
    setStatus("error", "Не удалось запустить E2E", friendlyErrors[error.code] || error.code || "request_failed");
    setControlsDisabled(false);
    renderControls();
  }
}

function recoverLocally() {
  if (!state.scenario || runIsActive()) return;
  state.recoveryOfRunId = state.run?.execution === "live" && terminalState(state.run) === "failed" ? state.run.run_id : null;
  ui.execution.value = "local";
  ui.paid.checked = false;
  syncExecutionControls();
  setPage("process");
  startRun();
}

async function exportRunReport() {
  if (!state.run?.run_id || !terminalState(state.run)) return;
  ui.exportReportButton.disabled = true;
  try {
    const report = await request(`/api/v2/runs/${encodeURIComponent(state.run.run_id)}/report`);
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = `aga-self-evolution-${state.run.run_id}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  } catch (error) {
    setStatus("error", "Не удалось экспортировать report", friendlyErrors[error.code] || error.code || "report_failed");
  } finally {
    ui.exportReportButton.disabled = false;
  }
}

function schedulePoll(runId, delay = 700) {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  state.pollTimer = window.setTimeout(() => pollRun(runId), delay);
}

async function pollRun(runId) {
  if (!state.run || state.run.run_id !== runId) return;
  try {
    const run = await request(`/api/v2/runs/${encodeURIComponent(runId)}`);
    if (!state.run || state.run.run_id !== runId) return;
    state.run = run;
    if (run.scenario) state.scenario = run.scenario;
    state.pollErrors = 0;
    renderAll();
    if (terminalState(run)) {
      restoreAfterTerminal();
      return;
    }
    schedulePoll(runId, 650);
  } catch (error) {
    state.pollErrors += 1;
    setStatus("running", "E2E выполняется · восстанавливаю связь…", `Попытка ${state.pollErrors}; run ${runId} не потерян`);
    schedulePoll(runId, Math.min(5000, 700 * 2 ** Math.min(state.pollErrors, 3)));
  }
}

async function bootstrap() {
  setStatus("running", "Подключаю Control Room…", "Загружаю runtime и последний run");
  try {
    const payload = await request("/api/v2/bootstrap");
    state.token = payload.session_token || "";
    state.presets = normalizedPresets(payload.presets);
    state.runtime = payload.runtime;
    renderPresetOptions();
    renderRuntime();
    renderWorkerOptions();
    if (payload.last_run) {
      state.run = payload.last_run;
      state.scenario = payload.last_run.scenario || null;
      state.selectedTestId = safeArray(state.scenario?.tests)[0]?.id || null;
    }
    renderModelOptions();
    applyDemoProfile({ clearScenario: false });
    renderAll();
    if (runIsActive()) {
      setControlsDisabled(true);
      schedulePoll(state.run.run_id, 200);
    } else if (state.scenario) {
      renderRunStatus();
    } else {
      setStatus("idle", "Готово к запуску", "Данные создадутся автоматически; заранее показанных findings или pass-результатов нет");
    }
    if (!runIsActive() && ui.execution.value === "live") refreshLiveReadiness(false);
  } catch (error) {
    setStatus("error", "Control Room не подключился к API v2", error.code || "bootstrap_failed");
    ui.generate.disabled = true;
    ui.runButton.disabled = true;
  }
}

ui.pageTabs.forEach((tab) => tab.addEventListener("click", () => setPage(tab.dataset.page)));
ui.testFilters.forEach((button) => button.addEventListener("click", () => {
  state.testFilter = button.dataset.testFilter;
  ui.testFilters.forEach((candidate) => {
    const active = candidate === button;
    candidate.classList.toggle("is-active", active);
    candidate.setAttribute("aria-pressed", String(active));
  });
  renderTests();
}));
ui.testSearch.addEventListener("input", () => {
  state.testSearch = ui.testSearch.value;
  renderTests();
});
ui.execution.addEventListener("change", () => {
  renderControls();
  if (ui.execution.value === "live") refreshLiveReadiness(false);
});
ui.model.addEventListener("change", () => {
  state.liveReadiness = null;
  renderControls();
  if (ui.execution.value === "live") refreshLiveReadiness(true);
});
ui.executionRadios.forEach((radio) => radio.addEventListener("change", () => {
  if (!radio.checked) return;
  ui.execution.value = radio.value;
  renderControls();
  if (radio.value === "live") refreshLiveReadiness(false);
}));
ui.demoProfileRadios.forEach((radio) => radio.addEventListener("change", () => {
  if (!radio.checked || runIsActive()) return;
  applyDemoProfile();
  renderAll();
  refreshLiveReadiness(true);
}));
ui.paid.addEventListener("change", renderControls);
ui.watchLinks.forEach((button) => button.addEventListener("click", () => setPage(button.dataset.watchPage)));
ui.generate.addEventListener("click", generateScenario);
ui.runButton.addEventListener("click", startRun);
ui.recoveryLocalButton.addEventListener("click", recoverLocally);
ui.refreshReadinessButton.addEventListener("click", () => refreshLiveReadiness(true));
ui.exportReportButton.addEventListener("click", exportRunReport);

startElapsedClock();
renderPhaseTrack();
bootstrap();
