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

// ─── saleStatus 取值（参见 har_utils.py SALE_STATUS_MAP）─────
// 0=可售 / 1=未开售（saleStartTime 之前）/ 2=已结束（saleEndTime 之后）
const SALE_STATUS_TEXT = { 0: "可售", 1: "未开售", 2: "已结束" };
const SALE_STATUS_CLASS = {
  0: "har-product-status-ok",
  1: "har-product-status-pending",
  2: "har-product-status-ended",
};

function formatSaleStatus(s) {
  if (s == null) return "";
  return SALE_STATUS_TEXT[s] != null ? SALE_STATUS_TEXT[s] : `未知(${s})`;
}

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

  // 默认开抢时间 = 当前 +1 小时（必须用本地时区格式化，否则 UTC+8 用户会看到 8 小时前的时间）
  const input = document.getElementById("snipe_time");
  if (!input.value) {
    input.value = formatDatetimeLocal(new Date(Date.now() + 3600 * 1000));
  }

  // 设 min = 当前时间（让浏览器原生标灰过去日期），每 30 秒刷新一次
  refreshSnipeTimeMin();
  setInterval(refreshSnipeTimeMin, 30 * 1000);

  // 自动校正过去时间：选了已过去的时刻立即弹回当前 + 1 分钟
  document.getElementById("snipe_time").addEventListener("change", onSnipeTimeChange);

  // 输入框下显示当前实时时间（每秒刷新）作为参考
  refreshNowHint();
  setInterval(refreshNowHint, 1000);

  // SPU URL 自动识别
  wireSpuAutoParse();

  // CK 自动验证（如果上次有保存）
  const ck0 = document.getElementById("ck").value.trim();
  if (ck0) verifyCkNow(ck0);

  // 启动状态轮询
  startSnapshotPolling();
  startLogPolling();
});

// ─── CK 验证 / HAR 导入 ────────────────────────
let _verifyCkTimer = null;

function verifyCkSoon() {
  // textarea blur 时触发，debounce 600ms 防止误触发
  if (_verifyCkTimer) clearTimeout(_verifyCkTimer);
  _verifyCkTimer = setTimeout(() => {
    const ck = document.getElementById("ck").value.trim();
    if (ck) verifyCkNow(ck);
  }, 600);
}

async function verifyCkNow(ck) {
  setCkStatus("checking", "🔄 验证 CK 中...");
  try {
    const res = await pywebview.api.verify_ck(ck);
    if (res.ok) {
      setCkStatus("valid", `✅ CK 有效 · memberId=${res.member_id || "?"}`);
    } else {
      const info = classifyError(res.error || "未知");
      setCkStatus("invalid", `${info.icon} ${info.title} · 点上方"📁 从 HAR 导入 CK"换一个`);
    }
  } catch (e) {
    setCkStatus("invalid", `验证异常: ${e}`);
  }
}

function setCkStatus(level, text) {
  const box = document.getElementById("ck-status");
  if (!box) return;
  box.className = "ck-status " + level;
  box.textContent = text;
}

async function importCkFromHar() {
  setCkStatus("checking", "🔄 选 HAR 文件中...");
  try {
    const res = await pywebview.api.import_ck_from_har();
    if (!res.ok) {
      if (res.error === "已取消") {
        // 还原到上次状态：如果 ck 框有值就再验证一次，否则隐藏徽章
        const ck = document.getElementById("ck").value.trim();
        if (ck) verifyCkNow(ck);
        else document.getElementById("ck-status").classList.add("hidden");
        return;
      }
      setCkStatus("invalid", `❌ 导入失败: ${res.error}`);
      return;
    }
    // 成功，填进 textarea + 立即验证
    const ta = document.getElementById("ck");
    ta.value = res.ck;
    flashOk(ta);
    showFeedback(`✅ 从 HAR 抽出 CK（${res.ck.length} 字符）· 验证中...`, "success");
    verifyCkNow(res.ck);
  } catch (e) {
    setCkStatus("invalid", `导入异常: ${e}`);
  }
}

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
    // 文本：保留空字符串（不转 null），避免后端 pydantic 报 NoneType 错
    else out[id] = el.value || "";
  }
  // 用系统真实时区（朋友在中国默认 Asia/Shanghai，你在日本是 Asia/Tokyo）。
  // 万代服务器按北京时间公布开抢窗口；用户负责保证「填的开抢时间」和
  // 系统时钟一致即可。
  out.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  return out;
}

// ─── 表单操作 ──────────────────────────────

async function runPrecheck() {
  showFeedback("验证中...", "info");
  const form = collectForm();
  try {
    const res = await pywebview.api.precheck_only(form);
    if (!res.ok) {
      const info = classifyError(res.error || "未知");
      showFeedback(`${info.icon} ${info.title} · ${info.hint}`, "error");
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
    document.getElementById("product-status").textContent = formatSaleStatus(p.saleStatus);

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

    // 自动拉 SKU（silent：已有"预检通过"提示，不重复）
    fetchSkus({ silent: true });
  } catch (e) {
    showFeedback("预检异常：" + e, "error");
  }
}

async function fetchSkus(opts = {}) {
  const ck = document.getElementById("ck").value;
  const spuId = document.getElementById("spu_id").value;
  if (!ck || !spuId) {
    if (!opts.silent) showFeedback("需要先填 CK 和 SPU ID", "error");
    return;
  }
  try {
    const res = await pywebview.api.list_skus(ck, spuId);
    if (!res.ok) {
      // 常见：CK 过期返 302 → Api 层转成 {ok: false, error: "ApiError: [302] ..."}
      const info = classifyError(res.error || "");
      showFeedback(`${info.icon} ${info.title} · ${info.hint}`, "error");
      return;
    }
    const sel = document.getElementById("sku_id");
    sel.innerHTML = "";
    for (const s of (res.skus || [])) {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = `${s.name} · ¥${s.price} · 库存 ${s.stock}`;
      sel.appendChild(opt);
    }
    if (!opts.silent) {
      showFeedback(`✅ 已加载 ${res.skus.length} 个 SKU`, "success");
    }
  } catch (e) {
    console.warn("list_skus failed", e);
    showFeedback("刷新 SKU 异常: " + e, "error");
  }
}

// 可识别的 SPU id 位置（按优先级尝试）
const SPU_URL_PATTERNS = [
  /[?&]spuId=(\d+)/i,                        // spuId=6521
  /[?&]id=(\d+)/i,                           // 商品详情页 ?id=6521
  /\/(?:spu|commodity)\/[^?]*?(\d+)/i,       // /spu/6521 或 /commodity/6521/xxx
  /\b(\d{4,7})\b/,                           // 兜底：4-7 位纯数字 token
];

function extractSpuId(raw) {
  const s = (raw || "").trim();
  if (!s) return null;
  // 已经是纯数字（3-7 位），直接用
  if (/^\d{3,7}$/.test(s)) return s;
  for (const re of SPU_URL_PATTERNS) {
    const m = s.match(re);
    if (m) return m[1];
  }
  return null;
}

function parseSpuUrl(opts = {}) {
  const input = document.getElementById("spu_id");
  const raw = input.value || "";
  const found = extractSpuId(raw);
  if (!found) {
    if (!opts.silent) showFeedback("没识别到 SPU ID，手动输数字也行", "error");
    return null;
  }
  // 只有当当前值不是纯数字（即原始是 URL 之类）才回填，避免把用户手输的 SPU 覆盖
  if (input.value.trim() !== found) {
    input.value = found;
    flashOk(input);
    if (!opts.silent) showFeedback(`已解析 SPU ID: ${found}`, "success");
  }
  return found;
}

// 粘贴时自动解析（setTimeout 0 让浏览器先完成 value 更新）
function wireSpuAutoParse() {
  const input = document.getElementById("spu_id");
  if (!input) return;
  input.addEventListener("paste", () => {
    setTimeout(() => parseSpuUrl({ silent: true }), 0);
  });
  // input 变化超过 20 字符（明显是 URL 不是手输 SPU）时也自动解析
  input.addEventListener("input", () => {
    if ((input.value || "").length > 20) parseSpuUrl({ silent: true });
  });
}

// 输入框右上角瞬闪一个绿✓
function flashOk(inputEl) {
  const parent = inputEl.parentElement;
  if (!parent) return;
  parent.style.position = parent.style.position || "relative";
  const tag = document.createElement("span");
  tag.textContent = "✓";
  tag.style.cssText = `
    position: absolute; right: 12px; top: 50%; transform: translateY(-50%);
    color: var(--gundam-yellow); font-weight: 700; font-size: 16px;
    pointer-events: none; transition: opacity 0.5s; z-index: 2;
  `;
  parent.appendChild(tag);
  setTimeout(() => { tag.style.opacity = "0"; }, 600);
  setTimeout(() => tag.remove(), 1100);
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

// datetime-local 把 min 设成当前时间，浏览器会标灰过去日期/时间
function refreshSnipeTimeMin() {
  const input = document.getElementById("snipe_time");
  if (!input) return;
  const now = new Date();
  // 写本地时区（datetime-local 不带 TZ）
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const mi = String(now.getMinutes()).padStart(2, "0");
  input.min = `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
}

// datetime-local 的 native picker 不会灰显已过去的时分（只灰日期）。
// 选完时如果落在过去，立刻弹回当前 + 1 分钟。
// 返回 true 表示这次确实改了 input.value（startSnipe 会用它判断是否中断）。
function autoCorrectSnipeTime() {
  const input = document.getElementById("snipe_time");
  if (!input || !input.value) return false;
  const t = new Date(input.value).getTime();
  if (isNaN(t)) return false;
  const now = Date.now();
  if (t < now) {
    const next = new Date(now + 60 * 1000);
    input.value = formatDatetimeLocal(next);
    return true;
  }
  return false;
}

// change 事件的处理函数：调 autoCorrect，根据返回值决定 toast
function onSnipeTimeChange() {
  if (autoCorrectSnipeTime()) {
    showFeedback("⏰ 选了过去的时刻，已自动调到当前 +1 分钟", "info");
  }
}

function formatDatetimeLocal(d) {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}:${ss}`;
}

// 实时显示当前时间，给用户对比 snipe_time 的参考
function refreshNowHint() {
  const el = document.getElementById("now-hint");
  if (!el) return;
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mi = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  el.textContent = `当前时间：${hh}:${mi}:${ss}`;

  // 同步刷新真实系统时区到 #tz-hint，以及非北京时区的提醒
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "未知";
  const tzEl = document.getElementById("tz-hint");
  if (tzEl) tzEl.textContent = tz;
  const warnEl = document.getElementById("tz-warn");
  if (warnEl) {
    if (tz !== "Asia/Shanghai" && tz !== "Asia/Hong_Kong") {
      // 万代官方按北京时间公布开抢窗口，用户系统时区不一致时提醒
      const offsetMin = -now.getTimezoneOffset();   // 你的本地时区 vs UTC 的分钟偏移
      const beijingOffsetMin = 8 * 60;
      const diffH = (offsetMin - beijingOffsetMin) / 60;
      const diffStr = diffH > 0 ? `+${diffH}` : `${diffH}`;
      warnEl.textContent = `⚠️ 你系统时区是 ${tz}（与北京 ${diffStr}h），万代按北京时间开抢，请按系统时区换算后填入`;
      warnEl.classList.remove("hidden");
    } else {
      warnEl.classList.add("hidden");
    }
  }
}

async function startSnipe() {
  // 兜底：强制再校正一次过去时间
  // （change 事件在某些时序下可能没及时 fire；用户敲键盘 + 立即点抢购等情况）
  if (autoCorrectSnipeTime()) {
    showFeedback(
      "⏰ 开抢时间已过去，自动调到当前 +1 分钟。请确认时间后再次点「开始抢购」",
      "warning",
    );
    return;
  }

  const form = collectForm();
  // 最小校验
  if (!form.ck) return showFeedback("请先填 CK", "error");
  if (!form.spu_id || !form.sku_id) return showFeedback("请填完整 SPU / SKU", "error");
  if (!form.snipe_time) return showFeedback("请选开抢时间", "error");

  // 检查开抢时间是否已过 / 太近（少于 10 秒不允许）
  const targetMs = new Date(form.snipe_time).getTime();
  if (isNaN(targetMs)) {
    return showFeedback(
      `开抢时间无法解析，原始值 "${form.snipe_time}"。请重新用日期选择器选`,
      "error",
    );
  }
  const diff = (targetMs - Date.now()) / 1000;
  if (diff < -5) {
    // 走到这一步说明 autoCorrect 也没救（理论不该发生）
    return showFeedback(
      `⏰ 开抢时间已过去 ${Math.round(-diff)} 秒，请重选未来时间`,
      "error",
    );
  }
  if (diff < 10) {
    return showFeedback(
      `⏰ 开抢时间太近（剩 ${Math.round(diff)} 秒），最少留 10 秒预热时间`,
      "error",
    );
  }

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
  // 离开表单视图（用户开抢 / 抢中 / 失败 / etc）→ 停掉自动轮询
  if (name !== "form" && autoPollTimer) {
    stopAutoPoll();
  }
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
    renderSuccess(s.pay_params || {}, s.fire_duration_ms);
  } else if (st === "failed" || st === "stopped") {
    if (currentView !== "failed") switchView("failed");
    stopCountdown();
    renderFailure(s.error || s.phase_msg || "未知错误", s.fire_duration_ms);
  }
  // 阶段文案
  const pl = document.getElementById("phase-label");
  if (pl) pl.textContent = s.phase_msg || "";
}

function formatDuration(ms) {
  if (ms == null || ms < 0) return "";
  if (ms < 1000) return `⏱️ 用时 ${ms} ms`;
  return `⏱️ 用时 ${(ms / 1000).toFixed(2)} s`;
}

function renderSuccess(pay, durationMs) {
  document.getElementById("order-id").textContent = pay.order_id || "(未知)";
  document.getElementById("prepay-id").textContent = pay.prepay_id || "(未知)";
  const badge = document.getElementById("success-duration");
  if (badge) badge.textContent = formatDuration(durationMs);
}

// ─── 错误分类 ──────────────────────────────
// 按最像-先匹配顺序，捕到就返回 {icon, title, hint, severity}
// severity: "error" | "warning" | "info"
const ERROR_CHECKS = [
  [/code=(?:302|703|307|1004)|api-access-token.*(过期|失效)/i, {
    icon: "🔑", sev: "warning",
    title: "CK 已失效",
    hint: "抓一个新的 api-access-token 粘到「账号」卡片，重新开始。",
  }],
  [/code=2001|风控|rate.?limit/i, {
    icon: "🛡️", sev: "error",
    title: "被万代风控拦截",
    hint: "等 5-10 分钟再试；避免同一账号短时间内频繁试同一商品。",
  }],
  [/code=101|ValidationError|参数/i, {
    icon: "⚙️", sev: "error",
    title: "参数异常",
    hint: "脚本字段和服务端不对齐（万代可能改版了），查看下面原始错误。",
  }],
  [/限购|purchaseLimit|over.*limit/i, {
    icon: "🚫", sev: "warning",
    title: "超出限购",
    hint: "该商品限购 N 件，当前账号已超。换账号或减少数量。",
  }],
  [/库存|stock|sold.?out|sellOut/i, {
    icon: "📦", sev: "error",
    title: "库存不足",
    hint: "抢晚了或真卖光了。下次注意 snipe_time 精度。",
  }],
  [/未开售|未开抢|saleStatus/i, {
    icon: "⏰", sev: "warning",
    title: "尚未开售",
    hint: "检查 snipe_time 是否和官方预告一致（含时区）。",
  }],
  [/PRICE_GUARD|价格.*超过|price_ceiling/i, {
    icon: "💰", sev: "warning",
    title: "价格护栏触发",
    hint: "结算价超过你设的 price_ceiling，可能是运费/优惠意外。提升上限或检查配置。",
  }],
  [/HTTPStatusError.*432|\b432\b/, {
    icon: "🕵️", sev: "error",
    title: "UA/Referer 被拒（432）",
    hint: "client.py 默认头应该带 User-Agent + Referer；确认没被改过。",
  }],
  [/(connect|read|pool).*timeout|ConnectError/i, {
    icon: "📡", sev: "info",
    title: "网络超时",
    hint: "检查网络连通性；WSL 用户可以试 Windows 原生网络。",
  }],
  [/validation\s*error|field required/i, {
    icon: "📝", sev: "warning",
    title: "配置格式错",
    hint: "填写的字段格式不合法（日期、数字或缺必填项）。",
  }],
  [/已有抢购.*正在进行/i, {
    icon: "⏳", sev: "info",
    title: "上一轮抢购没结束",
    hint: "点返回等几秒再试，或重启 GUI。",
  }],
  [/Padding|aes_decrypt|decrypt/i, {
    icon: "🔐", sev: "error",
    title: "解密失败",
    hint: "服务端返回了非预期内容；通常 CK 不对或接口改版。",
  }],
  [/全部.*worker.*失败/i, {
    icon: "💥", sev: "error",
    title: "所有 worker 都失败",
    hint: "展开原始错误看最后一次的具体 code；真抢不到 / 风控 / 限购 最常见。",
  }],
  [/已中止|cancelled|CancelledError/i, {
    icon: "✋", sev: "info",
    title: "已手动中止",
    hint: "你点了中止按钮，没毛病。",
  }],
];

function classifyError(raw) {
  const s = String(raw || "").trim();
  if (!s) return { icon: "❓", sev: "info", title: "未知错误", hint: "没有错误信息，看日志定位。", raw: "" };
  for (const [re, info] of ERROR_CHECKS) {
    if (re.test(s)) return { ...info, raw: s };
  }
  return { icon: "⚠️", sev: "error", title: "异常", hint: "未分类错误，展开看原始报错。", raw: s };
}

function renderFailure(raw, durationMs) {
  const info = classifyError(raw);
  const card = document.getElementById("error-card");
  card.classList.remove("sev-error", "sev-warning", "sev-info");
  card.classList.add("sev-" + info.sev);
  document.getElementById("err-icon").textContent = info.icon;
  document.getElementById("err-title").textContent = info.title;
  document.getElementById("err-hint").textContent = info.hint;
  document.getElementById("error-msg").textContent = info.raw || "(无详细)";
  const badge = document.getElementById("failed-duration");
  if (badge) badge.textContent = formatDuration(durationMs);
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
    alert([
      "CK 获取方式：",
      "",
      "方式 A · 推荐：从抓的 HAR 一键导入",
      "  1. 按文档 3_抓包指南 抓一次 HAR",
      "  2. 点上方「📁 从 HAR 导入 CK」",
      "",
      "方式 B：朋友给的「万代上号小程序抓Token.exe」",
      "  连上微信小程序 → 工具窗口会显示 Token，复制粘进 CK 框",
      "",
      "方式 C：自己 mitmproxy 抓包后从 HAR 找 api-access-token header",
    ].join("\n"));
  } else if (topic === "notify") {
    alert([
      "推送通道获取教程：",
      "",
      "🟢 Server 酱 — 微信公众号推送（推荐）",
      "  1. 浏览器打开 https://sct.ftqq.com/",
      "  2. 用 GitHub 登录",
      "  3. 微信扫码关注「方糖气球」公众号",
      "  4. 在网站「SendKey」页面复制 SCTKEY（一串字母数字）",
      "  5. 粘到这里 → 点「试发」→ 微信里收到推送 = 成功",
      "  抢中后推送会出现在微信「服务通知」里。",
      "",
      "🟣 PushPlus — 微信 + QQ + 钉钉等多通道",
      "  1. 浏览器打开 https://www.pushplus.plus/",
      "  2. 微信扫码登录（自动关注「pushplus推送加」公众号）",
      "  3. 首页直接复制「您的token」",
      "  4. 粘到这里 → 点「试发」",
      "  默认推送到关注的公众号；想推到 QQ 邮箱 / 钉钉 / 企微，",
      "  在 PushPlus 网站「一对一」改默认通道即可。",
      "",
      "🍎 Bark — iOS 推送",
      "  1. App Store 装 Bark",
      "  2. 打开 App，复制顶部那条专属推送 URL",
      "  3. 粘到这里",
      "",
      "💼 飞书机器人",
      "  1. 飞书拉一个群（自己一个人也行）",
      "  2. 群设置 → 群机器人 → 添加 → 自定义机器人",
      "  3. 复制 Webhook URL 粘到这里",
    ].join("\n"));
  }
}

// ─── 自动轮询搜索（关键词命中前每 N 秒搜一次） ────────────
let autoPollTimer = null;
let autoPollLastTotal = 0;
let autoPollKeyword = "";

function setAutoPollStatus(text, level = "running") {
  const el = document.getElementById("auto-poll-status");
  if (!el) return;
  el.className = "auto-poll-status " + level;
  el.textContent = text || "";
}

function toggleAutoPoll() {
  if (document.getElementById("auto_poll_enabled").checked) {
    startAutoPoll();
  } else {
    stopAutoPoll("已手动关闭");
  }
}

function startAutoPoll() {
  const ck = document.getElementById("ck").value.trim();
  if (!ck) {
    showFeedback("请先填 CK", "error");
    document.getElementById("auto_poll_enabled").checked = false;
    return;
  }
  const kw = document.getElementById("search_keyword").value.trim();
  if (!kw) {
    showFeedback("请输入关键词后再开自动轮询", "error");
    document.getElementById("auto_poll_enabled").checked = false;
    return;
  }

  let interval = parseInt(document.getElementById("auto_poll_interval").value) || 15;
  interval = Math.max(5, Math.min(120, interval));

  autoPollKeyword = kw;
  autoPollLastTotal = -1;  // -1 = 未跑过；首次跑出来无论 0 还是 N，都不算"新增"

  // 请求桌面通知权限（首次会弹原生授权框）
  if (typeof Notification !== "undefined" && Notification.permission === "default") {
    try { Notification.requestPermission(); } catch (e) {}
  }

  setAutoPollStatus(`🔁 轮询「${kw}」每 ${interval}s 一次...`);
  pollSearchOnce();   // 立即跑一次基线
  autoPollTimer = setInterval(pollSearchOnce, interval * 1000);
}

function stopAutoPoll(reason = "") {
  if (autoPollTimer) {
    clearInterval(autoPollTimer);
    autoPollTimer = null;
  }
  document.getElementById("auto_poll_enabled").checked = false;
  if (reason) setAutoPollStatus(reason, "running");
  else setAutoPollStatus("");
}

async function pollSearchOnce() {
  if (!autoPollKeyword) return;
  const ck = document.getElementById("ck").value.trim();
  if (!ck) {
    stopAutoPoll("CK 已空，停止");
    return;
  }
  try {
    const res = await pywebview.api.search_products(ck, autoPollKeyword);
    if (!res.ok) {
      stopAutoPoll(`错误：${res.error || "未知"}`);
      return;
    }
    const total = res.total || 0;
    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;

    if (autoPollLastTotal < 0) {
      // 首次：建立基线
      autoPollLastTotal = total;
      setAutoPollStatus(`🔁 ${ts} 基线 ${total} 个 · 等新商品...`);
      return;
    }

    if (total > autoPollLastTotal) {
      // 命中！
      const delta = total - autoPollLastTotal;
      stopAutoPoll(`🎯 ${ts} 发现 ${delta} 个新商品（共 ${total}）`);
      setAutoPollStatus(`🎯 ${ts} 发现 ${delta} 个新商品（共 ${total}）`, "hit");

      // 桌面通知（如果 grant 了权限）
      try {
        if (typeof Notification !== "undefined" && Notification.permission === "granted") {
          new Notification("万代抢购器 · 发现新商品", {
            body: `「${autoPollKeyword}」搜到了 ${delta} 个新商品，回到 GUI 选商品下单`,
            requireInteraction: true,
          });
        }
      } catch (e) {}

      // 弹 modal 显示结果
      document.querySelector("#har-modal .modal-header h2").textContent = "🎯 自动轮询命中";
      document.getElementById("har-modal-hint").textContent =
        `搜「${autoPollKeyword}」自动轮询发现 ${total} 个商品 · 点一行填入`;
      renderHarProducts(res.products, null);
      document.getElementById("har-modal").classList.remove("hidden");
    } else {
      setAutoPollStatus(`🔁 ${ts} 还是 ${total} 个 · 继续等...`);
    }
  } catch (e) {
    console.warn("auto poll error", e);
  }
}

// ─── 关键词搜索商品（Phase 2.x · 直连万代 spu/query）──
async function searchProducts() {
  const ck = document.getElementById("ck").value.trim();
  if (!ck) {
    showFeedback("请先在 ① 账号 卡片填 CK", "error");
    document.getElementById("ck").focus();
    return;
  }
  const kw = document.getElementById("search_keyword").value.trim();
  if (!kw) {
    showFeedback("请输入关键词", "error");
    return;
  }

  const hint = document.getElementById("har-modal-hint");
  const list = document.getElementById("har-product-list");
  // modal 标题改成"搜索结果"语境
  document.querySelector("#har-modal .modal-header h2").textContent = "搜索结果";
  hint.textContent = `搜索"${kw}"中…`;
  list.innerHTML = "";
  document.getElementById("har-modal").classList.remove("hidden");

  try {
    const res = await pywebview.api.search_products(ck, kw);
    if (!res.ok) {
      const info = classifyError(res.error || "搜索失败");
      hint.textContent = `${info.icon} ${info.title} · ${info.hint}`;
      return;
    }
    if (!res.products || res.products.length === 0) {
      hint.textContent = `没找到含"${kw}"的商品。换个关键词试试`;
      return;
    }
    hint.textContent = `搜索"${kw}" · 共 ${res.total} 个匹配，本页显示 ${res.products.length} 个 · 点一行填入`;
    // 复用 HAR modal 的渲染逻辑
    renderHarProducts(res.products, null /* 不显示来源路径 */);
  } catch (e) {
    hint.textContent = "异常: " + e;
  }
}

// ─── 从 HAR 选商品（Phase 2.x）──────────────
async function openHarPicker() {
  // 还原 modal 标题（万一刚用过搜索）
  document.querySelector("#har-modal .modal-header h2").textContent = "从 HAR 选商品";
  const hint = document.getElementById("har-modal-hint");
  const list = document.getElementById("har-product-list");
  hint.textContent = "弹出文件选择器中…";
  list.innerHTML = "";
  document.getElementById("har-modal").classList.remove("hidden");

  try {
    const res = await pywebview.api.pick_har_and_list();
    if (!res.ok) {
      hint.textContent = res.error || "失败";
      if (res.error === "已取消") {
        closeHarModal();
      }
      return;
    }
    renderHarProducts(res.products, res.har_path);
  } catch (e) {
    hint.textContent = "异常: " + e;
  }
}

function renderHarProducts(products, harPath) {
  const hint = document.getElementById("har-modal-hint");
  const list = document.getElementById("har-product-list");
  // 搜索调用方会自己设 hint，HAR 调用方走默认文案
  if (harPath) {
    hint.textContent = `来自 ${harPath} · 共 ${products.length} 个商品 · 点一行即可填入`;
  }
  list.innerHTML = "";

  for (const p of products) {
    const item = document.createElement("div");
    item.className = "har-product-item";
    item.onclick = () => pickProductFromHar(p);

    const head = document.createElement("div");
    head.className = "har-product-head";

    const idBadge = document.createElement("span");
    idBadge.className = "har-product-spuid";
    idBadge.textContent = p.spu_id;
    head.appendChild(idBadge);

    if (p.price != null) {
      const price = document.createElement("span");
      price.className = "har-product-price";
      price.textContent = "¥" + p.price;
      head.appendChild(price);
    }
    if (p.stock != null) {
      const stock = document.createElement("span");
      stock.className = "har-product-stock";
      stock.textContent = "库存 " + p.stock;
      head.appendChild(stock);
    }
    if (p.status != null) {
      const st = document.createElement("span");
      st.className = SALE_STATUS_CLASS[p.status] || "har-product-status-pending";
      st.textContent = formatSaleStatus(p.status);
      if (p.status === 1 && p.sale_start) st.textContent += "（" + p.sale_start + "）";
      head.appendChild(st);
    }

    item.appendChild(head);

    const name = document.createElement("div");
    name.className = "har-product-name";
    name.textContent = p.name_cn || "(未知中文名)";
    item.appendChild(name);

    if (p.name_jp) {
      const jp = document.createElement("div");
      jp.className = "har-product-name-jp";
      jp.textContent = "（日）" + p.name_jp;
      item.appendChild(jp);
    }

    list.appendChild(item);
  }
}

function pickProductFromHar(p) {
  const input = document.getElementById("spu_id");
  input.value = p.spu_id;
  flashOk(input);
  showFeedback(`已选商品 SPU=${p.spu_id}（${p.name_cn || ""}）`, "success");
  closeHarModal();
  // 触发自动拉 SKU（silent，因为上面已经有 feedback）
  fetchSkus({ silent: true });
}

function closeHarModal() {
  document.getElementById("har-modal").classList.add("hidden");
}

// ESC 关闭 modal
window.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!document.getElementById("har-modal").classList.contains("hidden")) {
    closeHarModal(); return;
  }
  if (!document.getElementById("info-modal").classList.contains("hidden")) {
    closeInfoModal(); return;
  }
});

// ─── 通用 Info Modal（订单 / 搜索历史）─────────
function openInfoModal(title, hint = "") {
  document.getElementById("info-modal-title").textContent = title;
  document.getElementById("info-modal-hint").textContent = hint;
  document.getElementById("info-modal-body").innerHTML = "";
  document.getElementById("info-modal-footer").innerHTML = "";
  document.getElementById("info-modal").classList.remove("hidden");
}

function setInfoModalHint(text) {
  document.getElementById("info-modal-hint").textContent = text;
}

function setInfoModalFooter(html) {
  document.getElementById("info-modal-footer").innerHTML = html;
}

function setInfoModalEmpty(text) {
  const body = document.getElementById("info-modal-body");
  body.innerHTML = `<div class="empty-hint">${text}</div>`;
}

function closeInfoModal() {
  document.getElementById("info-modal").classList.add("hidden");
}

// ─── 我的订单 ───────────────────────────
const ORDER_STATUS_TEXT = {
  pending_pay: "待支付",
  paid: "已付款",
  cancelled: "已取消",
  unknown: "未知",
};

async function openOrdersModal() {
  openInfoModal("📦 我的订单", "加载中...");
  try {
    const res = await pywebview.api.list_orders(50);
    if (!res.ok) {
      setInfoModalHint("加载失败：" + (res.error || ""));
      return;
    }
    if (!res.orders || res.orders.length === 0) {
      setInfoModalHint("还没有抢购记录");
      setInfoModalEmpty("成功抢中后这里会显示订单。");
      return;
    }
    setInfoModalHint(`共 ${res.orders.length} 条订单 · 按时间倒序`);
    renderOrders(res.orders);
  } catch (e) {
    setInfoModalHint("异常: " + e);
  }
}

function renderOrders(orders) {
  const body = document.getElementById("info-modal-body");
  body.innerHTML = "";
  for (const o of orders) {
    const item = document.createElement("div");
    item.className = "info-item";
    const status = o.status || "unknown";
    const statusText = ORDER_STATUS_TEXT[status] || status;
    const name = o.spu_name_cn || `SPU ${o.spu_id}` + (o.sku_id ? ` / SKU ${o.sku_id}` : "");
    const amount = o.order_amount != null
      ? `¥${o.order_amount}` + (o.deposit_amount ? `（定金 ¥${o.deposit_amount}）` : "")
      : "";

    const head = document.createElement("div");
    head.className = "info-item-head";
    head.innerHTML = `
      <span class="info-item-id">订单 #${escapeHtml(o.order_id)}</span>
      <span class="info-item-time">${formatTimeAgo(o.created_at)}</span>
      <span class="info-item-status status-${status}">${statusText}</span>
    `;
    item.appendChild(head);

    const nameDiv = document.createElement("div");
    nameDiv.className = "info-item-name";
    nameDiv.textContent = name;
    item.appendChild(nameDiv);

    if (amount || o.num > 1) {
      const meta = document.createElement("div");
      meta.className = "info-item-meta";
      meta.textContent = [amount, o.num > 1 ? `${o.num} 件` : ""].filter(Boolean).join(" · ");
      item.appendChild(meta);
    }

    const actions = document.createElement("div");
    actions.className = "info-item-actions";
    actions.innerHTML = `
      <button class="btn-mini" onclick="copyTextRaw('${escapeHtml(o.order_id)}')">复制订单 ID</button>
      ${o.prepay_id ? `<button class="btn-mini" onclick="copyTextRaw('${escapeHtml(o.prepay_id)}')">复制 prepay_id</button>` : ""}
    `;
    item.appendChild(actions);

    body.appendChild(item);
  }
}

// ─── 搜索历史 ───────────────────────────
async function openSearchHistoryModal() {
  openInfoModal("🔍 搜索历史", "加载中...");
  try {
    const res = await pywebview.api.list_search_history(30);
    if (!res.ok) {
      setInfoModalHint("加载失败：" + (res.error || ""));
      return;
    }
    if (!res.items || res.items.length === 0) {
      setInfoModalHint("还没有搜索记录");
      setInfoModalEmpty("用 ② 商品 卡片的搜索框试试。");
      return;
    }
    setInfoModalHint(`点击关键词重新搜索 · 共 ${res.items.length} 个`);
    renderSearchHistory(res.items);
    setInfoModalFooter(`<button class="btn-secondary" onclick="clearSearchHistoryConfirm()">清空历史</button>`);
  } catch (e) {
    setInfoModalHint("异常: " + e);
  }
}

function renderSearchHistory(items) {
  const body = document.getElementById("info-modal-body");
  body.innerHTML = "";
  for (const it of items) {
    const row = document.createElement("div");
    row.className = "info-item";
    row.onclick = () => {
      document.getElementById("search_keyword").value = it.keyword;
      closeInfoModal();
      searchProducts();
    };
    const kw = document.createElement("span");
    kw.className = "info-item-keyword";
    kw.textContent = it.keyword;
    const meta = document.createElement("div");
    meta.className = "info-item-meta";
    const avg = Math.round(it.avg_result || 0);
    meta.textContent = `${it.times} 次搜索 · 平均 ${avg} 个结果 · ${formatTimeAgo(it.searched_at)}`;
    row.appendChild(kw);
    row.appendChild(meta);
    body.appendChild(row);
  }
}

async function clearSearchHistoryConfirm() {
  if (!confirm("确认清空所有搜索历史？")) return;
  try {
    const res = await pywebview.api.clear_search_history();
    showFeedback(`已清空 ${res.cleared || 0} 条记录`, "success");
    closeInfoModal();
  } catch (e) {
    showFeedback("清空失败: " + e, "error");
  }
}

// ─── 工具函数 ───────────────────────────
function formatTimeAgo(iso) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return iso;
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 30 * 86400) return `${Math.floor(diff / 86400)} 天前`;
  return new Date(iso).toLocaleDateString("zh-CN");
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
}

function copyTextRaw(s) {
  navigator.clipboard.writeText(s).then(
    () => showFeedback("已复制", "success"),
    () => showFeedback("复制失败", "error")
  );
}
