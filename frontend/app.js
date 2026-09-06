// API_BASE و WS_BASE از فایل config.js می‌آیند (که قبل از این فایل لود می‌شود)

let state = {
  token: localStorage.getItem("chatyar_token") || null,
  me: JSON.parse(localStorage.getItem("chatyar_me") || "null"),
  rooms: [],
  activeRoomId: null,
  ws: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ---------- API helper ----------

async function api(path, options = {}) {
  const headers = options.headers || {};
  headers["Content-Type"] = "application/json";
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const res = await fetch(API_BASE + path, { ...options, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "خطای ناشناخته" }));
    throw new Error(err.detail || "خطا در ارتباط با سرور");
  }
  return res.json();
}

// ---------- Auth screen tabs ----------

$$(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    $("#login-form").classList.toggle("hidden", tab !== "login");
    $("#register-form").classList.toggle("hidden", tab !== "register");
  });
});

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    const data = await api("/login", {
      method: "POST",
      body: JSON.stringify({
        username: $("#login-username").value.trim(),
        password: $("#login-password").value,
      }),
    });
    onAuthSuccess(data);
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

$("#register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#register-error").textContent = "";
  try {
    const data = await api("/register", {
      method: "POST",
      body: JSON.stringify({
        username: $("#register-username").value.trim(),
        display_name: $("#register-name").value.trim(),
        password: $("#register-password").value,
      }),
    });
    onAuthSuccess(data);
  } catch (err) {
    $("#register-error").textContent = err.message;
  }
});

function onAuthSuccess(data) {
  state.token = data.access_token;
  state.me = {
    id: data.user_id,
    username: data.username,
    display_name: data.display_name,
    is_admin: !!data.is_admin,
  };
  localStorage.setItem("chatyar_token", state.token);
  localStorage.setItem("chatyar_me", JSON.stringify(state.me));
  enterChatScreen();
}

$("#logout-btn").addEventListener("click", () => {
  if (state.ws) state.ws.close();
  localStorage.removeItem("chatyar_token");
  localStorage.removeItem("chatyar_me");
  state = { token: null, me: null, rooms: [], activeRoomId: null, ws: null };
  $("#chat-screen").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
});

// در موبایل، دکمه‌ی بازگشت از صفحه‌ی چت به لیست گفتگوها برمی‌گردد
$("#mobile-back-btn").addEventListener("click", () => {
  $("#chat-screen").classList.remove("mobile-chat-view");
  state.activeRoomId = null;
  if (state.ws) state.ws.close();
});

// ---------- Chat screen bootstrap ----------

function enterChatScreen() {
  $("#auth-screen").classList.add("hidden");
  $("#chat-screen").classList.remove("hidden");
  $("#me-name").textContent = state.me.display_name;
  $("#me-avatar").textContent = state.me.display_name[0];
  $("#admin-link").classList.remove("hidden");
  loadTheme();
  loadRooms();
}

async function loadTheme() {
  try {
    const res = await fetch(`${API_BASE}/settings/theme`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.accent_color) {
      document.documentElement.style.setProperty("--accent", data.accent_color);
    }
  } catch (e) {
    // اگر بک‌اند در دسترس نبود، رنگ پیش‌فرض همان‌طور که در style.css است باقی می‌ماند
  }
}

async function loadRooms() {
  state.rooms = await api("/rooms");
  renderRoomList();
}

function renderRoomList() {
  const list = $("#room-list");
  list.innerHTML = "";
  state.rooms.forEach((room) => {
    const li = document.createElement("li");
    li.className = room.id === state.activeRoomId ? "active" : "";
    const title = roomTitle(room);
    li.innerHTML = `<span class="avatar">${title[0]}</span>
      <span>
        <span class="room-name">${title}</span>
        <span class="room-preview">${room.is_group ? (room.room_type === "channel" ? "کانال" : "گروه") : "گفتگوی خصوصی"}</span>
      </span>`;
    li.addEventListener("click", () => openRoom(room.id));
    list.appendChild(li);
  });
}

function roomTitle(room) {
  if (room.is_group) {
    const prefix = room.room_type === "channel" ? "📢 " : "";
    return prefix + (room.name || (room.room_type === "channel" ? "کانال بدون نام" : "گروه بدون نام"));
  }
  const other = room.members.find((m) => m.id !== state.me.id);
  return other ? other.display_name : "گفتگو";
}

// ---------- AI assistant shortcut ----------

$("#assistant-btn").addEventListener("click", async () => {
  const room = await api("/assistant/room");
  const exists = state.rooms.some((r) => r.id === room.id);
  if (!exists) {
    state.rooms.unshift(room);
  }
  renderRoomList();
  openRoom(room.id);
});

// ---------- User search / new chat ----------

let searchTimer = null;

async function renderUserResults(q) {
  const users = await api("/users?q=" + encodeURIComponent(q));
  const results = $("#user-results");
  results.innerHTML = "";
  users.forEach((u) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="avatar">${u.display_name[0]}</span>
      <span>
        <span class="room-name">${escapeHtml(u.display_name)}</span>
        <span class="room-preview">${u.is_online ? "آنلاین" : "آفلاین"}</span>
      </span>`;
    li.addEventListener("click", async () => {
      const room = await api("/rooms", {
        method: "POST",
        body: JSON.stringify({ is_group: false, member_ids: [u.id] }),
      });
      $("#user-search").value = "";
      results.classList.add("hidden");
      await loadRooms();
      openRoom(room.id);
    });
    results.appendChild(li);
  });
  results.classList.toggle("hidden", users.length === 0);
}

$("#user-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = $("#user-search").value.trim();
  searchTimer = setTimeout(() => renderUserResults(q), 250);
});

// با فوکوس روی جستجو (حتی خالی)، همه‌ی کاربران (آنلاین و آفلاین) نمایش داده می‌شوند
$("#user-search").addEventListener("focus", () => {
  renderUserResults($("#user-search").value.trim());
});

document.addEventListener("click", (e) => {
  if (!e.target.closest("#user-search") && !e.target.closest("#user-results")) {
    $("#user-results").classList.add("hidden");
  }
});

// هر چند ثانیه یک‌بار لیست گفتگوها را چک کن تا اگر کسی برای اولین بار پیام فرستاد،
// گفتگوی جدید خودکار در سایدبار ظاهر شود — بدون نیاز به رفرش صفحه
setInterval(async () => {
  if (!state.token) return;
  try {
    const rooms = await api("/rooms");
    const known = new Set(state.rooms.map((r) => r.id));
    const hasNew = rooms.some((r) => !known.has(r.id));
    if (hasNew || rooms.length !== state.rooms.length) {
      state.rooms = rooms;
      renderRoomList();
    }
  } catch (e) {
    // بی‌سروصدا نادیده بگیر (مثلاً موقع لاگ‌اوت)
  }
}, 6000);

// ---------- Active room / messages ----------

async function openRoom(roomId) {
  state.activeRoomId = roomId;
  renderRoomList();
  hideTypingIndicator();

  $("#empty-state").classList.add("hidden");
  $("#active-chat").classList.remove("hidden");
  $("#chat-screen").classList.add("mobile-chat-view"); // در موبایل، صفحه‌ی چت را نشان بده

  const room = state.rooms.find((r) => r.id === roomId);
  $("#chat-title").textContent = roomTitle(room);
  $("#chat-status").textContent = room.is_group
    ? `${room.members.length} عضو${room.room_type === "channel" ? " — کانال" : ""}`
    : "";

  const isReadOnlyChannel = room.room_type === "channel" && room.created_by !== state.me.id;
  $("#channel-readonly-note").classList.toggle("hidden", !isReadOnlyChannel);
  $("#send-form").classList.toggle("hidden", isReadOnlyChannel);

  const messages = await api(`/rooms/${roomId}/messages`);
  const box = $("#messages");
  box.innerHTML = "";
  messages.forEach((m) => appendMessage(m));
  box.scrollTop = box.scrollHeight;

  connectWebSocket(roomId);
}

function renderRichText(str) {
  const escaped = escapeHtml(str || "");
  return escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function appendMessage(m) {
  const box = $("#messages");
  const mine = m.sender_id === state.me.id;
  const div = document.createElement("div");
  div.className = "msg " + (mine ? "mine" : "theirs");
  const time = new Date(m.created_at).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
  const senderTag = !mine ? `<span class="msg-sender">${escapeHtml(m.sender_name)}</span>` : "";

  let bodyHtml = "";
  if (m.message_type === "image" && m.file_url) {
    bodyHtml = `<img class="msg-image" src="${API_BASE}${m.file_url}" alt="${escapeHtml(m.file_name || "image")}" onclick="window.open('${API_BASE}${m.file_url}', '_blank')" />`;
    if (m.content) bodyHtml += `<div>${renderRichText(m.content)}</div>`;
  } else if (m.message_type === "voice" && m.file_url) {
    bodyHtml = `<div class="msg-voice"><audio controls src="${API_BASE}${m.file_url}"></audio></div>`;
    if (m.content) bodyHtml += `<div class="voice-transcript">${renderRichText(m.content)}</div>`;
  } else if (m.message_type === "file" && m.file_url) {
    bodyHtml = `<a class="msg-file" href="${API_BASE}${m.file_url}" target="_blank" download="${escapeHtml(m.file_name || "")}">
      <span class="file-icon">📄</span>
      <span class="file-info">
        <span class="file-name">${escapeHtml(m.file_name || "فایل")}</span>
        <span class="file-size">${formatFileSize(m.file_size)}</span>
      </span>
    </a>`;
  } else {
    bodyHtml = renderRichText(m.content || "");
  }

  div.innerHTML = `${senderTag}${bodyHtml}<span class="msg-meta">${time}</span>`;
  box.appendChild(div);
}

function formatFileSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function connectWebSocket(roomId) {
  if (state.ws) state.ws.close();
  const ws = new WebSocket(`${WS_BASE}/ws/${roomId}?token=${state.token}`);
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "message" && data.room_id === state.activeRoomId) {
      hideTypingIndicator();
      appendMessage(data);
      const box = $("#messages");
      box.scrollTop = box.scrollHeight;
    } else if (data.type === "typing") {
      showTypingIndicator();
    } else if (data.type === "error") {
      alert(data.detail || "خطا در ارسال پیام");
    }
  };
  state.ws = ws;
}

function showTypingIndicator() {
  let el = document.getElementById("typing-indicator");
  if (!el) {
    el = document.createElement("div");
    el.id = "typing-indicator";
    el.className = "typing-indicator";
    el.textContent = "دستیار هوشمند در حال تایپ است...";
    $("#messages").after(el);
  }
}

function hideTypingIndicator() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

$("#send-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("#message-input");
  const content = input.value.trim();
  if (!content || !state.ws || state.ws.readyState !== WebSocket.OPEN) return;
  state.ws.send(JSON.stringify({ content, message_type: "text" }));
  input.value = "";
});

// ---------- File upload ----------

function showUploadStatus(text) {
  const el = $("#upload-status");
  el.textContent = text;
  el.classList.remove("hidden");
}

function hideUploadStatus() {
  $("#upload-status").classList.add("hidden");
}

async function uploadAndSend(file) {
  if (!state.activeRoomId) return;
  showUploadStatus(`در حال ارسال «${file.name}»...`);
  try {
    const formData = new FormData();
    formData.append("room_id", state.activeRoomId);
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/upload`, {
      method: "POST",
      headers: { Authorization: "Bearer " + state.token },
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "خطا در آپلود" }));
      throw new Error(err.detail || "خطا در آپلود فایل");
    }
    const data = await res.json();
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        message_type: data.message_type,
        file_url: data.file_url,
        file_name: data.file_name,
        file_size: data.file_size,
        content: "",
      }));
    }
  } catch (err) {
    alert(err.message);
  } finally {
    hideUploadStatus();
  }
}

$("#attach-btn").addEventListener("click", () => {
  if (!state.activeRoomId) {
    alert("اول یک گفتگو را باز کن");
    return;
  }
  $("#file-input").click();
});

$("#file-input").addEventListener("change", () => {
  const file = $("#file-input").files[0];
  if (file) uploadAndSend(file);
  $("#file-input").value = "";
});

// ---------- Voice recording ----------

let mediaRecorder = null;
let recordedChunks = [];

// سرویس‌های گفتار-به-متن (مثل GapGPT/Whisper) گاهی نمی‌توانند مدت‌زمان فایل‌های
// webm را درست بخوانند. برای رفع این مشکل، صدای ضبط‌شده را قبل از ارسال به فرمت
// WAV (که همیشه ساده و قابل‌خواندن است) تبدیل می‌کنیم.
function audioBufferToWavBlob(audioBuffer) {
  const numChannels = audioBuffer.numberOfChannels;
  const sampleRate = audioBuffer.sampleRate;
  const format = 1; // PCM
  const bitDepth = 16;

  let interleaved;
  if (numChannels === 2) {
    const left = audioBuffer.getChannelData(0);
    const right = audioBuffer.getChannelData(1);
    interleaved = new Float32Array(left.length * 2);
    for (let i = 0, j = 0; i < left.length; i++, j += 2) {
      interleaved[j] = left[i];
      interleaved[j + 1] = right[i];
    }
  } else {
    interleaved = audioBuffer.getChannelData(0);
  }

  const bytesPerSample = bitDepth / 8;
  const blockAlign = numChannels * bytesPerSample;
  const dataSize = interleaved.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  function writeString(offset, str) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  }

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, format, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitDepth, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < interleaved.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, interleaved[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  return new Blob([buffer], { type: "audio/wav" });
}

async function convertToWavFile(webmBlob) {
  const arrayBuffer = await webmBlob.arrayBuffer();
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  const audioCtx = new AudioCtx();
  const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
  const wavBlob = audioBufferToWavBlob(audioBuffer);
  audioCtx.close();
  return new File([wavBlob], `voice-${Date.now()}.wav`, { type: "audio/wav" });
}

$("#voice-btn").addEventListener("click", async () => {
  if (!state.activeRoomId) {
    alert("اول یک گفتگو را باز کن");
    return;
  }
  const btn = $("#voice-btn");

  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) recordedChunks.push(e.data);
    };
    mediaRecorder.onstop = async () => {
      btn.classList.remove("recording");
      stream.getTracks().forEach((t) => t.stop());
      const webmBlob = new Blob(recordedChunks, { type: "audio/webm" });
      try {
        showUploadStatus("در حال آماده‌سازی پیام صوتی...");
        const wavFile = await convertToWavFile(webmBlob);
        uploadAndSend(wavFile);
      } catch (err) {
        // اگر تبدیل به WAV ممکن نشد (مرورگر قدیمی)، همان فایل اصلی را بفرست
        const fallbackFile = new File([webmBlob], `voice-${Date.now()}.webm`, { type: "audio/webm" });
        uploadAndSend(fallbackFile);
      }
    };
    mediaRecorder.start();
    btn.classList.add("recording");
  } catch (err) {
    alert("دسترسی به میکروفون ممکن نشد: " + err.message);
  }
});

// ---------- ساخت گروه / کانال ----------

let groupSelectedType = "group";
let groupSelectedMembers = new Map(); // id -> display_name

function openGroupModal() {
  groupSelectedType = "group";
  groupSelectedMembers = new Map();
  $("#group-name-input").value = "";
  $("#group-member-search").value = "";
  $("#group-member-list").innerHTML = "";
  $("#group-modal-error").textContent = "";
  $("#group-selected-count").textContent = "۰ عضو انتخاب شده";
  document.querySelectorAll(".type-btn").forEach((b) => b.classList.toggle("active", b.dataset.type === "group"));
  $("#group-type-hint").textContent = "در گروه همه‌ی اعضا می‌توانند پیام بفرستند.";
  $("#group-modal").classList.remove("hidden");
}

$("#new-group-btn").addEventListener("click", openGroupModal);
$("#group-cancel-btn").addEventListener("click", () => $("#group-modal").classList.add("hidden"));

document.querySelectorAll(".type-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".type-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    groupSelectedType = btn.dataset.type;
    $("#group-type-hint").textContent =
      groupSelectedType === "channel"
        ? "در کانال فقط سازنده (تو) می‌تواند پیام بفرستد؛ بقیه فقط می‌خوانند."
        : "در گروه همه‌ی اعضا می‌توانند پیام بفرستند.";
  });
});

function renderGroupSelectedList() {
  $("#group-selected-count").textContent = `${groupSelectedMembers.size} عضو انتخاب شده`;
}

async function renderGroupMemberSearch(q) {
  const users = await api("/users?q=" + encodeURIComponent(q || ""));
  const list = $("#group-member-list");
  list.innerHTML = "";
  users.forEach((u) => {
    const li = document.createElement("li");
    const checked = groupSelectedMembers.has(u.id);
    li.className = checked ? "selected" : "";
    li.innerHTML = `<span class="avatar">${u.display_name[0]}</span>
      <span>
        <span class="room-name">${escapeHtml(u.display_name)}</span>
        <span class="room-preview">${u.is_online ? "آنلاین" : "آفلاین"}</span>
      </span>
      <span class="check-mark">${checked ? "✓" : ""}</span>`;
    li.addEventListener("click", () => {
      if (groupSelectedMembers.has(u.id)) {
        groupSelectedMembers.delete(u.id);
      } else {
        groupSelectedMembers.set(u.id, u.display_name);
      }
      renderGroupSelectedList();
      renderGroupMemberSearch($("#group-member-search").value.trim());
    });
    list.appendChild(li);
  });
}

let groupSearchTimer = null;
$("#group-member-search").addEventListener("input", () => {
  clearTimeout(groupSearchTimer);
  const q = $("#group-member-search").value.trim();
  groupSearchTimer = setTimeout(() => renderGroupMemberSearch(q), 200);
});

$("#group-create-btn").addEventListener("click", async () => {
  const name = $("#group-name-input").value.trim();
  const errEl = $("#group-modal-error");
  errEl.textContent = "";

  if (!name) {
    errEl.textContent = "اسم گروه/کانال را وارد کن";
    return;
  }
  if (groupSelectedMembers.size === 0) {
    errEl.textContent = "حداقل یک عضو انتخاب کن";
    return;
  }

  try {
    const room = await api("/rooms", {
      method: "POST",
      body: JSON.stringify({
        is_group: true,
        name,
        room_type: groupSelectedType,
        member_ids: Array.from(groupSelectedMembers.keys()),
      }),
    });
    $("#group-modal").classList.add("hidden");
    await loadRooms();
    openRoom(room.id);
  } catch (err) {
    errEl.textContent = err.message;
  }
});

// ---------- Boot ----------

loadTheme();

if (state.token && state.me) {
  enterChatScreen();
}
