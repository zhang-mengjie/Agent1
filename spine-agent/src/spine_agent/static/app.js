const texturePrompt = document.querySelector("#texturePrompt");
const splitPrompt = document.querySelector("#splitPrompt");
const animatePrompt = document.querySelector("#animatePrompt");
function hintOf(form) {
  return form.querySelector("[data-hint]");
}

function clearHints() {
  document.querySelectorAll("[data-hint]").forEach((node) => {
    node.textContent = "";
  });
}
const warnings = document.querySelector("#warnings");
const pillHealth = document.querySelector("#pillHealth");
const pillStage = document.querySelector("#pillStage");
const downloads = document.querySelector("#downloads");
const textureFrame = document.querySelector("#textureFrame");
const assembledFrame = document.querySelector("#assembledFrame");
const partList = document.querySelector("#partList");
const pieceGrid = document.querySelector("#pieceGrid");
const boneList = document.querySelector("#boneList");
const animSelect = document.querySelector("#animSelect");
const playBtn = document.querySelector("#playBtn");
const showBones = document.querySelector("#showBones");
const playhead = document.querySelector("#playhead");
const canvas = document.querySelector("#stageCanvas");
const ctx = canvas.getContext("2d");

const prompts = {
  texture: "一只站立的橙色小猫，圆脸，蓝色围巾，短手臂，长尾巴",
  split: "按图拆开：头、两只耳朵、身体、蓝色围巾、双手、双腿、尾巴。关节处留一点重叠。",
  animate: "待机时身体轻轻起伏，头小幅点动，尾巴左右摆。另外做一个挥手：右臂抬起再放下。",
};

const stageLabel = { new: "尚未开始", texture: "已有贴图", split: "已拆碎图", animate: "可预览动画" };
let projectId = localStorage.getItem("spine-project") || "";
let playback = null;
let textureImage = new Image();
let playing = true;
let raf = 0;
let clock = 0;
let camera = null;

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === `panel-${name}`));
}

async function api(url, body) {
  const response = await fetch(url, {
    method: body ? "POST" : "GET",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "请求失败");
  }
  return data;
}

function setBusy(form, busy) {
  form.querySelector("button").disabled = busy;
}

async function ensureProject() {
  if (projectId) return projectId;
  const created = await api("/api/projects", { title: "" });
  projectId = created.id;
  localStorage.setItem("spine-project", projectId);
  return projectId;
}

function showError(error, form) {
  const hint = form ? hintOf(form) : null;
  if (hint) hint.textContent = error.message || String(error);
}

function renderProject(project) {
  clearHints();
  projectId = project.id;
  localStorage.setItem("spine-project", projectId);
  pillStage.textContent = stageLabel[project.stage] || project.stage;
  if (project.content_prompt) texturePrompt.value = project.content_prompt;
  if (project.skeleton_prompt) splitPrompt.value = project.skeleton_prompt;
  if (project.animation_prompt) animatePrompt.value = project.animation_prompt;

  warnings.hidden = !project.warnings?.length;
  warnings.textContent = (project.warnings || []).join(" ");

  const textureCaption = document.querySelector("#textureCaption");
  const assembledCaption = document.querySelector("#assembledCaption");
  const cut = (project.parts || []).length > 0;
  if (textureCaption) textureCaption.textContent = cut ? "切开后的图集" : "整图";
  if (assembledCaption) assembledCaption.textContent = cut ? "按原位置拼回" : "确认这张整图，满意后再拆";
  textureFrame.innerHTML = project.texture_url
    ? `<img alt="${cut ? "图集" : "整图"}" src="${project.texture_url}" />`
    : `<p class="empty">完成第 1 步后显示整图</p>`;
  assembledFrame.innerHTML = project.assembled_url
    ? `<img alt="${cut ? "拼回的角色" : "整图"}" src="${project.assembled_url}" />`
    : `<p class="empty">完成第 1 步后显示整图</p>`;

  partList.innerHTML = (project.parts || [])
    .map((part) => `<li>${part.name} · ${part.w}×${part.h} · ${part.pivot}</li>`)
    .join("");

  if (project.pieces?.length) {
    pieceGrid.innerHTML = project.pieces
      .map((piece) => `<div class="piece checker"><img alt="${piece.name}" src="${piece.url}?v=${project.updated_at}" /><span>${piece.name}</span></div>`)
      .join("");
  } else {
    pieceGrid.innerHTML = `<p class="empty">完成第 2 步后，这里是按骨骼裁开的碎图。</p>`;
  }

  boneList.innerHTML = (project.bones || [])
    .map((bone) => `<li>${bone.name}${bone.parent ? ` ← ${bone.parent}` : ""}${bone.part ? ` · ${bone.part}` : ""}</li>`)
    .join("");

  downloads.innerHTML = "";
  if (project.downloads) {
    const links = [
      ["JSON", project.downloads.json],
      ["Atlas", project.downloads.atlas],
      ["ZIP", project.downloads.zip],
    ];
    downloads.innerHTML = links
      .map(([label, href]) => `<a class="btn ghost" href="${href}">下载 ${label}</a>`)
      .join("");
  }

  const names = Object.keys(project.playback?.animations || {});
  animSelect.innerHTML = names.map((name) => `<option value="${name}">${name}</option>`).join("");
  animSelect.disabled = names.length === 0;
  startPlayer(project.playback);
}

function startPlayer(next) {
  cancelAnimationFrame(raf);
  playback = next;
  clock = 0;
  tick.last = 0;
  camera = null;
  if (!playback) {
    drawEmpty("完成第 2 步后可预览骨骼，第 3 步开始播放动画");
    return;
  }
  textureImage = new Image();
  textureImage.onload = () => {
    camera = makeCamera();
    tick(performance.now());
  };
  textureImage.onerror = () => drawEmpty("贴图加载失败");
  textureImage.src = playback.texture;
}

function drawEmpty(message) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#1a140f";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#b5a89a";
  ctx.font = "24px Outfit, sans-serif";
  ctx.fillText(message, 36, 72);
}

function sampleChannel(keys, time, field, fallback) {
  if (!keys?.length) return fallback;
  if (time <= keys[0].time) return keys[0][field] ?? fallback;
  for (let index = 0; index < keys.length - 1; index += 1) {
    const left = keys[index];
    const right = keys[index + 1];
    if (time <= right.time) {
      const span = right.time - left.time || 1;
      const mix = (time - left.time) / span;
      const from = left[field] ?? fallback;
      const to = right[field] ?? fallback;
      return from + (to - from) * mix;
    }
  }
  return keys[keys.length - 1][field] ?? fallback;
}

function poseAt(time, useAnimation = true) {
  const locals = {};
  for (const bone of playback.bones) {
    locals[bone.name] = {
      x: bone.x,
      y: bone.y,
      rotation: bone.rotation,
      scaleX: 1,
      scaleY: 1,
    };
  }
  const selected = animSelect.value;
  const channels = useAnimation ? playback.animations?.[selected]?.bones || {} : {};
  for (const [name, channel] of Object.entries(channels)) {
    if (!locals[name]) continue;
    locals[name].rotation = sampleChannel(channel.rotate, time, "angle", locals[name].rotation);
    locals[name].x = sampleChannel(channel.translate, time, "x", locals[name].x);
    locals[name].y = sampleChannel(channel.translate, time, "y", locals[name].y);
    locals[name].scaleX = sampleChannel(channel.scale, time, "x", 1);
    locals[name].scaleY = sampleChannel(channel.scale, time, "y", 1);
  }
  const world = {};
  function pose(name) {
    if (world[name]) return world[name];
    const local = locals[name];
    const bone = playback.bones.find((item) => item.name === name);
    const radians = (local.rotation * Math.PI) / 180;
    const la = Math.cos(radians) * local.scaleX;
    const lb = Math.cos(radians + Math.PI / 2) * local.scaleY;
    const lc = Math.sin(radians) * local.scaleX;
    const ld = Math.sin(radians + Math.PI / 2) * local.scaleY;
    const parent = bone.parent ? pose(bone.parent) : null;
    if (!parent) {
      world[name] = { a: la, b: lb, c: lc, d: ld, x: local.x, y: local.y };
      return world[name];
    }
    world[name] = {
      a: parent.a * la + parent.b * lc,
      b: parent.a * lb + parent.b * ld,
      c: parent.c * la + parent.d * lc,
      d: parent.c * lb + parent.d * ld,
      x: parent.a * local.x + parent.b * local.y + parent.x,
      y: parent.c * local.x + parent.d * local.y + parent.y,
    };
    return world[name];
  }
  playback.bones.forEach((bone) => pose(bone.name));
  return world;
}

function durationOf() {
  const selected = animSelect.value;
  const bones = playback?.animations?.[selected]?.bones || {};
  let end = 0;
  for (const channel of Object.values(bones)) {
    for (const keys of Object.values(channel)) {
      if (Array.isArray(keys) && keys.length) end = Math.max(end, keys[keys.length - 1].time || 0);
    }
  }
  return end;
}

function tick(now) {
  if (!playback || !textureImage.complete) return;
  const duration = durationOf();
  if (playing && duration > 0) clock += Math.min(0.05, (now - (tick.last || now)) / 1000);
  tick.last = now;
  const time = duration > 0 ? clock % duration : 0;
  const world = poseAt(time);
  drawFrame(world);
  playhead.style.width = duration > 0 ? `${(time / duration) * 100}%` : "0%";
  raf = requestAnimationFrame(tick);
}

function attachmentPoints(world) {
  const points = [];
  for (const attachment of playback.attachments) {
    const bone = world[attachment.bone];
    if (!bone) continue;
    const halfW = attachment.width / 2;
    const halfH = attachment.height / 2;
    for (const ox of [-halfW, halfW]) {
      for (const oy of [-halfH, halfH]) {
        const lx = attachment.x + ox;
        const ly = attachment.y + oy;
        points.push([lx * bone.a + ly * bone.b + bone.x, lx * bone.c + ly * bone.d + bone.y]);
      }
    }
  }
  return points;
}

function makeCamera() {
  const points = attachmentPoints(poseAt(0, false));
  const minX = Math.min(...points.map((point) => point[0]));
  const maxX = Math.max(...points.map((point) => point[0]));
  const minY = Math.min(...points.map((point) => point[1]));
  const maxY = Math.max(...points.map((point) => point[1]));
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const halfW = ((maxX - minX) / 2) * 1.18;
  const halfH = ((maxY - minY) / 2) * 1.18;
  const pad = 36;
  const zoom = Math.min((canvas.width - pad * 2) / (halfW * 2 || 1), (canvas.height - pad * 2) / (halfH * 2 || 1));
  const originX = canvas.width / 2 - cx * zoom;
  const originY = canvas.height / 2 + cy * zoom;
  return { zoom, originX, originY, minY };
}

function drawFrame(world) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#1a140f";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!camera) return;
  const { zoom, originX, originY, minY } = camera;
  const toScreen = (x, y) => [originX + x * zoom, originY - y * zoom];
  const footY = originY - minY * zoom;
  ctx.fillStyle = "rgba(227, 155, 74, 0.16)";
  ctx.beginPath();
  ctx.ellipse(canvas.width / 2, footY, 90 * (zoom / 2), 16, 0, 0, Math.PI * 2);
  ctx.fill();

  for (const attachment of playback.attachments) {
    const bone = world[attachment.bone];
    if (!bone) continue;
    const [sx, sy] = toScreen(
      attachment.x * bone.a + attachment.y * bone.b + bone.x,
      attachment.x * bone.c + attachment.y * bone.d + bone.y,
    );
    const angle = Math.atan2(bone.c, bone.a) + ((attachment.rotation || 0) * Math.PI) / 180;
    const scaleX = Math.hypot(bone.a, bone.c) || 1;
    const scaleY = Math.hypot(bone.b, bone.d) || 1;
    const [srcX, srcY, srcW, srcH] = attachment.src;
    ctx.save();
    ctx.translate(sx, sy);
    ctx.rotate(-angle);
    ctx.scale(scaleX, scaleY);
    ctx.drawImage(
      textureImage,
      srcX,
      srcY,
      srcW,
      srcH,
      (-attachment.width / 2) * zoom,
      (-attachment.height / 2) * zoom,
      attachment.width * zoom,
      attachment.height * zoom,
    );
    ctx.restore();
  }

  if (showBones.checked) {
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(227, 155, 74, 0.95)";
    ctx.fillStyle = "#ffe0b8";
    for (const bone of playback.bones) {
      const node = world[bone.name];
      const parent = bone.parent ? world[bone.parent] : null;
      const [x, y] = toScreen(node.x, node.y);
      if (parent) {
        const [px, py] = toScreen(parent.x, parent.y);
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(x, y);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

async function runStep(form, path, prompt, offline) {
  setBusy(form, true);
  clearHints();
  const busy = {
    texture: offline ? "正在用内置橙猫生成…" : "正在生成整图…",
    split: offline ? "正在用内置橙猫生成…" : "正在拆解部件…",
    animate: offline ? "正在用内置橙猫生成…" : "正在生成…",
  };
  hintOf(form).textContent = busy[path] || "正在生成…";
  try {
    const id = await ensureProject();
    const project = await api(`/api/projects/${id}/${path}`, { prompt, offline });
    renderProject(project);
    if (path === "texture") activateTab("sheet");
    if (path === "split") activateTab("pieces");
    if (path === "animate") activateTab("preview");
    return true;
  } catch (error) {
    showError(error, form);
    return false;
  } finally {
    setBusy(form, false);
  }
}

document.querySelector("#textureForm").addEventListener("submit", (event) => {
  event.preventDefault();
  runStep(event.currentTarget, "texture", texturePrompt.value, false);
});
document.querySelector("#splitForm").addEventListener("submit", (event) => {
  event.preventDefault();
  runStep(event.currentTarget, "split", splitPrompt.value, false);
});
document.querySelector("#animateForm").addEventListener("submit", (event) => {
  event.preventDefault();
  runStep(event.currentTarget, "animate", animatePrompt.value, false);
});

document.querySelector("#demoBtn").addEventListener("click", async () => {
  const button = document.querySelector("#demoBtn");
  button.disabled = true;
  try {
    texturePrompt.value = prompts.texture;
    splitPrompt.value = prompts.split;
    animatePrompt.value = prompts.animate;
    projectId = "";
    localStorage.removeItem("spine-project");
    const textured = await runStep(document.querySelector("#textureForm"), "texture", prompts.texture, true);
    if (!textured) return;
    const split = await runStep(document.querySelector("#splitForm"), "split", prompts.split, true);
    if (!split) return;
    await runStep(document.querySelector("#animateForm"), "animate", prompts.animate, true);
  } finally {
    button.disabled = false;
  }
});

playBtn.addEventListener("click", () => {
  playing = !playing;
  playBtn.textContent = playing ? "暂停" : "播放";
  tick.last = performance.now();
});
animSelect.addEventListener("change", () => {
  clock = 0;
});
showBones.addEventListener("change", () => {
  if (playback && textureImage.complete && camera) {
    const duration = durationOf();
    drawFrame(poseAt(duration > 0 ? clock % duration : 0));
  }
});

async function boot() {
  try {
    const health = await api("/health");
    pillHealth.textContent = health.llm_configured ? `模型 ${health.llm_model}` : "未配置模型，可用内置示例";
  } catch {
    pillHealth.textContent = "服务未响应";
  }
  drawEmpty("完成第 2 步后可预览骨骼，第 3 步开始播放动画");
  if (!projectId) return;
  try {
    renderProject(await api(`/api/projects/${projectId}`));
    if (playback?.animations && Object.keys(playback.animations).length) activateTab("preview");
    else if (document.querySelector(".piece img")) activateTab("pieces");
  } catch {
    projectId = "";
    localStorage.removeItem("spine-project");
  }
}

boot();
