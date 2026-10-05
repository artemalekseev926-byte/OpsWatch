"use strict";

const S = {
  token: store("ow_token"),
  me: null,
  meta: null,
  route: "overview",
  unread: 0,
  open: {},
  lastNotif: -1,
  pollTimer: null,
  refreshTimer: null,
  refresh: null,
  seq: 0,
  dropdown: null,
};

const SEV = { info: "Информация", warning: "Предупреждение", critical: "Критично" };
const SEV_SHORT = { info: "Инфо", warning: "Предупр.", critical: "Критично" };
const STATUS = { new: "Новое", acked: "Принято", resolved: "Решено" };
const CAT = { monitoring: "Мониторинг", database: "Базы данных", onec: "1С", backup: "Бэкапы", bug: "Ошибки", system: "Система" };
const CAT_ICON = { monitoring: "activity", database: "database", onec: "box", backup: "archive", bug: "bug", system: "shield" };
const CAT_TAB = { monitoring: "monitoring", database: "databases", onec: "onec", backup: "backups", bug: "bugs", system: "journal" };
const VIEW_PERMS = ["monitoring.view", "databases.view", "onec.view", "backups.view", "bugs.view", "system.view"];
const BACKUP_STATUS = { ok: "Успешно", failed: "Ошибка", running: "Выполняется", never: "Не запускался" };
const SOURCE_STATUS = { ok: "Работает", error: "Недоступен", unknown: "Ожидает проверки", waiting: "Ожидает данных" };

const ICONS = {
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.27 6.96 12 12.01l8.73-5.05M12 22.08V12"/>',
  archive: '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
  bug: '<path d="m8 2 1.88 1.88M14.12 3.88 16 2M9 7.13v-1a3 3 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9M6.53 9C4.6 8.8 3 7.1 3 5M6 13H2M3 21c0-2.1 1.7-3.9 3.8-4M20.97 5c0 2.1-1.6 3.8-3.5 4M22 13h-4M17.2 17c2.1.1 3.8 1.9 3.8 4"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  trash: '<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4M12 17h.01"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  server: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/>',
};

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key) || "";
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch (e) {
    return "";
  }
  return value;
}

function icon(name) {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
  return t.content.firstChild;
}

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style") el.style.cssText = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (["value", "checked", "selected", "disabled", "multiple", "indeterminate"].includes(k)) el[k] = v;
      else el.setAttribute(k, v === true ? "" : String(v));
    }
  }
  append(el, kids);
  return el;
}

function fill(el, ...kids) {
  el.replaceChildren();
  return append(el, kids);
}

function append(el, kids) {
  for (const kid of (Array.isArray(kids) ? kids : [kids]).flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function can(perm) {
  return !!(S.me && S.me.status === "active" && S.me.permissions.includes(perm));
}

function bridge() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

async function api(path, opts = {}) {
  const headers = {};
  if (S.token) headers.Authorization = "Bearer " + S.token;
  let body = opts.body;
  if (body !== undefined && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, { method: opts.method || (body !== undefined ? "POST" : "GET"), headers, body });
  } catch (e) {
    throw new Error("Сервер недоступен");
  }
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (e) {
    data = text;
  }
  if (res.status === 401 && S.token && !opts.silent401) {
    logoutLocal();
    throw new Error("Сессия завершена, войдите снова");
  }
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : "Ошибка " + res.status;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function toast(message, type = "") {
  const box = document.getElementById("toasts");
  const el = h("div", { class: "toast " + type }, message);
  box.append(el);
  setTimeout(() => el.remove(), type === "error" ? 6000 : 3500);
}

async function guard(fn, okMessage) {
  try {
    const result = await fn();
    if (okMessage) toast(okMessage);
    return result;
  } catch (e) {
    toast(e.message, "error");
    return undefined;
  }
}

function modal({ title, subtitle, body, foot, wide, onClose }) {
  const root = document.getElementById("modal-root");
  let backdrop;
  const onKey = (e) => {
    if (e.key === "Escape") close();
  };
  function close() {
    if (!backdrop.isConnected) return;
    backdrop.remove();
    document.removeEventListener("keydown", onKey);
    if (onClose) onClose();
  }
  backdrop = h(
    "div",
    { class: "modal-backdrop", onmousedown: (e) => { if (e.target === backdrop) close(); } },
    h(
      "div",
      { class: "modal" + (wide ? " wide" : ""), role: "dialog" },
      h(
        "div",
        { class: "modal-head" },
        h("div", null, h("h2", null, title), subtitle ? h("div", { class: "muted small" }, subtitle) : null),
        h("button", { class: "icon-btn", onclick: close, title: "Закрыть" }, icon("x"))
      ),
      h("div", { class: "modal-body" }, body),
      foot && foot.length ? h("div", { class: "modal-foot" }, foot) : null
    )
  );
  document.addEventListener("keydown", onKey);
  root.append(backdrop);
  return { close, el: backdrop };
}

function confirmDialog(text, action, label = "Удалить") {
  const m = modal({
    title: "Подтверждение",
    body: h("p", null, text),
    foot: [
      h("button", { class: "btn", onclick: () => m.close() }, "Отмена"),
      h("button", { class: "btn primary", onclick: async () => { m.close(); await action(); } }, label),
    ],
  });
}

function parseDate(iso) {
  return iso ? new Date(iso) : null;
}

function fmtDate(iso, withYear = false) {
  const d = parseDate(iso);
  if (!d) return "—";
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: withYear ? "numeric" : undefined,
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ago(iso) {
  const d = parseDate(iso);
  if (!d) return "—";
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 0) return "через " + duration(-sec);
  if (sec < 45) return "только что";
  return duration(sec) + " назад";
}

function duration(sec) {
  if (sec < 90) return Math.max(1, Math.round(sec / 60)) + " мин";
  if (sec < 3600) return Math.round(sec / 60) + " мин";
  if (sec < 86400) return Math.round(sec / 3600) + " ч";
  return Math.round(sec / 86400) + " дн";
}

function humanSize(n) {
  if (n === null || n === undefined) return "—";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let v = Number(n);
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + " " + units[i];
}

function sevBadge(sev) {
  return h("span", { class: "badge " + sev }, SEV[sev] || sev);
}

function statusBadge(status) {
  const cls = { new: "accent", acked: "warning", resolved: "ok" }[status] || "";
  return h("span", { class: "badge " + cls }, STATUS[status] || status);
}

function emptyState(iconName, text) {
  return h("div", { class: "empty" }, icon(iconName), h("div", null, text));
}

function loading() {
  return h("div", { class: "empty" }, h("span", { class: "spinner" }));
}

function field(label, input, help) {
  return h("div", { class: "field" }, h("label", null, label), input, help ? h("div", { class: "help" }, help) : null);
}

function input(props) {
  return h("input", Object.assign({ type: "text" }, props));
}

function select(options, value, props = {}) {
  return h(
    "select",
    props,
    options.map(([v, t]) => h("option", { value: v, selected: String(v) === String(value) }, t))
  );
}

function checkbox(label, checked, onchange) {
  return h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!checked, onchange: (e) => onchange(e.target.checked) }), label);
}

function checkboxGroup(options, selected, onchange) {
  const set = new Set((selected || []).map(String));
  return h(
    "div",
    { class: "row" },
    options.map(([v, t]) =>
      checkbox(t, set.has(String(v)), (on) => {
        if (on) set.add(String(v));
        else set.delete(String(v));
        onchange([...set]);
      })
    )
  );
}

function copyField(value) {
  const inp = input({ value, readonly: true });
  return h(
    "div",
    { class: "copy-field" },
    inp,
    h("button", {
      class: "btn",
      type: "button",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(value);
        } catch (e) {
          inp.select();
          document.execCommand("copy");
        }
        toast("Скопировано");
      },
    }, icon("copy"))
  );
}

function panel(title, actions, body, flush = false) {
  return h(
    "section",
    { class: "panel" },
    title || actions ? h("div", { class: "panel-head" }, h("h2", null, title), actions ? h("div", { class: "row" }, actions) : null) : null,
    h("div", { class: "panel-body" + (flush ? " flush" : "") }, body)
  );
}

function pageHead(title, subtitle, actions) {
  return h("div", { class: "page-head" }, h("div", null, h("h1", null, title), subtitle ? h("p", null, subtitle) : null), actions ? h("div", { class: "row" }, actions) : null);
}

function roleOptions() {
  return (S.meta.roles || []).map((r) => [r.name, r.title]);
}

function userOptions() {
  return (S.meta.users || []).map((u) => [u.id, u.full_name ? `${u.full_name} (${u.username})` : u.username]);
}

function connectorOf(type) {
  return (S.meta.connectors || []).find((c) => c.type === type) || { title: type, fields: [], category: "monitoring" };
}

const TABS = [
  { id: "overview", title: "Обзор", show: () => true },
  { id: "monitoring", title: "Мониторинг", show: () => can("monitoring.view"), cat: "monitoring" },
  { id: "databases", title: "Базы данных", show: () => can("databases.view"), cat: "database" },
  { id: "onec", title: "1С", show: () => can("onec.view"), cat: "onec" },
  { id: "backups", title: "Бэкапы", show: () => can("backups.view"), cat: "backup" },
  { id: "bugs", title: "Ошибки", show: () => can("bugs.view") || can("bugs.report"), cat: "bug" },
  { id: "journal", title: "Журнал", show: () => VIEW_PERMS.some(can) },
  { sep: true, show: () => ["sources.manage", "rules.manage", "users.manage", "settings.manage"].some(can) },
  { id: "sources", title: "Источники", show: () => can("sources.manage") },
  { id: "rules", title: "Правила", show: () => can("rules.manage") },
  { id: "users", title: "Пользователи", show: () => can("users.manage") },
  { id: "settings", title: "Настройки", show: () => can("settings.manage") },
];

function allowedRoute(route) {
  if (route === "profile") return true;
  if (!S.me || S.me.status !== "active") return false;
  const tab = TABS.find((t) => t.id === route);
  return !!(tab && tab.show());
}

function navigate(route) {
  if (location.hash !== "#/" + route) location.hash = "#/" + route;
  else renderPage();
}

function applyTheme() {
  const theme = store("ow_theme");
  if (theme) document.documentElement.setAttribute("data-theme", theme);
  else document.documentElement.removeAttribute("data-theme");
}

function cycleTheme() {
  const order = ["", "light", "dark"];
  const next = order[(order.indexOf(store("ow_theme")) + 1) % order.length];
  store("ow_theme", next);
  applyTheme();
  toast("Тема: " + ({ "": "как в системе", light: "светлая", dark: "тёмная" }[next]));
}

async function boot() {
  applyTheme();
  window.addEventListener("hashchange", onHash);
  window.addEventListener("pywebviewready", syncBridge);
  document.addEventListener("click", (e) => {
    if (S.dropdown && !S.dropdown.contains(e.target) && !e.target.closest("[data-dropdown]")) closeDropdown();
  });
  try {
    S.meta = await api("/api/meta");
  } catch (e) {
    S.meta = { registration_enabled: true, categories: [], severities: [] };
  }
  if (S.token) {
    try {
      S.me = await api("/api/auth/me");
      S.meta = await api("/api/meta");
    } catch (e) {
      S.token = "";
      store("ow_token", "");
    }
  }
  render();
}

function onHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [route, param] = raw.split("/");
  if (route === "event" && param) {
    if (S.me && S.me.status === "active") openEvent(Number(param));
    history.replaceState(null, "", "#/" + S.route);
    return;
  }
  if (!S.me) return;
  S.route = allowedRoute(route) ? route : S.me.status === "active" ? "overview" : "profile";
  renderPage();
}

function render() {
  const app = document.getElementById("app");
  closeDropdown();
  if (!S.me) {
    stopTimers();
    app.replaceChildren(authView());
    return;
  }
  const raw = location.hash.replace(/^#\/?/, "");
  const [route, param] = raw.split("/");
  S.route = allowedRoute(route) ? route : S.me.status === "active" ? "overview" : "profile";
  app.replaceChildren(topbar(), h("main", { class: "page", id: "page" }));
  renderPage();
  startTimers();
  syncBridge();
  if (route === "event" && param && S.me.status === "active") {
    history.replaceState(null, "", "#/" + S.route);
    openEvent(Number(param));
  }
}

function topbar() {
  const tabs = h("nav", { class: "tabs", id: "tabs" });
  for (const tab of TABS) {
    if (!tab.show()) continue;
    if (S.me.status !== "active") continue;
    if (tab.sep) {
      tabs.append(h("span", { class: "tab-sep" }));
      continue;
    }
    tabs.append(h("a", { class: "tab", href: "#/" + tab.id, "data-tab": tab.id }, tab.title, h("span", { class: "count hidden", "data-count": tab.cat || "" })));
  }
  const initials = (S.me.full_name || S.me.username).split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  return h(
    "header",
    { class: "topbar" },
    h("a", { class: "brand", href: "#/overview" }, h("span", { class: "brand-mark" }, icon("eye")), h("span", null, "OpsWatch")),
    tabs,
    h(
      "div",
      { class: "top-actions" },
      h("button", { class: "icon-btn", title: "Уведомления", "data-dropdown": "1", onclick: toggleNotifications }, icon("bell"), h("span", { class: "badge-dot hidden", id: "bell-count" })),
      h("button", { class: "user-chip", "data-dropdown": "1", title: S.me.full_name || S.me.username, onclick: toggleUserMenu }, h("span", { class: "avatar" }, initials))
    )
  );
}

function highlightTabs() {
  document.querySelectorAll(".tab").forEach((el) => el.classList.toggle("active", el.dataset.tab === S.route));
}

function updateBadges() {
  const bell = document.getElementById("bell-count");
  if (bell) {
    bell.textContent = S.unread > 99 ? "99+" : String(S.unread);
    bell.classList.toggle("hidden", !S.unread);
  }
  document.querySelectorAll("[data-count]").forEach((el) => {
    const cat = el.dataset.count;
    const n = cat && S.open[cat] ? S.open[cat].critical || 0 : 0;
    el.textContent = String(n);
    el.classList.toggle("hidden", !n);
  });
}

function closeDropdown() {
  if (S.dropdown) {
    S.dropdown.remove();
    S.dropdown = null;
  }
}

function toggleUserMenu() {
  if (S.dropdown && S.dropdown.dataset.kind === "user") return closeDropdown();
  closeDropdown();
  const item = (ic, text, fn) => h("a", { class: "menu-item", onclick: () => { closeDropdown(); fn(); } }, icon(ic), text);
  S.dropdown = h(
    "div",
    { class: "dropdown", style: "width:260px" },
    h("div", { class: "dropdown-head" }, h("div", { style: "font-weight:600" }, S.me.full_name || S.me.username), h("div", { class: "muted small" }, (S.me.role && S.me.role.title) || "Без роли", " · ", S.me.username)),
    item("user", "Профиль и уведомления", () => navigate("profile")),
    item("moon", "Сменить тему", cycleTheme),
    bridge() ? item("server", "Сменить сервер", () => bridge().change_server()) : null,
    item("logout", "Выйти", logout)
  );
  S.dropdown.dataset.kind = "user";
  document.body.append(S.dropdown);
}

async function toggleNotifications() {
  if (S.dropdown && S.dropdown.dataset.kind === "notif") return closeDropdown();
  closeDropdown();
  const list = h("div", { class: "dropdown-list" }, loading());
  S.dropdown = h(
    "div",
    { class: "dropdown" },
    h(
      "div",
      { class: "dropdown-head between" },
      h("strong", null, "Уведомления"),
      h("button", {
        class: "btn sm ghost",
        onclick: async () => {
          await guard(() => api("/api/notifications/read", { body: { all: true } }));
          S.unread = 0;
          updateBadges();
          list.querySelectorAll(".notif").forEach((n) => n.classList.remove("unread"));
        },
      }, "Прочитать все")
    ),
    list
  );
  S.dropdown.dataset.kind = "notif";
  document.body.append(S.dropdown);
  const data = await guard(() => api("/api/notifications?limit=40"));
  if (!data) return;
  list.replaceChildren();
  if (!data.items.length) list.append(emptyState("inbox", "Уведомлений пока нет"));
  for (const n of data.items) {
    list.append(
      h(
        "div",
        {
          class: "notif" + (n.is_read ? "" : " unread"),
          onclick: async () => {
            closeDropdown();
            if (!n.is_read) {
              await api("/api/notifications/read", { body: { ids: [n.id] } }).catch(() => {});
              S.unread = Math.max(0, S.unread - 1);
              updateBadges();
            }
            if (n.event_id && S.me.status === "active") openEvent(n.event_id);
          },
        },
        h("span", { class: "dot " + n.severity, style: "margin-top:6px" }),
        h("div", { class: "grow" }, h("div", { class: "title" }, n.title), n.body ? h("div", { class: "muted small", style: "white-space:pre-line;max-height:3.2em;overflow:hidden" }, n.body) : null, h("div", { class: "faint small" }, ago(n.created_at)))
      )
    );
  }
}

function startTimers() {
  stopTimers();
  poll();
  S.pollTimer = setInterval(poll, 15000);
  S.refreshTimer = setInterval(() => {
    if (document.hidden || document.querySelector(".modal-backdrop")) return;
    if (S.refresh) S.refresh();
  }, 30000);
}

function stopTimers() {
  clearInterval(S.pollTimer);
  clearInterval(S.refreshTimer);
  S.pollTimer = S.refreshTimer = null;
}

async function poll() {
  if (!S.token) return;
  let data;
  try {
    data = await api("/api/notifications/poll?after=" + S.lastNotif, { silent401: false });
  } catch (e) {
    return;
  }
  const isNew = S.lastNotif >= 0;
  S.lastNotif = Math.max(data.last_id || 0, S.lastNotif, 0);
  S.unread = data.unread || 0;
  S.open = data.open || {};
  updateBadges();
  if (isNew && data.items.length && data.desktop && !bridge()) {
    for (const n of data.items) browserNotify(n);
  }
}

function browserNotify(n) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const note = new Notification(n.title, { body: n.body || "", tag: "ow-" + n.id, icon: "/favicon.svg" });
    note.onclick = () => {
      window.focus();
      if (n.event_id) openEvent(n.event_id);
      note.close();
    };
  } catch (e) {
    return;
  }
}

function syncBridge() {
  const b = bridge();
  if (!b) return;
  try {
    if (S.me && S.token) b.set_session(location.origin, S.token, !!S.me.notify_desktop, S.me.full_name || S.me.username);
    else b.set_session(location.origin, "", false, "");
  } catch (e) {
    return;
  }
}

function logoutLocal() {
  S.token = "";
  S.me = null;
  S.lastNotif = -1;
  store("ow_token", "");
  syncBridge();
  render();
}

async function logout() {
  await api("/api/auth/logout", { body: {} }).catch(() => {});
  logoutLocal();
}

function authView() {
  let mode = "login";
  const box = h("div");
  const notice = h("div");
  const registration = S.meta && S.meta.registration_enabled;

  function draw() {
    box.replaceChildren(mode === "login" ? loginForm() : registerForm());
    seg.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  }

  function loginForm() {
    const u = input({ autocomplete: "username", placeholder: "Логин", required: true, autofocus: true });
    const p = input({ type: "password", autocomplete: "current-password", placeholder: "Пароль", required: true });
    const btn = h("button", { class: "btn primary block", type: "submit" }, "Войти");
    return h(
      "form",
      {
        onsubmit: async (e) => {
          e.preventDefault();
          btn.disabled = true;
          try {
            const r = await api("/api/auth/login", { body: { username: u.value.trim(), password: p.value } });
            S.token = r.token;
            store("ow_token", r.token);
            S.me = r.user;
            S.meta = await api("/api/meta");
            render();
          } catch (err) {
            notice.replaceChildren(h("div", { class: "notice critical" }, icon("alert"), h("div", null, err.message)));
          } finally {
            btn.disabled = false;
          }
        },
      },
      field("Логин", u),
      field("Пароль", p),
      btn
    );
  }

  function registerForm() {
    const fn = input({ placeholder: "Иван Петров", autocomplete: "name" });
    const u = input({ placeholder: "ivan.petrov", autocomplete: "username", required: true });
    const p = input({ type: "password", autocomplete: "new-password", required: true });
    const p2 = input({ type: "password", autocomplete: "new-password", required: true });
    const tg = input({ placeholder: "@username" });
    const btn = h("button", { class: "btn primary block", type: "submit" }, "Отправить заявку");
    return h(
      "form",
      {
        onsubmit: async (e) => {
          e.preventDefault();
          if (p.value !== p2.value) {
            notice.replaceChildren(h("div", { class: "notice critical" }, icon("alert"), h("div", null, "Пароли не совпадают")));
            return;
          }
          btn.disabled = true;
          try {
            const r = await api("/api/auth/register", { body: { full_name: fn.value, username: u.value.trim(), password: p.value, telegram_username: tg.value } });
            mode = "login";
            draw();
            notice.replaceChildren(h("div", { class: "notice" }, icon("info"), h("div", null, r.message, " Вы уже можете войти и привязать Telegram в профиле.")));
          } catch (err) {
            notice.replaceChildren(h("div", { class: "notice critical" }, icon("alert"), h("div", null, err.message)));
          } finally {
            btn.disabled = false;
          }
        },
      },
      field("Имя и фамилия", fn),
      field("Логин", u, "Латиница, цифры, точка, дефис"),
      h("div", { class: "grid-2", style: "gap:10px" }, field("Пароль", p), field("Повторите пароль", p2)),
      field("Telegram (необязательно)", tg),
      btn
    );
  }

  const seg = h(
    "div",
    { class: "segmented" },
    h("button", { type: "button", "data-mode": "login", onclick: () => { mode = "login"; notice.replaceChildren(); draw(); } }, "Вход"),
    h("button", { type: "button", "data-mode": "register", disabled: !registration, onclick: () => { mode = "register"; notice.replaceChildren(); draw(); } }, "Регистрация")
  );
  draw();
  return h(
    "div",
    { class: "auth-wrap" },
    h(
      "div",
      { class: "auth-card" },
      h("div", { class: "auth-brand" }, h("span", { class: "brand-mark" }, icon("eye")), h("h1", null, "OpsWatch"), h("div", { class: "muted" }, "Мониторинг, резервные копии и уведомления для системных администраторов и 1С")),
      h("div", { class: "panel" }, h("div", { class: "panel-body" }, seg, notice, box)),
      h(
        "div",
        { class: "row muted small", style: "justify-content:center;margin-top:14px" },
        h("span", null, "Сервер: " + location.host),
        h("span", null, "·"),
        h("span", null, "v" + ((S.meta && S.meta.version) || "")),
        bridge() ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); bridge().change_server(); } }, "Сменить сервер") : null
      )
    )
  );
}

async function renderPage() {
  const page = document.getElementById("page");
  if (!page) return;
  closeDropdown();
  highlightTabs();
  S.refresh = null;
  const seq = ++S.seq;
  page.replaceChildren(loading());
  const fn = PAGES[S.route] || PAGES.overview;
  try {
    const content = h("div");
    await fn(content, seq);
    if (seq !== S.seq) return;
    page.replaceChildren(content);
  } catch (e) {
    if (seq !== S.seq) return;
    page.replaceChildren(h("div", { class: "notice critical" }, icon("alert"), h("div", null, e.message)));
  }
}

function eventsTable(items, opts = {}) {
  if (!items.length) return emptyState("check", opts.empty || "Событий нет");
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "table" },
      h("thead", null, h("tr", null, h("th", null, "Важность"), h("th", null, "Событие"), opts.category === false ? null : h("th", null, "Категория"), h("th", null, "Статус"), h("th", { class: "right" }, "Когда"))),
      h(
        "tbody",
        null,
        items.map((e) =>
          h(
            "tr",
            { class: "clickable", onclick: () => openEvent(e.id) },
            h("td", null, sevBadge(e.severity)),
            h("td", { class: "title-cell" }, e.title, h("div", { class: "sub" }, [e.source_name, e.message].filter(Boolean).join(" · ")), e.attachments && e.attachments.length ? h("div", { class: "faint small" }, "📎 " + e.attachments.length) : null),
            opts.category === false ? null : h("td", { class: "nowrap muted" }, CAT[e.category] || e.category),
            h("td", null, statusBadge(e.status)),
            h("td", { class: "right nowrap muted small" }, ago(e.last_seen_at), e.count > 1 ? h("div", null, "×" + e.count) : null)
          )
        )
      )
    )
  );
}

function eventsPanel({ category = "", title = "События", allowCategoryFilter = false, defaultStatus = "open" }) {
  const st = { status: defaultStatus, severity: "", q: "", offset: 0, limit: 50, category };
  const body = h("div", null, loading());
  const counter = h("span", { class: "muted small" });
  const statusChips = h("div", { class: "chips" });
  const sevChips = h("div", { class: "chips" });
  const catChips = h("div", { class: "chips" });

  function chips(container, options, key) {
    container.replaceChildren(
      ...options.map(([v, t]) =>
        h("button", { class: "chip" + (st[key] === v ? " active" : ""), onclick: () => { st[key] = v; st.offset = 0; drawChips(); load(); } }, t)
      )
    );
  }

  function drawChips() {
    chips(statusChips, [["open", "Открытые"], ["", "Все"], ["resolved", "Решённые"]], "status");
    chips(sevChips, [["", "Любая важность"], ["critical", "Критично"], ["warning", "Предупреждения"], ["info", "Информация"]], "severity");
    if (allowCategoryFilter) {
      const cats = (S.meta.categories || []).filter((c) => can({ monitoring: "monitoring.view", database: "databases.view", onec: "onec.view", backup: "backups.view", bug: "bugs.view", system: "system.view" }[c.id]));
      chips(catChips, [["", "Все категории"], ...cats.map((c) => [c.id, c.title])], "category");
    }
  }

  let timer;
  const search = input({
    type: "search",
    class: "search",
    placeholder: "Поиск…",
    oninput: (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { st.q = e.target.value; st.offset = 0; load(); }, 300);
    },
  });

  async function load() {
    const params = new URLSearchParams({ limit: st.limit, offset: st.offset });
    if (st.category) params.set("category", st.category);
    if (st.status) params.set("status", st.status);
    if (st.severity) params.set("severity", st.severity);
    if (st.q) params.set("q", st.q);
    const data = await guard(() => api("/api/events?" + params));
    if (!data) return;
    counter.textContent = "Всего: " + data.total;
    const pager =
      data.total > st.limit
        ? h(
            "div",
            { class: "pager" },
            h("span", { class: "muted small" }, `${st.offset + 1}–${Math.min(st.offset + st.limit, data.total)} из ${data.total}`),
            h(
              "div",
              { class: "row" },
              h("button", { class: "btn sm", disabled: st.offset === 0, onclick: () => { st.offset = Math.max(0, st.offset - st.limit); load(); } }, "Назад"),
              h("button", { class: "btn sm", disabled: st.offset + st.limit >= data.total, onclick: () => { st.offset += st.limit; load(); } }, "Вперёд")
            )
          )
        : null;
    fill(body, eventsTable(data.items, { category: !category, empty: st.status === "open" ? "Открытых событий нет — всё спокойно" : "Событий не найдено" }), pager);
  }

  drawChips();
  load();
  const el = h(
    "section",
    { class: "panel" },
    h("div", { class: "panel-head" }, h("div", { class: "row" }, h("h2", null, title), counter), h("div", { class: "row" }, search)),
    h("div", { class: "panel-body", style: "padding-bottom:0;display:flex;flex-direction:column;gap:8px" }, h("div", { class: "row" }, statusChips, sevChips), allowCategoryFilter ? catChips : null),
    h("div", { class: "panel-body flush", style: "margin-top:10px;border-top:1px solid var(--border)" }, body)
  );
  return { el, load };
}

function metricBadges(source) {
  const m = source.metrics || {};
  const items = [];
  if (m.size_human) items.push(m.size_human);
  if (m.version) items.push(m.version);
  if (m.latency_ms !== undefined) items.push(m.latency_ms + " мс");
  if (m.status) items.push("HTTP " + m.status);
  if (m.problems !== undefined) items.push("Проблем: " + m.problems);
  if (m.in_use !== undefined) items.push(m.in_use ? "Есть пользователи" : "Пользователей нет");
  if (m.http) items.push(m.http);
  if (m.log_matches) items.push("Ошибок в журнале: " + m.log_matches);
  if (m.received !== undefined) items.push("Получено: " + m.received);
  return items.map((t) => h("span", { class: "badge outline" }, t));
}

function sourceCard(source, reload) {
  const status = source.status || "unknown";
  return h(
    "div",
    { class: "source-card" },
    h("div", { class: "between" }, h("div", { class: "name" }, h("span", { class: "dot " + status }), source.name), source.enabled ? null : h("span", { class: "badge" }, "Выключен")),
    h("div", { class: "muted small" }, source.type_title, " · ", SOURCE_STATUS[status] || status),
    h("div", { class: "metrics" }, metricBadges(source)),
    source.last_error ? h("div", { class: "error-text" }, source.last_error.slice(0, 220)) : null,
    h(
      "div",
      { class: "between" },
      h("span", { class: "faint small" }, source.last_check_at ? "Проверено " + ago(source.last_check_at) : source.passive ? "Принимает webhook" : "Ещё не проверялся"),
      can("sources.manage") && !source.passive
        ? h("button", {
            class: "btn sm ghost",
            onclick: async (e) => {
              e.target.disabled = true;
              const r = await guard(() => api(`/api/sources/${source.id}/poll`, { body: {} }));
              if (r) toast(r.ok ? "Проверено: " + (r.message || "OK") : "Ошибка: " + r.message, r.ok ? "" : "error");
              reload();
            },
          }, icon("refresh"), "Проверить")
        : null
    )
  );
}

async function pageOverview(root) {
  const d = await api("/api/dashboard");
  let critical = 0;
  let warning = 0;
  let sourcesTotal = 0;
  let sourcesOk = 0;
  for (const [, c] of Object.entries(d.categories)) {
    critical += c.open.critical || 0;
    warning += c.open.warning || 0;
    sourcesTotal += c.sources.total;
    sourcesOk += c.sources.ok;
  }
  const backupsOk = d.backups.filter((b) => b.last_status === "ok").length;
  const backupsFailed = d.backups.filter((b) => b.last_status === "failed").length;
  append(root, pageHead("Обзор", "Состояние инфраструктуры и последние события", h("button", { class: "btn", onclick: renderPage }, icon("refresh"), "Обновить")));
  if (can("settings.manage") && d.bot.status !== "running") {
    root.append(
      h("div", { class: "notice warning" }, icon("alert"), h("div", null, d.bot.status === "error" ? "Telegram-бот не запущен: " + d.bot.error : "Telegram-бот не настроен — уведомления приходят только в программу.", " ", h("a", { href: "#/settings" }, "Открыть настройки")))
    );
  }
  if (S.me.username === "admin1" && S.me.is_superuser) {
    root.append(h("div", { class: "notice" }, icon("shield"), h("div", null, "Если вы ещё не меняли пароль администратора по умолчанию, сделайте это в ", h("a", { href: "#/profile" }, "профиле"), ".")));
  }
  const kpi = (label, value, cls) => h("div", { class: "kpi" }, h("div", { class: "label" }, label), h("div", { class: "value " + (cls || "") }, value));
  root.append(
    h(
      "div",
      { class: "kpis" },
      kpi("Критичных открыто", critical, critical ? "critical" : "ok"),
      kpi("Предупреждений", warning, warning ? "warning" : ""),
      kpi("Источники в норме", sourcesTotal ? `${sourcesOk} / ${sourcesTotal}` : "—", sourcesTotal && sourcesOk === sourcesTotal ? "ok" : sourcesTotal ? "warning" : ""),
      can("backups.view") ? kpi("Бэкапы", d.backups.length ? `${backupsOk} / ${d.backups.length}` : "—", backupsFailed ? "critical" : d.backups.length ? "ok" : "") : null
    )
  );
  const grid = h("div", { class: "cat-grid" });
  for (const [cat, c] of Object.entries(d.categories)) {
    const badges = ["critical", "warning", "info"].filter((s) => c.open[s]).map((s) => h("span", { class: "badge " + s }, `${SEV_SHORT[s]}: ${c.open[s]}`));
    grid.append(
      h(
        "div",
        { class: "cat-card", onclick: () => navigate(CAT_TAB[cat] || "journal") },
        h("div", { class: "head" }, icon(CAT_ICON[cat]), CAT[cat]),
        h("div", { class: "row" }, badges.length ? badges : h("span", { class: "badge ok" }, "Всё спокойно")),
        c.sources.total ? h("div", { class: "muted small", style: "margin-top:8px" }, `Источников: ${c.sources.total}`, c.sources.error ? h("span", { style: "color:var(--critical)" }, ` · недоступно: ${c.sources.error}`) : null) : null
      )
    );
  }
  root.append(grid);
  if (d.failing_sources.length) {
    root.append(
      panel(
        "Недоступные источники",
        null,
        h("div", { class: "stack" }, d.failing_sources.map((s) => h("div", { class: "row" }, h("span", { class: "dot error" }), h("strong", null, s.name), h("span", { class: "muted small" }, s.error))))
      )
    );
  }
  root.append(panel("Последние события", h("a", { href: "#/journal", class: "small" }, "Весь журнал →"), eventsTable(d.recent, { empty: "Событий пока нет" }), true));
  S.refresh = renderPage;
}

function categoryPage(cat, title, subtitle) {
  return async (root) => {
    const sources = await api("/api/sources?category=" + cat);
    const actions = can("sources.manage") ? h("button", { class: "btn", onclick: () => sourceForm(null, cat) }, icon("plus"), "Источник") : null;
    append(root, pageHead(title, subtitle, actions));
    const grid = h("div", { class: "sources-grid" });
    const drawSources = (items) => {
      grid.replaceChildren(...items.map((s) => sourceCard(s, reloadSources)));
      grid.classList.toggle("hidden", !items.length);
    };
    const reloadSources = async () => {
      const data = await api("/api/sources?category=" + cat).catch(() => null);
      if (data) drawSources(data.items);
    };
    drawSources(sources.items);
    root.append(grid);
    if (!sources.items.length) {
      root.append(h("div", { class: "notice" }, icon("info"), h("div", null, "Источники этой категории ещё не подключены.", can("sources.manage") ? " Добавьте их на вкладке «Источники»." : "")));
    }
    const events = eventsPanel({ category: cat, title: "События" });
    root.append(events.el);
    S.refresh = () => {
      reloadSources();
      events.load();
    };
  };
}

async function pageJournal(root) {
  append(root, pageHead("Журнал событий", "Все события, доступные вашей роли"));
  const events = eventsPanel({ title: "События", allowCategoryFilter: true, defaultStatus: "" });
  root.append(events.el);
  S.refresh = events.load;
}

async function pageBugs(root) {
  append(root, pageHead("Ошибки и баг-репорты", "Сообщения об ошибках от пользователей и систем"));
  if (can("bugs.report")) {
    const title = input({ placeholder: "Кратко: что случилось" });
    const text = h("textarea", { placeholder: "Подробно: что делали, что ожидали, что получили. Можно указать базу, документ, время." });
    const sev = select([["info", "Не срочно"], ["warning", "Мешает работе"], ["critical", "Работа остановлена"]], "warning");
    const files = h("input", { type: "file", multiple: true, accept: "image/*,.txt,.log,.pdf,.zip,.7z,.json,.xml,.csv,.docx,.xlsx,.mxl,.epf,.erf" });
    const btn = h("button", { class: "btn primary" }, icon("send"), "Отправить");
    btn.onclick = async () => {
      if (!title.value.trim() && !text.value.trim()) return toast("Опишите проблему", "error");
      const form = new FormData();
      form.append("title", title.value);
      form.append("text", text.value);
      form.append("severity", sev.value);
      for (const f of files.files) form.append("files", f);
      btn.disabled = true;
      const r = await guard(() => api("/api/bugs", { body: form }), "Баг-репорт отправлен");
      btn.disabled = false;
      if (r) {
        title.value = "";
        text.value = "";
        files.value = "";
        if (S.refresh) S.refresh();
      }
    };
    const hint = S.meta.bot_username ? h("span", { class: "muted small" }, "Или отправьте боту ", h("a", { href: `https://t.me/${S.meta.bot_username}`, target: "_blank" }, "@" + S.meta.bot_username), " команду /bug со скриншотом") : null;
    root.append(
      panel(
        "Сообщить об ошибке",
        null,
        h("div", null, h("div", { class: "grid-2" }, field("Заголовок", title), field("Срочность", sev)), field("Описание", text), field("Скриншоты и файлы", files, "До 5 файлов, не больше 20 МБ каждый"), h("div", { class: "between" }, hint || h("span"), btn))
      )
    );
  }
  if (can("bugs.view")) {
    const events = eventsPanel({ category: "bug", title: "Баг-репорты" });
    root.append(events.el);
    S.refresh = events.load;
  } else {
    const box = h("div", null, loading());
    root.append(panel("Мои обращения", null, box, true));
    const load = async () => {
      const data = await guard(() => api("/api/bugs/mine"));
      if (data) box.replaceChildren(eventsTable(data.items, { category: false, empty: "Вы ещё не отправляли баг-репорты" }));
    };
    load();
    S.refresh = load;
  }
}

async function openEvent(id) {
  let e;
  try {
    e = await api("/api/events/" + id);
  } catch (err) {
    toast(err.message, "error");
    return;
  }
  const note = h("textarea", { placeholder: "Комментарий к решению (необязательно)", style: "min-height:60px" });
  const manage = can("events.manage") && e.status !== "resolved";
  const kv = (k, v) => (v === null || v === undefined || v === "" ? null : [h("div", { class: "k" }, k), h("div", null, v)]);
  const attachments = (e.attachments || []).map((a) => {
    const url = a.url + "?access_token=" + encodeURIComponent(S.token);
    const isImage = (a.content_type || "").startsWith("image/");
    return h("div", null, h("a", { href: url, target: "_blank" }, "📎 " + a.filename), h("span", { class: "muted small" }, " · " + humanSize(a.size)), isImage ? h("img", { class: "attachment-preview", src: url, alt: a.filename }) : null);
  });
  const details = Object.entries(e.details || {});
  const body = h(
    "div",
    { class: "stack" },
    h("div", { class: "row" }, sevBadge(e.severity), statusBadge(e.status), h("span", { class: "badge outline" }, CAT[e.category] || e.category), e.escalation_level ? h("span", { class: "badge critical" }, "Эскалация: " + e.escalation_level) : null),
    h(
      "div",
      { class: "kv" },
      kv("Источник", e.source_name),
      kv("Тип", h("code", null, e.type)),
      kv("Впервые", fmtDate(e.created_at, true)),
      kv("Последний раз", fmtDate(e.last_seen_at, true)),
      kv("Повторов", e.count > 1 ? String(e.count) : null),
      kv("Отправитель", e.reporter),
      kv("Принял", e.acked_by ? `${e.acked_by}, ${fmtDate(e.acked_at)}` : null),
      kv("Решил", e.resolved_at ? `${e.resolved_by || "автоматически"}, ${fmtDate(e.resolved_at)}` : null)
    ),
    e.message ? h("pre", null, e.message) : null,
    e.resolution ? h("div", { class: "notice" }, icon("check"), h("div", null, e.resolution)) : null,
    details.length ? h("details", null, h("summary", { class: "muted small", style: "cursor:pointer" }, "Технические детали"), h("div", { class: "kv", style: "margin-top:8px" }, details.map(([k, v]) => kv(k, typeof v === "object" ? JSON.stringify(v) : String(v))))) : null,
    attachments.length ? h("div", { class: "stack" }, h("div", { class: "label" }, "Вложения"), attachments) : null,
    manage ? field("Комментарий", note) : null
  );
  const actions = [];
  if (manage && e.status === "new") {
    actions.push(h("button", { class: "btn", onclick: async () => { const r = await guard(() => api(`/api/events/${id}/ack`, { body: {} }), "Принято в работу"); if (r) { m.close(); openEvent(id); if (S.refresh) S.refresh(); } } }, icon("check"), "Принял"));
  }
  if (manage) {
    actions.push(h("button", { class: "btn primary", onclick: async () => { const r = await guard(() => api(`/api/events/${id}/resolve`, { body: { note: note.value } }), "Событие закрыто"); if (r) { m.close(); if (S.refresh) S.refresh(); } } }, icon("check"), "Решено"));
  }
  const m = modal({ title: e.title, subtitle: "#" + e.id, body, foot: actions, wide: true });
}

async function pageBackups(root) {
  const manage = can("backups.manage");
  append(root, pageHead("Резервное копирование", "Задания по расписанию, проверка архивов и отправка администраторам", manage ? h("button", { class: "btn primary", onclick: () => jobForm(null) }, icon("plus"), "Новое задание") : null));
  const jobsBox = h("div", null, loading());
  const recordsBox = h("div", null, loading());
  root.append(panel("Задания", null, jobsBox, true));
  root.append(panel("История", null, recordsBox, true));
  let jobs = [];

  async function load() {
    const [j, r] = await Promise.all([api("/api/backups/jobs"), api("/api/backups/records?limit=60")]);
    jobs = j.items;
    if (!jobs.length) {
      jobsBox.replaceChildren(emptyState("archive", manage ? "Заданий пока нет. Создайте первое задание резервного копирования." : "Заданий пока нет"));
    } else {
      jobsBox.replaceChildren(
        h(
          "div",
          { class: "table-wrap" },
          h(
            "table",
            { class: "table" },
            h("thead", null, h("tr", null, h("th", null, "Задание"), h("th", null, "Расписание"), h("th", null, "Последний запуск"), h("th", null, "Хранить"), manage ? h("th", { class: "right" }, "") : null)),
            h(
              "tbody",
              null,
              jobs.map((job) => {
                const st = job.last_status;
                const cls = { ok: "ok", failed: "critical", running: "accent" }[st] || "";
                return h(
                  "tr",
                  null,
                  h("td", { class: "title-cell" }, job.name, h("div", { class: "sub" }, job.source_name || "источник удалён", job.encrypt ? " · 🔒 AES-256" : "", job.enabled ? "" : " · выключено")),
                  h("td", null, h("code", null, job.schedule), h("div", { class: "muted small" }, job.next_run ? "След.: " + fmtDate(job.next_run) : "")),
                  h("td", null, h("span", { class: "badge " + cls }, st === "running" ? h("span", { class: "spinner", style: "width:10px;height:10px" }) : null, BACKUP_STATUS[st] || st), h("div", { class: "muted small" }, job.last_run_at ? ago(job.last_run_at) : ""), job.last_error ? h("div", { class: "small", style: "color:var(--critical);max-width:340px" }, job.last_error.slice(0, 200)) : null),
                  h("td", { class: "muted" }, job.keep_last ? job.keep_last + " шт." : "все"),
                  manage
                    ? h(
                        "td",
                        { class: "right nowrap" },
                        h("button", { class: "btn sm", disabled: job.running, onclick: async () => { const r = await guard(() => api(`/api/backups/jobs/${job.id}/run`, { body: {} }), "Бэкап запущен"); if (r) setTimeout(load, 800); } }, icon("play"), "Запустить"),
                        " ",
                        h("button", { class: "btn sm ghost", title: "Изменить", onclick: () => jobForm(job) }, icon("edit")),
                        h("button", { class: "btn sm ghost danger", title: "Удалить", onclick: () => confirmDialog(`Удалить задание «${job.name}»? Файлы бэкапов останутся на диске.`, async () => { await guard(() => api(`/api/backups/jobs/${job.id}`, { method: "DELETE" }), "Задание удалено"); load(); }) }, icon("trash"))
                      )
                    : null
                );
              })
            )
          )
        )
      );
    }
    const names = Object.fromEntries(jobs.map((x) => [x.id, x.name]));
    if (!r.items.length) {
      recordsBox.replaceChildren(emptyState("inbox", "Резервных копий ещё не было"));
    } else {
      recordsBox.replaceChildren(
        h(
          "div",
          { class: "table-wrap" },
          h(
            "table",
            { class: "table" },
            h("thead", null, h("tr", null, h("th", null, "Дата"), h("th", null, "Задание"), h("th", null, "Размер"), h("th", null, "Проверка"), h("th", null, "Доставка"), h("th", null, "Статус"), h("th", { class: "right" }, ""))),
            h(
              "tbody",
              null,
              r.items.map((rec) => {
                const tg = (rec.delivery || {}).telegram;
                const delivery = [];
                if (tg) delivery.push(tg.mode === "no_bot" ? "Telegram: бот не настроен" : `Telegram: ${tg.sent}${tg.failed ? ", ошибок " + tg.failed : ""}${tg.mode === "parts" ? " (частями)" : tg.mode === "link" ? " (ссылка)" : ""}`);
                if (rec.delivery && rec.delivery.folder) delivery.push(rec.delivery.folder.error ? "Папка: ошибка" : "Папка ✓");
                if (rec.delivery && rec.delivery.s3) delivery.push(rec.delivery.s3.error ? "S3: ошибка" : "S3 ✓");
                const cls = { ok: "ok", failed: "critical", running: "accent" }[rec.status] || "";
                return h(
                  "tr",
                  null,
                  h("td", { class: "nowrap" }, fmtDate(rec.started_at), rec.manual ? h("div", { class: "faint small" }, "вручную") : null),
                  h("td", null, names[rec.job_id] || "#" + rec.job_id, rec.file_name ? h("div", { class: "faint small mono" }, rec.file_name) : null),
                  h("td", { class: "nowrap" }, rec.size ? humanSize(rec.size) : "—"),
                  h("td", null, rec.verified ? h("span", { class: "badge ok" }, "Целостность OK") : h("span", { class: "muted" }, "—")),
                  h("td", { class: "muted small" }, delivery.join(" · ") || "—"),
                  h("td", null, h("span", { class: "badge " + cls }, BACKUP_STATUS[rec.status] || rec.status), rec.deleted ? h("div", { class: "faint small" }, "удалён ротацией") : null, rec.error ? h("div", { class: "small", style: "color:var(--critical);max-width:320px" }, rec.error.slice(0, 240)) : null),
                  h("td", { class: "right" }, manage && rec.available ? h("a", { class: "btn sm ghost", href: `/api/backups/records/${rec.id}/download?access_token=${encodeURIComponent(S.token)}` }, icon("download")) : null)
                );
              })
            )
          )
        )
      );
    }
    if (jobs.some((x) => x.running)) setTimeout(() => { if (S.route === "backups") load(); }, 4000);
  }
  await load();
  S.refresh = load;
}

function jobForm(job) {
  const backupTypes = new Set((S.meta.connectors || []).filter((c) => c.supports_backup).map((c) => c.type));
  const sources = (S.meta.sources || []).filter((s) => backupTypes.has(s.type));
  if (!sources.length) {
    toast("Сначала добавьте источник: MySQL, PostgreSQL, MS SQL или базу 1С", "error");
    return;
  }
  const d = job
    ? JSON.parse(JSON.stringify(job))
    : { name: "", source_id: sources[0].id, schedule: "0 2 * * *", enabled: true, keep_last: 7, encrypt: true, options: {}, destinations: { telegram: true, split: true } };
  d.options = d.options || {};
  d.destinations = Object.assign({ telegram: true, split: true }, d.destinations || {});
  const password = input({ type: "password", placeholder: job && job.has_password ? "•••••••• (не менять)" : "Пароль архива", autocomplete: "new-password" });
  const sched = input({ value: d.schedule, class: "mono", oninput: (e) => (d.schedule = e.target.value) });
  const optsBox = h("div");
  const presets = [["0 2 * * *", "Ежедневно 02:00"], ["0 */6 * * *", "Каждые 6 ч"], ["0 22 * * 1-5", "Будни 22:00"], ["0 3 * * 0", "Вс 03:00"]];

  function drawOptions() {
    const source = sources.find((s) => String(s.id) === String(d.source_id));
    const type = source ? source.type : "";
    const opt = (key, label, help, placeholder) => field(label, input({ value: d.options[key] || "", placeholder: placeholder || "", oninput: (e) => (d.options[key] = e.target.value) }), help);
    const items = [];
    if (type === "mysql") items.push(opt("tool_path", "Путь к mysqldump", "Пусто — из общих настроек", "C:\\Program Files\\MySQL\\bin\\mysqldump.exe"));
    if (type === "postgresql") items.push(opt("tool_path", "Путь к pg_dump", "Пусто — из общих настроек", "C:\\Program Files\\PostgreSQL\\16\\bin\\pg_dump.exe"));
    if (type === "mssql" || type === "onec_server") {
      items.push(opt("server_dir", "Каталог для .bak на сервере SQL (для MS SQL)", "Путь, доступный службе SQL Server", "D:\\Backup"));
      items.push(opt("local_dir", "Тот же каталог, доступный OpsWatch", "Например, сетевой путь. Пусто — совпадает с каталогом на сервере", "\\\\sql01\\Backup"));
    }
    if (type === "onec_server") items.push(opt("tool_path", "Путь к pg_dump (для PostgreSQL)", "Пусто — из общих настроек"));
    if (type === "onec_file") {
      items.push(checkbox("Использовать теневое копирование (VSS), если база занята", d.options.use_vss, (v) => (d.options.use_vss = v)));
      items.push(checkbox("Добавить журнал регистрации в архив", d.options.include_log, (v) => (d.options.include_log = v)));
      items.push(h("div", { class: "help small muted" }, "Без VSS бэкап выполняется только когда в базе нет пользователей. VSS требует запуска от имени администратора."));
    }
    optsBox.replaceChildren(...items);
  }

  const body = h(
    "div",
    null,
    h("div", { class: "grid-2" }, field("Название", input({ value: d.name, placeholder: "Бухгалтерия — ночной бэкап", oninput: (e) => (d.name = e.target.value) })), field("Источник", select(sources.map((s) => [s.id, `${s.name} (${connectorOf(s.type).title})`]), d.source_id, { onchange: (e) => { d.source_id = Number(e.target.value); drawOptions(); } }))),
    field("Расписание (cron: минута час день месяц день_недели)", sched),
    h("div", { class: "chips", style: "margin:-4px 0 12px" }, presets.map(([v, t]) => h("button", { class: "chip", type: "button", onclick: () => { sched.value = v; d.schedule = v; } }, t))),
    h("div", { class: "grid-2" }, field("Сколько копий хранить локально", input({ type: "number", min: 0, value: d.keep_last, oninput: (e) => (d.keep_last = Number(e.target.value)) }), "0 — хранить все"), field("Пароль шифрования (AES-256)", password)),
    h("div", { class: "row", style: "margin-bottom:12px" }, checkbox("Шифровать архив", d.encrypt, (v) => (d.encrypt = v)), checkbox("Задание включено", d.enabled, (v) => (d.enabled = v))),
    h("fieldset", null, h("legend", null, "Параметры источника"), optsBox),
    h(
      "fieldset",
      null,
      h("legend", null, "Доставка"),
      h("div", { class: "row" }, checkbox("Отправлять в Telegram", d.destinations.telegram, (v) => (d.destinations.telegram = v)), checkbox("Делить большие файлы на части", d.destinations.split, (v) => (d.destinations.split = v)), checkbox("Выгружать в S3", d.destinations.s3, (v) => (d.destinations.s3 = v))),
      field("Кому отправлять (роли)", checkboxGroup(roleOptions(), d.destinations.telegram_roles, (v) => (d.destinations.telegram_roles = v)), "Если не выбрано — всем, у кого есть право управления бэкапами"),
      field("Кому отправлять (пользователи)", checkboxGroup(userOptions(), d.destinations.telegram_users, (v) => (d.destinations.telegram_users = v.map(Number)))),
      field("Копировать в папку (сетевую)", input({ value: d.destinations.folder || "", placeholder: "\\\\nas\\backup\\opswatch", oninput: (e) => (d.destinations.folder = e.target.value) }))
    )
  );
  drawOptions();
  const m = modal({
    title: job ? "Задание резервного копирования" : "Новое задание",
    body,
    wide: true,
    foot: [
      h("button", { class: "btn", onclick: () => m.close() }, "Отмена"),
      h("button", {
        class: "btn primary",
        onclick: async () => {
          const payload = Object.assign({}, d, { password: password.value });
          const r = await guard(() => api(job ? `/api/backups/jobs/${job.id}` : "/api/backups/jobs", { method: job ? "PUT" : "POST", body: payload }), "Сохранено");
          if (r) {
            m.close();
            renderPage();
          }
        },
      }, "Сохранить"),
    ],
  });
}

async function pageSources(root) {
  append(root, pageHead("Источники", "Базы данных, 1С, системы мониторинга и webhook-и", h("button", { class: "btn primary", onclick: () => sourceForm(null) }, icon("plus"), "Добавить источник")));
  const data = await api("/api/sources");
  if (!data.items.length) {
    root.append(panel(null, null, emptyState("server", "Источников пока нет. Подключите базу данных, 1С или систему мониторинга.")));
    return;
  }
  root.append(
    panel(
      null,
      null,
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "table" },
          h("thead", null, h("tr", null, h("th", null, "Источник"), h("th", null, "Категория"), h("th", null, "Статус"), h("th", null, "Опрос"), h("th", null, "Доступ"), h("th", { class: "right" }, ""))),
          h(
            "tbody",
            null,
            data.items.map((s) =>
              h(
                "tr",
                null,
                h("td", { class: "title-cell" }, s.name, h("div", { class: "sub" }, s.type_title)),
                h("td", { class: "muted" }, CAT[s.category] || s.category),
                h("td", null, h("div", { class: "row" }, h("span", { class: "dot " + s.status }), SOURCE_STATUS[s.status] || s.status), s.last_error ? h("div", { class: "small", style: "color:var(--critical);max-width:300px" }, s.last_error.slice(0, 160)) : null),
                h("td", { class: "muted small nowrap" }, s.passive ? "webhook" : `каждые ${s.poll_interval} с`, s.last_check_at ? h("div", null, ago(s.last_check_at)) : null),
                h("td", { class: "muted small" }, s.visible_roles.length ? s.visible_roles.map((r) => (S.meta.roles.find((x) => x.name === r) || { title: r }).title).join(", ") : "Все по правам"),
                h(
                  "td",
                  { class: "right nowrap" },
                  !s.passive ? h("button", { class: "btn sm ghost", title: "Проверить сейчас", onclick: async () => { const r = await guard(() => api(`/api/sources/${s.id}/poll`, { body: {} })); if (r) toast(r.ok ? "OK: " + r.message : "Ошибка: " + r.message, r.ok ? "" : "error"); renderPage(); } }, icon("refresh")) : null,
                  h("button", { class: "btn sm ghost", title: "Изменить", onclick: () => sourceForm(s) }, icon("edit")),
                  h("button", { class: "btn sm ghost danger", title: "Удалить", onclick: () => confirmDialog(`Удалить источник «${s.name}»? История событий сохранится.`, async () => { await guard(() => api(`/api/sources/${s.id}`, { method: "DELETE" }), "Источник удалён"); S.meta = await api("/api/meta"); renderPage(); }) }, icon("trash"))
                )
              )
            )
          )
        )
      ),
      true
    )
  );
  S.refresh = renderPage;
}

function sourceForm(existing, presetCategory) {
  if (existing) return sourceEditor(existing.type, existing);
  const connectors = (S.meta.connectors || []).filter((c) => !presetCategory || c.category === presetCategory || (presetCategory === "monitoring" && c.passive));
  const m = modal({
    title: "Новый источник",
    subtitle: "Выберите тип подключения",
    wide: true,
    body: h(
      "div",
      { class: "cat-grid", style: "margin:0" },
      connectors.map((c) =>
        h(
          "div",
          { class: "cat-card", onclick: () => { m.close(); sourceEditor(c.type, null); } },
          h("div", { class: "head" }, icon(CAT_ICON[c.category] || "server"), c.title),
          h("div", { class: "muted small" }, c.description)
        )
      )
    ),
  });
}

function renderInput(spec, cfg) {
  const value = cfg[spec.name] !== undefined && cfg[spec.name] !== null ? cfg[spec.name] : spec.default !== null && spec.default !== undefined ? spec.default : "";
  if (spec.type === "bool") {
    if (cfg[spec.name] === undefined && spec.default !== null) cfg[spec.name] = !!spec.default;
    return checkbox(spec.label, !!value, (v) => (cfg[spec.name] = v));
  }
  let el;
  if (spec.type === "select") {
    el = select(spec.options || [], value, { onchange: (e) => (cfg[spec.name] = e.target.value) });
    if (cfg[spec.name] === undefined) cfg[spec.name] = value;
  } else if (spec.type === "textarea") {
    el = h("textarea", { value, oninput: (e) => (cfg[spec.name] = e.target.value) });
  } else {
    el = input({
      type: spec.type === "password" ? "password" : spec.type === "number" ? "number" : "text",
      value,
      placeholder: spec.placeholder || "",
      autocomplete: spec.type === "password" ? "new-password" : "off",
      class: spec.type === "path" ? "mono" : null,
      oninput: (e) => (cfg[spec.name] = spec.type === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value),
    });
  }
  return field(spec.label + (spec.required ? " *" : ""), el, spec.help);
}

function checksEditor(cfg, ctx) {
  cfg.checks = Array.isArray(cfg.checks) ? cfg.checks : [];
  const box = h("div");
  function draw() {
    box.replaceChildren(
      ...cfg.checks.map((c, i) => {
        const extra = h("div", { class: "grid-3" });
        const preview = h("div");
        function drawExtra() {
          const items = [];
          if (c.mode === "new_rows") items.push(field("Ключевая колонка", input({ value: c.key_column || "", placeholder: "id", oninput: (e) => (c.key_column = e.target.value) })));
          if (c.mode === "threshold") {
            items.push(field("Условие тревоги", select([[">", "больше"], [">=", "больше или равно"], ["<", "меньше"], ["<=", "меньше или равно"], ["==", "равно"], ["!=", "не равно"]], c.operator || ">", { onchange: (e) => (c.operator = e.target.value) })));
            items.push(field("Порог", input({ type: "number", value: c.threshold ?? 0, oninput: (e) => (c.threshold = Number(e.target.value)) })));
          }
          items.push(field("Шаблон заголовка", input({ value: c.title || "", placeholder: c.mode === "new_rows" ? "Новый заказ №{id}" : "", oninput: (e) => (c.title = e.target.value) })));
          extra.replaceChildren(...items);
        }
        if (!c.mode) c.mode = "threshold";
        if (!c.severity) c.severity = "warning";
        drawExtra();
        return h(
          "div",
          { class: "check-row" },
          h(
            "div",
            { class: "grid-3" },
            field("Название", input({ value: c.name || "", placeholder: "Очередь заданий", oninput: (e) => (c.name = e.target.value) })),
            field("Режим", select([["new_rows", "Новые записи"], ["threshold", "Порог значения"], ["rows_exist", "Есть строки — тревога"]], c.mode, { onchange: (e) => { c.mode = e.target.value; drawExtra(); } })),
            field("Важность", select([["info", "Информация"], ["warning", "Предупреждение"], ["critical", "Критично"]], c.severity, { onchange: (e) => (c.severity = e.target.value) }))
          ),
          field("SQL-запрос (только SELECT)", h("textarea", { class: "code", value: c.query || "", placeholder: c.mode === "new_rows" ? "SELECT id, number, total FROM orders ORDER BY id DESC LIMIT 50" : "SELECT COUNT(*) FROM jobs WHERE status = 'failed'", oninput: (e) => (c.query = e.target.value) })),
          extra,
          h(
            "div",
            { class: "between" },
            checkbox("Включена", c.enabled !== false, (v) => (c.enabled = v)),
            h(
              "div",
              { class: "row" },
              h("button", {
                class: "btn sm",
                type: "button",
                onclick: async () => {
                  preview.replaceChildren(loading());
                  const r = await guard(() => api("/api/sources/preview-check", { body: Object.assign({}, ctx(), { check: c }) }));
                  if (!r) return preview.replaceChildren();
                  if (!r.ok) return preview.replaceChildren(h("div", { class: "notice critical" }, icon("alert"), h("div", null, r.message)));
                  const cols = r.rows.length ? Object.keys(r.rows[0]) : [];
                  fill(
                    preview,
                    h("div", { class: "muted small", style: "margin:8px 0 4px" }, r.message),
                    cols.length
                      ? h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("thead", null, h("tr", null, cols.map((k) => h("th", null, k)))), h("tbody", null, r.rows.slice(0, 10).map((row) => h("tr", null, cols.map((k) => h("td", { class: "small" }, String(row[k] ?? ""))))))))
                      : null
                  );
                },
              }, "Проверить запрос"),
              h("button", { class: "btn sm danger", type: "button", onclick: () => { cfg.checks.splice(i, 1); draw(); } }, icon("trash"))
            )
          ),
          preview
        );
      }),
      h("button", { class: "btn", type: "button", onclick: () => { cfg.checks.push({ name: "", mode: "threshold", severity: "warning", enabled: true, operator: ">", threshold: 0 }); draw(); } }, icon("plus"), "Добавить проверку")
    );
  }
  draw();
  return box;
}

function ingestHelp(type, url) {
  if (type === "zabbix_webhook") {
    return h("div", { class: "stack small" }, h("div", null, "В Zabbix: Оповещения → Способы оповещений → Создать → тип «Webhook». Вставьте скрипт из файла ", h("code", null, "examples/zabbix_webhook.js"), ", параметр URL — адрес выше."), h("div", { class: "muted" }, "Параметры: event_id={EVENT.ID}, event_value={EVENT.VALUE}, severity={EVENT.SEVERITY}, host={HOST.NAME}, trigger_name={EVENT.NAME}, message={ALERT.MESSAGE}."));
  }
  if (type === "alertmanager") {
    return h("div", { class: "stack small" }, h("div", null, "В alertmanager.yml добавьте получателя:"), h("pre", null, `receivers:\n  - name: opswatch\n    webhook_configs:\n      - url: "${url}"\n        send_resolved: true`));
  }
  return h("div", { class: "stack small" }, h("div", null, "Отправьте POST с JSON:"), h("pre", null, `curl -X POST "${url}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"title":"Диск заполнен","message":"C: 95%","severity":"critical","category":"monitoring"}'`), h("div", { class: "muted" }, 'Для закрытия события отправьте тот же "external_id" со "status": "resolved". Для баг-репортов укажите "category": "bug".'));
}

function sourceEditor(type, existing) {
  const conn = connectorOf(type);
  const d = existing
    ? { name: existing.name, category: existing.category, enabled: existing.enabled, poll_interval: existing.poll_interval, visible_roles: [...existing.visible_roles], config: JSON.parse(JSON.stringify(existing.config || {})) }
    : { name: "", category: conn.category, enabled: true, poll_interval: conn.default_interval || 60, visible_roles: [], config: {} };
  const result = h("div");
  const ctx = () => ({ id: existing ? existing.id : null, name: d.name, type, category: d.category, config: d.config });
  const groups = new Map();
  for (const spec of conn.fields) {
    const g = spec.group || "Параметры";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(spec);
  }
  const fieldsets = [];
  for (const [name, specs] of groups) {
    fieldsets.push(h("fieldset", null, h("legend", null, name), h("div", { class: "form-grid" }, specs.map((spec) => (spec.type === "checks" ? h("div", { class: "span-all" }, checksEditor(d.config, ctx)) : renderInput(spec, d.config))))));
  }
  const body = h(
    "div",
    null,
    h("div", { class: "muted small", style: "margin-bottom:12px" }, conn.description),
    h(
      "div",
      { class: "grid-2" },
      field("Название *", input({ value: d.name, placeholder: conn.title, oninput: (e) => (d.name = e.target.value) })),
      field("Категория", select((S.meta.categories || []).map((c) => [c.id, c.title]), d.category, { onchange: (e) => (d.category = e.target.value) }))
    ),
    h(
      "div",
      { class: "grid-2" },
      conn.passive ? h("div") : field("Интервал опроса, сек", input({ type: "number", min: 15, value: d.poll_interval, oninput: (e) => (d.poll_interval = Number(e.target.value)) })),
      field("Состояние", checkbox("Источник включён", d.enabled, (v) => (d.enabled = v)))
    ),
    field("Кто видит события источника", checkboxGroup(roleOptions(), d.visible_roles, (v) => (d.visible_roles = v)), "Если ничего не выбрано — все, у кого есть право на категорию"),
    existing && existing.ingest_path
      ? h("fieldset", null, h("legend", null, "Адрес для отправки событий"), copyField(existing.ingest_url || location.origin + existing.ingest_path), h("div", { style: "margin-top:10px" }, ingestHelp(type, existing.ingest_url || location.origin + existing.ingest_path)))
      : conn.passive
      ? h("div", { class: "notice" }, icon("info"), h("div", null, "После сохранения здесь появится адрес webhook с секретным токеном."))
      : null,
    fieldsets,
    result
  );
  const foot = [];
  if (!conn.passive) {
    foot.push(
      h("button", {
        class: "btn",
        onclick: async (e) => {
          e.target.disabled = true;
          result.replaceChildren(loading());
          const r = await guard(() => api("/api/sources/test", { body: ctx() }));
          e.target.disabled = false;
          if (!r) return result.replaceChildren();
          result.replaceChildren(h("div", { class: "notice " + (r.ok ? "" : "critical") }, icon(r.ok ? "check" : "alert"), h("div", null, r.message)));
        },
      }, "Проверить подключение")
    );
  }
  foot.push(h("button", { class: "btn", onclick: () => m.close() }, "Отмена"));
  foot.push(
    h("button", {
      class: "btn primary",
      onclick: async () => {
        if (!d.name.trim()) return toast("Укажите название", "error");
        const payload = Object.assign({ type }, d);
        const r = await guard(() => api(existing ? `/api/sources/${existing.id}` : "/api/sources", { method: existing ? "PUT" : "POST", body: payload }), "Источник сохранён");
        if (!r) return;
        m.close();
        S.meta = await api("/api/meta");
        if (!existing && r.ingest_path) sourceEditor(type, r);
        renderPage();
      },
    }, "Сохранить")
  );
  const m = modal({ title: existing ? existing.name : conn.title, subtitle: existing ? conn.title : "Новый источник", body, foot, wide: true });
}

async function pageRules(root) {
  append(root, pageHead("Правила маршрутизации", "Кому и какие события отправлять. Правила применяются по порядку", h("button", { class: "btn primary", onclick: () => ruleForm(null) }, icon("plus"), "Новое правило")));
  const data = await api("/api/rules");
  const roleTitle = (n) => (S.meta.roles.find((r) => r.name === n) || { title: n }).title;
  const userTitle = (id) => { const u = (S.meta.users || []).find((x) => x.id === id); return u ? u.full_name || u.username : "#" + id; };
  const sourceTitle = (id) => { const s = (S.meta.sources || []).find((x) => x.id === id); return s ? s.name : "#" + id; };
  if (!data.items.length) {
    root.append(panel(null, null, emptyState("sliders", "Правил нет — события никому не отправляются")));
    return;
  }
  root.append(
    panel(
      null,
      null,
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "table" },
          h("thead", null, h("tr", null, h("th", null, "№"), h("th", null, "Правило"), h("th", null, "Получатели"), h("th", null, "Эскалация"), h("th", null, "Вкл."), h("th", { class: "right" }, ""))),
          h(
            "tbody",
            null,
            data.items.map((r) => {
              const cond = [r.categories.length ? r.categories.map((c) => CAT[c]).join(", ") : "Все категории", "от «" + SEV[r.min_severity] + "»"];
              if (r.source_ids.length) cond.push("источники: " + r.source_ids.map(sourceTitle).join(", "));
              if (r.event_types.length) cond.push("типы: " + r.event_types.join(", "));
              const targets = [...r.target_roles.map(roleTitle), ...r.target_users.map(userTitle)];
              const esc = r.escalate_after_min && (r.escalate_roles.length || r.escalate_users.length) ? `через ${r.escalate_after_min} мин → ${[...r.escalate_roles.map(roleTitle), ...r.escalate_users.map(userTitle)].join(", ")}` : "—";
              return h(
                "tr",
                null,
                h("td", { class: "muted" }, r.priority),
                h("td", { class: "title-cell" }, r.name, h("div", { class: "sub" }, cond.join(" · ")), r.stop ? h("span", { class: "badge outline small" }, "Остановить дальнейшие правила") : null),
                h("td", { class: "small" }, targets.join(", ") || "—"),
                h("td", { class: "small muted" }, esc),
                h("td", null, h("input", { type: "checkbox", checked: r.enabled, onchange: async (e) => { await guard(() => api(`/api/rules/${r.id}`, { method: "PUT", body: Object.assign({}, r, { enabled: e.target.checked }) }), e.target.checked ? "Правило включено" : "Правило выключено"); } })),
                h(
                  "td",
                  { class: "right nowrap" },
                  h("button", { class: "btn sm ghost", onclick: () => ruleForm(r) }, icon("edit")),
                  h("button", { class: "btn sm ghost danger", onclick: () => confirmDialog(`Удалить правило «${r.name}»?`, async () => { await guard(() => api(`/api/rules/${r.id}`, { method: "DELETE" }), "Правило удалено"); renderPage(); }) }, icon("trash"))
                )
              );
            })
          )
        )
      ),
      true
    )
  );
}

function ruleForm(rule) {
  const d = rule
    ? JSON.parse(JSON.stringify(rule))
    : { name: "", enabled: true, priority: 100, categories: [], source_ids: [], event_types: [], min_severity: "warning", target_roles: [], target_users: [], escalate_after_min: 0, escalate_roles: [], escalate_users: [], stop: false };
  const body = h(
    "div",
    null,
    h("div", { class: "grid-2" }, field("Название", input({ value: d.name, oninput: (e) => (d.name = e.target.value) })), field("Порядок", input({ type: "number", value: d.priority, oninput: (e) => (d.priority = Number(e.target.value)) }), "Меньше — раньше")),
    h(
      "fieldset",
      null,
      h("legend", null, "Условия"),
      field("Категории", checkboxGroup((S.meta.categories || []).map((c) => [c.id, c.title]), d.categories, (v) => (d.categories = v)), "Пусто — любые"),
      field("Минимальная важность", select([["info", "Информация"], ["warning", "Предупреждение"], ["critical", "Критично"]], d.min_severity, { onchange: (e) => (d.min_severity = e.target.value) })),
      (S.meta.sources || []).length ? field("Источники", checkboxGroup(S.meta.sources.map((s) => [s.id, s.name]), d.source_ids, (v) => (d.source_ids = v.map(Number))), "Пусто — любые") : null,
      field("Типы событий", input({ value: d.event_types.join(", "), placeholder: "source.down, backup.*, check.*", oninput: (e) => (d.event_types = e.target.value.split(",").map((x) => x.trim()).filter(Boolean)) }), "Через запятую, можно использовать * . Пусто — любые")
    ),
    h(
      "fieldset",
      null,
      h("legend", null, "Получатели"),
      field("Роли", checkboxGroup(roleOptions(), d.target_roles, (v) => (d.target_roles = v))),
      field("Пользователи", checkboxGroup(userOptions(), d.target_users, (v) => (d.target_users = v.map(Number))))
    ),
    h(
      "fieldset",
      null,
      h("legend", null, "Эскалация критичных событий"),
      field("Если не подтверждено за, минут", input({ type: "number", min: 0, value: d.escalate_after_min, oninput: (e) => (d.escalate_after_min = Number(e.target.value)) }), "0 — без эскалации"),
      field("Отправить ролям", checkboxGroup(roleOptions(), d.escalate_roles, (v) => (d.escalate_roles = v))),
      field("Отправить пользователям", checkboxGroup(userOptions(), d.escalate_users, (v) => (d.escalate_users = v.map(Number))))
    ),
    h("div", { class: "row" }, checkbox("Правило включено", d.enabled, (v) => (d.enabled = v)), checkbox("Не проверять следующие правила, если это сработало", d.stop, (v) => (d.stop = v)))
  );
  const m = modal({
    title: rule ? "Правило" : "Новое правило",
    body,
    wide: true,
    foot: [
      h("button", { class: "btn", onclick: () => m.close() }, "Отмена"),
      h("button", {
        class: "btn primary",
        onclick: async () => {
          const r = await guard(() => api(rule ? `/api/rules/${rule.id}` : "/api/rules", { method: rule ? "PUT" : "POST", body: d }), "Правило сохранено");
          if (r) {
            m.close();
            renderPage();
          }
        },
      }, "Сохранить"),
    ],
  });
}

async function pageUsers(root) {
  append(root, pageHead("Пользователи и роли", "Подтверждение заявок, права доступа и роли"));
  const [users, roles] = await Promise.all([api("/api/users"), api("/api/roles")]);
  const roleOpts = roles.items.map((r) => [r.id, r.title]);
  const pending = users.items.filter((u) => u.status === "pending");
  if (pending.length) {
    root.append(
      panel(
        `Заявки на регистрацию (${pending.length})`,
        null,
        h(
          "div",
          { class: "stack" },
          pending.map((u) => {
            const roleSel = select(roleOpts, (roles.items.find((r) => r.name === "user") || roles.items[0]).id);
            return h(
              "div",
              { class: "between", style: "padding:6px 0;border-bottom:1px solid var(--border)" },
              h("div", null, h("strong", null, u.full_name || u.username), h("div", { class: "muted small" }, u.username, u.telegram_username ? " · @" + u.telegram_username : "", " · ", ago(u.created_at))),
              h(
                "div",
                { class: "row" },
                roleSel,
                h("button", { class: "btn primary", onclick: async () => { const r = await guard(() => api(`/api/users/${u.id}/approve`, { body: { role_id: Number(roleSel.value) } }), "Пользователь подтверждён"); if (r) { S.meta = await api("/api/meta"); renderPage(); } } }, icon("check"), "Подтвердить"),
                h("button", { class: "btn danger", onclick: () => confirmDialog(`Отклонить заявку ${u.username}?`, async () => { await guard(() => api(`/api/users/${u.id}/reject`, { body: {} }), "Заявка отклонена"); renderPage(); }, "Отклонить") }, "Отклонить")
              )
            );
          })
        )
      )
    );
  }
  const others = users.items.filter((u) => u.status !== "pending");
  root.append(
    panel(
      "Пользователи",
      null,
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "table" },
          h("thead", null, h("tr", null, h("th", null, "Пользователь"), h("th", null, "Роль"), h("th", null, "Статус"), h("th", null, "Telegram"), h("th", null, "Вход"), h("th", { class: "right" }, ""))),
          h(
            "tbody",
            null,
            others.map((u) =>
              h(
                "tr",
                null,
                h("td", { class: "title-cell" }, u.full_name || u.username, h("div", { class: "sub" }, u.username, u.is_superuser ? " · главный администратор" : "")),
                h("td", null, select([["", "— нет —"], ...roleOpts], u.role ? u.role.id : "", { disabled: u.is_superuser, onchange: async (e) => { await guard(() => api(`/api/users/${u.id}`, { method: "PUT", body: { role_id: e.target.value ? Number(e.target.value) : null } }), "Роль изменена"); } })),
                h("td", null, select([["active", "Активен"], ["blocked", "Заблокирован"]], u.status, { disabled: u.is_superuser, onchange: async (e) => { await guard(() => api(`/api/users/${u.id}`, { method: "PUT", body: { status: e.target.value } }), "Статус изменён"); } })),
                h("td", { class: "small" }, u.telegram_linked || u.personal_bot_linked ? h("span", { class: "badge ok" }, "✓ " + (u.telegram_username ? "@" + u.telegram_username : "привязан")) : h("span", { class: "muted" }, u.telegram_username ? "@" + u.telegram_username + " (не привязан)" : "—")),
                h("td", { class: "muted small nowrap" }, u.last_login_at ? ago(u.last_login_at) : "—"),
                h(
                  "td",
                  { class: "right nowrap" },
                  h("button", { class: "btn sm ghost", title: "Сбросить пароль", onclick: () => resetPassword(u) }, "Пароль"),
                  u.is_superuser || u.id === S.me.id ? null : h("button", { class: "btn sm ghost danger", onclick: () => confirmDialog(`Удалить пользователя ${u.username}?`, async () => { await guard(() => api(`/api/users/${u.id}`, { method: "DELETE" }), "Пользователь удалён"); renderPage(); }) }, icon("trash"))
                )
              )
            )
          )
        )
      ),
      true
    )
  );
  const permTitle = Object.fromEntries((S.meta.permissions || []).map((p) => [p.id, p.title]));
  root.append(
    panel(
      "Роли",
      h("button", { class: "btn sm", onclick: () => roleForm(null) }, icon("plus"), "Новая роль"),
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "table" },
          h("thead", null, h("tr", null, h("th", null, "Роль"), h("th", null, "Права"), h("th", { class: "right" }, ""))),
          h(
            "tbody",
            null,
            roles.items.map((r) =>
              h(
                "tr",
                null,
                h("td", { class: "title-cell" }, r.title, h("div", { class: "sub mono" }, r.name)),
                h("td", { class: "small muted" }, r.permissions.map((p) => permTitle[p] || p).join(" · ") || "—"),
                h("td", { class: "right nowrap" }, r.name === "admin" ? h("span", { class: "faint small" }, "все права") : h("button", { class: "btn sm ghost", onclick: () => roleForm(r) }, icon("edit")), r.builtin ? null : h("button", { class: "btn sm ghost danger", onclick: () => confirmDialog(`Удалить роль «${r.title}»?`, async () => { await guard(() => api(`/api/roles/${r.id}`, { method: "DELETE" }), "Роль удалена"); renderPage(); }) }, icon("trash")))
              )
            )
          )
        )
      ),
      true
    )
  );
}

function resetPassword(u) {
  const p = input({ type: "password", autocomplete: "new-password" });
  const m = modal({
    title: "Новый пароль для " + u.username,
    body: field("Пароль (минимум 6 символов)", p),
    foot: [
      h("button", { class: "btn", onclick: () => m.close() }, "Отмена"),
      h("button", { class: "btn primary", onclick: async () => { const r = await guard(() => api(`/api/users/${u.id}/password`, { body: { password: p.value } }), "Пароль изменён"); if (r) m.close(); } }, "Сохранить"),
    ],
  });
}

function roleForm(role) {
  const d = role ? { name: role.name, title: role.title, permissions: [...role.permissions] } : { name: "", title: "", permissions: [] };
  const body = h(
    "div",
    null,
    h("div", { class: "grid-2" }, field("Название", input({ value: d.title, oninput: (e) => (d.title = e.target.value) })), field("Код (латиница)", input({ value: d.name, disabled: role && role.builtin, placeholder: "support", oninput: (e) => (d.name = e.target.value) }))),
    field("Права", h("div", { class: "stack", style: "gap:2px" }, (S.meta.permissions || []).map((p) => checkbox(p.title, d.permissions.includes(p.id), (on) => { d.permissions = on ? [...d.permissions, p.id] : d.permissions.filter((x) => x !== p.id); }))))
  );
  const m = modal({
    title: role ? "Роль: " + role.title : "Новая роль",
    body,
    foot: [
      h("button", { class: "btn", onclick: () => m.close() }, "Отмена"),
      h("button", { class: "btn primary", onclick: async () => { const r = await guard(() => api(role ? `/api/roles/${role.id}` : "/api/roles", { method: role ? "PUT" : "POST", body: d }), "Роль сохранена"); if (r) { m.close(); S.meta = await api("/api/meta"); renderPage(); } } }, "Сохранить"),
    ],
  });
}

async function pageSettings(root) {
  const data = await api("/api/settings");
  const v = Object.assign({}, data.values);
  const locked = new Set(v.env_locked || []);
  const txt = (key, label, help, placeholder, type = "text") =>
    field(label, input({ type, value: v[key] ?? "", placeholder: placeholder || "", disabled: locked.has(key), autocomplete: type === "password" ? "new-password" : "off", oninput: (e) => (v[key] = type === "number" ? Number(e.target.value) : e.target.value) }), locked.has(key) ? "Задано в .env" : help);
  const bot = data.bot;
  const botState =
    bot.status === "running"
      ? h("span", { class: "badge ok" }, "Работает: @" + bot.username)
      : bot.status === "error"
      ? h("span", { class: "badge critical" }, "Ошибка: " + bot.error)
      : h("span", { class: "badge" }, "Не настроен");
  const save = async () => {
    const payload = Object.assign({}, v);
    delete payload.env_locked;
    const r = await guard(() => api("/api/settings", { method: "PUT", body: payload }), "Настройки сохранены");
    if (r) {
      S.meta = await api("/api/meta");
      renderPage();
    }
  };
  append(root, pageHead("Настройки", "Telegram, резервное копирование, хранилища", h("button", { class: "btn primary", onclick: save }, "Сохранить")));
  root.append(
    panel(
      "Telegram",
      h("div", { class: "row" }, botState, h("button", { class: "btn sm", onclick: async () => { await guard(() => api("/api/settings/telegram/restart", { body: {} }), "Бот перезапущен"); renderPage(); } }, icon("refresh"), "Перезапустить")),
      h(
        "div",
        null,
        h("div", { class: "grid-2" }, txt("telegram_token", "Токен бота", "Получите у @BotFather", "123456:ABC…", "password"), txt("telegram_api_url", "Локальный Bot API сервер", "Для файлов до 2 ГБ. Пусто — api.telegram.org", "http://127.0.0.1:8081")),
        h("div", { class: "grid-2" }, txt("public_url", "Внешний адрес OpsWatch", "Для ссылок в уведомлениях и webhook-адресов", data.base_url), field("Лимит части файла, МБ", input({ type: "number", value: v.telegram_part_mb, oninput: (e) => (v.telegram_part_mb = Number(e.target.value)) }), "Не больше 49 для api.telegram.org")),
        h("div", { class: "row" }, checkbox("Принимать /bug от непривязанных пользователей Telegram", v.bot_public_bugs, (x) => (v.bot_public_bugs = x)))
      )
    )
  );
  root.append(
    panel(
      "Уведомления и доступ",
      null,
      h(
        "div",
        null,
        h("div", { class: "grid-2" }, field("Группировать одинаковые события, мин", input({ type: "number", min: 0, value: v.group_window_min, oninput: (e) => (v.group_window_min = Number(e.target.value)) }), "Повторное уведомление не чаще этого интервала"), field("Хранить историю, дней", input({ type: "number", min: 1, value: v.event_retention_days, oninput: (e) => (v.event_retention_days = Number(e.target.value)) }))),
        checkbox("Разрешить регистрацию новых пользователей", v.registration_enabled, (x) => (v.registration_enabled = x))
      )
    )
  );
  root.append(
    panel(
      "Резервное копирование",
      null,
      h(
        "div",
        null,
        h("div", { class: "grid-2" }, txt("backup_dir", "Каталог бэкапов", "Пусто — " + data.backup_dir, data.backup_dir), txt("onec_platform_path", "Каталог платформы 1С", "Для проверки целостности", "C:\\Program Files\\1cv8\\8.3.24.1691\\bin")),
        h("div", { class: "grid-2" }, txt("mysqldump_path", "Путь к mysqldump", "", "mysqldump"), txt("pg_dump_path", "Путь к pg_dump", "", "pg_dump"))
      )
    )
  );
  root.append(
    panel(
      "S3-хранилище для больших бэкапов",
      null,
      h(
        "div",
        null,
        h("div", { class: "grid-3" }, txt("s3_endpoint", "Endpoint", "Пусто — AWS", "https://storage.yandexcloud.net"), txt("s3_region", "Регион", "", "ru-central1"), txt("s3_bucket", "Bucket", "")),
        h("div", { class: "grid-3" }, txt("s3_access_key", "Access key", ""), txt("s3_secret_key", "Secret key", "", "", "password"), txt("s3_prefix", "Префикс", "", "opswatch/")),
        field("Срок действия ссылки, дней", input({ type: "number", min: 1, max: 7, value: v.s3_link_days, oninput: (e) => (v.s3_link_days = Number(e.target.value)) }))
      )
    )
  );
  root.append(
    panel(
      "Хранилище",
      null,
      h(
        "div",
        { class: "kv" },
        h("div", { class: "k" }, "База данных"),
        h("div", null, h("code", null, data.database)),
        h("div", { class: "k" }, "Каталог данных"),
        h("div", null, h("code", null, data.data_dir))
      ),
      false
    )
  );
  if (data.database_dialect === "sqlite") {
    root.append(h("div", { class: "notice", style: "margin-top:12px" }, icon("database"), h("div", null, "Для большой нагрузки можно перенести данные в PostgreSQL: ", h("code", null, "OpsWatchServer.exe migrate-db postgresql://user:pass@host/opswatch --write-env"), ", затем перезапустить программу.")));
  }
}

async function pageProfile(root) {
  const me = await api("/api/auth/me");
  S.me = me;
  append(root, pageHead("Профиль", (me.role ? me.role.title : "Роль не назначена") + " · " + me.username));
  if (me.status !== "active") {
    root.append(h("div", { class: "notice warning" }, icon("alert"), h("div", null, h("strong", null, "Учётная запись ожидает подтверждения администратором. "), "Пока можно заполнить профиль и привязать Telegram — уведомления начнут приходить после выдачи прав.")));
  }
  const p = { full_name: me.full_name, email: me.email, telegram_username: me.telegram_username, notify_telegram: me.notify_telegram, notify_desktop: me.notify_desktop, quiet_start: me.quiet_start, quiet_end: me.quiet_end };
  const saveProfile = async (msg = "Сохранено") => {
    const r = await guard(() => api("/api/profile", { method: "PUT", body: p }), msg);
    if (r) {
      S.me = r;
      syncBridge();
    }
    return r;
  };
  const left = h("div", { class: "stack" });
  const right = h("div", { class: "stack" });
  root.append(h("div", { class: "grid-2", style: "align-items:start" }, left, right));

  left.append(
    panel(
      "Учётная запись",
      null,
      h(
        "div",
        null,
        field("Имя и фамилия", input({ value: p.full_name, oninput: (e) => (p.full_name = e.target.value) })),
        field("Email", input({ type: "email", value: p.email, oninput: (e) => (p.email = e.target.value) })),
        field("Telegram", input({ value: p.telegram_username, placeholder: "@username", oninput: (e) => (p.telegram_username = e.target.value) })),
        h("button", { class: "btn primary", onclick: () => saveProfile() }, "Сохранить")
      )
    )
  );

  const tgBox = h("div");
  function drawTelegram(user) {
    const linked = user.telegram_linked;
    const items = [];
    if (linked) {
      items.push(h("div", { class: "notice" }, icon("check"), h("div", null, "Telegram привязан", user.telegram_username ? " (@" + user.telegram_username + ")" : "", ". Уведомления приходят в личные сообщения бота", S.meta.bot_username ? " @" + S.meta.bot_username : "", ".")));
      items.push(
        h(
          "div",
          { class: "row" },
          h("button", { class: "btn", onclick: () => guard(() => api("/api/profile/telegram/test", { body: {} }), "Тестовое сообщение отправлено") }, icon("send"), "Тестовое сообщение"),
          h("button", { class: "btn danger", onclick: async () => { const r = await guard(() => api("/api/profile/telegram", { method: "DELETE" }), "Telegram отвязан"); if (r) drawTelegram(r); } }, "Отвязать")
        )
      );
    } else {
      items.push(h("p", { class: "muted" }, "Привяжите Telegram, чтобы получать уведомления, нажимать «Принял / Решено» и отправлять баг-репорты боту."));
      const linkArea = h("div");
      items.push(
        h("button", {
          class: "btn primary",
          onclick: async () => {
            const r = await guard(() => api("/api/profile/telegram/link", { body: {} }));
            if (!r) return;
            linkArea.replaceChildren(
              h(
                "div",
                { class: "stack", style: "margin-top:12px" },
                r.bot_username
                  ? h("a", { class: "btn", href: r.deep_link, target: "_blank" }, icon("send"), "Открыть @" + r.bot_username + " и нажать «Старт»")
                  : h("div", { class: "notice warning" }, icon("alert"), h("div", null, "Системный бот не настроен администратором. Используйте собственного бота ниже.")),
                h("div", null, h("div", { class: "muted small" }, "или отправьте боту команду:"), h("span", { class: "code-badge" }, "/start " + r.code)),
                h("div", { class: "faint small" }, "Код действует 15 минут. Страница обновится автоматически после привязки.")
              )
            );
            let tries = 0;
            const timer = setInterval(async () => {
              tries++;
              if (tries > 60 || S.route !== "profile") return clearInterval(timer);
              const fresh = await api("/api/auth/me").catch(() => null);
              if (fresh && fresh.telegram_linked) {
                clearInterval(timer);
                S.me = fresh;
                toast("Telegram привязан");
                drawTelegram(fresh);
              }
            }, 3000);
          },
        }, icon("link"), "Привязать Telegram"),
        linkArea
      );
    }
    const tokenInput = input({ type: "password", placeholder: "123456789:AA…", autocomplete: "off" });
    const personal = h(
      "details",
      { style: "margin-top:16px", open: !!user.personal_bot },
      h("summary", { class: "muted", style: "cursor:pointer" }, "Свой бот для уведомлений"),
      h(
        "div",
        { style: "margin-top:10px" },
        user.personal_bot
          ? h(
              "div",
              { class: "stack" },
              h("div", null, "Бот ", h("a", { href: "https://t.me/" + user.personal_bot, target: "_blank" }, "@" + user.personal_bot), user.personal_bot_linked ? h("span", { class: "badge ok", style: "margin-left:6px" }, "привязан") : h("span", { class: "badge warning", style: "margin-left:6px" }, "ожидает /start")),
              user.personal_bot_linked ? null : h("div", { class: "muted small" }, "Откройте бота в Telegram, нажмите «Старт», затем «Проверить»."),
              h(
                "div",
                { class: "row" },
                user.personal_bot_linked ? null : h("button", { class: "btn primary", onclick: async () => { const r = await guard(() => api("/api/profile/personal-bot/detect", { body: {} }), "Бот привязан"); if (r) drawTelegram(r); } }, "Проверить"),
                h("button", { class: "btn danger", onclick: async () => { const r = await guard(() => api("/api/profile/personal-bot", { method: "DELETE" }), "Бот отключён"); if (r) drawTelegram(r); } }, "Отключить")
              )
            )
          : h(
              "div",
              null,
              field("Токен бота от @BotFather", tokenInput, "Уведомления будут приходить через вашего бота вместо системного"),
              h("button", { class: "btn", onclick: async () => { const r = await guard(() => api("/api/profile/personal-bot", { method: "PUT", body: { token: tokenInput.value.trim() } })); if (r) { toast("Бот @" + r.username + " сохранён. Откройте его и нажмите «Старт»."); const fresh = await api("/api/auth/me"); drawTelegram(fresh); } } }, "Сохранить бота")
            )
      )
    );
    tgBox.replaceChildren(...items, personal);
  }
  drawTelegram(me);
  left.append(panel("Telegram", null, tgBox));

  const pass = { current: input({ type: "password", autocomplete: "current-password" }), next: input({ type: "password", autocomplete: "new-password" }), again: input({ type: "password", autocomplete: "new-password" }) };
  left.append(
    panel(
      "Пароль",
      null,
      h(
        "div",
        null,
        field("Текущий пароль", pass.current),
        h("div", { class: "grid-2", style: "gap:10px" }, field("Новый пароль", pass.next), field("Ещё раз", pass.again)),
        h("button", {
          class: "btn",
          onclick: async () => {
            if (pass.next.value !== pass.again.value) return toast("Пароли не совпадают", "error");
            const r = await guard(() => api("/api/profile/password", { body: { current: pass.current.value, new: pass.next.value } }), "Пароль изменён");
            if (r) pass.current.value = pass.next.value = pass.again.value = "";
          },
        }, "Сменить пароль")
      )
    )
  );

  const inDesktop = !!bridge();
  const desktopToggle = h("input", {
    type: "checkbox",
    checked: p.notify_desktop,
    onchange: async (e) => {
      p.notify_desktop = e.target.checked;
      if (p.notify_desktop && !inDesktop && "Notification" in window && Notification.permission !== "granted") {
        const perm = await Notification.requestPermission();
        if (perm !== "granted") toast("Браузер запретил уведомления — разрешите их в настройках сайта", "error");
      }
      await saveProfile(p.notify_desktop ? "Уведомления на ПК включены" : "Уведомления на ПК выключены");
      if (p.notify_desktop && !inDesktop && "Notification" in window && Notification.permission === "granted") {
        new Notification("OpsWatch", { body: "Уведомления на этом компьютере включены", icon: "/favicon.svg" });
      }
    },
  });
  right.append(
    panel(
      "Уведомления",
      null,
      h(
        "div",
        null,
        h("label", { class: "switch" }, h("div", null, h("div", null, "Telegram"), h("div", { class: "muted small" }, "Личные сообщения от бота")), h("input", { type: "checkbox", checked: p.notify_telegram, onchange: (e) => { p.notify_telegram = e.target.checked; saveProfile(); } })),
        h("label", { class: "switch" }, h("div", null, h("div", null, inDesktop ? "Уведомления Windows" : "Уведомления на этом компьютере"), h("div", { class: "muted small" }, inDesktop ? "Программа сама покажет всплывающие уведомления, даже свёрнутая в трей" : "Всплывающие уведомления браузера, пока открыта вкладка")), desktopToggle),
        h(
          "div",
          { style: "padding-top:12px" },
          h("div", { class: "label", style: "margin-bottom:6px" }, "Тихие часы (некритичные приходят без звука)"),
          h("div", { class: "row" }, input({ type: "time", value: p.quiet_start, style: "width:130px", onchange: (e) => (p.quiet_start = e.target.value) }), "—", input({ type: "time", value: p.quiet_end, style: "width:130px", onchange: (e) => (p.quiet_end = e.target.value) }), h("button", { class: "btn", onclick: () => saveProfile("Тихие часы сохранены") }, "Сохранить"))
        )
      )
    )
  );

  if (me.status === "active") {
    const subs = await api("/api/profile/subscriptions");
    const items = subs.items.map((x) => Object.assign({}, x));
    const rows = items.map((it) => {
      const minSel = select([["info", "все"], ["warning", "от предупреждений"], ["critical", "только критичные"]], it.min_severity, { onchange: (e) => (it.min_severity = e.target.value) });
      const sync = () => minSel.classList.toggle("hidden", it.mode !== "subscribed");
      const modeSel = select([["rules", "По правилам"], ["subscribed", "Подписаться"], ["muted", "Отключить"]], it.mode, { onchange: (e) => { it.mode = e.target.value; sync(); } });
      sync();
      return h("div", { class: "between", style: "padding:8px 0;border-bottom:1px solid var(--border)" }, h("div", { class: "row" }, icon(CAT_ICON[it.category]), CAT[it.category]), h("div", { class: "row" }, modeSel, minSel));
    });
    right.append(
      panel(
        "Подписки на категории",
        null,
        h(
          "div",
          null,
          h("p", { class: "muted small" }, "«По правилам» — как настроил администратор. «Подписаться» — получать все события категории. «Отключить» — не получать (кроме критичных по правилам). Также доступно в боте: /subscribe"),
          rows.length ? rows : h("div", { class: "muted" }, "Нет доступных категорий"),
          h("button", { class: "btn primary", style: "margin-top:12px", onclick: () => guard(() => api("/api/profile/subscriptions", { method: "PUT", body: { items } }), "Подписки сохранены") }, "Сохранить подписки")
        )
      )
    );
  }
}

const PAGES = {
  overview: pageOverview,
  monitoring: categoryPage("monitoring", "Мониторинг", "Zabbix, Prometheus, HTTP-проверки и другие системы"),
  databases: categoryPage("database", "Базы данных", "MySQL, PostgreSQL, MS SQL: доступность, размер, SQL-проверки"),
  onec: categoryPage("onec", "1С", "Файловые и серверные базы, журнал регистрации, целостность"),
  backups: pageBackups,
  bugs: pageBugs,
  journal: pageJournal,
  sources: pageSources,
  rules: pageRules,
  users: pageUsers,
  settings: pageSettings,
  profile: pageProfile,
};

boot();
