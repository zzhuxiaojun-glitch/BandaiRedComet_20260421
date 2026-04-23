// ═══════════════════════════════════════════
// 万代抢购器 · 前端逻辑
// 所有后端调用通过 window.pywebview.api.* (Promise 风格)
// ═══════════════════════════════════════════

// ─── 全局状态 ───────────────────────────────
let POLL_SNAPSHOT_INTERVAL = 500;
let POLL_LOGS_INTERVAL = 250;
let countdownTimer = null;
let snapshotTimer = null;
let logTimer = null;
let currentView = "form";
let cachedAddresses = []; // 填地址下拉用
let totalWait = null;     // 总等待时间，用于 progress 计算

// ─── 启动 ─────────────────────────────────
window.addEventListener("pywebviewready", async () => {
  // 预填用户上次填过的字段
  try {
    const saved = await pywebview.api.load_saved();
    if (saved && Object.keys(saved).length > 0) {
      hydrateForm(saved);
    }
  } catch (e) {
    console.warn("load_saved failed", e);
  }

  // 默认开抢时间 = 当前 +1 小时
  const input = document.getElementById("snipe_time");
  if (!input.value) {
    const t = new Date(Date.now() + 3600 * 1000);
    input.value = t.toISOString().slice(0, 19);
  }

  // 启动状态轮询
  startSnapshotPolling();
  startLogPolling();
});

function hydrateForm(data) {
  for (const [k, v] of Object.entries(data)) {
    const el = document.getElementById(k);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v != null ? v : "";
  }
}

function collectForm() {
  const ids = [
    "ck", "spu_id", "sku_id", "num", "address_id", "snipe_time",
    "concurrency", "max_retries", "pre_warmup_seconds", "max_early_fire_ms",
    "price_ceiling", "poll_stock",
    "notify_enabled", "notify_provider", "notify_token",
    "remember_ck",
  ];
  const out = {};
  for (const id of ids) {
    const el = document.getElementById(id);
    if (!el) continue;
    if (el.type === "checkbox") out[id] = el.checked;
    else if (el.type === "number") out[id] = el.value ? Number(el.value) : null;
    else out[id] = el.value || null;
  }
  // 默认 timezone
  out.timezone = "Asia/Shanghai";
  return out;
}

// ─── 表单操作 ──────────────────────────────

async function runPrecheck() {
  showFeedback("验证中...", "info");
  const form = collectForm();
  try {
    const res = await pywebview.api.precheck_only(form);
    if (!res.ok) {
      showFeedback("预检失败：" + (res.error || "未知"), "error");
      return;
    }
    // 渲染商品
    const p = res.product || {};
    document.getElementById("product-preview").classList.remove("hidden");
    document.getElementById("product-name-cn").textContent = p.nameCn || "(未查到中文名)";
    document.getElementById("product-name-jp").textContent =
      p.nameJp ? "日文原名：" + p.nameJp : "";
    document.getElementById("product-price").textContent =
      p.price != null ? "¥" + p.price : "价格 ?";
    document.getElementById("product-stock").textContent =
      p.stock != null ? ("库存 " + p.stock) : "";
    document.getElementById("product-status").textContent =
      p.saleStatus === 0 ? "可售" : "未开售 (" + p.saleStatus + ")";

    // 地址下拉
    cachedAddresses = res.addresses || [];
    const addrSel = document.getElementById("address_id");
    addrSel.innerHTML = "";
    for (const a of cachedAddresses) {
      const opt = document.createElement("option");
      opt.value = a.id;
      opt.textContent = `${a.receiver} · ${a.summary}`;
      addrSel.appendChild(opt);
    }

    showFeedback(
      `✅ 预检通过 · memberId=${res.member_id} · ${cachedAddresses.length} 个地址`,
      "success"
    );

    // 自动拉 SKU
    fetchSkus();
  } catch (e) {
    showFeedback("预检异常：" + e, "error");
  }
}

async function fetchSkus() {
  const ck = document.getElementById("ck").value;
  const spuId = document.getElementById("spu_id").value;
  if (!ck || !spuId) return;
  try {
    const res = await pywebview.api.list_skus(ck, spuId);
    if (!res.ok) return;
    const sel = document.getElementById("sku_id");
    sel.innerHTML = "";
    for (const s of (res.skus || [])) {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = `${s.name} · ¥${s.price} · 库存 ${s.stock}`;
      sel.appendChild(opt);
    }
  } catch (e) {
    console.warn("list_skus failed", e);
  }
}

function parseSpuUrl() {
  const input = document.getElementById("spu_id");
  const v = (input.value || "").trim();
  // 从 URL 里 id=XXXX 抽 SPU
  const m = v.match(/[?&]id=(\d+)/);
  if (m) {
    input.value = m[1];
    showFeedback(`已解析 SPU ID: ${m[1]}`, "info");
  }
}

async function testNotify() {
  const provider = document.getElementById("notify_provider").value;
  const token = document.getElementById("notify_token").value;
  try {
    const res = await pywebview.api.send_test_notify(provider, token);
    if (res.ok) showFeedback("✅ 测试推送已发送", "success");
    else showFeedback("推送失败：" + res.error, "error");
  } catch (e) {
    showFeedback("推送异常：" + e, "error");
  }
}

async function startSnipe() {
  const form = collectForm();
  // 最小校验
  if (!form.ck) return showFeedback("请先填 CK", "error");
  if (!form.spu_id || !form.sku_id) return showFeedback("请填完整 SPU / SKU", "error");
  if (!form.snipe_time) return showFeedback("请选开抢时间", "error");

  // 保存表单
  try { await pywebview.api.save_form(form); } catch(e) {}

  // 启动
  try {
    const res = await pywebview.api.start_snipe(form);
    if (!res.ok) {
      showFeedback("启动失败：" + res.error, "error");
      return;
    }
    // 计算总等待时间（用于 progress bar）
    totalWait = new Date(form.snipe_time).getTime() - Date.now();
    if (totalWait < 0) totalWait = null;
    switchView("running");
    startCountdown();
    // 在抢购中视图也显示商品概要
    const pNameCn = document.getElementById("product-name-cn").textContent;
    document.getElementById("running-product").textContent =
      pNameCn || `SPU ${form.spu_id} · SKU ${form.sku_id} · ${form.num}件`;
  } catch (e) {
    showFeedback("启动异常：" + e, "error");
  }
}

async function stopSnipe() {
  await pywebview.api.stop_snipe();
}

async function backToForm() {
  try { await pywebview.api.reset(); } catch(e) {}
  switchView("form");
  totalWait = null;
}

// ─── 视图切换 ──────────────────────────────
function switchView(name) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  const el = document.getElementById("view-" + name);
  if (el) el.classList.add("active");
  currentView = name;
}

// ─── 倒计时 ──────────────────────────────
function startCountdown() {
  stopCountdown();
  countdownTimer = setInterval(updateCountdown, 100);
  updateCountdown();
}

function stopCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
}

function updateCountdown() {
  const snapshot = window._lastSnapshot;
  if (!snapshot || !snapshot.target_ts) return;
  const now = Date.now() / 1000;
  const remain = snapshot.target_ts - now;

  const box = document.getElementById("countdown");
  if (remain > 0) {
    const h = Math.floor(remain / 3600);
    const m = Math.floor((remain % 3600) / 60);
    const s = Math.floor(remain % 60);
    box.textContent = `T-${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  } else {
    box.textContent = `T+${(-remain).toFixed(1)}s`;
  }

  // progress
  if (totalWait && totalWait > 0 && remain > 0) {
    const pct = 100 * (1 - remain * 1000 / totalWait);
    document.getElementById("progress-bar").style.width = Math.min(100, Math.max(0, pct)) + "%";
  } else if (remain <= 0) {
    document.getElementById("progress-bar").style.width = "100%";
  }
}

// ─── 状态轮询 ──────────────────────────────
async function startSnapshotPolling() {
  if (snapshotTimer) return;
  async function tick() {
    try {
      const s = await pywebview.api.get_snapshot();
      window._lastSnapshot = s;
      applySnapshot(s);
    } catch (e) {
      // ignore
    }
  }
  await tick();
  snapshotTimer = setInterval(tick, POLL_SNAPSHOT_INTERVAL);
}

function applySnapshot(s) {
  // 根据 state 切视图
  const st = s.state;
  if (st === "idle") {
    if (currentView !== "form") switchView("form");
  } else if (st === "prechecking" || st === "waiting" || st === "firing") {
    if (currentView !== "running") switchView("running");
    startCountdown();
  } else if (st === "success") {
    if (currentView !== "success") switchView("success");
    stopCountdown();
    renderSuccess(s.pay_params || {});
  } else if (st === "failed" || st === "stopped") {
    if (currentView !== "failed") switchView("failed");
    stopCountdown();
    document.getElementById("error-msg").textContent = s.error || s.phase_msg || "未知错误";
  }
  // 阶段文案
  const pl = document.getElementById("phase-label");
  if (pl) pl.textContent = s.phase_msg || "";
}

function renderSuccess(pay) {
  document.getElementById("order-id").textContent = pay.order_id || "(未知)";
  document.getElementById("prepay-id").textContent = pay.prepay_id || "(未知)";
}

// ─── 日志轮询 ──────────────────────────────
async function startLogPolling() {
  if (logTimer) return;
  async function tick() {
    try {
      const logs = await pywebview.api.drain_logs();
      if (logs && logs.length) {
        appendLogs(logs);
      }
    } catch (e) {}
  }
  await tick();
  logTimer = setInterval(tick, POLL_LOGS_INTERVAL);
}

const MAX_LOG_LINES = 300;

function appendLogs(logs) {
  const box = document.getElementById("log-stream");
  if (!box) return;
  for (const l of logs) {
    const line = document.createElement("div");
    line.className = "log-" + l.level;
    const ts = new Date(l.ts * 1000).toLocaleTimeString("zh-CN", { hour12: false });
    line.textContent = `${ts} [${l.level}] ${l.message}`;
    box.appendChild(line);
  }
  while (box.children.length > MAX_LOG_LINES) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;

  // 失败视图也同步更新
  const failedBox = document.getElementById("failed-logs");
  if (failedBox) {
    const recent = Array.from(box.children).slice(-15);
    failedBox.innerHTML = "";
    recent.forEach(c => failedBox.appendChild(c.cloneNode(true)));
  }
}

// ─── 工具函数 ──────────────────────────────
function showFeedback(msg, level = "info") {
  const box = document.getElementById("form-feedback");
  box.className = "feedback " + level;
  box.textContent = msg;
  box.classList.remove("hidden");
  if (level === "success" || level === "info") {
    setTimeout(() => box.classList.add("hidden"), 5000);
  }
}

function copyText(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(
    () => showFeedback("已复制", "success"),
    () => showFeedback("复制失败", "error")
  );
}

async function openWechat() {
  const res = await pywebview.api.open_wechat();
  if (!res.ok) showFeedback(res.error || "打开失败", "error");
}

function showHelp(topic) {
  if (topic === "ck") {
    alert("CK 获取方式：\n\n1) 使用朋友给的「万代上号小程序抓Token.exe」\n   ↳ 连上微信小程序 → 工具窗口会显示 Token\n\n2) 或按文档 10_使用指南.md §10.2 自己抓包");
  }
}
