/**
 * finance-agent 前端（按角色切换 Tab）
 *
 * 【目的】登录后：普通用户看「提交/我的申请」；管理员看「待审批/全部/制度」。
 * 【易错点】
 * 1. token 在 localStorage；清站点数据会掉登录。
 * 2. api() 统一加 Bearer；FormData 上传不要手动设 content-type。
 * 3. ROLE_TABS 决定菜单——加新页要同时改 HTML panel 的 data-roles。
 */
const TOKEN_KEY = "finance-agent-token";
const USER_KEY = "finance-agent-user";

const ROLE_TABS = {
  user: [
    { id: "expense", label: "提交申请" },
    { id: "mylist", label: "我的申请" },
    { id: "policy", label: "制度问答" },
  ],
  admin: [
    { id: "approve", label: "待审批" },
    { id: "all", label: "全部单据" },
    { id: "expense", label: "代提申请" },
    { id: "mylist", label: "本人单据" },
    { id: "policy", label: "财务制度" },
  ],
};

const $ = (sel) => document.querySelector(sel);

let currentUser = null;

function setHint(el, text, ok) {
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("ok", ok === true);
  el.classList.toggle("bad", ok === false);
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  currentUser = user;
}

function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  currentUser = null;
}

function authHeaders(json = true) {
  const headers = { Authorization: `Bearer ${getToken()}` };
  if (json) headers["content-type"] = "application/json";
  return headers;
}

async function api(path, options = {}) {
  const headers = { ...authHeaders(!(options.body instanceof FormData)), ...(options.headers || {}) };
  if (options.body instanceof FormData) delete headers["content-type"];
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    clearSession();
    showLogin("登录已过期，请重新登录");
    throw new Error(data.detail || "未登录");
  }
  if (!res.ok) {
    const detail = data.detail || res.statusText || "请求失败";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function showLogin(hint) {
  $("#loginView").classList.remove("hidden");
  $("#mainView").classList.add("hidden");
  if (hint) setHint($("#loginHint"), hint, false);
}

function showMain() {
  $("#loginView").classList.add("hidden");
  $("#mainView").classList.remove("hidden");
}

function fillIdentity() {
  if (!currentUser) return;
  $("#employeeId").value = currentUser.employee_id;
  $("#employeeName").value = currentUser.display_name;
  $("#department").value = currentUser.department;
  const isAdmin = currentUser.role === "admin";
  $("#employeeId").readOnly = !isAdmin;
  $("#employeeName").readOnly = !isAdmin;
  $("#department").readOnly = !isAdmin;
  $("#pillUser").textContent = `${currentUser.display_name} · ${isAdmin ? "管理员" : "普通用户"} · ${currentUser.employee_id}`;
  $("#heroTitle").textContent = isAdmin ? "财务审批管理台" : "员工报销工作台";
  $("#heroLead").textContent = isAdmin
    ? "审核待办 · 查看全量单据 · 维护制度 · 可代提报销"
    : "提交报销申请 · 查看本人申请进度 · 查询财务制度";
  document.querySelectorAll(".admin-only").forEach((el) => {
    el.style.display = isAdmin ? "" : "none";
  });
}

function buildTabs() {
  const tabs = ROLE_TABS[currentUser.role] || ROLE_TABS.user;
  const nav = $("#tabs");
  nav.innerHTML = tabs
    .map((t, i) => `<button class="tab${i === 0 ? " active" : ""}" data-tab="${t.id}" type="button">${t.label}</button>`)
    .join("");
  nav.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  });
  activateTab(tabs[0].id);
}

function activateTab(tabId) {
  document.querySelectorAll("#tabs .tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tabId));
  document.querySelectorAll("#mainView .panel").forEach((p) => {
    const roles = (p.dataset.roles || "").split(",");
    const allowed = roles.includes(currentUser.role);
    p.classList.toggle("active", allowed && p.id === `panel-${tabId}`);
  });
  if (tabId === "mylist") refreshMyList();
  if (tabId === "approve") refreshApprove();
  if (tabId === "all") refreshAllList();
  if (tabId === "policy") refreshKb();
}

function statusBadge(status) {
  const map = {
    auto_approved: "ok",
    approved: "ok",
    pending_approval: "warn",
    rejected: "bad",
  };
  return map[status] || "";
}

function formatReportDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 19).replace("T", " ");
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function renderExpenseCards(items, { canApprove = false, adminManage = false } = {}) {
  if (!items?.length) return `<div class="chunk"><p>暂无单据</p></div>`;
  return items
    .map((r) => {
      const receiptBtn = r.has_receipt_file
        ? `<button type="button" class="btn ghost btn-sm" data-receipt="${escapeHtml(r.expense_id)}">查看原件</button>`
        : `<span class="badge">无原件</span>`;
      const paidBadge = r.paid
        ? `<span class="badge ok">已打款</span>`
        : `<span class="badge warn">未打款</span>`;
      let manage = "";
      if (adminManage) {
        manage = `
          <button type="button" class="btn ghost btn-sm" data-paid="${escapeHtml(r.expense_id)}" data-paid-to="${r.paid ? "false" : "true"}">
            ${r.paid ? "取消打款" : "标记已打款"}
          </button>
          <button type="button" class="btn ghost btn-sm" data-del="${escapeHtml(r.expense_id)}">删除</button>`;
      }
      const actions = canApprove
        ? `<div class="card-actions">
            <input class="note-input" data-id="${escapeHtml(r.expense_id)}" placeholder="审批意见（可选）" />
            <button type="button" class="btn primary btn-sm" data-act="approve" data-id="${escapeHtml(r.expense_id)}">批准</button>
            <button type="button" class="btn ghost btn-sm" data-act="reject" data-id="${escapeHtml(r.expense_id)}">驳回</button>
            ${receiptBtn}
          </div>`
        : `<div class="card-actions">${receiptBtn}${manage}</div>`;
      return `<article class="chunk">
        <div class="chunk-meta">
          <span class="badge">${escapeHtml(r.expense_id)}</span>
          <span class="badge ${statusBadge(r.status)}">${escapeHtml(r.status)}</span>
          ${paidBadge}
          <span class="badge">${escapeHtml(r.risk_level)}</span>
          ${r.invoice_no ? `<span class="badge">票号 ${escapeHtml(r.invoice_no)}</span>` : ""}
          <span class="badge">上报 ${escapeHtml(formatReportDate(r.created_at))}</span>
        </div>
        <p>${escapeHtml(r.employee_name)} · ${escapeHtml(r.department)} · ${escapeHtml(r.category)} · ¥${r.amount}
        ${r.erp_voucher_id ? ` · ERP ${escapeHtml(r.erp_voucher_id)}` : ""}</p>
        ${r.summary ? `<p class="muted">${escapeHtml(r.summary)}</p>` : ""}
        ${actions}
      </article>`;
    })
    .join("");
}

function buildAllListQuery() {
  const params = new URLSearchParams({ limit: "100" });
  const status = $("#filterStatus")?.value;
  const paid = $("#filterPaid")?.value;
  const dept = $("#filterDept")?.value?.trim();
  const q = $("#filterQ")?.value?.trim();
  const df = $("#filterDateFrom")?.value;
  const dt = $("#filterDateTo")?.value;
  if (status) params.set("status", status);
  if (paid === "true" || paid === "false") params.set("paid", paid);
  if (dept) params.set("department", dept);
  if (q) params.set("q", q);
  if (df) params.set("date_from", df);
  if (dt) params.set("date_to", dt);
  return params.toString();
}

async function refreshHealth() {
  try {
    const h = await fetch("/health").then((r) => r.json());
    const ok = h.postgres && h.redis;
    $("#pillHealth").textContent = `服务 ${ok ? "正常" : "部分异常"} · PG ${h.postgres ? "✓" : "×"} · Redis ${h.redis ? "✓" : "×"}`;
    $("#pillHealth").className = `pill ${ok ? "ok" : "warn"}`;
  } catch (err) {
    $("#pillHealth").textContent = `服务不可用：${err.message}`;
    $("#pillHealth").className = "pill bad";
  }
}

async function refreshKb() {
  if (!getToken()) return;
  try {
    const [stats, list] = await Promise.all([api("/documents/stats"), api("/documents?limit=30")]);
    $("#pillKb").textContent = `制度库 ${stats.total_chunks} 块 · 已向量化 ${stats.vectorized_chunks}`;
    $("#pillKb").className = `pill ${stats.total_chunks ? "ok" : ""}`;
    $("#kbStats").innerHTML = `
      <div class="stat"><b>${stats.total_chunks}</b><span>总切片</span></div>
      <div class="stat"><b>${stats.vectorized_chunks}</b><span>已向量化</span></div>
      <div class="stat"><b>${stats.embedding_dims || "—"}</b><span>维度</span></div>`;
    $("#chunkList").innerHTML =
      (list.items || [])
        .map(
          (i) => `<article class="chunk"><div class="chunk-meta"><span class="badge">#${i.id}</span>
          <span class="badge">${escapeHtml(i.source)}</span>
          <span class="badge ${i.vectorized ? "ok" : ""}">${i.vectorized ? "已向量化" : "未向量化"}</span></div>
          <p>${escapeHtml(i.content.slice(0, 220))}</p></article>`
        )
        .join("") || `<div class="chunk"><p>暂无制度</p></div>`;
  } catch (err) {
    $("#kbStats").textContent = `加载失败：${err.message}`;
  }
}

function parseContentFilename(disposition, fallback) {
  if (!disposition) return fallback;
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/"/g, ""));
    } catch {
      /* ignore */
    }
  }
  const plain = /filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)/i.exec(disposition);
  if (plain) return (plain[1] || plain[2] || "").trim() || fallback;
  return fallback;
}

async function openReceipt(expenseId) {
  const res = await fetch(`/expenses/${encodeURIComponent(expenseId)}/receipt`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "无法打开原件");
  }
  const headerType = (res.headers.get("Content-Type") || "").split(";")[0].trim();
  const filename = parseContentFilename(
    res.headers.get("Content-Disposition"),
    `${expenseId}.bin`,
  );
  const buf = await res.arrayBuffer();
  // 强制带上正确 MIME，避免 blob: 预览丢失后缀/无法显示
  const mime =
    headerType && headerType !== "application/octet-stream"
      ? headerType
      : guessMimeFromName(filename);
  const blob = new Blob([buf], { type: mime });
  const url = URL.createObjectURL(blob);

  if (mime.startsWith("image/")) {
    const w = window.open("", "_blank", "noopener");
    if (w) {
      const safeName = escapeHtml(filename);
      w.document.write(
        `<!doctype html><html><head><meta charset="utf-8"><title>${safeName}</title></head>` +
          `<body style="margin:0;background:#111;color:#eee;font-family:sans-serif">` +
          `<div style="padding:10px 14px;display:flex;gap:12px;align-items:center;background:#1a1a1a">` +
          `<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${safeName}</span>` +
          `<a href="${url}" download="${safeName}" style="color:#8ec8ff">下载原件</a></div>` +
          `<div style="display:flex;justify-content:center;padding:8px">` +
          `<img src="${url}" alt="${safeName}" style="max-width:100%;height:auto"/>` +
          `</div></body></html>`,
      );
      w.document.close();
    } else {
      triggerNamedDownload(url, filename);
    }
  } else if (mime === "application/pdf") {
    // PDF 可直接预览；同时提供带后缀的下载，避免另存丢扩展名
    const w = window.open(url, "_blank", "noopener");
    if (!w) triggerNamedDownload(url, filename);
  } else {
    triggerNamedDownload(url, filename);
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function guessMimeFromName(name) {
  const ext = String(name).split(".").pop()?.toLowerCase();
  const map = {
    pdf: "application/pdf",
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    webp: "image/webp",
    bmp: "image/bmp",
    tif: "image/tiff",
    tiff: "image/tiff",
  };
  return map[ext] || "application/octet-stream";
}

function triggerNamedDownload(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function bindReceiptButtons(root) {
  root.querySelectorAll("button[data-receipt]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await openReceipt(btn.dataset.receipt);
      } catch (err) {
        alert(err.message);
      }
    });
  });
}

async function refreshMyList() {
  try {
    const mine = currentUser.role === "admin";
    const data = await api(`/expenses?limit=40${mine ? "&mine=true" : ""}`);
    $("#myListTitle").textContent = currentUser.role === "admin" ? "本人单据" : "我的申请";
    $("#myExpenseList").innerHTML = renderExpenseCards(data.items);
    bindReceiptButtons($("#myExpenseList"));
  } catch (err) {
    $("#myExpenseList").innerHTML = `<div class="chunk"><p>${escapeHtml(err.message)}</p></div>`;
  }
}

async function refreshApprove() {
  try {
    const data = await api("/expenses?limit=50&status=pending_approval");
    $("#approveList").innerHTML = renderExpenseCards(data.items, { canApprove: true });
    $("#approveList").querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", () => decideExpense(btn.dataset.id, btn.dataset.act));
    });
    bindReceiptButtons($("#approveList"));
  } catch (err) {
    $("#approveList").innerHTML = `<div class="chunk"><p>${escapeHtml(err.message)}</p></div>`;
  }
}

function bindAdminManageButtons(root) {
  root.querySelectorAll("button[data-paid]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const paid = btn.dataset.paidTo === "true";
        await api(`/expenses/${encodeURIComponent(btn.dataset.paid)}/paid`, {
          method: "POST",
          body: JSON.stringify({ paid }),
        });
        await refreshAllList();
      } catch (err) {
        alert(err.message);
      }
    });
  });
  root.querySelectorAll("button[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`确认删除单据 ${btn.dataset.del}？将同时删除票据原件。`)) return;
      try {
        await api(`/expenses/${encodeURIComponent(btn.dataset.del)}`, { method: "DELETE" });
        await refreshAllList();
      } catch (err) {
        alert(err.message);
      }
    });
  });
}

async function refreshAllList() {
  try {
    const data = await api(`/expenses?${buildAllListQuery()}`);
    $("#allExpenseList").innerHTML = renderExpenseCards(data.items, { adminManage: true });
    bindReceiptButtons($("#allExpenseList"));
    bindAdminManageButtons($("#allExpenseList"));
  } catch (err) {
    $("#allExpenseList").innerHTML = `<div class="chunk"><p>${escapeHtml(err.message)}</p></div>`;
  }
}

async function decideExpense(expenseId, action) {
  const note = $(`#approveList .note-input[data-id="${expenseId}"]`)?.value?.trim() || null;
  try {
    await api(`/expenses/${expenseId}/decide`, {
      method: "POST",
      body: JSON.stringify({ action, note, submit_to_erp: true }),
    });
    await refreshApprove();
    await refreshAllList();
  } catch (err) {
    alert(err.message);
  }
}

function fillParsedReceipt(parsed, extractedText) {
  // 以原件识别结果为准覆盖表单（金额 / 发票号）
  if (extractedText) $("#receiptText").value = extractedText;
  if (parsed?.invoice_no) {
    $("#invoiceNo").value = parsed.invoice_no;
  }
  if (parsed?.amount != null && Number(parsed.amount) > 0) {
    $("#amount").value = String(parsed.amount);
  }
}

async function recognizeReceiptFile(file) {
  const hint = $("#parseHint");
  if (!file) {
    setHint(hint, "请先选择发票 PDF 或图片", false);
    return null;
  }
  setHint(hint, "正在识别原件…");
  const fd = new FormData();
  fd.append("file", file);
  const data = await api("/expenses/parse-receipt", { method: "POST", body: fd });
  fillParsedReceipt(data.parsed, data.extracted_text);
  const parts = [];
  if (data.parsed?.amount != null) parts.push(`金额 ¥${data.parsed.amount}`);
  if (data.parsed?.invoice_no) parts.push(`发票号 ${data.parsed.invoice_no}`);
  const filled = parts.length ? parts.join(" · ") : "未识别到金额/发票号，请手工填写";
  setHint(hint, `已识别（${data.method}）：${filled}`, parts.length > 0);
  return data;
}

function renderPipeline(res) {
  const method = res.parsed_receipt?.source_method;
  const lines = [
    `单号: ${res.expense_id}`,
    `状态: ${res.status} · 风险: ${res.risk_level} · 人工复核: ${res.need_manual_review}`,
    `票据来源: ${method || "—"} · 文件: ${res.parsed_receipt?.source_filename || "—"}`,
    `摘要: ${res.summary}`,
    `ERP: ${res.erp_voucher_id || "—"}`,
    "",
    "步骤:",
    ...res.steps.map((s) => `- [${s.ok ? "OK" : "NG"}] ${s.step}: ${s.message}`),
    "",
    "审批链:",
    ...(res.approval_chain.length
      ? res.approval_chain.map((a) => `- ${a.role} / ${a.name}`)
      : ["- （自动审批，无人工链）"]),
  ];
  $("#pipelineOut").textContent = lines.join("\n");
}

async function enterApp(user) {
  currentUser = user;
  fillIdentity();
  buildTabs();
  showMain();
  await Promise.all([refreshHealth(), refreshKb()]);
}

async function bootstrap() {
  const token = getToken();
  if (!token) {
    showLogin();
    return loadDemoAccounts();
  }
  try {
    const user = await api("/auth/me");
    saveSession(token, user);
    await enterApp(user);
  } catch {
    clearSession();
    showLogin();
    await loadDemoAccounts();
  }
}

async function loadDemoAccounts() {
  try {
    const data = await fetch("/auth/demo-users").then((r) => r.json());
    $("#demoAccounts").innerHTML =
      `<p class="demo-title">演示账号（点击填入）</p>` +
      (data.items || [])
        .map(
          (a) => `<button type="button" class="btn ghost demo-btn" data-u="${escapeHtml(a.username)}" data-p="${escapeHtml(a.password_hint)}">
            ${escapeHtml(a.display_name)} · ${a.role === "admin" ? "管理员" : "用户"}
            <span>${escapeHtml(a.username)} / ${escapeHtml(a.password_hint)}</span>
          </button>`
        )
        .join("");
    $("#demoAccounts").querySelectorAll(".demo-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        $("#loginUser").value = btn.dataset.u;
        $("#loginPass").value = btn.dataset.p;
      });
    });
  } catch {
    $("#demoAccounts").textContent = "";
  }
}

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  setHint($("#loginHint"), "登录中…");
  try {
    const res = await fetch("/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        username: $("#loginUser").value.trim(),
        password: $("#loginPass").value,
      }),
    }).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || "登录失败");
      return data;
    });
    saveSession(res.token, res.user);
    setHint($("#loginHint"), "", true);
    await enterApp(res.user);
  } catch (err) {
    setHint($("#loginHint"), err.message, false);
  }
});

$("#logoutBtn").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST", body: "{}" });
  } catch {
    /* ignore */
  }
  clearSession();
  showLogin("已退出");
  loadDemoAccounts();
});

$("#refreshKb").addEventListener("click", refreshKb);
$("#refreshMyList").addEventListener("click", refreshMyList);
$("#refreshApprove").addEventListener("click", refreshApprove);
$("#refreshAllList").addEventListener("click", refreshAllList);

$("#ingestForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const hint = $("#ingestHint");
  const raw = $("#texts").value.trim();
  if (!raw) return setHint(hint, "请填写制度文本", false);
  const texts = raw.split(/\n\s*\n/).map((t) => t.trim()).filter(Boolean);
  try {
    const res = await api("/documents", {
      method: "POST",
      body: JSON.stringify({ texts, source: $("#source").value.trim() || "finance-policy" }),
    });
    setHint(hint, `入库成功 ${res.ingested_chunks} 个切片`, true);
    $("#texts").value = "";
    await refreshKb();
  } catch (err) {
    setHint(hint, err.message, false);
  }
});

$("#receiptFile").addEventListener("change", async () => {
  const file = $("#receiptFile").files?.[0];
  if (!file) return;
  try {
    await recognizeReceiptFile(file);
  } catch (err) {
    setHint($("#parseHint"), err.message, false);
  }
});

$("#parseReceiptBtn").addEventListener("click", async () => {
  const file = $("#receiptFile").files?.[0];
  try {
    await recognizeReceiptFile(file);
  } catch (err) {
    setHint($("#parseHint"), err.message, false);
  }
});

$("#expenseForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const hint = $("#expenseHint");
  const btn = e.target.querySelector("button[type=submit]");
  const file = $("#receiptFile").files?.[0];
  if (!file) {
    setHint(hint, "必须上传票据原件（同一文件只能报销一次）", false);
    return;
  }
  btn.disabled = true;
  setHint(hint, "审批链路执行中…");
  try {
    const fd = new FormData();
    fd.append("employee_id", $("#employeeId").value.trim());
    fd.append("employee_name", $("#employeeName").value.trim());
    fd.append("department", $("#department").value.trim());
    fd.append("category", $("#category").value);
    fd.append("amount", String(Number($("#amount").value)));
    fd.append("description", $("#description").value.trim());
    const inv = $("#invoiceNo").value.trim();
    if (inv) fd.append("invoice_no", inv);
    const text = $("#receiptText").value.trim();
    if (text) fd.append("receipt_text", text);
    fd.append("submit_to_erp", $("#submitErp").checked ? "true" : "false");
    fd.append("receipt", file);
    const res = await api("/expenses/submit-file", { method: "POST", body: fd });
    renderPipeline(res);
    const dup = res.steps?.find((s) => s.step === "duplicate_check" && !s.ok);
    setHint(hint, dup ? dup.message : "完成（原件已保存）", !dup);
    refreshMyList();
  } catch (err) {
    setHint(hint, err.message, false);
  } finally {
    btn.disabled = false;
  }
});

$("#allFilterForm")?.addEventListener("submit", (e) => {
  e.preventDefault();
  refreshAllList();
});

$("#filterResetBtn")?.addEventListener("click", () => {
  ["filterStatus", "filterPaid", "filterDept", "filterQ", "filterDateFrom", "filterDateTo"].forEach(
    (id) => {
      const el = $(`#${id}`);
      if (el) el.value = "";
    }
  );
  refreshAllList();
});

$("#exportAllBtn")?.addEventListener("click", async () => {
  try {
    const qs = buildAllListQuery().replace("limit=100", "limit=200");
    const res = await fetch(`/admin/expenses/export?${qs}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || res.statusText || "导出失败");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `expenses-export-${Date.now()}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(err.message);
  }
});

$("#chatForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = $("#message").value.trim();
  if (!message) return;
  const box = $("#messages");
  box.insertAdjacentHTML("beforeend", `<div class="msg user">${escapeHtml(message)}</div>`);
  $("#message").value = "";
  try {
    const res = await api("/chat", {
      method: "POST",
      body: JSON.stringify({ message, use_rag: true, model_params: {} }),
    });
    box.insertAdjacentHTML(
      "beforeend",
      `<div class="msg assistant">${escapeHtml(res.answer)}<div class="meta">RAG=${res.used_rag ? "命中" : "未命中"}</div></div>`
    );
  } catch (err) {
    box.insertAdjacentHTML("beforeend", `<div class="msg assistant">错误：${escapeHtml(err.message)}</div>`);
  }
});

refreshHealth();
setInterval(refreshHealth, 15000);
bootstrap();
