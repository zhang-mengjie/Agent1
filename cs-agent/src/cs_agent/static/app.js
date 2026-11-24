/**
 * cs-agent 前端
 * 【目的】FAQ 入库 + 对话；展示 intent / need_human。
 * 【易错点】sessionId 要复用；转人工提示看响应字段 need_human，不要只看答句。
 */
const $ = (sel) => document.querySelector(sel);

function setHint(el, text, ok) {
  el.textContent = text || "";
  el.classList.toggle("ok", ok === true);
  el.classList.toggle("bad", ok === false);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || res.statusText || "请求失败";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === name);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${name}`);
  });
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

async function refreshHealth() {
  const pill = $("#pillHealth");
  try {
    const h = await api("/health");
    const ok = h.postgres && h.redis;
    pill.textContent = `服务 ${ok ? "正常" : "部分异常"} · PG ${h.postgres ? "✓" : "×"} · Redis ${h.redis ? "✓" : "×"}`;
    pill.className = `pill ${ok ? "ok" : "warn"}`;
  } catch (err) {
    pill.textContent = `服务不可用：${err.message}`;
    pill.className = "pill bad";
  }
}

function renderStats(stats) {
  const allVectorized =
    stats.total_chunks > 0 && stats.total_chunks === stats.vectorized_chunks;
  $("#pillKb").textContent = `知识库 ${stats.total_chunks} 块 · 已向量化 ${stats.vectorized_chunks}` +
    (stats.embedding_dims ? ` · ${stats.embedding_dims} 维` : "");
  $("#pillKb").className = `pill ${allVectorized ? "ok" : stats.total_chunks ? "warn" : ""}`;

  const sourceText = (stats.sources || [])
    .map((s) => `${s.source}:${s.count}`)
    .join(" · ") || "暂无来源";

  $("#kbStats").innerHTML = `
    <div class="stat"><b>${stats.total_chunks}</b><span>总切片</span></div>
    <div class="stat"><b>${stats.vectorized_chunks}</b><span>已向量化</span></div>
    <div class="stat"><b>${stats.embedding_dims || "—"}</b><span>向量维度</span></div>
    <div class="stat" style="grid-column: 1 / -1"><b style="font-size:0.95rem">${sourceText}</b><span>collection: ${stats.collection}</span></div>
  `;
}

function renderChunks(items) {
  const box = $("#chunkList");
  if (!items.length) {
    box.innerHTML = `<div class="chunk"><p>暂无数据。先在左侧提交文本。</p></div>`;
    return;
  }
  box.innerHTML = items
    .map((item) => {
      const preview = item.content.length > 280 ? `${item.content.slice(0, 280)}…` : item.content;
      return `
        <article class="chunk">
          <div class="chunk-meta">
            <span class="badge">#${item.id}</span>
            <span class="badge">${item.source}</span>
            <span class="badge ${item.vectorized ? "ok" : ""}">
              ${item.vectorized ? `已向量化 · ${item.embedding_dims} 维` : "未向量化"}
            </span>
            <span>${item.created_at || ""}</span>
          </div>
          <p>${escapeHtml(preview)}</p>
        </article>
      `;
    })
    .join("");
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function refreshKb() {
  try {
    const [stats, list] = await Promise.all([
      api("/documents/stats"),
      api("/documents?limit=50"),
    ]);
    renderStats(stats);
    renderChunks(list.items || []);
  } catch (err) {
    $("#kbStats").textContent = `加载失败：${err.message}`;
    $("#chunkList").innerHTML = "";
    $("#pillKb").textContent = "知识库不可用";
    $("#pillKb").className = "pill bad";
  }
}

$("#refreshKb").addEventListener("click", refreshKb);

async function apiForm(path, formData) {
  const res = await fetch(path, { method: "POST", body: formData });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || res.statusText || "请求失败";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

$("#pdfForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const hint = $("#pdfHint");
  const fileInput = $("#pdfFile");
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    setHint(hint, "请先选择 PDF 文件。", false);
    return;
  }
  const form = new FormData();
  form.append("file", file);
  const source = $("#pdfSource").value.trim();
  if (source) form.append("source", source);

  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true;
  setHint(hint, "正在解析并向量化 PDF…");
  try {
    const res = await apiForm("/documents/pdf", form);
    setHint(hint, `PDF 入库成功：${res.ingested_chunks} 个切片（source=${res.source}）。`, true);
    fileInput.value = "";
    await refreshKb();
  } catch (err) {
    setHint(hint, err.message, false);
  } finally {
    btn.disabled = false;
  }
});

$("#ingestForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const hint = $("#ingestHint");
  const raw = $("#texts").value.trim();
  if (!raw) {
    setHint(hint, "请先填写文本。", false);
    return;
  }
  const texts = raw
    .split(/\n\s*\n/)
    .map((t) => t.trim())
    .filter(Boolean);
  const source = $("#source").value.trim() || "manual";
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true;
  setHint(hint, "入库中（切分 + embedding）…");
  try {
    const res = await api("/documents", {
      method: "POST",
      body: JSON.stringify({ texts, source }),
    });
    setHint(hint, `成功写入 ${res.ingested_chunks} 个向量切片（source=${res.source}）。`, true);
    $("#texts").value = "";
    await refreshKb();
  } catch (err) {
    setHint(hint, err.message, false);
  } finally {
    btn.disabled = false;
  }
});

function appendMessage(role, content, meta = "") {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = `${escapeHtml(content)}${meta ? `<div class="meta">${escapeHtml(meta)}</div>` : ""}`;
  $("#messages").appendChild(el);
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

$("#chatForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = $("#message").value.trim();
  if (!message) return;
  const sessionId = $("#sessionId").value.trim() || null;
  const useRag = $("#useRag").checked;
  const btn = e.target.querySelector("button[type=submit]");
  appendMessage("user", message);
  $("#message").value = "";
  btn.disabled = true;
  try {
    const res = await api("/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        session_id: sessionId,
        use_rag: useRag,
        model_params: {},
      }),
    });
    $("#sessionId").value = res.session_id;
    const meta = [
      `model=${res.model}`,
      `intent=${res.intent || "other"}`,
      res.need_human ? "转人工=建议" : "转人工=否",
      res.used_rag ? "FAQ=命中" : "FAQ=未命中",
      res.sources?.length ? `sources=${res.sources.length}` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    appendMessage("assistant", res.answer, meta);
  } catch (err) {
    appendMessage("assistant", `错误：${err.message}`);
  } finally {
    btn.disabled = false;
  }
});

refreshHealth();
refreshKb();
setInterval(refreshHealth, 15000);
