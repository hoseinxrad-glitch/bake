// API_BASE از فایل config.js می‌آید (که قبل از این فایل لود می‌شود)

const token = localStorage.getItem("chatyar_token");
const me = JSON.parse(localStorage.getItem("chatyar_me") || "null");

const $ = (sel) => document.querySelector(sel);

let adminPassword = sessionStorage.getItem("chatyar_admin_pw") || "";

async function api(path, options = {}) {
  const headers = options.headers || {};
  headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = "Bearer " + token;
  if (adminPassword) headers["X-Admin-Password"] = adminPassword;
  const res = await fetch(API_BASE + path, { ...options, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "خطای ناشناخته" }));
    const e = new Error(err.detail || "خطا در ارتباط با سرور");
    e.status = res.status;
    throw e;
  }
  return res.json();
}

async function init() {
  if (!token || !me) {
    window.location.href = "index.html";
    return;
  }

  if (adminPassword) {
    const ok = await tryEnterAdmin();
    if (ok) return;
  }

  $("#password-gate").classList.remove("hidden");
}

async function tryEnterAdmin() {
  try {
    await loadStats();
    await loadUsers();
    $("#password-gate").classList.add("hidden");
    $("#admin-app").classList.remove("hidden");
    return true;
  } catch (err) {
    sessionStorage.removeItem("chatyar_admin_pw");
    adminPassword = "";
    return false;
  }
}

$("#password-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#admin-password-input");
  const errEl = $("#password-error");
  errEl.textContent = "";
  adminPassword = input.value;
  const ok = await tryEnterAdmin();
  if (!ok) {
    errEl.textContent = "رمز اشتباه است";
    return;
  }
  sessionStorage.setItem("chatyar_admin_pw", adminPassword);
});

async function loadStats() {
  const stats = await api("/admin/stats");
  const grid = $("#stats-grid");
  const items = [
    ["کل کاربران", stats.total_users],
    ["آنلاین الان", stats.online_users],
    ["کل گفتگوها", stats.total_rooms],
    ["کل پیام‌ها", stats.total_messages],
    ["کاربران مسدود", stats.banned_users],
  ];
  grid.innerHTML = items
    .map(
      ([label, value]) =>
        `<div class="stat-card"><span class="stat-value">${value}</span><span class="stat-label">${label}</span></div>`
    )
    .join("");
}

async function loadUsers(q = "") {
  const users = await api("/admin/users" + (q ? "?q=" + encodeURIComponent(q) : ""));
  const body = $("#users-table-body");
  body.innerHTML = "";
  users.forEach((u) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${u.id}</td>
      <td>${u.display_name}</td>
      <td>${u.username}</td>
      <td>
        <span class="badge ${u.is_online ? "online" : "offline"}">${u.is_online ? "آنلاین" : "آفلاین"}</span>
        ${u.is_banned ? '<span class="badge banned">مسدود</span>' : ""}
      </td>
      <td>${u.is_admin ? '<span class="badge admin">ادمین</span>' : "کاربر عادی"}</td>
      <td class="row-actions"></td>
    `;
    const actions = tr.querySelector(".row-actions");

    if (u.id !== me.id) {
      const banBtn = document.createElement("button");
      banBtn.textContent = u.is_banned ? "رفع مسدودیت" : "مسدود کردن";
      banBtn.className = u.is_banned ? "" : "danger";
      banBtn.addEventListener("click", async () => {
        await api(`/admin/users/${u.id}/${u.is_banned ? "unban" : "ban"}`, { method: "POST" });
        loadUsers($("#admin-user-search").value.trim());
        loadStats();
      });
      actions.appendChild(banBtn);

      if (!u.is_admin) {
        const promoteBtn = document.createElement("button");
        promoteBtn.textContent = "ارتقا به ادمین";
        promoteBtn.addEventListener("click", async () => {
          await api(`/admin/users/${u.id}/make-admin`, { method: "POST" });
          loadUsers($("#admin-user-search").value.trim());
        });
        actions.appendChild(promoteBtn);
      }

      const delBtn = document.createElement("button");
      delBtn.textContent = "حذف کاربر";
      delBtn.className = "danger";
      delBtn.addEventListener("click", async () => {
        if (!confirm(`کاربر «${u.display_name}» برای همیشه حذف شود؟`)) return;
        await api(`/admin/users/${u.id}`, { method: "DELETE" });
        loadUsers($("#admin-user-search").value.trim());
        loadStats();
      });
      actions.appendChild(delBtn);
    } else {
      actions.textContent = "—";
    }

    body.appendChild(tr);
  });
}

async function loadRooms() {
  const rooms = await api("/admin/rooms");
  const body = $("#rooms-table-body");
  body.innerHTML = "";
  rooms.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.id}</td>
      <td>${r.name || (r.is_group ? "گروه بدون نام" : "گفتگوی خصوصی")}</td>
      <td>${r.is_group ? "گروهی" : "خصوصی"}</td>
      <td>${r.member_count}</td>
      <td>${r.message_count}</td>
      <td class="row-actions"></td>
    `;
    const actions = tr.querySelector(".row-actions");
    const delBtn = document.createElement("button");
    delBtn.textContent = "حذف گفتگو";
    delBtn.className = "danger";
    delBtn.addEventListener("click", async () => {
      if (!confirm("این گفتگو و تمام پیام‌های آن حذف شود؟")) return;
      await api(`/admin/rooms/${r.id}`, { method: "DELETE" });
      loadRooms();
      loadStats();
    });
    actions.appendChild(delBtn);
    body.appendChild(tr);
  });
}

// ---------- دستیار هوشمند: مدل و کلیدها ----------

async function loadAISettings() {
  const settings = await api("/admin/ai-settings");
  $("#ai-model-input").value = settings.model;
  $("#ai-stt-input").value = settings.stt_model;
  $("#ai-tts-input").value = settings.tts_model;
  $("#ai-voice-input").value = settings.tts_voice;
  $("#ai-settings-meta").textContent =
    `مدل پیش‌فرض: ${settings.default_model} — کلیدهای فعال (${settings.key_count}): ${settings.masked_keys.join(", ") || "هیچ‌کدام"}`;
}

$("#ai-voice-save")?.addEventListener("click", async () => {
  const status = $("#ai-voice-status");
  const stt = $("#ai-stt-input").value.trim();
  const tts = $("#ai-tts-input").value.trim();
  const voice = $("#ai-voice-input").value.trim();
  try {
    await api("/admin/ai-settings", {
      method: "POST",
      body: JSON.stringify({ stt_model: stt || undefined, tts_model: tts || undefined, tts_voice: voice || undefined }),
    });
    status.textContent = "تنظیمات صوتی ذخیره و اعمال شد.";
    status.className = "ai-settings-status ok";
    loadAISettings();
  } catch (err) {
    status.textContent = err.message;
    status.className = "ai-settings-status error";
  }
});

$("#ai-model-save")?.addEventListener("click", async () => {
  const input = $("#ai-model-input");
  const status = $("#ai-model-status");
  const newModel = input.value.trim();
  if (!newModel) {
    status.textContent = "اسم مدل نمی‌تواند خالی باشد";
    status.className = "ai-settings-status error";
    return;
  }
  try {
    const settings = await api("/admin/ai-settings", {
      method: "POST",
      body: JSON.stringify({ model: newModel }),
    });
    status.textContent = `مدل به «${settings.model}» تغییر کرد و فعال است.`;
    status.className = "ai-settings-status ok";
    loadAISettings();
  } catch (err) {
    status.textContent = err.message;
    status.className = "ai-settings-status error";
  }
});

$("#ai-keys-save")?.addEventListener("click", async () => {
  const input = $("#ai-keys-input");
  const status = $("#ai-keys-status");
  const raw = input.value.trim();
  if (!raw) {
    status.textContent = "حداقل یک کلید API وارد کن";
    status.className = "ai-settings-status error";
    return;
  }
  try {
    const settings = await api("/admin/ai-settings", {
      method: "POST",
      body: JSON.stringify({ api_keys: raw }),
    });
    status.textContent = `${settings.key_count} کلید ذخیره و فعال شد.`;
    status.className = "ai-settings-status ok";
    input.value = "";
    loadAISettings();
  } catch (err) {
    status.textContent = err.message;
    status.className = "ai-settings-status error";
  }
});

// ---------- ظاهر اپ ----------

async function loadTheme() {
  const res = await fetch(`${API_BASE}/settings/theme`);
  const data = await res.json();
  $("#theme-color-picker").value = data.accent_color;
  $("#theme-color-input").value = data.accent_color;
}

$("#theme-color-picker")?.addEventListener("input", () => {
  $("#theme-color-input").value = $("#theme-color-picker").value;
});

$("#theme-save")?.addEventListener("click", async () => {
  const status = $("#theme-status");
  const color = $("#theme-color-input").value.trim();
  try {
    await api("/admin/theme", {
      method: "POST",
      body: JSON.stringify({ accent_color: color }),
    });
    document.documentElement.style.setProperty("--accent", color);
    status.textContent = "رنگ اپلیکیشن برای همه‌ی کاربران تغییر کرد.";
    status.className = "ai-settings-status ok";
  } catch (err) {
    status.textContent = err.message;
    status.className = "ai-settings-status error";
  }
});

// ---------- تب‌ها ----------

document.querySelectorAll(".admin-tabs .tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".admin-tabs .tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const panel = btn.dataset.panel;
    $("#panel-users").classList.toggle("hidden", panel !== "users");
    $("#panel-rooms").classList.toggle("hidden", panel !== "rooms");
    $("#panel-ai").classList.toggle("hidden", panel !== "ai");
    $("#panel-appearance").classList.toggle("hidden", panel !== "appearance");
    if (panel === "rooms") loadRooms();
    if (panel === "ai") loadAISettings();
    if (panel === "appearance") loadTheme();
  });
});

let userSearchTimer = null;
$("#admin-user-search")?.addEventListener("input", () => {
  clearTimeout(userSearchTimer);
  userSearchTimer = setTimeout(() => loadUsers($("#admin-user-search").value.trim()), 250);
});

init();
