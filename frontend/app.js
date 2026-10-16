/**
 * ChangeScope — Intelligent Website Change Detector
 * Premium SaaS Dashboard & Monitor Manager Controller
 * Handles dual-theme switching, responsive navigation, live API telemetry,
 * and full CRUD operations for Monitored Websites.
 */

// API Base URL configuration
const API_BASE_URL = window.location.origin.startsWith("http")
  ? window.location.origin
  : "http://127.0.0.1:8000";

// Theme Storage Key
const THEME_STORAGE_KEY = "changescope-theme";

// Navigation view titles map
const VIEW_TITLES = {
  dashboard: "Dashboard",
  monitors: "Monitors",
  timemachine: "Time Machine",
  heatmap: "Change Heatmap",
  history: "Change History",
  notifications: "Notifications",
  analytics: "Analytics",
  reliability: "Reliability Lab",
  settings: "Settings",
};

// Application State
let monitorsList = [];
let changesList = [];
let activeFilter = "all"; // 'all' | 'active' | 'paused'
let searchQuery = "";
let pendingDeleteSiteId = null;
let currentViewingSiteId = null;
let currentViewingChangeId = null;

// Time Machine State
let tmCurrentSiteId = null;
let tmSnapshots = [];
let tmCurrentIndex = 0;
let tmSortOrder = "asc";
let tmViewerMode = "inspect";
let tmCompareSubtab = "unified";

// Heatmap & Analytics State (Prompt 7)
let hmCurrentSiteId = "all";
let hmCurrentDays = 30;
let hmData = null;

let anCurrentSiteId = "all";
let anCurrentDays = 30;
let anData = null;

// Notifications & Alerts State (Prompt 8)
let notifList = [];
let notifUnreadCount = 0;
let notifFilterUnreadOnly = false;
let notifFilterEventType = "all";
let notifFilterSiteId = "all";

// Scheduler State (Prompt 9)
let schedulerData = null;
let schedulerAutoChecksEnabled = true;

// Authentication State (Prompt 10)
const AUTH_TOKEN_STORAGE_KEY = "changescope_auth_token";
let currentUser = null;

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
}

function setAuthToken(token) {
  if (token) {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  }
}

// Global fetch interceptor to automatically attach JWT token and handle 401s
const _originalFetch = window.fetch;
window.fetch = async function (resource, init = {}) {
  const options = Object.assign({}, init);
  const url = typeof resource === "string" ? resource : resource.url || "";

  options.credentials = options.credentials || "include";

  const token = getAuthToken();
  if (token && (url.startsWith(API_BASE_URL) || url.startsWith("/api"))) {
    options.headers = options.headers || {};
    if (options.headers instanceof Headers) {
      if (!options.headers.has("Authorization")) {
        options.headers.set("Authorization", `Bearer ${token}`);
      }
    } else if (Array.isArray(options.headers)) {
      if (!options.headers.some(([k]) => k.toLowerCase() === "authorization")) {
        options.headers.push(["Authorization", `Bearer ${token}`]);
      }
    } else {
      if (!options.headers["Authorization"]) {
        options.headers["Authorization"] = `Bearer ${token}`;
      }
    }
  }

  const response = await _originalFetch(resource, options);

  if (
    response.status === 401 &&
    !url.includes("/api/auth/login") &&
    !url.includes("/api/auth/register") &&
    !url.includes("/api/health")
  ) {
    if (currentUser) {
      currentUser = null;
      showToast("Session expired. Please sign in again.", "error");
    }
    showAuthOverlay("login");
  }

  return response;
};

/* ==========================================================================
   Prompt 10: Authentication & User Accounts Controller
   ========================================================================== */

function showAuthOverlay(initialTab = "login") {
  const overlay = document.getElementById("auth-overlay");
  if (overlay) {
    overlay.style.display = "flex";
  }
  switchAuthTab(initialTab);
  clearAuthAlert();
}

function hideAuthOverlay() {
  const overlay = document.getElementById("auth-overlay");
  if (overlay) {
    overlay.style.display = "none";
  }
  clearAuthAlert();
  window.scrollTo({ top: 0, left: 0, behavior: "instant" });
}

function switchAuthTab(tab) {
  const tabLogin = document.getElementById("tab-auth-login");
  const tabRegister = document.getElementById("tab-auth-register");
  const formLogin = document.getElementById("form-auth-login");
  const formRegister = document.getElementById("form-auth-register");

  clearAuthAlert();

  if (tab === "register") {
    if (tabLogin) {
      tabLogin.classList.remove("active");
      tabLogin.setAttribute("aria-selected", "false");
    }
    if (tabRegister) {
      tabRegister.classList.add("active");
      tabRegister.setAttribute("aria-selected", "true");
    }
    if (formLogin) formLogin.style.display = "none";
    if (formRegister) formRegister.style.display = "flex";
    const regName = document.getElementById("register-name");
    if (regName) regName.focus({ preventScroll: true });
  } else {
    if (tabRegister) {
      tabRegister.classList.remove("active");
      tabRegister.setAttribute("aria-selected", "false");
    }
    if (tabLogin) {
      tabLogin.classList.add("active");
      tabLogin.setAttribute("aria-selected", "true");
    }
    if (formRegister) formRegister.style.display = "none";
    if (formLogin) formLogin.style.display = "flex";
    const logEmail = document.getElementById("login-email");
    if (logEmail) logEmail.focus({ preventScroll: true });
  }
}

function showAuthAlert(message, isSuccess = false) {
  const alertEl = document.getElementById("auth-alert");
  const textEl = document.getElementById("auth-alert-text");
  if (!alertEl || !textEl) return;

  textEl.textContent = message;
  alertEl.className = isSuccess ? "form-alert form-alert-success" : "form-alert form-alert-error";
  alertEl.style.display = "flex";
}

function clearAuthAlert() {
  const alertEl = document.getElementById("auth-alert");
  if (alertEl) {
    alertEl.style.display = "none";
  }
}

async function handleLoginSubmit(e) {
  if (e && e.preventDefault) e.preventDefault();
  clearAuthAlert();

  const emailInput = document.getElementById("login-email");
  const passwordInput = document.getElementById("login-password");
  const submitBtn = document.getElementById("btn-submit-login");
  const spinner = submitBtn ? submitBtn.querySelector(".btn-spinner") : null;
  const btnText = document.getElementById("btn-submit-login-text");

  const email = emailInput ? emailInput.value.trim() : "";
  const password = passwordInput ? passwordInput.value : "";

  if (!email || !password) {
    showAuthAlert("Please enter both email and password.");
    return;
  }

  if (submitBtn) submitBtn.disabled = true;
  if (spinner) spinner.style.display = "inline-block";
  if (btnText) btnText.textContent = "Signing In...";

  try {
    const res = await _originalFetch(`${API_BASE_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      credentials: "include",
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Authentication failed.");
    }

    setAuthToken(data.access_token);
    currentUser = data.user;
    hideAuthOverlay();
    renderUserProfile();
    showToast(`Welcome back, ${currentUser.full_name || currentUser.email}!`, "success");

    refreshAllData();
  } catch (err) {
    showAuthAlert(err.message || "Failed to sign in. Please verify your credentials.");
  } finally {
    if (submitBtn) submitBtn.disabled = false;
    if (spinner) spinner.style.display = "none";
    if (btnText) btnText.textContent = "Sign In to ChangeScope";
  }
}

async function handleRegisterSubmit(e) {
  if (e && e.preventDefault) e.preventDefault();
  clearAuthAlert();

  const nameInput = document.getElementById("register-name");
  const emailInput = document.getElementById("register-email");
  const passwordInput = document.getElementById("register-password");
  const submitBtn = document.getElementById("btn-submit-register");
  const spinner = submitBtn ? submitBtn.querySelector(".btn-spinner") : null;
  const btnText = document.getElementById("btn-submit-register-text");

  const fullName = nameInput ? nameInput.value.trim() : "";
  const email = emailInput ? emailInput.value.trim() : "";
  const password = passwordInput ? passwordInput.value : "";

  if (!email || !password) {
    showAuthAlert("Email and password are required.");
    return;
  }
  if (password.length < 8) {
    showAuthAlert("Password must be at least 8 characters.");
    return;
  }

  if (submitBtn) submitBtn.disabled = true;
  if (spinner) spinner.style.display = "inline-block";
  if (btnText) btnText.textContent = "Creating Account...";

  try {
    const res = await _originalFetch(`${API_BASE_URL}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, full_name: fullName || null }),
      credentials: "include",
    });

    const data = await res.json();
    if (!res.ok) {
      let detailMsg = data.detail;
      if (Array.isArray(detailMsg)) {
        detailMsg = detailMsg.map((d) => d.msg).join(", ");
      }
      throw new Error(detailMsg || "Registration failed.");
    }

    setAuthToken(data.access_token);
    currentUser = data.user;
    hideAuthOverlay();
    renderUserProfile();
    showToast("Account created successfully! Welcome to ChangeScope.", "success");

    refreshAllData();
  } catch (err) {
    showAuthAlert(err.message || "Failed to create account.");
  } finally {
    if (submitBtn) submitBtn.disabled = false;
    if (spinner) spinner.style.display = "none";
    if (btnText) btnText.textContent = "Create Free Account";
  }
}

async function handleLogout() {
  try {
    await fetch(`${API_BASE_URL}/api/auth/logout`, { method: "POST" });
  } catch (e) {
    // Ignore network error on logout
  }
  setAuthToken("");
  currentUser = null;
  monitorsList = [];
  changesList = [];
  notifList = [];
  closeUserDropdown();
  showAuthOverlay("login");
  showToast("You have been signed out.", "info");
}

async function checkAuthStatus() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/me`);
    if (res.ok) {
      currentUser = await res.json();
      hideAuthOverlay();
      renderUserProfile();
      refreshAllData();
      return true;
    }
  } catch (e) {
    // Backend offline or token invalid
  }
  showAuthOverlay("login");
  return false;
}

function refreshAllData() {
  checkBackendHealth();
  fetchMonitors();
  fetchChangeHistory();
  fetchUnreadCount();
  loadNotificationPreferences();
  fetchSchedulerStatus();
  loadSchedulerSettings();
}

function renderUserProfile() {
  if (!currentUser) return;

  const displayName = currentUser.full_name || currentUser.email.split("@")[0];
  const initials = (currentUser.full_name
    ? currentUser.full_name.split(" ").map((n) => n[0]).join("")
    : currentUser.email.slice(0, 2)
  ).toUpperCase().slice(0, 2);

  const avatarEl = document.getElementById("topbar-user-avatar");
  const nameEl = document.getElementById("topbar-user-name");
  if (avatarEl) avatarEl.textContent = initials;
  if (nameEl) nameEl.textContent = displayName;

  const dropName = document.getElementById("dropdown-user-name");
  const dropEmail = document.getElementById("dropdown-user-email");
  const dropRole = document.getElementById("dropdown-user-role");
  if (dropName) dropName.textContent = currentUser.full_name || displayName;
  if (dropEmail) dropEmail.textContent = currentUser.email;
  if (dropRole) dropRole.textContent = currentUser.is_admin ? "Administrator" : "Member";

  const setEmail = document.getElementById("settings-user-email");
  const setName = document.getElementById("settings-user-name");
  const setRole = document.getElementById("settings-user-role");
  const setCreated = document.getElementById("settings-user-created");
  const inputName = document.getElementById("settings-input-name");

  if (setEmail) setEmail.textContent = currentUser.email;
  if (setName) setName.textContent = currentUser.full_name || "—";
  if (setRole) setRole.textContent = currentUser.is_admin ? "Administrator" : "Standard Account";
  if (setCreated && currentUser.created_at) {
    setCreated.textContent = new Date(currentUser.created_at).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }
  if (inputName && currentUser.full_name) {
    inputName.value = currentUser.full_name;
  }
}

function toggleUserDropdown() {
  const dropdown = document.getElementById("user-dropdown");
  const btn = document.getElementById("btn-user-profile");
  if (!dropdown) return;
  const isHidden = dropdown.style.display === "none";
  dropdown.style.display = isHidden ? "block" : "none";
  if (btn) btn.setAttribute("aria-expanded", isHidden ? "true" : "false");
}

function closeUserDropdown() {
  const dropdown = document.getElementById("user-dropdown");
  const btn = document.getElementById("btn-user-profile");
  if (dropdown) dropdown.style.display = "none";
  if (btn) btn.setAttribute("aria-expanded", "false");
}

async function handleProfileNameUpdate(e) {
  if (e && e.preventDefault) e.preventDefault();
  const input = document.getElementById("settings-input-name");
  const newName = input ? input.value.trim() : "";

  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/me`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name: newName || null }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to update profile name.");
    }
    currentUser = await res.json();
    renderUserProfile();
    showToast("Profile display name updated.", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function handlePasswordChange(e) {
  if (e && e.preventDefault) e.preventDefault();
  const currentPwdInput = document.getElementById("pwd-current");
  const newPwdInput = document.getElementById("pwd-new");
  const currentPassword = currentPwdInput ? currentPwdInput.value : "";
  const newPassword = newPwdInput ? newPwdInput.value : "";

  if (!currentPassword || !newPassword) {
    showToast("Please enter both current and new password.", "error");
    return;
  }
  if (newPassword.length < 8) {
    showToast("New password must be at least 8 characters.", "error");
    return;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/me`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to change password.");
    }
    if (currentPwdInput) currentPwdInput.value = "";
    if (newPwdInput) newPwdInput.value = "";
    showToast("Password updated successfully.", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

/* ==========================================================================
   1. Theme Management (Dark / Light / System Preference)
   ========================================================================== */

function getPreferredTheme() {
  const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
  if (storedTheme === "dark" || storedTheme === "light") {
    return storedTheme;
  }
  // Fall back to system preference on first visit
  const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  return systemPrefersDark ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const themeToggleBtn = document.getElementById("btn-theme-toggle");
  if (themeToggleBtn) {
    themeToggleBtn.setAttribute(
      "aria-label",
      theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
    );
    themeToggleBtn.setAttribute(
      "title",
      theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
    );
  }

  // Update Settings view buttons if present
  const btnLight = document.getElementById("btn-theme-light-select");
  const btnDark = document.getElementById("btn-theme-dark-select");
  if (btnLight && btnDark) {
    if (theme === "light") {
      btnLight.classList.add("active-tag");
      btnDark.classList.remove("active-tag");
    } else {
      btnDark.classList.add("active-tag");
      btnLight.classList.remove("active-tag");
    }
  }
}

function setTheme(theme) {
  localStorage.setItem(THEME_STORAGE_KEY, theme);
  applyTheme(theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const target = current === "dark" ? "light" : "dark";
  setTheme(target);
}

// React to OS-level theme changes when no manual preference is pinned
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
  if (!localStorage.getItem(THEME_STORAGE_KEY)) {
    applyTheme(e.matches ? "dark" : "light");
  }
});

/* ==========================================================================
   2. Toast Notification System
   ========================================================================== */

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  let iconSvg = "";
  if (type === "success") {
    iconSvg = `
      <svg class="toast-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
        <polyline points="22 4 12 14.01 9 11.01"></polyline>
      </svg>
    `;
  } else if (type === "error") {
    iconSvg = `
      <svg class="toast-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="15" y1="9" x2="9" y2="15"></line>
        <line x1="9" y1="9" x2="15" y2="15"></line>
      </svg>
    `;
  } else {
    iconSvg = `
      <svg class="toast-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="16" x2="12" y2="12"></line>
        <line x1="12" y1="8" x2="12.01" y2="8"></line>
      </svg>
    `;
  }

  toast.innerHTML = `
    ${iconSvg}
    <span class="toast-msg">${escapeHtml(message)}</span>
    <button class="toast-close-btn" aria-label="Close notification">✕</button>
  `;

  const closeBtn = toast.querySelector(".toast-close-btn");
  closeBtn.addEventListener("click", () => removeToast(toast));

  container.appendChild(toast);

  // Auto-dismiss after 3.8s
  setTimeout(() => {
    removeToast(toast);
  }, 3800);
}

function removeToast(toast) {
  if (!toast || !toast.parentElement) return;
  toast.style.opacity = "0";
  toast.style.transform = "translateY(10px)";
  setTimeout(() => {
    if (toast.parentElement) {
      toast.parentElement.removeChild(toast);
    }
  }, 220);
}

/* ==========================================================================
   3. Navigation & View Routing
   ========================================================================== */

function switchView(viewId) {
  if (!VIEW_TITLES[viewId]) {
    viewId = "dashboard";
  }

  // Update sidebar active states
  const navItems = document.querySelectorAll(".nav-item");
  navItems.forEach((item) => {
    if (item.getAttribute("data-view") === viewId) {
      item.classList.add("active");
      item.setAttribute("aria-current", "page");
    } else {
      item.classList.remove("active");
      item.removeAttribute("aria-current");
    }
  });

  // Switch visible view container
  const views = document.querySelectorAll(".app-view");
  views.forEach((view) => {
    if (view.id === `view-${viewId}`) {
      view.classList.add("active");
    } else {
      view.classList.remove("active");
    }
  });

  // Update topbar breadcrumb
  const currentTitle = document.getElementById("current-view-title");
  if (currentTitle) {
    currentTitle.textContent = VIEW_TITLES[viewId];
  }

  // Close mobile sidebar drawer if open
  closeMobileSidebar();

  // Reset scroll to top of view
  window.scrollTo({ top: 0, left: 0, behavior: "instant" });

  // Lazy refresh when switching into views
  if (viewId === "history") {
    fetchChangeHistory();
  } else if (viewId === "monitors") {
    fetchMonitors();
  } else if (viewId === "timemachine") {
    initTimeMachine(tmCurrentSiteId);
  } else if (viewId === "heatmap") {
    initHeatmapView();
  } else if (viewId === "analytics") {
    initAnalyticsView();
  } else if (viewId === "notifications") {
    fetchNotifications();
  } else if (viewId === "settings") {
    loadNotificationPreferences();
    loadSchedulerSettings();
  } else if (viewId === "dashboard") {
    fetchMonitors();
    fetchSchedulerStatus();
  }
}

function openMobileSidebar() {
  const sidebar = document.getElementById("app-sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (sidebar) sidebar.classList.add("mobile-open");
  if (backdrop) backdrop.classList.add("active");
}

function closeMobileSidebar() {
  const sidebar = document.getElementById("app-sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (sidebar) sidebar.classList.remove("mobile-open");
  if (backdrop) backdrop.classList.remove("active");
}

/* ==========================================================================
   4. Live Backend Health Telemetry
   ========================================================================== */

const statusPill = document.getElementById("backend-status-pill");
const statusText = document.getElementById("backend-status-text");
const sidebarDbStatus = document.getElementById("sidebar-db-status");

const diagApiStatus = document.getElementById("diag-api-status");
const diagLatency = document.getElementById("diag-latency");
const diagDbStatus = document.getElementById("diag-db-status");
const diagTimestamp = document.getElementById("diag-timestamp");
const healthJsonOutput = document.getElementById("health-json-output");

const metricSitesCount = document.getElementById("metric-sites-count");
const metricActiveCount = document.getElementById("metric-active-count");
const metricLatency = document.getElementById("metric-latency");
const navMonitorsCount = document.getElementById("nav-monitors-count");
const sitesBadge = document.getElementById("sites-badge");

async function checkBackendHealth() {
  setLoadingState();
  const startTime = performance.now();

  try {
    const response = await fetch(`${API_BASE_URL}/api/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });

    const elapsedMs = Math.round(performance.now() - startTime);

    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}`);
    }

    const data = await response.json();
    setOnlineState(data, elapsedMs);
  } catch (error) {
    setOfflineState(error.message);
  }
}

function setLoadingState() {
  if (statusPill) {
    statusPill.className = "status-pill status-loading";
    statusText.textContent = "Connecting...";
  }
  if (sidebarDbStatus) {
    sidebarDbStatus.textContent = "Connecting...";
  }
  if (diagApiStatus) {
    diagApiStatus.textContent = "Checking...";
    diagApiStatus.style.color = "var(--text-secondary)";
  }
}

function setOnlineState(data, elapsedMs) {
  if (statusPill) {
    statusPill.className = "status-pill status-online";
    statusText.textContent = `Online (${data.version || "0.1.0"})`;
  }
  if (sidebarDbStatus) {
    sidebarDbStatus.textContent = `Connected (${data.database || "SQLite"})`;
  }
  if (diagApiStatus) {
    diagApiStatus.textContent = "Operational (HTTP 200)";
    diagApiStatus.style.color = "var(--accent-emerald)";
  }
  if (diagLatency) {
    diagLatency.textContent = `${elapsedMs} ms`;
  }
  if (metricLatency) {
    metricLatency.textContent = `${elapsedMs} ms`;
  }
  if (diagDbStatus) {
    diagDbStatus.textContent = `SQLite (${data.database || "connected"})`;
  }
  if (diagTimestamp) {
    diagTimestamp.textContent = data.timestamp || new Date().toISOString();
  }
  if (healthJsonOutput) {
    healthJsonOutput.textContent = JSON.stringify(data, null, 2);
  }
}

function setOfflineState(errorMessage) {
  if (statusPill) {
    statusPill.className = "status-pill status-offline";
    statusText.textContent = "Offline";
  }
  if (sidebarDbStatus) {
    sidebarDbStatus.textContent = "Disconnected";
  }
  if (diagApiStatus) {
    diagApiStatus.textContent = "Unreachable";
    diagApiStatus.style.color = "var(--accent-rose)";
  }
  if (diagLatency) {
    diagLatency.textContent = "—";
  }
  if (metricLatency) {
    metricLatency.textContent = "—";
  }
  if (diagDbStatus) {
    diagDbStatus.textContent = "Unreachable";
  }
  if (diagTimestamp) {
    diagTimestamp.textContent = "—";
  }
  if (healthJsonOutput) {
    healthJsonOutput.textContent = JSON.stringify(
      {
        error: "ChangeScope backend unreachable",
        details: errorMessage,
        hint: "Run 'uvicorn backend.main:app --reload' in your terminal.",
        target_url: `${API_BASE_URL}/api/health`,
      },
      null,
      2
    );
  }
}

/* ==========================================================================
   5. Monitor Manager CRUD Operations
   ========================================================================== */

/**
 * Fetch all monitors from backend and update both Monitors page and Dashboard
 */
async function fetchMonitors() {
  const monitorsContainer = document.getElementById("monitors-table-container");

  try {
    const response = await fetch(`${API_BASE_URL}/api/sites`);
    if (!response.ok) {
      throw new Error(`Failed to load monitors (HTTP ${response.status})`);
    }

    const sites = await response.json();
    monitorsList = Array.isArray(sites) ? sites : [];

    updateMonitorCounts();
    renderMonitorsTable();
    renderDashboardSitesList();
    initVisualChanges();
    populateHeatmapSiteSelect();
    populateAnalyticsSiteSelect();
    populateNotificationSiteSelect();
    fetchUnreadCount();
    fetchSchedulerStatus();
  } catch (error) {
    console.error("Error loading monitors:", error);
    if (monitorsContainer) {
      monitorsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-art" style="border-color: var(--accent-rose); color: var(--accent-rose);">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
          </div>
          <h3 class="empty-state-title">Error Loading Monitors</h3>
          <p class="empty-state-desc">${escapeHtml(error.message)}. Please check your backend connection.</p>
          <button class="btn btn-secondary btn-sm" onclick="fetchMonitors()">Retry</button>
        </div>
      `;
    }
    const dashboardContainer = document.getElementById("sites-list-container");
    if (dashboardContainer) {
      dashboardContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-art" style="border-color: var(--accent-rose); color: var(--accent-rose);">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
          </div>
          <h3 class="empty-state-title">Error Loading Monitors</h3>
          <p class="empty-state-desc">${escapeHtml(error.message)}. Please check your backend connection.</p>
          <button class="btn btn-secondary btn-sm" onclick="fetchMonitors()">Retry</button>
        </div>
      `;
    }
  }
}

function updateMonitorCounts() {
  const total = monitorsList.length;
  const activeCount = monitorsList.filter((s) => s.is_active).length;
  const pausedCount = total - activeCount;

  // Filter tabs count
  const filterCountAll = document.getElementById("filter-count-all");
  const filterCountActive = document.getElementById("filter-count-active");
  const filterCountPaused = document.getElementById("filter-count-paused");

  if (filterCountAll) filterCountAll.textContent = total;
  if (filterCountActive) filterCountActive.textContent = activeCount;
  if (filterCountPaused) filterCountPaused.textContent = pausedCount;

  // Dashboard & sidebar badges
  if (metricSitesCount) metricSitesCount.textContent = total;
  if (metricActiveCount) metricActiveCount.textContent = activeCount;
  if (navMonitorsCount) navMonitorsCount.textContent = total;
  if (sitesBadge) sitesBadge.textContent = `${total} configured`;
}

function updateChangeMetrics() {
  const metricChangesCount = document.getElementById("metric-changes-count");
  if (metricChangesCount) {
    metricChangesCount.textContent = changesList.length;
  }
}

/**
 * Render monitors table based on active filter and search query
 */
function renderMonitorsTable() {
  const container = document.getElementById("monitors-table-container");
  if (!container) return;

  // Filter by status
  let filtered = monitorsList.filter((site) => {
    if (activeFilter === "active") return site.is_active;
    if (activeFilter === "paused") return !site.is_active;
    return true;
  });

  // Filter by search query
  if (searchQuery.trim() !== "") {
    const q = searchQuery.trim().toLowerCase();
    filtered = filtered.filter(
      (site) =>
        (site.name && site.name.toLowerCase().includes(q)) ||
        (site.url && site.url.toLowerCase().includes(q))
    );
  }

  // 1. Overall Empty State (0 monitors in database)
  if (monitorsList.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-art">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="2" y1="12" x2="22" y2="12"></line>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
          </svg>
        </div>
        <h3 class="empty-state-title">No Websites Added Yet</h3>
        <p class="empty-state-desc">
          Register your first target website to start monitoring text, HTML DOM changes, and availability over time.
        </p>
        <button id="btn-empty-add-monitor" class="btn btn-primary">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          Add Your First Monitor
        </button>
      </div>
    `;

    const emptyAddBtn = document.getElementById("btn-empty-add-monitor");
    if (emptyAddBtn) {
      emptyAddBtn.addEventListener("click", openAddMonitorModal);
    }
    return;
  }

  // 2. Search / Filter Yielded No Results
  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="padding: 36px 20px;">
        <div class="empty-state-art">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
        </div>
        <h3 class="empty-state-title">No Matching Monitors</h3>
        <p class="empty-state-desc">
          No websites matched "${escapeHtml(searchQuery)}" with filter "${activeFilter}".
        </p>
        <button id="btn-reset-filters" class="btn btn-secondary btn-sm">Reset Search & Filters</button>
      </div>
    `;

    const resetBtn = document.getElementById("btn-reset-filters");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        searchQuery = "";
        activeFilter = "all";
        const searchInput = document.getElementById("monitors-search-input");
        if (searchInput) searchInput.value = "";
        const clearBtn = document.getElementById("btn-clear-search");
        if (clearBtn) clearBtn.style.display = "none";
        document.querySelectorAll(".filter-pill").forEach((p) => {
          p.classList.toggle("active", p.getAttribute("data-filter") === "all");
        });
        renderMonitorsTable();
      });
    }
    return;
  }

  // 3. Render Rich Data Table
  let html = `
    <div class="table-responsive">
      <table class="data-table">
        <thead>
          <tr>
            <th>Target Website</th>
            <th>Check Frequency</th>
            <th>Monitoring State</th>
            <th>Last Status</th>
            <th style="text-align: right;">Actions</th>
          </tr>
        </thead>
        <tbody>
  `;

  for (const site of filtered) {
    const statusBadgeClass = site.is_active ? "status-badge-active" : "status-badge-paused";
    const statusBadgeText = site.is_active ? "Active" : "Paused";
    const dotClass = site.is_active ? "badge-dot-green" : "badge-dot-gray";

    let lastStatusDisplay = "";
    if (site.last_status_code) {
      const is2xx = site.last_status_code >= 200 && site.last_status_code < 300;
      const badgeClass = is2xx ? "status-badge-http" : "status-badge-error";
      const timeAgo = formatTimeAgo(site.last_checked_at);
      const latency = site.last_response_time_ms ? `${site.last_response_time_ms}ms` : "";
      lastStatusDisplay = `
        <div style="display: flex; flex-direction: column; gap: 3px;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span class="status-badge ${badgeClass}">HTTP ${site.last_status_code}</span>
            ${latency ? `<span style="font-size: 0.73rem; color: var(--text-muted);">${latency}</span>` : ""}
          </div>
          <span style="font-size: 0.73rem; color: var(--text-secondary);">${timeAgo}</span>
        </div>
      `;
    } else if (site.last_error) {
      lastStatusDisplay = `
        <div style="display: flex; flex-direction: column; gap: 3px;">
          <span class="status-badge status-badge-error" title="${escapeHtml(site.last_error)}">Failed</span>
          <span style="font-size: 0.73rem; color: var(--accent-rose);">${formatTimeAgo(site.last_checked_at)}</span>
        </div>
      `;
    } else {
      lastStatusDisplay = `<span style="color: var(--text-muted); font-size: 0.8rem;">Pending check</span>`;
    }

    const intervalDisplay = formatInterval(site.check_interval_minutes);

    html += `
      <tr data-site-id="${site.id}">
        <td>
          <div class="site-identity-cell">
            <div class="site-name-wrapper">
              <span class="site-name-text">${escapeHtml(site.name)}</span>
              <span class="site-id-tag">#${site.id}</span>
            </div>
            <a href="${escapeHtml(site.url)}" target="_blank" rel="noopener noreferrer" class="site-url-link" title="Open destination in new tab">
              <span>${escapeHtml(site.url)}</span>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                <polyline points="15 3 21 3 21 9"></polyline>
                <line x1="10" y1="14" x2="21" y2="3"></line>
              </svg>
            </a>
          </div>
        </td>
        <td>
          <span style="font-weight: 500;">${intervalDisplay}</span>
        </td>
        <td>
          <button class="status-badge ${statusBadgeClass} btn-toggle-state" data-site-id="${site.id}" title="Click to toggle Active/Paused">
            <span class="${dotClass}"></span>
            <span>${statusBadgeText}</span>
          </button>
        </td>
        <td>
          ${lastStatusDisplay}
        </td>
        <td style="text-align: right;">
          <div class="action-btn-group" style="justify-content: flex-end;">
            <button class="action-btn btn-check-action" data-site-id="${site.id}" title="Check Now (Run Detection)">
              <svg class="check-icon-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="23 4 23 10 17 10"></polyline>
                <polyline points="1 20 1 14 7 14"></polyline>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
            </button>
            <button class="action-btn btn-view-action" data-site-id="${site.id}" title="View Details">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                <circle cx="12" cy="12" r="3"></circle>
              </svg>
            </button>
            <button class="action-btn btn-tm-action" data-site-id="${site.id}" title="Time Machine & Version History">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 14 14"></polyline>
              </svg>
            </button>
            <button class="action-btn btn-visual-action" data-site-id="${site.id}" title="Visual Screenshots & Diff">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
                <circle cx="12" cy="13" r="4"></circle>
              </svg>
            </button>
            <button class="action-btn btn-edit-action" data-site-id="${site.id}" title="Edit Monitor">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
              </svg>
            </button>
            <button class="action-btn btn-delete-action" data-site-id="${site.id}" title="Delete Monitor">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
          </div>
        </td>
      </tr>
    `;
  }

  html += `
        </tbody>
      </table>
    </div>
  `;

  container.innerHTML = html;

  // Bind row action listeners
  container.querySelectorAll(".btn-check-action").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.getAttribute("data-site-id"), 10);
      checkMonitorNow(id, btn);
    });
  });

  container.querySelectorAll(".btn-view-action").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.getAttribute("data-site-id"), 10);
      openViewModal(id);
    });
  });

  container.querySelectorAll(".btn-tm-action").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.getAttribute("data-site-id"), 10);
      openTimeMachineForSite(id);
    });
  });

  container.querySelectorAll(".btn-visual-action").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.getAttribute("data-site-id"), 10);
      openVisualChangesForSite(id);
    });
  });

  container.querySelectorAll(".btn-edit-action").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.getAttribute("data-site-id"), 10);
      openEditMonitorModal(id);
    });
  });

  container.querySelectorAll(".btn-delete-action").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.getAttribute("data-site-id"), 10);
      openDeleteModal(id);
    });
  });

  container.querySelectorAll(".btn-toggle-state").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.getAttribute("data-site-id"), 10);
      toggleMonitorState(id);
    });
  });
}

/**
 * Render the dashboard's Monitored Websites panel
 */
function renderDashboardSitesList() {
  const container = document.getElementById("sites-list-container");
  if (!container) return;

  if (monitorsList.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-art">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
            <line x1="8" y1="21" x2="16" y2="21"></line>
            <line x1="12" y1="17" x2="12" y2="21"></line>
          </svg>
        </div>
        <h3 class="empty-state-title">No Targets Monitored Yet</h3>
        <p class="empty-state-desc">
          ChangeScope’s SQLite schema is initialized and waiting for website registration.
          Click below to register your first target website.
        </p>
        <button class="btn btn-primary btn-sm nav-switch-btn" data-target="monitors">
          Add Your First Monitor
        </button>
      </div>
    `;

    const addBtn = container.querySelector(".nav-switch-btn");
    if (addBtn) {
      addBtn.addEventListener("click", () => {
        switchView("monitors");
        openAddMonitorModal();
      });
    }
    return;
  }

  // Render recent 4 targets in dashboard card
  const topSites = monitorsList.slice(0, 4);
  let html = `
    <div class="table-responsive">
      <table class="data-table">
        <thead>
          <tr>
            <th>Website</th>
            <th>Frequency</th>
            <th>State</th>
            <th style="text-align: right;">Action</th>
          </tr>
        </thead>
        <tbody>
  `;

  for (const site of topSites) {
    const statusBadgeClass = site.is_active ? "status-badge-active" : "status-badge-paused";
    const statusBadgeText = site.is_active ? "Active" : "Paused";
    const dotClass = site.is_active ? "badge-dot-green" : "badge-dot-gray";

    html += `
      <tr>
        <td>
          <div class="site-identity-cell">
            <span class="site-name-text">${escapeHtml(site.name)}</span>
            <span style="font-size: 0.74rem; color: var(--text-muted);">${escapeHtml(site.url)}</span>
          </div>
        </td>
        <td>${formatInterval(site.check_interval_minutes)}</td>
        <td>
          <span class="status-badge ${statusBadgeClass}">
            <span class="${dotClass}"></span>
            <span>${statusBadgeText}</span>
          </span>
        </td>
        <td style="text-align: right;">
          <div style="display: flex; gap: 6px; justify-content: flex-end;">
            <button class="btn btn-secondary btn-sm" onclick="checkMonitorNow(${site.id}, this)" title="Check Now">
              Check
            </button>
            <button class="btn btn-secondary btn-sm" onclick="openTimeMachineForSite(${site.id})" title="Time Machine">
              Time Machine
            </button>
            <button class="btn btn-secondary btn-sm" onclick="openViewModal(${site.id})">
              Details
            </button>
          </div>
        </td>
      </tr>
    `;
  }

  html += `
        </tbody>
      </table>
    </div>
    <div style="padding: 12px 18px; border-top: 1px solid var(--border-subtle); display: flex; justify-content: flex-end;">
      <button class="btn btn-secondary btn-sm" onclick="switchView('monitors')">
        View All (${monitorsList.length}) →
      </button>
    </div>
  `;

  container.innerHTML = html;
}

function formatInterval(minutes) {
  if (!minutes) return "60m";
  if (minutes < 60) return `${minutes}m`;
  if (minutes === 60) return "1h";
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

/* ==========================================================================
   6. Modal Dialogs & Form Actions
   ========================================================================== */

function openAddMonitorModal() {
  const modal = document.getElementById("modal-monitor-form");
  const form = document.getElementById("monitor-form");
  const title = document.getElementById("modal-form-title");
  const subtitle = document.getElementById("modal-form-subtitle");
  const btnText = document.getElementById("btn-submit-monitor-text");
  const errorBanner = document.getElementById("form-error-banner");

  if (!modal || !form) return;

  // Reset fields
  form.reset();
  document.getElementById("form-monitor-id").value = "";
  document.getElementById("form-monitor-active").checked = true;
  document.getElementById("form-monitor-active-label").textContent = "Active";

  const captureCheck = document.getElementById("form-monitor-capture-screenshots");
  if (captureCheck) {
    captureCheck.checked = false;
    const label = document.getElementById("form-monitor-capture-screenshots-label");
    if (label) label.textContent = "Disabled";
  }
  const threshInput = document.getElementById("form-monitor-visual-threshold");
  if (threshInput) threshInput.value = "1.0";

  if (title) title.textContent = "Add Website Monitor";
  if (subtitle) subtitle.textContent = "Register a web endpoint for automated change detection.";
  if (btnText) btnText.textContent = "Create Monitor";
  if (errorBanner) errorBanner.style.display = "none";

  modal.classList.add("active");
  setTimeout(() => {
    const urlInput = document.getElementById("form-monitor-url");
    if (urlInput) urlInput.focus();
  }, 100);
}

function openEditMonitorModal(siteId) {
  const site = monitorsList.find((s) => s.id === siteId);
  if (!site) {
    showToast("Monitor not found", "error");
    return;
  }

  // Close view modal if opened from it
  closeModal(document.getElementById("modal-monitor-view"));

  const modal = document.getElementById("modal-monitor-form");
  const form = document.getElementById("monitor-form");
  const title = document.getElementById("modal-form-title");
  const subtitle = document.getElementById("modal-form-subtitle");
  const btnText = document.getElementById("btn-submit-monitor-text");
  const errorBanner = document.getElementById("form-error-banner");

  if (!modal || !form) return;

  document.getElementById("form-monitor-id").value = site.id;
  document.getElementById("form-monitor-url").value = site.url;
  document.getElementById("form-monitor-name").value = site.name || "";
  document.getElementById("form-monitor-interval").value = site.check_interval_minutes || 60;
  document.getElementById("form-monitor-active").checked = site.is_active;
  document.getElementById("form-monitor-active-label").textContent = site.is_active ? "Active" : "Paused";

  const captureCheck = document.getElementById("form-monitor-capture-screenshots");
  if (captureCheck) {
    captureCheck.checked = Boolean(site.capture_screenshots);
    const label = document.getElementById("form-monitor-capture-screenshots-label");
    if (label) label.textContent = site.capture_screenshots ? "Enabled" : "Disabled";
  }
  const threshInput = document.getElementById("form-monitor-visual-threshold");
  if (threshInput) threshInput.value = site.visual_threshold != null ? site.visual_threshold : 1.0;

  if (title) title.textContent = "Edit Website Monitor";
  if (subtitle) subtitle.textContent = `Update settings for #${site.id}: ${site.name}`;
  if (btnText) btnText.textContent = "Save Changes";
  if (errorBanner) errorBanner.style.display = "none";

  modal.classList.add("active");
}

function openViewModal(siteId) {
  const site = monitorsList.find((s) => s.id === siteId);
  if (!site) {
    showToast("Monitor details unavailable", "error");
    return;
  }

  currentViewingSiteId = site.id;
  const modal = document.getElementById("modal-monitor-view");
  if (!modal) return;

  document.getElementById("view-modal-title").textContent = site.name;
  document.getElementById("view-modal-subtitle").textContent = `Monitor #${site.id} • Registered Target`;

  const urlEl = document.getElementById("view-modal-url");
  urlEl.textContent = site.url;
  urlEl.href = site.url;

  const statusBadge = document.getElementById("view-modal-status-badge");
  statusBadge.className = `status-badge ${site.is_active ? "status-badge-active" : "status-badge-paused"}`;
  statusBadge.textContent = site.is_active ? "Active" : "Paused";

  document.getElementById("view-modal-interval").textContent = formatInterval(site.check_interval_minutes);
  document.getElementById("view-modal-http-status").textContent = site.last_status_code
    ? `HTTP ${site.last_status_code}`
    : "Pending initial check";
  document.getElementById("view-modal-latency").textContent = site.last_response_time_ms
    ? `${site.last_response_time_ms} ms`
    : "—";
  document.getElementById("view-modal-last-check").textContent = site.last_checked_at
    ? new Date(site.last_checked_at).toLocaleString()
    : "Never";

  const visualStatusEl = document.getElementById("view-modal-visual-status");
  if (visualStatusEl) {
    visualStatusEl.textContent = site.capture_screenshots ? "Enabled (Playwright active)" : "Disabled";
    visualStatusEl.style.color = site.capture_screenshots ? "var(--accent-indigo)" : "var(--text-muted)";
  }
  const visualThreshEl = document.getElementById("view-modal-visual-threshold");
  if (visualThreshEl) {
    visualThreshEl.textContent = site.visual_threshold != null ? `${site.visual_threshold}%` : "1.0%";
  }

  document.getElementById("view-modal-created-at").textContent = site.created_at
    ? new Date(site.created_at).toLocaleString()
    : "—";

  modal.classList.add("active");
}

function openDeleteModal(siteId) {
  const site = monitorsList.find((s) => s.id === siteId);
  if (!site) {
    showToast("Monitor not found", "error");
    return;
  }

  // Close view modal if opened from it
  closeModal(document.getElementById("modal-monitor-view"));

  pendingDeleteSiteId = site.id;
  const modal = document.getElementById("modal-monitor-delete");
  const nameDisplay = document.getElementById("delete-monitor-name-display");

  if (nameDisplay) {
    nameDisplay.textContent = `"${site.name}" (${site.url})`;
  }

  if (modal) modal.classList.add("active");
}

function closeModal(modal) {
  if (modal) modal.classList.remove("active");
}

/* ==========================================================================
   7. Form Submission & API Calls
   ========================================================================== */

async function handleMonitorFormSubmit(event) {
  event.preventDefault();

  const idVal = document.getElementById("form-monitor-id").value;
  const isEdit = Boolean(idVal);
  const siteId = isEdit ? parseInt(idVal, 10) : null;

  let url = document.getElementById("form-monitor-url").value.trim();
  const name = document.getElementById("form-monitor-name").value.trim();
  const interval = parseInt(document.getElementById("form-monitor-interval").value, 10);
  const isActive = document.getElementById("form-monitor-active").checked;

  const errorBanner = document.getElementById("form-error-banner");
  const errorText = document.getElementById("form-error-text");
  const submitBtn = document.getElementById("btn-submit-monitor");
  const submitSpinner = submitBtn.querySelector(".btn-spinner");
  const submitText = document.getElementById("btn-submit-monitor-text");

  // Client Validation
  if (!url) {
    showFormError("Website URL is required.");
    return;
  }

  // Auto-prefix https:// if user didn't enter protocol
  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    if (!url.includes("://")) {
      url = "https://" + url;
      document.getElementById("form-monitor-url").value = url;
    }
  }

  // Set loading UI state
  submitBtn.disabled = true;
  if (submitSpinner) submitSpinner.style.display = "inline-block";
  if (errorBanner) errorBanner.style.display = "none";

  const captureScreenshots = document.getElementById("form-monitor-capture-screenshots")?.checked ?? false;
  const visualThreshold = parseFloat(document.getElementById("form-monitor-visual-threshold")?.value) || 1.0;

  const payload = {
    url: url,
    name: name || null,
    check_interval_minutes: interval,
    is_active: isActive,
    capture_screenshots: captureScreenshots,
    visual_threshold: visualThreshold,
  };

  try {
    const endpoint = isEdit ? `${API_BASE_URL}/api/sites/${siteId}` : `${API_BASE_URL}/api/sites`;
    const method = isEdit ? "PUT" : "POST";

    const response = await fetch(endpoint, {
      method: method,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      const msg = data.detail || `Server returned error ${response.status}`;
      showFormError(msg);
      return;
    }

    // Success
    closeModal(document.getElementById("modal-monitor-form"));
    showToast(
      isEdit ? `Monitor "${data.name}" updated successfully.` : `Monitor "${data.name}" created successfully!`,
      "success"
    );
    await fetchMonitors();
  } catch (err) {
    showFormError(err.message || "Network error communicating with ChangeScope backend.");
  } finally {
    submitBtn.disabled = false;
    if (submitSpinner) submitSpinner.style.display = "none";
  }
}

function showFormError(msg) {
  const errorBanner = document.getElementById("form-error-banner");
  const errorText = document.getElementById("form-error-text");
  if (errorBanner && errorText) {
    errorText.textContent = msg;
    errorBanner.style.display = "flex";
  }
}

async function handleConfirmDelete() {
  if (!pendingDeleteSiteId) return;

  const btn = document.getElementById("btn-confirm-delete");
  const spinner = btn ? btn.querySelector(".btn-spinner") : null;
  const siteToDelete = monitorsList.find((s) => s.id === pendingDeleteSiteId);
  const siteName = siteToDelete ? siteToDelete.name : `ID #${pendingDeleteSiteId}`;

  if (btn) btn.disabled = true;
  if (spinner) spinner.style.display = "inline-block";

  try {
    const response = await fetch(`${API_BASE_URL}/api/sites/${pendingDeleteSiteId}`, {
      method: "DELETE",
    });

    if (!response.ok && response.status !== 204) {
      throw new Error(`Deletion failed with HTTP ${response.status}`);
    }

    closeModal(document.getElementById("modal-monitor-delete"));
    showToast(`Monitor "${siteName}" deleted.`, "info");
    pendingDeleteSiteId = null;
    await fetchMonitors();
  } catch (err) {
    showToast(`Error deleting monitor: ${err.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
    if (spinner) spinner.style.display = "none";
  }
}

async function toggleMonitorState(siteId) {
  const site = monitorsList.find((s) => s.id === siteId);
  if (!site) return;

  const newStatus = !site.is_active;

  try {
    const response = await fetch(`${API_BASE_URL}/api/sites/${siteId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: newStatus }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const updated = await response.json();
    showToast(`Monitor "${updated.name}" is now ${updated.is_active ? "Active" : "Paused"}.`, "info");
    await fetchMonitors();
  } catch (err) {
    showToast(`Failed to update status: ${err.message}`, "error");
  }
}

/* ==========================================================================
   8. Change Detection Engine & Diff Inspector
   ========================================================================== */

/**
 * Trigger immediate manual site check via POST /api/sites/{site_id}/check
 */
async function checkMonitorNow(siteId, triggerButton = null) {
  const site = monitorsList.find((s) => s.id === siteId);
  const siteName = site ? site.name : `Monitor #${siteId}`;

  // Find button icon if trigger button passed, or lookup in DOM
  let iconToSpin = null;
  if (triggerButton) {
    iconToSpin = triggerButton.querySelector("svg");
    triggerButton.disabled = true;
    triggerButton.classList.add("checking");
  }
  if (iconToSpin) iconToSpin.classList.add("spinning");

  // Also check if the view modal check button is present and active
  const modalCheckBtn = document.getElementById("btn-view-check-now");
  const modalCheckIcon = modalCheckBtn ? modalCheckBtn.querySelector(".check-icon-spin") : null;
  const modalCheckText = document.getElementById("btn-view-check-text");
  const isModalTrigger = triggerButton === modalCheckBtn;

  if (isModalTrigger && modalCheckIcon) {
    modalCheckIcon.classList.add("spinning");
    if (modalCheckText) modalCheckText.textContent = "Checking...";
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/sites/${siteId}/check`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });

    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      const errMsg = result.detail || `Server returned HTTP ${response.status}`;
      showToast(`Check failed for "${siteName}": ${errMsg}`, "error");
      await fetchMonitors();
      return;
    }

    // Process result
    if (result.status === "baseline_created") {
      showToast(`Baseline established for "${siteName}". Future checks will detect content deviations.`, "success");
    } else if (result.status === "unchanged") {
      showToast(`No changes detected for "${siteName}". Content matches baseline.`, "info");
    } else if (result.status === "change_detected") {
      showToast(`Change detected on "${siteName}" (${result.message || "Content updated"})!`, "success");
    } else if (result.status === "check_failed") {
      showToast(`Check failed for "${siteName}": ${result.message || "Unknown error"}`, "error");
    } else {
      showToast(result.message || `Check completed for "${siteName}".`, "info");
    }

    // Refresh both monitors and change history
    await Promise.all([fetchMonitors(), fetchChangeHistory()]);

    // If view modal is open for this site, update view modal with fresh data
    if (currentViewingSiteId === siteId) {
      openViewModal(siteId);
    }

    // If Time Machine is currently viewing this site, refresh its snapshots
    if (tmCurrentSiteId === siteId) {
      await loadTimeMachineSnapshots(siteId);
    }
  } catch (err) {
    showToast(`Check error for "${siteName}": ${err.message}`, "error");
  } finally {
    if (triggerButton) {
      triggerButton.disabled = false;
      triggerButton.classList.remove("checking");
    }
    if (iconToSpin) iconToSpin.classList.remove("spinning");
    if (modalCheckIcon) modalCheckIcon.classList.remove("spinning");
    if (modalCheckText) modalCheckText.textContent = "Check Now";
  }
}

/**
 * Fetch detected changes history from backend
 */
async function fetchChangeHistory() {
  const container = document.getElementById("history-table-container");

  try {
    const response = await fetch(`${API_BASE_URL}/api/changes`);
    if (!response.ok) {
      throw new Error(`Failed to load change history (HTTP ${response.status})`);
    }

    const data = await response.json();
    changesList = Array.isArray(data) ? data : [];
    updateChangeMetrics();
    renderHistoryTable();
  } catch (error) {
    if (container) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-art" style="border-color: var(--accent-rose); color: var(--accent-rose);">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
          </div>
          <h3 class="empty-state-title">Error Loading Changes</h3>
          <p class="empty-state-desc">${escapeHtml(error.message)}. Please check your backend connection.</p>
          <button class="btn btn-secondary btn-sm" onclick="fetchChangeHistory()">Retry</button>
        </div>
      `;
    }
  }
}

/**
 * Render change events into Change History table
 */
function renderHistoryTable() {
  const container = document.getElementById("history-table-container");
  if (!container) return;

  if (changesList.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-art">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
          </svg>
        </div>
        <h3 class="empty-state-title">No Changes Detected Yet</h3>
        <p class="empty-state-desc">
          When website monitors run and observe differences in page text or content compared to their baseline,
          diff summaries and cryptographic hash histories will be recorded here automatically.
        </p>
        <button class="btn btn-secondary btn-sm" onclick="switchView('monitors')">
          Go to Monitors to Run Checks
        </button>
      </div>
    `;
    return;
  }

  let html = `
    <div class="table-responsive">
      <table class="data-table">
        <thead>
          <tr>
            <th>Detected At</th>
            <th>Website</th>
            <th>Summary / Diff Delta</th>
            <th style="text-align: right;">Action</th>
          </tr>
        </thead>
        <tbody>
  `;

  for (const change of changesList) {
    const timestamp = change.created_at || change.detected_at;
    const formattedDate = timestamp ? new Date(timestamp).toLocaleString() : "Recently";
    const siteTitle = change.site_name || `Monitor #${change.site_id}`;
    const changeSummary = change.summary || change.diff_summary || "Content changed";

    html += `
      <tr data-change-id="${change.id}">
        <td>
          <div style="display: flex; flex-direction: column; gap: 2px;">
            <span style="font-weight: 500; font-size: 0.84rem;">${formattedDate}</span>
            <span style="font-size: 0.72rem; color: var(--text-muted);">${formatTimeAgo(timestamp)}</span>
          </div>
        </td>
        <td>
          <div class="site-identity-cell">
            <span class="site-name-text">${escapeHtml(siteTitle)}</span>
            ${
              change.site_url
                ? `<a href="${escapeHtml(change.site_url)}" target="_blank" rel="noopener noreferrer" class="site-url-link" style="font-size: 0.74rem;">
                     <span>${escapeHtml(change.site_url)}</span>
                   </a>`
                : ""
            }
          </div>
        </td>
        <td>
          <span class="status-badge status-badge-changed">
            ${escapeHtml(changeSummary)}
          </span>
        </td>
        <td style="text-align: right;">
          <div class="action-btn-group" style="justify-content: flex-end;">
            <button class="btn btn-secondary btn-sm btn-inspect-diff" data-change-id="${change.id}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
              </svg>
              <span>Inspect Diff</span>
            </button>
            <button class="btn btn-secondary btn-sm btn-history-tm" data-site-id="${change.site_id}" title="Open Time Machine for this monitor">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 14 14"></polyline>
              </svg>
              <span>Time Machine</span>
            </button>
          </div>
        </td>
      </tr>
    `;
  }

  html += `
        </tbody>
      </table>
    </div>
  `;

  container.innerHTML = html;

  // Bind inspect diff buttons
  container.querySelectorAll(".btn-inspect-diff").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.getAttribute("data-change-id"), 10);
      openDiffModal(id);
    });
  });

  // Bind Time Machine buttons
  container.querySelectorAll(".btn-history-tm").forEach((btn) => {
    btn.addEventListener("click", () => {
      const siteId = parseInt(btn.getAttribute("data-site-id"), 10);
      openTimeMachineForSite(siteId);
    });
  });
}

/**
 * Open and populate Diff Inspector Modal
 */
function openDiffModal(changeId) {
  const change = changesList.find((c) => c.id === changeId);
  if (!change) {
    showToast("Change details not found.", "error");
    return;
  }

  currentViewingChangeId = change.id;
  const modal = document.getElementById("modal-diff-view");
  if (!modal) return;

  const siteTitle = change.site_name || `Monitor #${change.site_id}`;
  document.getElementById("diff-modal-title").textContent = `Diff: ${siteTitle}`;
  document.getElementById("diff-modal-subtitle").textContent = `${change.site_url || ""} • Change #${change.id}`;

  const summaryBadge = document.getElementById("diff-modal-summary-badge");
  if (summaryBadge) {
    summaryBadge.textContent = change.summary || change.diff_summary || "Content changed";
    summaryBadge.className = "status-badge status-badge-changed";
  }

  const timeEl = document.getElementById("diff-modal-time");
  if (timeEl) {
    const timestamp = change.created_at || change.detected_at;
    timeEl.textContent = timestamp ? `Detected at ${new Date(timestamp).toLocaleString()}` : "";
  }

  // Format Unified Diff with line-by-line colored spans
  const unifiedOutput = document.getElementById("diff-unified-output");
  const diffText = change.details || change.diff_text || "";
  if (unifiedOutput) {
    if (diffText && diffText.trim()) {
      const lines = diffText.split("\n");
      const formattedLines = lines.map((line) => {
        const escaped = escapeHtml(line);
        if (line.startsWith("+++") || line.startsWith("---")) {
          return `<span class="diff-line-info">${escaped}</span>`;
        } else if (line.startsWith("+")) {
          return `<span class="diff-line-add">${escaped}</span>`;
        } else if (line.startsWith("-")) {
          return `<span class="diff-line-del">${escaped}</span>`;
        } else if (line.startsWith("@@")) {
          return `<span class="diff-line-info">${escaped}</span>`;
        }
        return `<span>${escaped}</span>`;
      });
      unifiedOutput.innerHTML = formattedLines.join("\n");
    } else {
      unifiedOutput.textContent = "// No line-by-line differences recorded.";
    }
  }

  // Set Before and After Text
  const beforeOutput = document.getElementById("diff-before-output");
  if (beforeOutput) {
    beforeOutput.textContent = change.previous_content || "(No previous baseline text available)";
  }

  const afterOutput = document.getElementById("diff-after-output");
  if (afterOutput) {
    afterOutput.textContent = change.new_content || "(No modified text recorded)";
  }

  // Reset tab selection to "unified"
  switchDiffTab("unified");

  modal.classList.add("active");
}

function switchDiffTab(tabName) {
  const tabs = document.querySelectorAll(".diff-tab-btn");
  tabs.forEach((tab) => {
    tab.classList.toggle("active", tab.getAttribute("data-tab") === tabName);
  });

  const panes = document.querySelectorAll(".diff-tab-pane");
  panes.forEach((pane) => {
    pane.classList.toggle("active", pane.id === `diff-pane-${tabName}`);
  });
}

/* ==========================================================================
   8.5. Time Machine & Version History Engine
   ========================================================================== */

/**
 * Initialize Time Machine for a selected monitor target
 */
async function initTimeMachine(preferredSiteId = null) {
  const siteSelect = document.getElementById("tm-site-select");
  if (!siteSelect) return;

  // Ensure monitorsList is loaded
  if (!monitorsList || monitorsList.length === 0) {
    await fetchMonitors();
  }

  // Populate monitor selector dropdown
  siteSelect.innerHTML = "";
  if (!monitorsList || monitorsList.length === 0) {
    siteSelect.innerHTML = `<option value="">No monitors configured</option>`;
    showTimeMachineEmptyState("no-monitors");
    return;
  }

  monitorsList.forEach((site) => {
    const opt = document.createElement("option");
    opt.value = site.id;
    opt.textContent = `${site.name} (${site.url})`;
    siteSelect.appendChild(opt);
  });

  // Resolve target monitor: preferred, existing, or first
  let targetId = preferredSiteId || tmCurrentSiteId;
  const exists = monitorsList.some((s) => s.id === targetId);
  if (!exists) {
    targetId = monitorsList[0].id;
  }

  siteSelect.value = String(targetId);
  await loadTimeMachineSnapshots(targetId);
}

/**
 * Load all snapshots for a monitor in chronological order
 */
async function loadTimeMachineSnapshots(siteId) {
  tmCurrentSiteId = parseInt(siteId, 10);
  const emptyContainer = document.getElementById("tm-empty-container");
  const workspace = document.getElementById("tm-workspace");

  try {
    const res = await fetch(`${API_BASE_URL}/api/sites/${tmCurrentSiteId}/snapshots?order=asc`);
    if (!res.ok) {
      if (res.status === 404) {
        showTimeMachineEmptyState("not-found");
        return;
      }
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();
    tmSnapshots = Array.isArray(data) ? data : [];

    if (tmSnapshots.length === 0) {
      showTimeMachineEmptyState("no-snapshots");
      return;
    }

    if (emptyContainer) emptyContainer.style.display = "none";
    if (workspace) workspace.style.display = "flex";

    // Setup scrubber slider
    const slider = document.getElementById("tm-slider");
    if (slider) {
      slider.min = "0";
      slider.max = String(tmSnapshots.length - 1);
      slider.value = String(tmSnapshots.length - 1);
    }

    // Render timeline ticks
    renderScrubberTicks();

    // Populate comparison dropdowns
    populateCompareDropdowns();

    // Select latest snapshot by default
    selectTimeMachineVersion(tmSnapshots.length - 1);
  } catch (err) {
    console.error("Error loading Time Machine snapshots:", err);
    showToast(`Failed to load version history: ${err.message}`, "error");
  }
}

/**
 * Show contextual honest empty state in Time Machine view
 */
function showTimeMachineEmptyState(reason) {
  const emptyContainer = document.getElementById("tm-empty-container");
  const workspace = document.getElementById("tm-workspace");
  if (workspace) workspace.style.display = "none";
  if (!emptyContainer) return;

  emptyContainer.style.display = "block";

  if (reason === "no-monitors") {
    emptyContainer.innerHTML = `
      <div class="empty-state" style="padding: 48px 24px;">
        <div class="empty-state-art">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 14 14"></polyline>
          </svg>
        </div>
        <h3 class="empty-state-title">No Monitored Websites Found</h3>
        <p class="empty-state-desc">
          Add at least one website monitor to start capturing historical versions and navigating changes across time.
        </p>
        <button class="btn btn-primary btn-sm" onclick="openAddMonitorModal()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          <span>Add Your First Monitor</span>
        </button>
      </div>
    `;
  } else if (reason === "no-snapshots") {
    const site = monitorsList.find((s) => s.id === tmCurrentSiteId);
    const siteName = site ? site.name : `Monitor #${tmCurrentSiteId}`;
    emptyContainer.innerHTML = `
      <div class="empty-state" style="padding: 48px 24px;">
        <div class="empty-state-art">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 14 14"></polyline>
          </svg>
        </div>
        <h3 class="empty-state-title">No Version Snapshots for "${escapeHtml(siteName)}"</h3>
        <p class="empty-state-desc">
          This target has not captured any baseline or comparison snapshots yet.
          Run a manual check to create its inaugural baseline version.
        </p>
        <button class="btn btn-primary btn-sm" onclick="captureSnapshotNow()">
          <svg class="check-icon-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"></polyline>
            <polyline points="1 20 1 14 7 14"></polyline>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
          <span>Capture Baseline Snapshot Now</span>
        </button>
      </div>
    `;
  } else {
    emptyContainer.innerHTML = `
      <div class="empty-state" style="padding: 48px 24px;">
        <h3 class="empty-state-title">Monitor Target Not Found</h3>
        <p class="empty-state-desc">The requested website monitor was not found in the database.</p>
      </div>
    `;
  }
}

/**
 * Capture a new snapshot for the active Time Machine monitor
 */
async function captureSnapshotNow() {
  if (!tmCurrentSiteId) return;
  const btn = document.getElementById("tm-btn-check-now");
  await checkMonitorNow(tmCurrentSiteId, btn);
  await loadTimeMachineSnapshots(tmCurrentSiteId);
}

/**
 * Render tick marks across the scrubber slider
 */
function renderScrubberTicks() {
  const container = document.getElementById("tm-slider-ticks");
  if (!container) return;
  container.innerHTML = "";
  if (tmSnapshots.length <= 1) return;

  const total = tmSnapshots.length;
  const step = total > 20 ? Math.ceil(total / 20) : 1;

  for (let i = 0; i < total; i += step) {
    const tick = document.createElement("span");
    tick.className = "tm-tick";
    const percent = total > 1 ? (i / (total - 1)) * 100 : 0;
    tick.style.left = `${percent}%`;
    const snap = tmSnapshots[i];
    if (snap.change_label === "change_detected") {
      tick.classList.add("tick-changed");
    } else if (snap.change_label === "baseline") {
      tick.classList.add("tick-baseline");
    }
    container.appendChild(tick);
  }
}

/**
 * Render the left chronological version timeline list
 */
function renderTimeMachineTimelineList() {
  const container = document.getElementById("tm-timeline-list");
  const countBadge = document.getElementById("tm-timeline-count");
  if (!container) return;

  if (countBadge) {
    countBadge.textContent = `${tmSnapshots.length} version${tmSnapshots.length === 1 ? "" : "s"}`;
  }

  const indices = tmSnapshots.map((_, i) => i);
  if (tmSortOrder === "desc") {
    indices.reverse();
  }

  let html = "";
  for (const idx of indices) {
    const snap = tmSnapshots[idx];
    const isCurrent = idx === tmCurrentIndex;
    const versionNum = idx + 1;
    const dateFormatted = new Date(snap.created_at).toLocaleString();
    const timeAgo = formatTimeAgo(snap.created_at);

    let badgeClass = "status-badge-baseline";
    let badgeText = "Baseline";
    if (snap.change_label === "change_detected") {
      badgeClass = "status-badge-changed";
      badgeText = "Change Detected";
    } else if (snap.change_label === "unchanged") {
      badgeClass = "status-badge-active";
      badgeText = "Unchanged";
    }

    const latency = snap.response_time_ms ? `${Math.round(snap.response_time_ms)}ms` : "";
    const lines = snap.line_count !== undefined ? `${snap.line_count} lines` : "";

    html += `
      <div class="tm-timeline-item ${isCurrent ? "active" : ""}" data-index="${idx}" role="button" tabindex="0">
        <div class="tm-item-header">
          <div class="tm-item-version">
            <span class="tm-ver-title">v${versionNum}</span>
            <span class="status-badge ${badgeClass}">${badgeText}</span>
          </div>
          <span class="tm-item-time">${timeAgo}</span>
        </div>
        <div class="tm-item-meta">
          <span>${dateFormatted}</span>
          <span>HTTP ${snap.status_code}</span>
          ${latency ? `<span>${latency}</span>` : ""}
          ${lines ? `<span>${lines}</span>` : ""}
        </div>
      </div>
    `;
  }

  container.innerHTML = html;

  // Bind click & keydown on timeline items
  container.querySelectorAll(".tm-timeline-item").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = parseInt(el.getAttribute("data-index"), 10);
      selectTimeMachineVersion(idx);
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        const idx = parseInt(el.getAttribute("data-index"), 10);
        selectTimeMachineVersion(idx);
      }
    });
  });

  // Ensure active element is scrolled into view smoothly
  const activeEl = container.querySelector(".tm-timeline-item.active");
  if (activeEl) {
    activeEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

/**
 * Select a specific version index on the scrubber and timeline
 */
function selectTimeMachineVersion(index) {
  if (!tmSnapshots || tmSnapshots.length === 0) return;
  index = Math.max(0, Math.min(tmSnapshots.length - 1, index));
  tmCurrentIndex = index;

  const snap = tmSnapshots[index];
  const versionNum = index + 1;
  const total = tmSnapshots.length;

  // Update scrubber slider & info
  const slider = document.getElementById("tm-slider");
  if (slider) slider.value = String(index);

  const versionIndicator = document.getElementById("tm-version-indicator");
  if (versionIndicator) {
    versionIndicator.textContent = `Version ${versionNum} of ${total}`;
  }

  const scrubberTimestamp = document.getElementById("tm-scrubber-timestamp");
  if (scrubberTimestamp) {
    const formatted = new Date(snap.created_at).toLocaleString();
    scrubberTimestamp.textContent = `Captured ${formatted} (${formatTimeAgo(snap.created_at)})`;
  }

  const scrubberBadge = document.getElementById("tm-scrubber-status-badge");
  if (scrubberBadge) {
    if (snap.change_label === "baseline") {
      scrubberBadge.className = "status-badge status-badge-baseline";
      scrubberBadge.textContent = "Baseline (v1)";
    } else if (snap.change_label === "change_detected") {
      scrubberBadge.className = "status-badge status-badge-changed";
      scrubberBadge.textContent = "Change Detected";
    } else {
      scrubberBadge.className = "status-badge status-badge-active";
      scrubberBadge.textContent = "Unchanged Check";
    }
  }

  // Update navigation button states
  const btnFirst = document.getElementById("tm-btn-first");
  const btnPrev = document.getElementById("tm-btn-prev");
  const btnNext = document.getElementById("tm-btn-next");
  const btnLatest = document.getElementById("tm-btn-latest");

  if (btnFirst) btnFirst.disabled = index === 0;
  if (btnPrev) btnPrev.disabled = index === 0;
  if (btnNext) btnNext.disabled = index === total - 1;
  if (btnLatest) btnLatest.disabled = index === total - 1;

  const currentLabel = document.getElementById("tm-slider-current-label");
  if (currentLabel) {
    currentLabel.textContent = `Viewing v${versionNum}`;
  }

  // Update timeline list highlighting
  renderTimeMachineTimelineList();

  // Update active pane content
  if (tmViewerMode === "inspect") {
    renderTimeMachineInspect(snap);
  } else if (tmViewerMode === "compare") {
    const targetSelect = document.getElementById("tm-compare-target-select");
    const baseSelect = document.getElementById("tm-compare-base-select");
    if (targetSelect && baseSelect) {
      targetSelect.value = String(snap.id);
      if (baseSelect.value === targetSelect.value && index > 0) {
        baseSelect.value = String(tmSnapshots[index - 1].id);
      }
      runTimeMachineComparison();
    }
  }
}

/**
 * Render the Inspector pane for a single snapshot
 */
function renderTimeMachineInspect(snap) {
  if (!snap) return;

  const metaId = document.getElementById("tm-meta-id");
  if (metaId) metaId.textContent = `#${snap.id}`;

  const metaDate = document.getElementById("tm-meta-date");
  if (metaDate) metaDate.textContent = new Date(snap.created_at).toLocaleString();

  const metaStatus = document.getElementById("tm-meta-status");
  if (metaStatus) {
    metaStatus.innerHTML = `<span class="status-badge ${snap.status_code < 400 ? "status-badge-active" : "status-badge-error"}">HTTP ${snap.status_code}</span>`;
  }

  const metaLatency = document.getElementById("tm-meta-latency");
  if (metaLatency) {
    metaLatency.textContent = snap.response_time_ms ? `${Math.round(snap.response_time_ms)} ms` : "N/A";
  }

  const metaSize = document.getElementById("tm-meta-size");
  if (metaSize) {
    const lines = snap.line_count !== undefined ? snap.line_count : (snap.text_content ? snap.text_content.split("\n").length : 0);
    const chars = snap.char_count !== undefined ? snap.char_count : (snap.text_content ? snap.text_content.length : 0);
    metaSize.textContent = `${lines} lines (${chars} chars)`;
  }

  const metaHash = document.getElementById("tm-meta-hash");
  if (metaHash) {
    metaHash.textContent = snap.content_hash || "—";
    metaHash.title = `Cryptographic SHA-256: ${snap.content_hash}`;
  }

  const textOutput = document.getElementById("tm-text-content");
  if (textOutput) {
    if (snap.text_content && snap.text_content.trim()) {
      textOutput.textContent = snap.text_content;
    } else {
      textOutput.textContent = "// Empty document content (0 characters extracted).";
    }
  }
}

/**
 * Populate base and target selectors for Before/After compare mode
 */
function populateCompareDropdowns() {
  const baseSelect = document.getElementById("tm-compare-base-select");
  const targetSelect = document.getElementById("tm-compare-target-select");
  if (!baseSelect || !targetSelect) return;

  baseSelect.innerHTML = "";
  targetSelect.innerHTML = "";

  tmSnapshots.forEach((snap, idx) => {
    const versionNum = idx + 1;
    const label = `v${versionNum} (#${snap.id}) — ${new Date(snap.created_at).toLocaleDateString()} (${snap.change_label})`;

    const optBase = document.createElement("option");
    optBase.value = String(snap.id);
    optBase.textContent = label;
    baseSelect.appendChild(optBase);

    const optTarget = document.createElement("option");
    optTarget.value = String(snap.id);
    optTarget.textContent = label;
    targetSelect.appendChild(optTarget);
  });

  if (tmSnapshots.length > 1) {
    baseSelect.value = String(tmSnapshots[0].id);
    targetSelect.value = String(tmSnapshots[tmSnapshots.length - 1].id);
  } else if (tmSnapshots.length === 1) {
    baseSelect.value = String(tmSnapshots[0].id);
    targetSelect.value = String(tmSnapshots[0].id);
  }
}

/**
 * Perform server-side snapshot comparison and render diff highlights
 */
async function runTimeMachineComparison() {
  const baseSelect = document.getElementById("tm-compare-base-select");
  const targetSelect = document.getElementById("tm-compare-target-select");
  if (!baseSelect || !targetSelect) return;

  const baseId = parseInt(baseSelect.value, 10);
  const targetId = parseInt(targetSelect.value, 10);
  if (!baseId || !targetId) return;

  const addedBadge = document.getElementById("tm-diff-added-badge");
  const removedBadge = document.getElementById("tm-diff-removed-badge");
  const summaryBadge = document.getElementById("tm-diff-summary-badge");
  const unifiedCode = document.getElementById("tm-diff-unified-code");
  const sideBaseCode = document.getElementById("tm-side-base-code");
  const sideTargetCode = document.getElementById("tm-side-target-code");
  const sideBaseLabel = document.getElementById("tm-side-base-label");
  const sideTargetLabel = document.getElementById("tm-side-target-label");

  if (summaryBadge) {
    summaryBadge.textContent = "Comparing...";
    summaryBadge.className = "status-badge status-badge-paused";
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/snapshots/compare?base_id=${baseId}&target_id=${targetId}`);
    if (!res.ok) {
      throw new Error(`Comparison API returned HTTP ${res.status}`);
    }

    const data = await res.json();

    if (addedBadge) addedBadge.textContent = `+${data.added_lines_count} lines`;
    if (removedBadge) removedBadge.textContent = `-${data.removed_lines_count} lines`;
    if (summaryBadge) {
      if (data.is_identical) {
        summaryBadge.textContent = "Identical (0 differences)";
        summaryBadge.className = "status-badge status-badge-active";
      } else {
        summaryBadge.textContent = data.summary || "Changes Detected";
        summaryBadge.className = "status-badge status-badge-changed";
      }
    }

    // Render Unified Diff with line-by-line highlight spans
    if (unifiedCode) {
      if (data.is_identical) {
        unifiedCode.textContent = "// Versions are identical. No differences found between these two snapshots.";
      } else if (data.diff_text && data.diff_text.trim()) {
        const lines = data.diff_text.split("\n");
        const formatted = lines.map((line) => {
          const esc = escapeHtml(line);
          if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) {
            return `<span class="diff-line-info">${esc}</span>`;
          } else if (line.startsWith("+")) {
            return `<span class="diff-line-add">${esc}</span>`;
          } else if (line.startsWith("-")) {
            return `<span class="diff-line-del">${esc}</span>`;
          }
          return `<span>${esc}</span>`;
        });
        unifiedCode.innerHTML = formatted.join("\n");
      } else {
        unifiedCode.textContent = "// No line-by-line diff content available.";
      }
    }

    // Render Side-by-Side view
    if (sideBaseCode) sideBaseCode.textContent = data.base_text || "(Empty document)";
    if (sideTargetCode) sideTargetCode.textContent = data.target_text || "(Empty document)";
    if (sideBaseLabel) sideBaseLabel.textContent = `Base: #${baseId} (${new Date(data.base_created_at).toLocaleString()})`;
    if (sideTargetLabel) sideTargetLabel.textContent = `Target: #${targetId} (${new Date(data.target_created_at).toLocaleString()})`;
  } catch (err) {
    console.error("Comparison error:", err);
    if (summaryBadge) {
      summaryBadge.textContent = "Comparison Failed";
      summaryBadge.className = "status-badge status-badge-error";
    }
    if (unifiedCode) {
      unifiedCode.textContent = `// Error loading comparison: ${err.message}`;
    }
  }
}

/**
 * Switch between Single Version Inspector and Before/After Compare tool
 */
function switchTimeMachineViewerTab(mode) {
  tmViewerMode = mode;
  const tabInspect = document.getElementById("tm-tab-btn-inspect");
  const tabCompare = document.getElementById("tm-tab-btn-compare");
  const paneInspect = document.getElementById("tm-pane-inspect");
  const paneCompare = document.getElementById("tm-pane-compare");
  const inspectActions = document.getElementById("tm-inspect-actions");

  if (tabInspect) tabInspect.classList.toggle("active", mode === "inspect");
  if (tabCompare) tabCompare.classList.toggle("active", mode === "compare");

  if (paneInspect) {
    paneInspect.style.display = mode === "inspect" ? "block" : "none";
    paneInspect.classList.toggle("active", mode === "inspect");
  }
  if (paneCompare) {
    paneCompare.style.display = mode === "compare" ? "block" : "none";
    paneCompare.classList.toggle("active", mode === "compare");
  }
  if (inspectActions) {
    inspectActions.style.display = mode === "inspect" ? "flex" : "none";
  }

  if (mode === "inspect") {
    if (tmSnapshots.length > 0) {
      renderTimeMachineInspect(tmSnapshots[tmCurrentIndex]);
    }
  } else if (mode === "compare") {
    runTimeMachineComparison();
  }
}

/**
 * Switch compare view between Unified Diff and Side-by-Side
 */
function switchTimeMachineCompareSubtab(subtab) {
  tmCompareSubtab = subtab;
  const tabUnified = document.getElementById("tm-diff-tab-unified");
  const tabSide = document.getElementById("tm-diff-tab-side");
  const paneUnified = document.getElementById("tm-diff-unified-pane");
  const paneSide = document.getElementById("tm-diff-side-pane");

  if (tabUnified) tabUnified.classList.toggle("active", subtab === "unified");
  if (tabSide) tabSide.classList.toggle("active", subtab === "side");

  if (paneUnified) paneUnified.style.display = subtab === "unified" ? "block" : "none";
  if (paneSide) paneSide.style.display = subtab === "side" ? "grid" : "none";
}

/**
 * Copy text of the currently inspected version to system clipboard
 */
function copyCurrentVersionText() {
  if (!tmSnapshots || tmSnapshots.length === 0) return;
  const snap = tmSnapshots[tmCurrentIndex];
  if (!snap || !snap.text_content) {
    showToast("No text content in this version to copy.", "info");
    return;
  }

  const onSuccess = () => {
    showToast(`Version ${tmCurrentIndex + 1} text copied to clipboard!`, "success");
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(snap.text_content).then(onSuccess).catch(() => {
      fallbackCopy(snap.text_content);
    });
  } else {
    fallbackCopy(snap.text_content);
  }

  function fallbackCopy(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      onSuccess();
    } catch {
      showToast("Could not access system clipboard.", "error");
    } finally {
      document.body.removeChild(textarea);
    }
  }
}

/**
 * Swap base and target versions in Before/After comparison
 */
function swapCompareVersions() {
  const baseSelect = document.getElementById("tm-compare-base-select");
  const targetSelect = document.getElementById("tm-compare-target-select");
  if (!baseSelect || !targetSelect) return;
  const temp = baseSelect.value;
  baseSelect.value = targetSelect.value;
  targetSelect.value = temp;
  runTimeMachineComparison();
}

/**
 * Toggle chronological / reverse sorting of the version list
 */
function toggleTimeMachineSort() {
  tmSortOrder = tmSortOrder === "asc" ? "desc" : "asc";
  const btn = document.getElementById("tm-btn-sort-toggle");
  if (btn) {
    btn.setAttribute(
      "title",
      tmSortOrder === "asc"
        ? "Sort: Oldest First (Click for Newest First)"
        : "Sort: Newest First (Click for Oldest First)"
    );
  }
  renderTimeMachineTimelineList();
}

/**
 * Switch to Time Machine view focused on a specific monitor
 */
function openTimeMachineForSite(siteId) {
  tmCurrentSiteId = parseInt(siteId, 10);
  document.querySelectorAll(".modal-backdrop.active").forEach(closeModal);
  switchView("timemachine");
  initTimeMachine(tmCurrentSiteId);
}

/* ==========================================================================
   8.6. Visual Changes & Screenshot Comparison Engine (Prompt 6)
   ========================================================================== */

let vcCurrentSiteId = null;
let vcLoading = false;

function formatBytes(bytes) {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

/**
 * Focus and open Visual Changes section for a specific site
 */
function openVisualChangesForSite(siteId) {
  const numericId = parseInt(siteId, 10);
  if (!numericId) return;

  document.querySelectorAll(".modal-backdrop.active").forEach(closeModal);
  switchView("monitors");
  initVisualChanges(numericId);

  const section = document.getElementById("visual-changes-section");
  if (section) {
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

/**
 * Initialize or re-populate the Visual Changes target dropdown and load comparison
 */
async function initVisualChanges(preferredSiteId = null) {
  const siteSelect = document.getElementById("vc-site-select");
  const contentBody = document.getElementById("vc-content-body");
  if (!siteSelect || !contentBody) return;

  // If monitorsList empty, show empty state
  if (!monitorsList || monitorsList.length === 0) {
    siteSelect.innerHTML = `<option value="">No monitors registered</option>`;
    contentBody.innerHTML = `
      <div class="vc-empty-box">
        <div class="vc-empty-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
            <line x1="8" y1="21" x2="16" y2="21"></line>
            <line x1="12" y1="17" x2="12" y2="21"></line>
          </svg>
        </div>
        <h4 class="vc-empty-title">No Monitored Websites</h4>
        <p class="vc-empty-desc">Register a website monitor first to enable visual screenshot rendering and diff tracking.</p>
        <button class="btn btn-primary btn-sm" onclick="openAddMonitorModal()">Add First Monitor</button>
      </div>
    `;
    return;
  }

  // Populate dropdown options
  siteSelect.innerHTML = "";
  monitorsList.forEach((site) => {
    const opt = document.createElement("option");
    opt.value = site.id;
    opt.textContent = `${site.name} (${site.url})`;
    siteSelect.appendChild(opt);
  });

  // Determine target site
  let targetId = preferredSiteId || vcCurrentSiteId;
  const exists = monitorsList.some((s) => s.id === targetId);
  if (!exists) {
    targetId = monitorsList[0].id;
  }

  vcCurrentSiteId = targetId;
  siteSelect.value = String(targetId);

  await loadVisualComparison(targetId);
}

/**
 * Fetch and render visual comparison data for a monitor
 */
async function loadVisualComparison(siteId) {
  const contentBody = document.getElementById("vc-content-body");
  if (!contentBody) return;

  const site = monitorsList.find((s) => s.id === siteId);
  if (!site) return;

  contentBody.innerHTML = `
    <div class="loading-state" style="padding: 36px 20px;">
      <div class="loading-spinner"></div>
      <p>Loading visual screenshot comparison for ${escapeHtml(site.name)}...</p>
    </div>
  `;

  try {
    const response = await fetch(`${API_BASE_URL}/api/sites/${siteId}/visual-comparison`);
    if (!response.ok) {
      throw new Error(`Failed to retrieve visual comparison (HTTP ${response.status})`);
    }

    const data = await response.json();
    renderVisualChangesSection(data, site);
  } catch (err) {
    contentBody.innerHTML = `
      <div class="vc-empty-box">
        <div class="vc-empty-icon" style="color: var(--accent-rose); border-color: var(--accent-rose);">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
        </div>
        <h4 class="vc-empty-title">Error Loading Visual Comparison</h4>
        <p class="vc-empty-desc">${escapeHtml(err.message)}</p>
        <button class="btn btn-secondary btn-sm" onclick="loadVisualComparison(${siteId})">Retry</button>
      </div>
    `;
  }
}

/**
 * Render visual comparison cards based on status
 */
function renderVisualChangesSection(data, site) {
  const contentBody = document.getElementById("vc-content-body");
  if (!contentBody) return;

  // Normalize status and screenshot objects to support current and historical backend responses
  const hasBaseline = Boolean(data.has_baseline || data.baseline_screenshot || data.baseline_snapshot);
  const hasComparison = Boolean(data.has_comparison);
  const status = data.status || (!hasBaseline ? "no_screenshots" : (hasComparison ? "comparison_ready" : "baseline_only"));

  const latest = data.latest_screenshot || data.latest_snapshot;
  const prev = data.previous_snapshot || data.baseline_screenshot || data.baseline_snapshot;
  const threshold = data.threshold != null ? data.threshold : (data.visual_threshold != null ? data.visual_threshold : 1.0);

  // 1. No screenshots yet
  if (status === "no_screenshots" || !hasBaseline) {
    contentBody.innerHTML = `
      <div class="vc-empty-box">
        <div class="vc-empty-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
            <circle cx="12" cy="13" r="4"></circle>
          </svg>
        </div>
        <h4 class="vc-empty-title">No Visual Snapshots Captured Yet</h4>
        <p class="vc-empty-desc">
          Capture a headless Playwright browser rendering to establish an initial visual baseline for "${escapeHtml(site.name)}".
          Subsequent captures will compare pixel differences using Pillow.
        </p>
        <button class="btn btn-primary btn-sm" onclick="captureVisualScreenshot(${site.id})">
          <svg class="camera-icon-spin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
            <circle cx="12" cy="13" r="4"></circle>
          </svg>
          <span>Capture Baseline Screenshot</span>
        </button>
      </div>
    `;
    return;
  }

  // 2. Baseline only (first screenshot)
  if ((status === "baseline_only" || !hasComparison) && latest) {
    const snap = latest;
    contentBody.innerHTML = `
      <div class="vc-summary-banner">
        <div class="vc-summary-left">
          <span class="vc-diff-pill baseline">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
            Baseline Established
          </span>
          <span style="font-size: 0.82rem; color: var(--text-secondary);">
            Initial visual reference recorded at ${snap.screenshot_width || snap.width || 1280}&times;${snap.screenshot_height || snap.height || 800} viewport. Future captures will compare against this baseline.
          </span>
        </div>
        <div class="vc-summary-right">
          <span>Captured: ${new Date(snap.created_at).toLocaleString()}</span>
          <button class="btn btn-primary btn-sm" onclick="captureVisualScreenshot(${site.id})">
            Capture New Screenshot
          </button>
        </div>
      </div>

      <div class="vc-grid" style="grid-template-columns: minmax(320px, 680px);">
        <div class="vc-screenshot-box">
          <div class="vc-box-header">
            <span class="vc-box-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 14 14"></polyline></svg>
              Baseline Screenshot #${snap.snapshot_id || snap.id}
            </span>
            <span class="vc-box-meta">${snap.screenshot_width || snap.width || 1280}&times;${snap.screenshot_height || snap.height || 800} &bull; ${formatBytes(snap.screenshot_size_bytes || snap.size_bytes || 0)}</span>
          </div>
          <div class="vc-screenshot-frame">
            <a href="${snap.screenshot_url}" target="_blank" rel="noopener noreferrer" title="Click to view full image in new tab">
              <img src="${snap.screenshot_url}" alt="Baseline Screenshot" loading="lazy" />
            </a>
          </div>
          <div class="vc-box-footer">
            <span>Target: ${escapeHtml(site.url)}</span>
            <a href="${snap.screenshot_url}" target="_blank" rel="noopener noreferrer" class="detail-link">Open Full Resolution &nearr;</a>
          </div>
        </div>
      </div>
    `;
    return;
  }

  // 3. Comparison ready (2+ screenshots)
  if ((status === "comparison_ready" || hasComparison) && latest) {
    const diffPct = data.diff_percent != null ? data.diff_percent : 0.0;
    const isChanged = Boolean(data.visual_change_detected);

    let html = `
      <div class="vc-summary-banner">
        <div class="vc-summary-left">
          <span class="vc-diff-pill ${isChanged ? 'changed' : 'unchanged'}">
            ${isChanged ? 'Visual Change Detected' : 'Visually Unchanged'} (${diffPct.toFixed(2)}% Difference)
          </span>
          <span style="font-size: 0.82rem; color: var(--text-secondary);">
            Configured threshold: <strong>${threshold}%</strong> &bull;
            ${isChanged
              ? `Pixel variation exceeds threshold by ${(diffPct - threshold).toFixed(2)}%`
              : `Pixel variance (${diffPct.toFixed(2)}%) is within acceptable threshold (&le; ${threshold}%)`
            }
          </span>
        </div>
        <div class="vc-summary-right">
          <span>Latest check: ${new Date(latest.created_at).toLocaleString()}</span>
          <button class="btn btn-primary btn-sm" onclick="captureVisualScreenshot(${site.id})">
            Capture Now
          </button>
        </div>
      </div>

      <div class="vc-grid">
    `;

    // Card 1: Previous / Baseline Screenshot
    if (prev) {
      html += `
        <div class="vc-screenshot-box">
          <div class="vc-box-header">
            <span class="vc-box-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 14 14"></polyline></svg>
              ${prev.is_baseline ? 'Baseline Reference' : 'Previous Snapshot'} #${prev.snapshot_id || prev.id}
            </span>
            <span class="vc-box-meta">${prev.screenshot_width || prev.width || 1280}&times;${prev.screenshot_height || prev.height || 800} &bull; ${formatBytes(prev.screenshot_size_bytes || prev.size_bytes || 0)}</span>
          </div>
          <div class="vc-screenshot-frame">
            <a href="${prev.screenshot_url}" target="_blank" rel="noopener noreferrer" title="Click to view full image in new tab">
              <img src="${prev.screenshot_url}" alt="Previous Screenshot" loading="lazy" />
            </a>
          </div>
          <div class="vc-box-footer">
            <span>Captured ${formatTimeAgo(prev.created_at)}</span>
            <a href="${prev.screenshot_url}" target="_blank" rel="noopener noreferrer" class="detail-link">Open Full &nearr;</a>
          </div>
        </div>
      `;
    }

    // Card 2: Latest Screenshot
    html += `
      <div class="vc-screenshot-box">
        <div class="vc-box-header">
          <span class="vc-box-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
            Latest Snapshot #${latest.snapshot_id || latest.id}
          </span>
          <span class="vc-box-meta">${latest.screenshot_width || latest.width || 1280}&times;${latest.screenshot_height || latest.height || 800} &bull; ${formatBytes(latest.screenshot_size_bytes || latest.size_bytes || 0)}</span>
        </div>
        <div class="vc-screenshot-frame">
          <a href="${latest.screenshot_url}" target="_blank" rel="noopener noreferrer" title="Click to view full image in new tab">
            <img src="${latest.screenshot_url}" alt="Latest Screenshot" loading="lazy" />
          </a>
        </div>
        <div class="vc-box-footer">
          <span>Captured ${formatTimeAgo(latest.created_at)}</span>
          <a href="${latest.screenshot_url}" target="_blank" rel="noopener noreferrer" class="detail-link">Open Full &nearr;</a>
        </div>
      </div>
    `;

    // Card 3: Difference Overlay
    if (data.diff_image_url) {
      html += `
        <div class="vc-screenshot-box">
          <div class="vc-box-header">
            <span class="vc-box-title" style="color: var(--accent-rose);">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
              Pixel Diff Overlay (${diffPct.toFixed(2)}%)
            </span>
            <span class="vc-box-meta">Pillow ImageChops</span>
          </div>
          <div class="vc-screenshot-frame">
            <a href="${data.diff_image_url}" target="_blank" rel="noopener noreferrer" title="Click to view full diff overlay in new tab">
              <img src="${data.diff_image_url}" alt="Pixel Diff Overlay" loading="lazy" />
            </a>
          </div>
          <div class="vc-box-footer">
            <span>Red highlights indicate visual differences</span>
            <a href="${data.diff_image_url}" target="_blank" rel="noopener noreferrer" class="detail-link">Open Full &nearr;</a>
          </div>
        </div>
      `;
    }

    html += `</div>`;
    contentBody.innerHTML = html;
    return;
  }

  // 4. Fallback / error state
  const displayStatus = status || data.status || "Pending";
  const displayMsg = data.message || (hasBaseline ? "Visual comparison processing." : "No visual snapshots have been captured yet for this monitor.");
  contentBody.innerHTML = `
    <div class="vc-empty-box">
      <h4 class="vc-empty-title">Visual Status: ${escapeHtml(displayStatus)}</h4>
      <p class="vc-empty-desc">${escapeHtml(displayMsg)}</p>
      <button class="btn btn-secondary btn-sm" onclick="captureVisualScreenshot(${site.id})">Capture Screenshot</button>
    </div>
  `;
}

/**
 * Trigger screenshot capture via POST /api/sites/{site_id}/capture-screenshot
 */
async function captureVisualScreenshot(siteId, triggerBtn = null) {
  const numericId = parseInt(siteId, 10);
  if (!numericId) return;

  const site = monitorsList.find((s) => s.id === numericId);
  const siteName = site ? site.name : `Monitor #${numericId}`;

  // Find camera icons and spin them
  let spinIcon = null;
  if (triggerBtn) {
    spinIcon = triggerBtn.querySelector("svg");
    triggerBtn.disabled = true;
  }
  const mainCaptureBtn = document.getElementById("vc-btn-capture");
  const mainIcon = mainCaptureBtn ? mainCaptureBtn.querySelector(".camera-icon-spin") : null;
  const mainText = document.getElementById("vc-btn-capture-text");

  if (spinIcon) spinIcon.classList.add("spinning");
  if (mainIcon) mainIcon.classList.add("spinning");
  if (mainText && (triggerBtn === mainCaptureBtn || !triggerBtn)) {
    mainText.textContent = "Rendering...";
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/sites/${numericId}/capture-screenshot`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      const errMsg = data.detail || `Server returned HTTP ${response.status}`;
      showToast(`Screenshot capture failed for "${siteName}": ${errMsg}`, "error");
      await loadVisualComparison(numericId);
      return;
    }

    if (data.is_baseline) {
      showToast(`Baseline screenshot captured for "${siteName}" (1280x800).`, "success");
    } else if (data.visual_change_detected) {
      showToast(`Visual change detected on "${siteName}" (${data.diff_percent?.toFixed(2)}% difference)!`, "success");
    } else {
      showToast(
        `Screenshot captured for "${siteName}": visually unchanged (${data.diff_percent?.toFixed(2)}% diff).`,
        "info"
      );
    }

    // Refresh visual comparison and monitors
    await Promise.all([
      loadVisualComparison(numericId),
      fetchMonitors(),
      fetchChangeHistory(),
    ]);
  } catch (err) {
    showToast(`Visual capture error: ${err.message}`, "error");
  } finally {
    if (triggerBtn) triggerBtn.disabled = false;
    if (spinIcon) spinIcon.classList.remove("spinning");
    if (mainIcon) mainIcon.classList.remove("spinning");
    if (mainText) mainText.textContent = "Capture Screenshot";
  }
}

/* ==========================================================================
   8.5. Change Heatmap & Monitoring Analytics Controller (Prompt 7)
   ========================================================================== */

function populateHeatmapSiteSelect() {
  const select = document.getElementById("hm-site-select");
  if (!select) return;
  const currentVal = select.value || hmCurrentSiteId || "all";
  let html = `<option value="all">All Monitors (Aggregated)</option>`;
  for (const s of monitorsList) {
    html += `<option value="${s.id}">${escapeHtml(s.name || s.url)} (#${s.id})</option>`;
  }
  select.innerHTML = html;
  if ([...select.options].some((o) => o.value === currentVal)) {
    select.value = currentVal;
  } else {
    select.value = "all";
    hmCurrentSiteId = "all";
  }
}

function populateAnalyticsSiteSelect() {
  const select = document.getElementById("an-site-select");
  if (!select) return;
  const currentVal = select.value || anCurrentSiteId || "all";
  let html = `<option value="all">All Monitors (Aggregated)</option>`;
  for (const s of monitorsList) {
    html += `<option value="${s.id}">${escapeHtml(s.name || s.url)} (#${s.id})</option>`;
  }
  select.innerHTML = html;
  if ([...select.options].some((o) => o.value === currentVal)) {
    select.value = currentVal;
  } else {
    select.value = "all";
    anCurrentSiteId = "all";
  }
}

function initHeatmapView() {
  populateHeatmapSiteSelect();
  const daysSelect = document.getElementById("hm-days-select");
  if (daysSelect) {
    hmCurrentDays = parseInt(daysSelect.value, 10);
  }
  const siteSelect = document.getElementById("hm-site-select");
  if (siteSelect) {
    hmCurrentSiteId = siteSelect.value;
  }
  loadHeatmapData(hmCurrentSiteId, hmCurrentDays);
}

async function loadHeatmapData(siteId = null, days = null) {
  if (siteId !== null) hmCurrentSiteId = siteId;
  if (days !== null) hmCurrentDays = days;

  const refreshBtn = document.getElementById("hm-btn-refresh");
  const refreshIcon = refreshBtn ? refreshBtn.querySelector(".spin-on-load") : null;
  if (refreshIcon) refreshIcon.classList.add("spinning");

  const container = document.getElementById("hm-content-container");
  if (container) {
    container.innerHTML = `
      <div class="card" style="padding: 36px; text-align: center;">
        <div class="loading-spinner" style="margin: 0 auto 12px auto;"></div>
        <p style="color: var(--text-muted); font-size: 0.88rem;">Calculating change telemetry and heat distributions...</p>
      </div>
    `;
  }

  try {
    let url = `${API_BASE_URL}/api/analytics/heatmap?days=${hmCurrentDays}`;
    if (hmCurrentSiteId && hmCurrentSiteId !== "all") {
      url += `&site_id=${hmCurrentSiteId}`;
    }

    const response = await fetch(url);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Server error (HTTP ${response.status})`);
    }

    hmData = await response.json();

    // Update KPI cards
    const kpiTotal = document.getElementById("hm-kpi-total-changes");
    const kpiPeakDay = document.getElementById("hm-kpi-peak-day");
    const kpiPeakHour = document.getElementById("hm-kpi-peak-hour");
    const kpiWindow = document.getElementById("hm-kpi-active-window");
    const kpiSubtext = document.getElementById("hm-kpi-changes-subtext");

    if (kpiTotal) kpiTotal.textContent = hmData.total_changes;
    if (kpiPeakDay) kpiPeakDay.textContent = hmData.peak_day || "None";
    if (kpiPeakHour) {
      if (hmData.peak_hour !== null && hmData.peak_hour !== undefined) {
        kpiPeakHour.textContent = `${String(hmData.peak_hour).padStart(2, "0")}:00 UTC`;
      } else {
        kpiPeakHour.textContent = "—";
      }
    }
    if (kpiWindow) {
      if (hmData.start_date && hmData.end_date) {
        kpiWindow.textContent = `${hmData.start_date.slice(5)} → ${hmData.end_date.slice(5)}`;
      } else {
        kpiWindow.textContent = "All recorded";
      }
    }
    if (kpiSubtext) {
      kpiSubtext.textContent = hmCurrentDays === 0 ? "All recorded history" : `Past ${hmCurrentDays} days window`;
    }

    renderHeatmapView(hmData);
  } catch (error) {
    if (container) {
      container.innerHTML = `
        <div class="card telemetry-empty-card">
          <div class="telemetry-empty-icon" style="color: var(--accent-error);">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
          </div>
          <h3 style="font-size: 1rem; font-weight: 600; margin-bottom: 6px;">Heatmap Computation Failed</h3>
          <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 440px; margin: 0 auto 16px auto;">
            ${escapeHtml(error.message)}
          </p>
          <button class="btn btn-secondary btn-sm" onclick="loadHeatmapData()">Retry</button>
        </div>
      `;
    }
  } finally {
    if (refreshIcon) {
      setTimeout(() => refreshIcon.classList.remove("spinning"), 350);
    }
  }
}

function renderHeatmapView(data) {
  const container = document.getElementById("hm-content-container");
  if (!container) return;

  const hasChanges = data && data.total_changes > 0;
  const hasDaily = data && Array.isArray(data.daily_matrix) && data.daily_matrix.some((d) => d.count > 0);

  if (!hasChanges && !hasDaily) {
    container.innerHTML = `
      <div class="card telemetry-empty-card">
        <div class="telemetry-empty-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <rect x="3" y="4" width="18" height="16" rx="2"></rect>
            <line x1="16" y1="2" x2="16" y2="6"></line>
            <line x1="8" y1="2" x2="8" y2="6"></line>
            <line x1="3" y1="10" x2="21" y2="10"></line>
          </svg>
        </div>
        <h3 style="font-size: 1.05rem; font-weight: 600; margin-bottom: 6px;">No Change Telemetry Recorded</h3>
        <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 460px; margin: 0 auto 18px auto; line-height: 1.5;">
          No text or visual mutations were detected during the selected timeframe (${data.days === 0 ? "All Time" : "Past " + data.days + " Days"}). Trigger a check or expand the date range to populate the cadence matrix.
        </p>
        <button class="btn btn-primary btn-sm" onclick="switchView('monitors')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="2" y1="12" x2="22" y2="12"></line>
          </svg>
          Go to Monitors
        </button>
      </div>
    `;
    return;
  }

  // 1. Build Hourly Matrix (7 rows Mon-Sun x 24 cols)
  const daysOfWeek = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const dayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

  const cellMap = {};
  if (Array.isArray(data.hourly_matrix)) {
    for (const c of data.hourly_matrix) {
      cellMap[`${c.day_of_week}_${c.hour}`] = c;
    }
  }

  let tableRows = "";
  for (let d = 0; d < 7; d++) {
    tableRows += `<tr><td class="hm-td-day">${daysOfWeek[d]}</td>`;
    for (let h = 0; h < 24; h++) {
      const cell = cellMap[`${d}_${h}`] || { count: 0, site_ids: [] };
      let lvl = "hm-lvl-0";
      if (cell.count >= 6) lvl = "hm-lvl-3";
      else if (cell.count >= 3) lvl = "hm-lvl-2";
      else if (cell.count >= 1) lvl = "hm-lvl-1";

      const title = `${dayNames[d]} ${String(h).padStart(2, "0")}:00 UTC: ${cell.count} change${cell.count === 1 ? "" : "s"} detected`;
      const displayVal = cell.count > 0 ? cell.count : "";
      tableRows += `<td class="hm-cell ${lvl}" title="${escapeHtml(title)}">${displayVal}</td>`;
    }
    tableRows += `</tr>`;
  }

  let hourHeaders = "";
  for (let h = 0; h < 24; h++) {
    hourHeaders += `<th class="hm-th-hour">${String(h).padStart(2, "0")}</th>`;
  }

  // 2. Build Daily Activity Matrix (Calendar Squares)
  let calendarSquares = "";
  if (Array.isArray(data.daily_matrix) && data.daily_matrix.length > 0) {
    for (const item of data.daily_matrix) {
      const dayNum = item.date.slice(8);
      const lvl = `hm-lvl-${item.intensity}`;
      const title = `${item.date} (${daysOfWeek[item.day_of_week]}): ${item.count} change${item.count === 1 ? "" : "s"} (${item.text_changes} text, ${item.visual_changes} visual)`;
      calendarSquares += `
        <div class="hm-cal-day ${lvl}" title="${escapeHtml(title)}">
          <span>${dayNum}</span>
        </div>
      `;
    }
  }

  // 3. Build Monitor Cadence Activity List
  let sitesTableRows = "";
  if (Array.isArray(data.sites_activity) && data.sites_activity.length > 0) {
    for (const site of data.sites_activity) {
      const lastChange = site.last_change_at ? formatTimeAgo(site.last_change_at) : "Never";
      sitesTableRows += `
        <tr>
          <td>
            <div class="site-identity-cell">
              <span class="site-name-text">${escapeHtml(site.name)}</span>
              <a href="${escapeHtml(site.url)}" target="_blank" rel="noopener noreferrer" class="site-url-link">
                ${escapeHtml(site.url)}
              </a>
            </div>
          </td>
          <td><span style="font-weight: 600;">${site.total_checks}</span></td>
          <td><span class="status-badge status-badge-active">${site.text_changes}</span></td>
          <td><span class="status-badge status-badge-paused">${site.visual_changes}</span></td>
          <td><span style="font-weight: 700; color: var(--accent-primary);">${site.total_changes}</span></td>
          <td><span style="font-weight: 600;">${site.change_rate_percent.toFixed(1)}%</span></td>
          <td><span style="font-size: 0.78rem; color: var(--text-secondary);">${lastChange}</span></td>
        </tr>
      `;
    }
  }

  let html = `
    <!-- Hourly Matrix Card -->
    <div class="card hm-section-card">
      <div class="hm-card-header">
        <div>
          <h3 class="card-title" style="font-size: 0.95rem;">Hourly Change Frequency Matrix</h3>
          <p class="card-subtitle">Distribution across 7 days of the week &amp; 24-hour UTC window</p>
        </div>
        <div class="hm-legend">
          <span>Less</span>
          <div class="hm-legend-items">
            <span class="hm-legend-swatch hm-lvl-0" title="0 changes"></span>
            <span class="hm-legend-swatch hm-lvl-1" title="1-2 changes"></span>
            <span class="hm-legend-swatch hm-lvl-2" title="3-5 changes"></span>
            <span class="hm-legend-swatch hm-lvl-3" title="6+ changes"></span>
          </div>
          <span>More</span>
        </div>
      </div>
      <div class="hm-grid-scroll">
        <table class="hm-table">
          <thead>
            <tr>
              <th class="hm-td-day" style="font-size: 0.7rem; color: var(--text-muted);">Day / UTC</th>
              ${hourHeaders}
            </tr>
          </thead>
          <tbody>
            ${tableRows}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Daily Calendar Squares Card -->
    ${calendarSquares ? `
    <div class="card hm-section-card">
      <div class="hm-card-header">
        <div>
          <h3 class="card-title" style="font-size: 0.95rem;">Daily Activity Calendar</h3>
          <p class="card-subtitle">Day-by-day mutation density for ${data.days === 0 ? "all recorded dates" : "the past " + data.days + " days"}</p>
        </div>
      </div>
      <div class="hm-calendar-matrix">
        ${calendarSquares}
      </div>
    </div>
    ` : ""}

    <!-- Monitor Cadence Breakdown Card -->
    ${sitesTableRows ? `
    <div class="card hm-section-card">
      <div class="hm-card-header">
        <div>
          <h3 class="card-title" style="font-size: 0.95rem;">Target Monitor Cadence Breakdown</h3>
          <p class="card-subtitle">Individual check counts, detected mutations, and volatility rate</p>
        </div>
      </div>
      <div class="table-responsive">
        <table class="data-table">
          <thead>
            <tr>
              <th>Monitored Target</th>
              <th>Total Checks</th>
              <th>Text Diff</th>
              <th>Visual Diff</th>
              <th>Total Mutations</th>
              <th>Change Rate</th>
              <th>Last Mutation</th>
            </tr>
          </thead>
          <tbody>
            ${sitesTableRows}
          </tbody>
        </table>
      </div>
    </div>
    ` : ""}
  `;

  container.innerHTML = html;
}

function initAnalyticsView() {
  populateAnalyticsSiteSelect();
  const daysSelect = document.getElementById("an-days-select");
  if (daysSelect) {
    anCurrentDays = parseInt(daysSelect.value, 10);
  }
  const siteSelect = document.getElementById("an-site-select");
  if (siteSelect) {
    anCurrentSiteId = siteSelect.value;
  }
  loadAnalyticsData(anCurrentSiteId, anCurrentDays);
}

async function loadAnalyticsData(siteId = null, days = null) {
  if (siteId !== null) anCurrentSiteId = siteId;
  if (days !== null) anCurrentDays = days;

  const refreshBtn = document.getElementById("an-btn-refresh");
  const refreshIcon = refreshBtn ? refreshBtn.querySelector(".spin-on-load") : null;
  if (refreshIcon) refreshIcon.classList.add("spinning");

  const container = document.getElementById("an-content-container");
  if (container) {
    container.innerHTML = `
      <div class="card" style="padding: 36px; text-align: center;">
        <div class="loading-spinner" style="margin: 0 auto 12px auto;"></div>
        <p style="color: var(--text-muted); font-size: 0.88rem;">Aggregating monitoring performance & availability telemetry...</p>
      </div>
    `;
  }

  try {
    let url = `${API_BASE_URL}/api/analytics/summary?days=${anCurrentDays}`;
    if (anCurrentSiteId && anCurrentSiteId !== "all") {
      url += `&site_id=${anCurrentSiteId}`;
    }

    const response = await fetch(url);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Server error (HTTP ${response.status})`);
    }

    anData = await response.json();

    // Update 6 KPI cards
    const kpiChecks = document.getElementById("an-kpi-total-checks");
    const kpiText = document.getElementById("an-kpi-text-changes");
    const kpiVisual = document.getElementById("an-kpi-visual-changes");
    const kpiFailed = document.getElementById("an-kpi-failed-checks");
    const kpiRate = document.getElementById("an-kpi-change-rate");
    const kpiLatency = document.getElementById("an-kpi-avg-latency");

    if (kpiChecks) kpiChecks.textContent = anData.total_checks;
    if (kpiText) kpiText.textContent = anData.text_changes;
    if (kpiVisual) kpiVisual.textContent = anData.visual_changes;
    if (kpiFailed) kpiFailed.textContent = anData.failed_checks;
    if (kpiRate) kpiRate.textContent = `${anData.change_rate_percent.toFixed(1)}%`;
    if (kpiLatency) {
      kpiLatency.textContent = anData.avg_response_time_ms ? `${Math.round(anData.avg_response_time_ms)} ms` : "—";
    }

    renderAnalyticsView(anData);
  } catch (error) {
    if (container) {
      container.innerHTML = `
        <div class="card telemetry-empty-card">
          <div class="telemetry-empty-icon" style="color: var(--accent-error);">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
          </div>
          <h3 style="font-size: 1rem; font-weight: 600; margin-bottom: 6px;">Failed to Load Analytics</h3>
          <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 440px; margin: 0 auto 16px auto;">
            ${escapeHtml(error.message)}
          </p>
          <button class="btn btn-secondary btn-sm" onclick="loadAnalyticsData()">Retry</button>
        </div>
      `;
    }
  } finally {
    if (refreshIcon) {
      setTimeout(() => refreshIcon.classList.remove("spinning"), 350);
    }
  }
}

function renderAnalyticsView(data) {
  const container = document.getElementById("an-content-container");
  if (!container) return;

  const hasActivity = data && (data.total_checks > 0 || data.total_changes > 0 || (Array.isArray(data.timeline) && data.timeline.some((d) => d.checks_count > 0 || d.total_changes > 0)));

  if (!hasActivity) {
    container.innerHTML = `
      <div class="card telemetry-empty-card">
        <div class="telemetry-empty-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <line x1="18" y1="20" x2="18" y2="10"></line>
            <line x1="12" y1="20" x2="12" y2="4"></line>
            <line x1="6" y1="20" x2="6" y2="14"></line>
          </svg>
        </div>
        <h3 style="font-size: 1.05rem; font-weight: 600; margin-bottom: 6px;">No Analytics Telemetry Available</h3>
        <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 460px; margin: 0 auto 18px auto; line-height: 1.5;">
          No monitor checks or response benchmarks were recorded in this timeframe (${data.days === 0 ? "All Time" : "Past " + data.days + " Days"}). Perform website checks to generate real-time uptime and latency analytics.
        </p>
        <button class="btn btn-primary btn-sm" onclick="switchView('monitors')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"></polyline>
            <polyline points="1 20 1 14 7 14"></polyline>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
          Run Checks Now
        </button>
      </div>
    `;
    return;
  }

  // 1. Build Timeline Bar Chart
  let timelineBarsHtml = "";
  if (Array.isArray(data.timeline) && data.timeline.length > 0) {
    const maxVal = Math.max(...data.timeline.map((d) => Math.max(d.checks_count, d.total_changes)), 1);
    const chartHeight = 150;

    for (const pt of data.timeline) {
      const checksH = Math.max(Math.round((pt.checks_count / maxVal) * chartHeight), pt.checks_count > 0 ? 5 : 2);
      const changesH = Math.max(Math.round((pt.total_changes / maxVal) * chartHeight), pt.total_changes > 0 ? 5 : 2);
      const shortDate = pt.date.slice(5);
      const title = `${pt.date}: ${pt.checks_count} checks executed, ${pt.total_changes} changes detected (${pt.text_changes} text, ${pt.visual_changes} visual), ${pt.failed_checks} failed`;

      timelineBarsHtml += `
        <div class="an-day-col" title="${escapeHtml(title)}">
          <div class="an-bars-pair">
            <div class="an-bar an-bar-checks" style="height: ${checksH}px;"></div>
            <div class="an-bar an-bar-changes" style="height: ${changesH}px;"></div>
          </div>
          <span class="an-col-date">${shortDate}</span>
        </div>
      `;
    }
  }

  // 2. Status Code Telemetry Breakdown
  const dist = data.status_distribution || {};
  let c2xx = 0, c3xx = 0, c4xx = 0, c5xx = 0, cFail = 0;
  for (const [k, v] of Object.entries(dist)) {
    const code = parseInt(k, 10);
    const count = Number(v) || 0;
    if (code >= 200 && code < 300) c2xx += count;
    else if (code >= 300 && code < 400) c3xx += count;
    else if (code >= 400 && code < 500) c4xx += count;
    else if (code >= 500 && code < 600) c5xx += count;
    else cFail += count;
  }
  const totalCodes = c2xx + c3xx + c4xx + c5xx + cFail || 1;
  const p2xx = ((c2xx / totalCodes) * 100).toFixed(1);
  const p3xx = ((c3xx / totalCodes) * 100).toFixed(1);
  const p4xx = ((c4xx / totalCodes) * 100).toFixed(1);
  const p5xx = ((c5xx / totalCodes) * 100).toFixed(1);
  const pFail = ((cFail / totalCodes) * 100).toFixed(1);

  // 3. Volatility Ranking (Leaderboard)
  let leaderboardHtml = "";
  if (Array.isArray(data.top_sites) && data.top_sites.length > 0) {
    let rank = 1;
    for (const site of data.top_sites.slice(0, 8)) {
      const rankClass = rank === 1 ? "rank-1" : rank === 2 ? "rank-2" : rank === 3 ? "rank-3" : "";
      leaderboardHtml += `
        <div class="leaderboard-item">
          <div class="leaderboard-rank ${rankClass}">#${rank}</div>
          <div class="leaderboard-info">
            <div class="leaderboard-name">${escapeHtml(site.name)}</div>
            <div class="leaderboard-url">${escapeHtml(site.url)}</div>
          </div>
          <div class="leaderboard-stats">
            <span class="leaderboard-stat-pill" style="background: rgba(99, 102, 241, 0.12); color: var(--accent-primary);">
              ${site.total_changes} mutations
            </span>
            <span class="leaderboard-stat-pill" style="background: var(--bg-surface); border: 1px solid var(--border-subtle); color: var(--text-secondary);">
              ${site.change_rate_percent.toFixed(1)}% rate
            </span>
          </div>
        </div>
      `;
      rank++;
    }
  } else {
    leaderboardHtml = `
      <div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 0.85rem;">
        No active monitors ranked yet.
      </div>
    `;
  }

  let html = `
    <!-- Activity & Mutation Timeline Chart -->
    <div class="card hm-section-card">
      <div class="an-timeline-wrapper">
        <div class="an-chart-header">
          <div>
            <h3 class="card-title" style="font-size: 0.95rem;">Activity &amp; Change Timeline</h3>
            <p class="card-subtitle">Daily comparison of executed checks versus detected mutations</p>
          </div>
          <div class="an-chart-legend">
            <div class="an-legend-pill">
              <span class="an-dot an-dot-checks"></span>
              <span>Executed Checks</span>
            </div>
            <div class="an-legend-pill">
              <span class="an-dot an-dot-changes"></span>
              <span>Detected Mutations</span>
            </div>
          </div>
        </div>
        <div class="an-bars-container">
          ${timelineBarsHtml}
        </div>
      </div>
    </div>

    <!-- Split Grid: Status Telemetry & Leaderboard -->
    <div class="an-split-grid">
      <!-- Status Code Distribution -->
      <div class="card hm-section-card">
        <div class="hm-card-header">
          <div>
            <h3 class="card-title" style="font-size: 0.95rem;">HTTP Status &amp; Availability Health</h3>
            <p class="card-subtitle">Distribution of HTTP responses across all check cycles</p>
          </div>
        </div>
        <div class="status-telemetry-list">
          <div class="status-telemetry-item">
            <div class="status-telemetry-meta">
              <span class="status-telemetry-label">
                <span class="an-dot" style="background: var(--accent-success);"></span>
                2xx Success (Active &amp; OK)
              </span>
              <span class="status-telemetry-count">${c2xx} (${p2xx}%)</span>
            </div>
            <div class="status-progress-track">
              <div class="status-progress-fill fill-2xx" style="width: ${p2xx}%;"></div>
            </div>
          </div>

          <div class="status-telemetry-item">
            <div class="status-telemetry-meta">
              <span class="status-telemetry-label">
                <span class="an-dot" style="background: #06b6d4;"></span>
                3xx Redirects
              </span>
              <span class="status-telemetry-count">${c3xx} (${p3xx}%)</span>
            </div>
            <div class="status-progress-track">
              <div class="status-progress-fill fill-3xx" style="width: ${p3xx}%;"></div>
            </div>
          </div>

          <div class="status-telemetry-item">
            <div class="status-telemetry-meta">
              <span class="status-telemetry-label">
                <span class="an-dot" style="background: #f59e0b;"></span>
                4xx Client Errors (404/403)
              </span>
              <span class="status-telemetry-count">${c4xx} (${p4xx}%)</span>
            </div>
            <div class="status-progress-track">
              <div class="status-progress-fill fill-4xx" style="width: ${p4xx}%;"></div>
            </div>
          </div>

          <div class="status-telemetry-item">
            <div class="status-telemetry-meta">
              <span class="status-telemetry-label">
                <span class="an-dot" style="background: var(--accent-error);"></span>
                5xx Server Errors (500/502)
              </span>
              <span class="status-telemetry-count">${c5xx} (${p5xx}%)</span>
            </div>
            <div class="status-progress-track">
              <div class="status-progress-fill fill-5xx" style="width: ${p5xx}%;"></div>
            </div>
          </div>

          <div class="status-telemetry-item">
            <div class="status-telemetry-meta">
              <span class="status-telemetry-label">
                <span class="an-dot" style="background: #ef4444;"></span>
                Check Failures / SSRF Blocks
              </span>
              <span class="status-telemetry-count">${cFail} (${pFail}%)</span>
            </div>
            <div class="status-progress-track">
              <div class="status-progress-fill fill-fail" style="width: ${pFail}%;"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Volatility Leaderboard -->
      <div class="card hm-section-card">
        <div class="hm-card-header">
          <div>
            <h3 class="card-title" style="font-size: 0.95rem;">Monitor Volatility Ranking</h3>
            <p class="card-subtitle">Targets with the highest mutation activity in selected window</p>
          </div>
        </div>
        <div class="leaderboard-list">
          ${leaderboardHtml}
        </div>
      </div>
    </div>
  `;

  container.innerHTML = html;
}

/* ==========================================================================
   8.8. Notifications & Alerts Controller (Prompt 8)
   ========================================================================== */

/**
 * Populate target monitor dropdown in Notifications view
 */
function populateNotificationSiteSelect() {
  const select = document.getElementById("notif-filter-site");
  if (!select) return;
  const currentVal = select.value || notifFilterSiteId || "all";
  let html = `<option value="all">All Monitors</option>`;
  for (const s of monitorsList) {
    html += `<option value="${s.id}">${escapeHtml(s.name || s.url)} (#${s.id})</option>`;
  }
  select.innerHTML = html;
  if ([...select.options].some((o) => o.value === currentVal)) {
    select.value = currentVal;
  } else {
    select.value = "all";
    notifFilterSiteId = "all";
  }
}

/**
 * Fetch unread notification count and update topbar bell & sidebar badge
 */
async function fetchUnreadCount() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/notifications/unread-count`);
    if (!res.ok) return;
    const data = await res.json();
    notifUnreadCount = typeof data.unread_count === "number" ? data.unread_count : 0;

    const topbarBadge = document.getElementById("topbar-unread-badge");
    if (topbarBadge) {
      topbarBadge.textContent = notifUnreadCount > 99 ? "99+" : notifUnreadCount;
      topbarBadge.style.display = notifUnreadCount > 0 ? "flex" : "none";
    }

    const navCount = document.getElementById("nav-notifications-count");
    if (navCount) {
      navCount.textContent = notifUnreadCount > 99 ? "99+" : notifUnreadCount;
      navCount.style.display = notifUnreadCount > 0 ? "inline-flex" : "none";
    }
  } catch (err) {
    console.warn("Error fetching unread notification count:", err);
  }
}

/**
 * Fetch notifications with active filters (site, type, unread-only)
 */
async function fetchNotifications() {
  const container = document.getElementById("notifications-list-container");
  if (!container) return;

  try {
    populateNotificationSiteSelect();

    const params = new URLSearchParams();
    if (notifFilterUnreadOnly) {
      params.append("unread_only", "true");
    }
    if (notifFilterEventType && notifFilterEventType !== "all") {
      params.append("event_type", notifFilterEventType);
    }
    if (notifFilterSiteId && notifFilterSiteId !== "all") {
      params.append("site_id", notifFilterSiteId);
    }

    const res = await fetch(`${API_BASE_URL}/api/notifications?${params.toString()}`);
    if (!res.ok) {
      throw new Error(`Failed to load notifications (HTTP ${res.status})`);
    }

    const data = await res.json();
    notifList = Array.isArray(data.notifications) ? data.notifications : [];
    notifUnreadCount = typeof data.unread_count === "number" ? data.unread_count : 0;

    // Update KPIs
    const kpiTotal = document.getElementById("notif-kpi-total");
    const kpiUnread = document.getElementById("notif-kpi-unread");
    const kpiText = document.getElementById("notif-kpi-text");
    const kpiVisual = document.getElementById("notif-kpi-visual");

    if (kpiTotal) kpiTotal.textContent = data.total ?? notifList.length;
    if (kpiUnread) kpiUnread.textContent = notifUnreadCount;

    const textCount = notifList.filter((n) => n.event_type === "text_change").length;
    const visualCount = notifList.filter((n) => n.event_type === "visual_change").length;
    if (kpiText) kpiText.textContent = textCount;
    if (kpiVisual) kpiVisual.textContent = visualCount;

    // Synchronize topbar & sidebar counts
    const topbarBadge = document.getElementById("topbar-unread-badge");
    if (topbarBadge) {
      topbarBadge.textContent = notifUnreadCount > 99 ? "99+" : notifUnreadCount;
      topbarBadge.style.display = notifUnreadCount > 0 ? "flex" : "none";
    }
    const navCount = document.getElementById("nav-notifications-count");
    if (navCount) {
      navCount.textContent = notifUnreadCount > 99 ? "99+" : notifUnreadCount;
      navCount.style.display = notifUnreadCount > 0 ? "inline-flex" : "none";
    }

    renderNotificationsList(notifList);
  } catch (err) {
    console.error("Error loading notifications:", err);
    container.innerHTML = `
      <div class="empty-state" style="padding: 40px 20px;">
        <div class="empty-state-art" style="border-color: var(--accent-rose); color: var(--accent-rose);">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
        </div>
        <h3 class="empty-state-title">Error Loading Notifications</h3>
        <p class="empty-state-desc">${escapeHtml(err.message)}. Please check your backend connection.</p>
        <button class="btn btn-secondary btn-sm" onclick="fetchNotifications()">Retry</button>
      </div>
    `;
  }
}

/**
 * Render notification feed list or honest empty state
 */
function renderNotificationsList(notifications) {
  const container = document.getElementById("notifications-list-container");
  if (!container) return;

  if (!notifications || notifications.length === 0) {
    const isFiltered = notifFilterUnreadOnly || notifFilterEventType !== "all" || notifFilterSiteId !== "all";
    container.innerHTML = `
      <div class="empty-state" style="padding: 48px 24px;">
        <div class="empty-state-art">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
          </svg>
        </div>
        <h3 class="empty-state-title">${isFiltered ? "No Matching Alerts Found" : "All Caught Up!"}</h3>
        <p class="empty-state-desc">
          ${isFiltered
            ? "No notifications match your active filter criteria. Try adjusting the target monitor, event type, or viewing all alerts."
            : "No notifications or alerts recorded yet. Detected text mutations, visual changes, or check failures will be reported here in real time."}
        </p>
        ${isFiltered
          ? `<button class="btn btn-secondary btn-sm" onclick="resetNotificationFilters()">Clear Active Filters</button>`
          : `<button class="btn btn-secondary btn-sm" onclick="switchView('monitors')">Go to Monitors</button>`}
      </div>
    `;
    return;
  }

  let html = "";
  for (const n of notifications) {
    const isUnread = !n.is_read;
    const siteName = n.site_name || (n.site_id ? `Monitor #${n.site_id}` : "System");
    const siteUrl = n.site_url || "";
    const timeFormatted = formatTimeAgo(n.created_at);
    const fullDate = n.created_at ? new Date(n.created_at).toLocaleString() : "";

    // Event styling & icons
    let iconClass = "type-text";
    let badgeClass = "badge-type-text";
    let badgeLabel = "Text Change";
    let iconSvg = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
        <polyline points="14 2 14 8 20 8"></polyline>
        <line x1="16" y1="13" x2="8" y2="13"></line>
        <line x1="16" y1="17" x2="8" y2="17"></line>
        <polyline points="10 9 9 9 8 9"></polyline>
      </svg>
    `;

    if (n.event_type === "visual_change") {
      iconClass = "type-visual";
      badgeClass = "badge-type-visual";
      badgeLabel = "Visual Change";
      iconSvg = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
          <circle cx="12" cy="13" r="4"></circle>
        </svg>
      `;
    } else if (n.event_type === "check_failed") {
      iconClass = "type-fail";
      badgeClass = "badge-type-fail";
      badgeLabel = "Check Failed";
      iconSvg = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
          <line x1="12" y1="9" x2="12" y2="13"></line>
          <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>
      `;
    }

    // Action button based on link_type
    let actionBtnHtml = "";
    if (n.link_type === "diff" && n.link_id) {
      actionBtnHtml = `
        <button class="btn btn-secondary btn-xs notif-action-btn" onclick="handleNotificationAction(${n.id}, 'diff', ${n.link_id})" title="Inspect before/after diff">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="16 18 22 12 16 6"></polyline>
            <polyline points="8 6 2 12 8 18"></polyline>
          </svg>
          Inspect Diff
        </button>
      `;
    } else if (n.link_type === "visual" && n.site_id) {
      actionBtnHtml = `
        <button class="btn btn-secondary btn-xs notif-action-btn" onclick="handleNotificationAction(${n.id}, 'visual', ${n.site_id})" title="View visual screenshots and diff">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
            <circle cx="12" cy="13" r="4"></circle>
          </svg>
          View Visuals
        </button>
      `;
    } else if (n.site_id) {
      actionBtnHtml = `
        <button class="btn btn-secondary btn-xs notif-action-btn" onclick="handleNotificationAction(${n.id}, 'monitor', ${n.site_id})" title="Inspect monitor target details">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="16" x2="12" y2="12"></line>
            <line x1="12" y1="8" x2="12.01" y2="8"></line>
          </svg>
          View Monitor
        </button>
      `;
    }

    // Toggle read/unread button
    const readToggleBtn = isUnread
      ? `
        <button class="btn btn-secondary btn-xs notif-action-btn" onclick="toggleNotificationRead(${n.id}, true)" title="Mark as read">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          Mark Read
        </button>
      `
      : `
        <button class="btn btn-secondary btn-xs notif-action-btn" onclick="toggleNotificationRead(${n.id}, false)" title="Mark as unread">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
          </svg>
          Mark Unread
        </button>
      `;

    // Delete button
    const deleteBtn = `
      <button class="btn btn-secondary btn-xs notif-action-btn notif-delete-btn" onclick="deleteNotificationItem(${n.id})" title="Delete alert" aria-label="Delete alert">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
      </button>
    `;

    html += `
      <div class="notif-item ${isUnread ? "unread" : "read"}" id="notif-item-${n.id}">
        <div class="notif-icon-badge ${iconClass}">
          ${iconSvg}
        </div>
        <div class="notif-content">
          <div class="notif-top-row">
            <div class="notif-title-group">
              <span class="notif-title">${escapeHtml(n.title)}</span>
              <span class="notif-badge-type ${badgeClass}">${escapeHtml(badgeLabel)}</span>
            </div>
            <span class="notif-time" title="${escapeHtml(fullDate)}">${escapeHtml(timeFormatted)}</span>
          </div>

          <div class="notif-site-info">
            <span style="font-weight: 600; color: var(--text-primary);">${escapeHtml(siteName)}</span>
            ${siteUrl ? `<span style="color: var(--text-muted);">&bull;</span><a href="${escapeHtml(siteUrl)}" target="_blank" rel="noopener noreferrer" class="notif-site-link">${escapeHtml(siteUrl)}</a>` : ""}
          </div>

          <div class="notif-message-text">${escapeHtml(n.message)}</div>

          <div class="notif-actions-row">
            ${actionBtnHtml}
            ${readToggleBtn}
            ${deleteBtn}
          </div>
        </div>
      </div>
    `;
  }

  container.innerHTML = html;
}

/**
 * Handle clicking deep link on a notification
 */
async function handleNotificationAction(notifId, linkType, linkId) {
  // Mark read silently if currently unread
  const notif = notifList.find((n) => n.id === notifId);
  if (notif && !notif.is_read) {
    try {
      await fetch(`${API_BASE_URL}/api/notifications/${notifId}/read`, { method: "PATCH" });
      notif.is_read = true;
      fetchUnreadCount();
      const el = document.getElementById(`notif-item-${notifId}`);
      if (el) {
        el.classList.remove("unread");
        el.classList.add("read");
      }
    } catch (e) {
      // Non-fatal
    }
  }

  if (linkType === "diff") {
    const existing = changesList.find((c) => c.id === linkId);
    if (existing) {
      openDiffModal(linkId);
    } else {
      await fetchChangeHistory();
      openDiffModal(linkId);
    }
  } else if (linkType === "visual") {
    openVisualChangesForSite(linkId);
  } else if (linkType === "monitor") {
    openViewModal(linkId);
  }
}

/**
 * Toggle individual notification read / unread status
 */
async function toggleNotificationRead(id, markAsRead) {
  try {
    const endpoint = markAsRead ? "read" : "unread";
    const res = await fetch(`${API_BASE_URL}/api/notifications/${id}/${endpoint}`, {
      method: "PATCH",
    });
    if (!res.ok) {
      throw new Error(`Failed to update notification (HTTP ${res.status})`);
    }
    await Promise.all([fetchNotifications(), fetchUnreadCount()]);
    showToast(markAsRead ? "Alert marked as read" : "Alert marked as unread", "info");
  } catch (err) {
    showToast(err.message, "error");
  }
}

/**
 * Mark all notifications as read
 */
async function markAllNotificationsRead() {
  const btn = document.getElementById("btn-mark-all-read");
  if (btn) btn.disabled = true;

  try {
    const res = await fetch(`${API_BASE_URL}/api/notifications/mark-all-read`, {
      method: "POST",
    });
    if (!res.ok) {
      throw new Error(`Failed to mark all as read (HTTP ${res.status})`);
    }
    const data = await res.json();
    await Promise.all([fetchNotifications(), fetchUnreadCount()]);
    showToast(
      data.updated_count > 0
        ? `Marked ${data.updated_count} alert${data.updated_count === 1 ? "" : "s"} as read.`
        : "No unread alerts to mark.",
      "success"
    );
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/**
 * Delete a notification
 */
async function deleteNotificationItem(id) {
  try {
    const res = await fetch(`${API_BASE_URL}/api/notifications/${id}`, {
      method: "DELETE",
    });
    if (!res.ok && res.status !== 204) {
      throw new Error(`Failed to delete alert (HTTP ${res.status})`);
    }
    await Promise.all([fetchNotifications(), fetchUnreadCount()]);
    showToast("Alert deleted", "info");
  } catch (err) {
    showToast(err.message, "error");
  }
}

/**
 * Reset notification filters to default
 */
function resetNotificationFilters() {
  notifFilterUnreadOnly = false;
  notifFilterEventType = "all";
  notifFilterSiteId = "all";

  const siteSelect = document.getElementById("notif-filter-site");
  if (siteSelect) siteSelect.value = "all";

  const typeSelect = document.getElementById("notif-filter-type");
  if (typeSelect) typeSelect.value = "all";

  const pillAll = document.getElementById("notif-pill-all");
  const pillUnread = document.getElementById("notif-pill-unread");
  if (pillAll) pillAll.classList.add("active");
  if (pillUnread) pillUnread.classList.remove("active");

  fetchNotifications();
}

/**
 * Load notification preferences into Settings view
 */
async function loadNotificationPreferences() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/notifications/preferences`);
    if (!res.ok) return;
    const data = await res.json();

    const prefText = document.getElementById("pref-notify-text-change");
    const prefVisual = document.getElementById("pref-notify-visual-change");
    const prefFailed = document.getElementById("pref-notify-check-failed");

    if (prefText) prefText.checked = !!data.notify_text_change;
    if (prefVisual) prefVisual.checked = !!data.notify_visual_change;
    if (prefFailed) prefFailed.checked = !!data.notify_check_failed;
  } catch (err) {
    console.warn("Error loading notification preferences:", err);
  }
}

/**
 * Save notification preferences from Settings view
 */
async function saveNotificationPreferences() {
  const btn = document.getElementById("btn-save-notif-prefs");
  if (btn) btn.disabled = true;

  try {
    const prefText = document.getElementById("pref-notify-text-change");
    const prefVisual = document.getElementById("pref-notify-visual-change");
    const prefFailed = document.getElementById("pref-notify-check-failed");

    const payload = {
      notify_text_change: prefText ? prefText.checked : true,
      notify_visual_change: prefVisual ? prefVisual.checked : true,
      notify_check_failed: prefFailed ? prefFailed.checked : true,
    };

    const res = await fetch(`${API_BASE_URL}/api/notifications/preferences`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`Failed to save preferences (HTTP ${res.status})`);
    }

    showToast("Notification preferences updated successfully", "success");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ==========================================================================
   8.9. Automated Monitoring Scheduler Controller (Prompt 9)
   ========================================================================== */

/**
 * Format relative remaining time until next scheduled run
 */
function formatNextRunCountdown(isoString) {
  if (!isoString) return "No scheduled run";
  const target = new Date(isoString);
  const now = new Date();
  const diffMs = target - now;

  if (diffMs <= 0) return "Due now";
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return `In ${diffSec}s`;
  const diffMin = Math.floor(diffSec / 60);
  const remSec = diffSec % 60;
  if (diffMin < 60) return `In ${diffMin}m ${remSec}s`;
  const diffHours = Math.floor(diffMin / 60);
  const remMin = diffMin % 60;
  return `In ${diffHours}h ${remMin}m`;
}

/**
 * Fetch and render background scheduler status, queue, and recent outcomes
 */
async function fetchSchedulerStatus() {
  const queueContainer = document.getElementById("dash-scheduler-queue-container");

  try {
    const res = await fetch(`${API_BASE_URL}/api/scheduler/status`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    schedulerData = data;
    schedulerAutoChecksEnabled = !!data.auto_checks_enabled;

    // 1. Status Badge
    const statusBadge = document.getElementById("dash-scheduler-status-badge");
    if (statusBadge) {
      if (data.is_running) {
        statusBadge.className = "status-badge status-badge-active";
        statusBadge.innerHTML = `<span class="badge-dot" style="background: var(--accent-emerald);"></span> Scheduler Running`;
      } else {
        statusBadge.className = "status-badge status-badge-paused";
        statusBadge.innerHTML = `<span class="badge-dot" style="background: var(--accent-amber);"></span> Scheduler Stopped`;
      }
    }

    // 2. Global State & Button Text
    const globalStateEl = document.getElementById("dash-scheduler-global-state");
    const globalSubtextEl = document.getElementById("dash-scheduler-global-subtext");
    const toggleBtnText = document.getElementById("dash-btn-toggle-text");

    if (globalStateEl) {
      if (data.auto_checks_enabled) {
        globalStateEl.textContent = "Active";
        globalStateEl.style.color = "var(--accent-emerald)";
      } else {
        globalStateEl.textContent = "Paused";
        globalStateEl.style.color = "var(--accent-amber)";
      }
    }

    if (globalSubtextEl) {
      globalSubtextEl.textContent = data.auto_checks_enabled
        ? "Automated checks enabled"
        : "Background polling suspended";
    }

    if (toggleBtnText) {
      toggleBtnText.textContent = data.auto_checks_enabled
        ? "Pause Auto Checks"
        : "Enable Auto Checks";
    }

    // 3. Active Jobs Count
    const activeJobsEl = document.getElementById("dash-scheduler-active-jobs");
    if (activeJobsEl) {
      activeJobsEl.textContent = data.active_jobs_count;
    }

    // 4. Next Scheduled Check
    const nextRunEl = document.getElementById("dash-scheduler-next-run");
    const nextRunSubtext = document.getElementById("dash-scheduler-next-run-subtext");
    if (nextRunEl) {
      if (data.next_scheduled_check) {
        nextRunEl.textContent = formatNextRunCountdown(data.next_scheduled_check);
        if (nextRunSubtext) {
          nextRunSubtext.textContent = new Date(data.next_scheduled_check).toLocaleTimeString();
        }
      } else {
        nextRunEl.textContent = data.auto_checks_enabled ? "No queue" : "Suspended";
        if (nextRunSubtext) {
          nextRunSubtext.textContent = data.auto_checks_enabled ? "Add active targets" : "Global auto checks paused";
        }
      }
    }

    // 5. Render Queue & Recent Outcomes
    renderSchedulerQueue(data.jobs);
    renderSchedulerOutcomes(data.recent_outcomes);
  } catch (err) {
    console.warn("Error fetching scheduler status:", err);
    if (queueContainer) {
      queueContainer.innerHTML = `
        <div class="empty-state" style="padding: 24px;">
          <p style="color: var(--text-muted); font-size: 0.82rem;">Scheduler telemetry unavailable.</p>
        </div>
      `;
    }
  }
}

/**
 * Render scheduled monitoring jobs queue table
 */
function renderSchedulerQueue(jobs) {
  const container = document.getElementById("dash-scheduler-queue-container");
  if (!container) return;

  if (!jobs || jobs.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="padding: 32px 16px;">
        <div class="empty-state-art" style="width: 44px; height: 44px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
        </div>
        <h4 class="empty-state-title" style="font-size: 0.92rem;">No Monitored Targets in Queue</h4>
        <p class="empty-state-desc" style="font-size: 0.78rem;">
          Add active website monitors to register automated periodic check loops.
        </p>
        <button class="btn btn-primary btn-xs" onclick="openAddMonitorModal()">Add Monitor</button>
      </div>
    `;
    return;
  }

  let rowsHtml = "";
  for (const job of jobs) {
    let statusBadge = "";
    if (job.job_status === "scheduled") {
      statusBadge = `<span class="status-badge status-badge-active">Scheduled</span>`;
    } else if (job.job_status === "paused") {
      statusBadge = `<span class="status-badge status-badge-paused">Paused</span>`;
    } else if (job.job_status === "disabled_globally") {
      statusBadge = `<span class="status-badge status-badge-paused">Globally Paused</span>`;
    } else {
      statusBadge = `<span class="status-badge">${escapeHtml(job.job_status)}</span>`;
    }

    const nextRunDisplay = job.next_run_time
      ? `<span class="scheduler-countdown-pill" title="${new Date(job.next_run_time).toLocaleString()}">${formatNextRunCountdown(job.next_run_time)}</span>`
      : `<span style="color: var(--text-muted); font-size: 0.78rem;">—</span>`;

    rowsHtml += `
      <tr class="scheduler-queue-row">
        <td>
          <div class="scheduler-target-cell">
            <span class="scheduler-target-name">${escapeHtml(job.site_name)}</span>
            <span class="scheduler-target-url" title="${escapeHtml(job.site_url)}">${escapeHtml(job.site_url)}</span>
          </div>
        </td>
        <td>
          <span style="font-family: var(--font-mono, monospace); font-size: 0.76rem; color: var(--text-secondary);">Every ${job.check_interval_minutes}m</span>
        </td>
        <td>${nextRunDisplay}</td>
        <td>${statusBadge}</td>
        <td>
          <button class="btn btn-secondary btn-xs" onclick="runSchedulerJobNow(${job.site_id}, this)" title="Trigger immediate check">
            Run Now
          </button>
        </td>
      </tr>
    `;
  }

  container.innerHTML = `
    <table class="scheduler-queue-table">
      <thead>
        <tr>
          <th>Target</th>
          <th>Interval</th>
          <th>Next Run</th>
          <th>Status</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${rowsHtml}
      </tbody>
    </table>
  `;
}

/**
 * Render recent check outcomes feed in scheduler card
 */
function renderSchedulerOutcomes(outcomes) {
  const container = document.getElementById("dash-scheduler-outcomes-container");
  if (!container) return;

  if (!outcomes || outcomes.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="padding: 32px 16px;">
        <h4 class="empty-state-title" style="font-size: 0.92rem;">No Check Logs Yet</h4>
        <p class="empty-state-desc" style="font-size: 0.78rem;">
          Telemetry logs and outcomes from scheduled check runs will stream here automatically.
        </p>
      </div>
    `;
    return;
  }

  let listHtml = "";
  for (const log of outcomes) {
    let dotColor = "var(--accent-emerald)";
    let badgeClass = "status-badge-active";
    let statusLabel = "Success";

    if (log.status === "baseline_created") {
      dotColor = "var(--accent-primary)";
      badgeClass = "status-badge-baseline";
      statusLabel = "Baseline";
    } else if (log.status === "unchanged") {
      dotColor = "var(--accent-emerald)";
      badgeClass = "status-badge-active";
      statusLabel = "Unchanged";
    } else if (log.status === "change_detected") {
      dotColor = "var(--accent-violet)";
      badgeClass = "status-badge-changed";
      statusLabel = "Changed";
    } else if (log.status === "check_failed") {
      dotColor = "var(--accent-rose)";
      badgeClass = "status-badge-failed";
      statusLabel = "Failed";
    }

    const latencyText = log.response_time_ms ? `${log.response_time_ms.toFixed(0)}ms` : "";
    const httpText = log.status_code ? `HTTP ${log.status_code}` : "";
    const timeAgo = formatTimeAgo(log.created_at);

    listHtml += `
      <div class="scheduler-outcome-item">
        <div class="scheduler-outcome-left">
          <div class="scheduler-outcome-dot" style="background: ${dotColor};"></div>
          <div class="scheduler-outcome-info">
            <span class="scheduler-outcome-title">${escapeHtml(log.site_name || "Monitor #" + log.site_id)}</span>
            <div class="scheduler-outcome-meta">
              <span class="status-badge ${badgeClass}" style="padding: 1px 6px; font-size: 0.65rem;">${statusLabel}</span>
              ${httpText ? `<span>&bull;</span><span>${httpText}</span>` : ""}
              ${latencyText ? `<span>&bull;</span><span>${latencyText}</span>` : ""}
            </div>
          </div>
        </div>
        <div class="scheduler-outcome-right">
          <span style="font-size: 0.72rem; color: var(--text-muted);">${timeAgo}</span>
        </div>
      </div>
    `;
  }

  container.innerHTML = `<div class="scheduler-outcomes-list">${listHtml}</div>`;
}

/**
 * Toggle automated monitoring checks globally
 */
async function toggleGlobalAutoChecks() {
  const btn = document.getElementById("dash-btn-toggle-auto-checks");
  if (btn) btn.disabled = true;

  try {
    const targetState = !schedulerAutoChecksEnabled;
    const res = await fetch(`${API_BASE_URL}/api/scheduler/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_checks_enabled: targetState }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    schedulerAutoChecksEnabled = !!data.auto_checks_enabled;

    showToast(
      schedulerAutoChecksEnabled
        ? "Automated background monitoring enabled."
        : "Automated background monitoring paused globally.",
      "info"
    );

    await fetchSchedulerStatus();
  } catch (err) {
    showToast(`Failed to update automation state: ${err.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/**
 * Re-synchronize scheduler jobs with database monitors
 */
async function syncSchedulerJobs() {
  const btn = document.getElementById("dash-btn-scheduler-sync");
  const icon = btn?.querySelector(".spin-on-load");
  if (icon) icon.classList.add("spinning");

  try {
    const res = await fetch(`${API_BASE_URL}/api/scheduler/sync`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await fetchSchedulerStatus();
    showToast("Scheduler jobs synchronized successfully.", "success");
  } catch (err) {
    showToast(`Sync failed: ${err.message}`, "error");
  } finally {
    setTimeout(() => {
      if (icon) icon.classList.remove("spinning");
    }, 400);
  }
}

/**
 * Run immediate check for a monitor via scheduler worker
 */
async function runSchedulerJobNow(siteId, triggerBtn) {
  if (triggerBtn) {
    triggerBtn.disabled = true;
    triggerBtn.textContent = "Checking...";
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/scheduler/jobs/${siteId}/run-now`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();

    if (result.status === "baseline_created") {
      showToast(result.message || "Baseline snapshot created.", "success");
    } else if (result.status === "change_detected") {
      showToast(`Change detected: ${result.message}`, "warning");
    } else if (result.status === "check_failed") {
      showToast(`Check failed: ${result.message}`, "error");
    } else {
      showToast(result.message || "Check complete (unchanged).", "info");
    }

    await Promise.all([
      fetchSchedulerStatus(),
      fetchMonitors(),
      fetchUnreadCount(),
      fetchChangeHistory(),
    ]);
  } catch (err) {
    showToast(`Check run failed: ${err.message}`, "error");
  } finally {
    if (triggerBtn) {
      triggerBtn.disabled = false;
      triggerBtn.textContent = "Run Now";
    }
  }
}

/**
 * Load global scheduler preferences into Settings view
 */
async function loadSchedulerSettings() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/scheduler/settings`);
    if (!res.ok) return;
    const data = await res.json();
    schedulerAutoChecksEnabled = !!data.auto_checks_enabled;

    const prefSwitch = document.getElementById("pref-scheduler-auto-checks");
    const prefWorkers = document.getElementById("pref-scheduler-max-workers");

    if (prefSwitch) prefSwitch.checked = schedulerAutoChecksEnabled;
    if (prefWorkers) prefWorkers.value = data.max_concurrent_jobs || 5;
  } catch (err) {
    console.warn("Error loading scheduler settings:", err);
  }
}

/**
 * Save global scheduler preferences from Settings view
 */
async function saveSchedulerSettings() {
  const btn = document.getElementById("btn-save-scheduler-prefs");
  if (btn) btn.disabled = true;

  try {
    const prefSwitch = document.getElementById("pref-scheduler-auto-checks");
    const prefWorkers = document.getElementById("pref-scheduler-max-workers");

    const payload = {
      auto_checks_enabled: prefSwitch ? prefSwitch.checked : true,
      max_concurrent_jobs: prefWorkers ? parseInt(prefWorkers.value, 10) || 5 : 5,
    };

    const res = await fetch(`${API_BASE_URL}/api/scheduler/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    schedulerAutoChecksEnabled = !!data.auto_checks_enabled;

    showToast("Automation preferences saved successfully.", "success");
    await fetchSchedulerStatus();
  } catch (err) {
    showToast(`Failed to save settings: ${err.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ==========================================================================
   9. Utilities
   ========================================================================== */

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str).replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[m]));
}

function formatTimeAgo(isoString) {
  if (!isoString) return "Never";
  const d = new Date(isoString);
  const now = new Date();
  const diffSec = Math.floor((now - d) / 1000);
  if (diffSec < 15) return "Just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return d.toLocaleDateString();
}

/* ==========================================================================
   10. Event Listeners & Bootstrapping
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
  // Ensure scroll restoration is manual and reset scroll position to top
  if ("scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }
  window.scrollTo(0, 0);

  // 1. Initialize Theme
  applyTheme(getPreferredTheme());

  const btnThemeToggle = document.getElementById("btn-theme-toggle");
  if (btnThemeToggle) {
    btnThemeToggle.addEventListener("click", toggleTheme);
  }

  const btnThemeLightSelect = document.getElementById("btn-theme-light-select");
  if (btnThemeLightSelect) {
    btnThemeLightSelect.addEventListener("click", () => setTheme("light"));
  }

  const btnThemeDarkSelect = document.getElementById("btn-theme-dark-select");
  if (btnThemeDarkSelect) {
    btnThemeDarkSelect.addEventListener("click", () => setTheme("dark"));
  }

  // 2. Navigation Item Clicks
  const navItems = document.querySelectorAll(".nav-item");
  navItems.forEach((btn) => {
    btn.addEventListener("click", () => {
      const viewId = btn.getAttribute("data-view");
      switchView(viewId);
    });
  });

  // Navigation switch buttons (e.g. "Add Monitor" button on dashboard)
  const navSwitchBtns = document.querySelectorAll(".nav-switch-btn");
  navSwitchBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-target");
      if (target) switchView(target);
    });
  });

  // Sidebar brand link returns to dashboard
  const brandLink = document.getElementById("brand-link");
  if (brandLink) {
    brandLink.addEventListener("click", (e) => {
      e.preventDefault();
      switchView("dashboard");
    });
  }

  // 3. Mobile Sidebar Drawer Toggles
  const btnSidebarToggle = document.getElementById("btn-sidebar-toggle");
  if (btnSidebarToggle) {
    btnSidebarToggle.addEventListener("click", openMobileSidebar);
  }

  const btnSidebarClose = document.getElementById("btn-sidebar-close");
  if (btnSidebarClose) {
    btnSidebarClose.addEventListener("click", closeMobileSidebar);
  }

  const backdrop = document.getElementById("sidebar-backdrop");
  if (backdrop) {
    backdrop.addEventListener("click", closeMobileSidebar);
  }

  // 4. Keyboard Shortcuts: Escape closes modals and drawers
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeMobileSidebar();
      document.querySelectorAll(".modal-backdrop.active").forEach(closeModal);
    }
  });

  // 5. Diagnostic & Sync Buttons
  const btnPingHealth = document.getElementById("btn-ping-health");
  if (btnPingHealth) {
    btnPingHealth.addEventListener("click", () => {
      checkBackendHealth();
    });
  }

  const btnRefreshData = document.getElementById("btn-refresh-data");
  if (btnRefreshData) {
    btnRefreshData.addEventListener("click", async () => {
      const icon = btnRefreshData.querySelector(".spin-on-load");
      if (icon) icon.classList.add("spinning");
      await Promise.all([checkBackendHealth(), fetchMonitors(), fetchChangeHistory()]);
      setTimeout(() => {
        if (icon) icon.classList.remove("spinning");
      }, 400);
      showToast("Data synchronized with backend", "info");
    });
  }

  // 6. Monitor Manager Controls
  const btnOpenAddMonitor = document.getElementById("btn-open-add-monitor");
  if (btnOpenAddMonitor) {
    btnOpenAddMonitor.addEventListener("click", openAddMonitorModal);
  }

  // Monitor Form Submit
  const monitorForm = document.getElementById("monitor-form");
  if (monitorForm) {
    monitorForm.addEventListener("submit", handleMonitorFormSubmit);
  }

  // Toggle active switch label in form
  const formActiveCheckbox = document.getElementById("form-monitor-active");
  const formActiveLabel = document.getElementById("form-monitor-active-label");
  if (formActiveCheckbox && formActiveLabel) {
    formActiveCheckbox.addEventListener("change", () => {
      formActiveLabel.textContent = formActiveCheckbox.checked ? "Active" : "Paused";
    });
  }

  // Toggle screenshot capture switch label in form
  const formCaptureCheckbox = document.getElementById("form-monitor-capture-screenshots");
  const formCaptureLabel = document.getElementById("form-monitor-capture-screenshots-label");
  if (formCaptureCheckbox && formCaptureLabel) {
    formCaptureCheckbox.addEventListener("change", () => {
      formCaptureLabel.textContent = formCaptureCheckbox.checked ? "Enabled" : "Disabled";
    });
  }

  // Close Form Modal Buttons
  const btnCloseFormModal = document.getElementById("btn-close-form-modal");
  const btnCancelFormModal = document.getElementById("btn-cancel-form-modal");
  if (btnCloseFormModal) {
    btnCloseFormModal.addEventListener("click", () => closeModal(document.getElementById("modal-monitor-form")));
  }
  if (btnCancelFormModal) {
    btnCancelFormModal.addEventListener("click", () => closeModal(document.getElementById("modal-monitor-form")));
  }

  // View Details Modal Buttons
  const btnCloseViewModal = document.getElementById("btn-close-view-modal");
  const btnCloseViewBtn = document.getElementById("btn-close-view-btn");
  const btnViewEdit = document.getElementById("btn-view-edit");
  const btnViewDelete = document.getElementById("btn-view-delete");
  const btnViewCheckNow = document.getElementById("btn-view-check-now");
  const btnViewCaptureScreenshot = document.getElementById("btn-view-capture-screenshot");

  if (btnCloseViewModal) {
    btnCloseViewModal.addEventListener("click", () => closeModal(document.getElementById("modal-monitor-view")));
  }
  if (btnCloseViewBtn) {
    btnCloseViewBtn.addEventListener("click", () => closeModal(document.getElementById("modal-monitor-view")));
  }
  if (btnViewEdit) {
    btnViewEdit.addEventListener("click", () => {
      if (currentViewingSiteId) openEditMonitorModal(currentViewingSiteId);
    });
  }
  if (btnViewDelete) {
    btnViewDelete.addEventListener("click", () => {
      if (currentViewingSiteId) openDeleteModal(currentViewingSiteId);
    });
  }
  if (btnViewCheckNow) {
    btnViewCheckNow.addEventListener("click", () => {
      if (currentViewingSiteId) checkMonitorNow(currentViewingSiteId, btnViewCheckNow);
    });
  }
  if (btnViewCaptureScreenshot) {
    btnViewCaptureScreenshot.addEventListener("click", () => {
      if (currentViewingSiteId) captureVisualScreenshot(currentViewingSiteId, btnViewCaptureScreenshot);
    });
  }

  const btnViewTimeMachine = document.getElementById("btn-view-timemachine");
  if (btnViewTimeMachine) {
    btnViewTimeMachine.addEventListener("click", () => {
      if (currentViewingSiteId) openTimeMachineForSite(currentViewingSiteId);
    });
  }

  // Delete Confirmation Modal Buttons
  const btnCloseDeleteModal = document.getElementById("btn-close-delete-modal");
  const btnCancelDelete = document.getElementById("btn-cancel-delete");
  const btnConfirmDelete = document.getElementById("btn-confirm-delete");

  if (btnCloseDeleteModal) {
    btnCloseDeleteModal.addEventListener("click", () => closeModal(document.getElementById("modal-monitor-delete")));
  }
  if (btnCancelDelete) {
    btnCancelDelete.addEventListener("click", () => closeModal(document.getElementById("modal-monitor-delete")));
  }
  if (btnConfirmDelete) {
    btnConfirmDelete.addEventListener("click", handleConfirmDelete);
  }

  // Diff Inspector Modal Buttons
  const btnCloseDiffModal = document.getElementById("btn-close-diff-modal");
  const btnCloseDiffBtn = document.getElementById("btn-close-diff-btn");
  if (btnCloseDiffModal) {
    btnCloseDiffModal.addEventListener("click", () => closeModal(document.getElementById("modal-diff-view")));
  }
  if (btnCloseDiffBtn) {
    btnCloseDiffBtn.addEventListener("click", () => closeModal(document.getElementById("modal-diff-view")));
  }

  // Diff tab button switcher
  document.querySelectorAll(".diff-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabName = btn.getAttribute("data-tab");
      if (tabName) switchDiffTab(tabName);
    });
  });

  // History view refresh button
  const btnRefreshHistory = document.getElementById("btn-refresh-history");
  if (btnRefreshHistory) {
    btnRefreshHistory.addEventListener("click", async () => {
      const icon = btnRefreshHistory.querySelector(".spin-on-load");
      if (icon) icon.classList.add("spinning");
      await fetchChangeHistory();
      setTimeout(() => {
        if (icon) icon.classList.remove("spinning");
      }, 400);
      showToast("Change history refreshed", "info");
    });
  }

  // Backdrop clicks close respective modals
  document.querySelectorAll(".modal-backdrop").forEach((backdropEl) => {
    backdropEl.addEventListener("click", (e) => {
      if (e.target === backdropEl) {
        closeModal(backdropEl);
      }
    });
  });

  // Search input live filtering
  const searchInput = document.getElementById("monitors-search-input");
  const clearSearchBtn = document.getElementById("btn-clear-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      searchQuery = searchInput.value;
      if (clearSearchBtn) {
        clearSearchBtn.style.display = searchQuery ? "block" : "none";
      }
      renderMonitorsTable();
    });
  }
  if (clearSearchBtn) {
    clearSearchBtn.addEventListener("click", () => {
      searchQuery = "";
      if (searchInput) searchInput.value = "";
      clearSearchBtn.style.display = "none";
      renderMonitorsTable();
    });
  }

  // Filter Pills (All / Active / Paused)
  const filterPills = document.querySelectorAll(".filter-pill");
  filterPills.forEach((pill) => {
    pill.addEventListener("click", () => {
      filterPills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      activeFilter = pill.getAttribute("data-filter") || "all";
      renderMonitorsTable();
    });
  });

  // 6.5. Time Machine Controls
  const tmSiteSelect = document.getElementById("tm-site-select");
  if (tmSiteSelect) {
    tmSiteSelect.addEventListener("change", () => {
      const selectedId = parseInt(tmSiteSelect.value, 10);
      if (selectedId) loadTimeMachineSnapshots(selectedId);
    });
  }

  const tmBtnCheckNow = document.getElementById("tm-btn-check-now");
  if (tmBtnCheckNow) {
    tmBtnCheckNow.addEventListener("click", captureSnapshotNow);
  }

  const tmBtnRefresh = document.getElementById("tm-btn-refresh");
  if (tmBtnRefresh) {
    tmBtnRefresh.addEventListener("click", async () => {
      const icon = tmBtnRefresh.querySelector(".spin-on-load");
      if (icon) icon.classList.add("spinning");
      if (tmCurrentSiteId) await loadTimeMachineSnapshots(tmCurrentSiteId);
      setTimeout(() => {
        if (icon) icon.classList.remove("spinning");
      }, 400);
      showToast("Snapshots refreshed", "info");
    });
  }

  const tmSlider = document.getElementById("tm-slider");
  if (tmSlider) {
    tmSlider.addEventListener("input", () => {
      const idx = parseInt(tmSlider.value, 10);
      selectTimeMachineVersion(idx);
    });
    tmSlider.addEventListener("change", () => {
      const idx = parseInt(tmSlider.value, 10);
      selectTimeMachineVersion(idx);
    });
  }

  const tmBtnFirst = document.getElementById("tm-btn-first");
  if (tmBtnFirst) {
    tmBtnFirst.addEventListener("click", () => selectTimeMachineVersion(0));
  }

  const tmBtnPrev = document.getElementById("tm-btn-prev");
  if (tmBtnPrev) {
    tmBtnPrev.addEventListener("click", () => selectTimeMachineVersion(tmCurrentIndex - 1));
  }

  const tmBtnNext = document.getElementById("tm-btn-next");
  if (tmBtnNext) {
    tmBtnNext.addEventListener("click", () => selectTimeMachineVersion(tmCurrentIndex + 1));
  }

  const tmBtnLatest = document.getElementById("tm-btn-latest");
  if (tmBtnLatest) {
    tmBtnLatest.addEventListener("click", () => selectTimeMachineVersion(tmSnapshots.length - 1));
  }

  const tmBtnSortToggle = document.getElementById("tm-btn-sort-toggle");
  if (tmBtnSortToggle) {
    tmBtnSortToggle.addEventListener("click", toggleTimeMachineSort);
  }

  const tmTabInspect = document.getElementById("tm-tab-btn-inspect");
  if (tmTabInspect) {
    tmTabInspect.addEventListener("click", () => switchTimeMachineViewerTab("inspect"));
  }

  const tmTabCompare = document.getElementById("tm-tab-btn-compare");
  if (tmTabCompare) {
    tmTabCompare.addEventListener("click", () => switchTimeMachineViewerTab("compare"));
  }

  const tmDiffTabUnified = document.getElementById("tm-diff-tab-unified");
  if (tmDiffTabUnified) {
    tmDiffTabUnified.addEventListener("click", () => switchTimeMachineCompareSubtab("unified"));
  }

  const tmDiffTabSide = document.getElementById("tm-diff-tab-side");
  if (tmDiffTabSide) {
    tmDiffTabSide.addEventListener("click", () => switchTimeMachineCompareSubtab("side"));
  }

  const tmCompareBaseSelect = document.getElementById("tm-compare-base-select");
  const tmCompareTargetSelect = document.getElementById("tm-compare-target-select");
  if (tmCompareBaseSelect) {
    tmCompareBaseSelect.addEventListener("change", runTimeMachineComparison);
  }
  if (tmCompareTargetSelect) {
    tmCompareTargetSelect.addEventListener("change", runTimeMachineComparison);
  }

  const tmBtnSwapCompare = document.getElementById("tm-btn-swap-compare");
  if (tmBtnSwapCompare) {
    tmBtnSwapCompare.addEventListener("click", swapCompareVersions);
  }

  const tmBtnCopyText = document.getElementById("tm-btn-copy-text");
  if (tmBtnCopyText) {
    tmBtnCopyText.addEventListener("click", copyCurrentVersionText);
  }

  // Keyboard navigation for Time Machine view (ArrowLeft / ArrowRight)
  document.addEventListener("keydown", (e) => {
    const activeView = document.querySelector(".app-view.active");
    if (activeView && activeView.id === "view-timemachine") {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
        return;
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        selectTimeMachineVersion(tmCurrentIndex - 1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        selectTimeMachineVersion(tmCurrentIndex + 1);
      }
    }
  });

  // Visual Changes section controls
  const vcSiteSelect = document.getElementById("vc-site-select");
  if (vcSiteSelect) {
    vcSiteSelect.addEventListener("change", () => {
      const selectedId = parseInt(vcSiteSelect.value, 10);
      if (selectedId) {
        vcCurrentSiteId = selectedId;
        loadVisualComparison(selectedId);
      }
    });
  }

  const vcBtnCapture = document.getElementById("vc-btn-capture");
  if (vcBtnCapture) {
    vcBtnCapture.addEventListener("click", () => {
      const siteId = vcCurrentSiteId || (vcSiteSelect ? parseInt(vcSiteSelect.value, 10) : null);
      if (siteId) {
        captureVisualScreenshot(siteId, vcBtnCapture);
      } else {
        showToast("Please select a target website first.", "warning");
      }
    });
  }

  // Heatmap controls (Prompt 7)
  const hmSiteSelect = document.getElementById("hm-site-select");
  if (hmSiteSelect) {
    hmSiteSelect.addEventListener("change", () => {
      hmCurrentSiteId = hmSiteSelect.value;
      loadHeatmapData(hmCurrentSiteId, hmCurrentDays);
    });
  }

  const hmDaysSelect = document.getElementById("hm-days-select");
  if (hmDaysSelect) {
    hmDaysSelect.addEventListener("change", () => {
      hmCurrentDays = parseInt(hmDaysSelect.value, 10);
      loadHeatmapData(hmCurrentSiteId, hmCurrentDays);
    });
  }

  const hmBtnRefresh = document.getElementById("hm-btn-refresh");
  if (hmBtnRefresh) {
    hmBtnRefresh.addEventListener("click", () => {
      loadHeatmapData(hmCurrentSiteId, hmCurrentDays);
    });
  }

  // Analytics controls (Prompt 7)
  const anSiteSelect = document.getElementById("an-site-select");
  if (anSiteSelect) {
    anSiteSelect.addEventListener("change", () => {
      anCurrentSiteId = anSiteSelect.value;
      loadAnalyticsData(anCurrentSiteId, anCurrentDays);
    });
  }

  const anDaysSelect = document.getElementById("an-days-select");
  if (anDaysSelect) {
    anDaysSelect.addEventListener("change", () => {
      anCurrentDays = parseInt(anDaysSelect.value, 10);
      loadAnalyticsData(anCurrentSiteId, anCurrentDays);
    });
  }

  const anBtnRefresh = document.getElementById("an-btn-refresh");
  if (anBtnRefresh) {
    anBtnRefresh.addEventListener("click", () => {
      loadAnalyticsData(anCurrentSiteId, anCurrentDays);
    });
  }

  // Notifications & Alerts controls (Prompt 8)
  const notifBellBtn = document.getElementById("btn-topbar-notifications");
  if (notifBellBtn) {
    notifBellBtn.addEventListener("click", () => switchView("notifications"));
  }

  const notifSiteSelect = document.getElementById("notif-filter-site");
  if (notifSiteSelect) {
    notifSiteSelect.addEventListener("change", () => {
      notifFilterSiteId = notifSiteSelect.value;
      fetchNotifications();
    });
  }

  const notifTypeSelect = document.getElementById("notif-filter-type");
  if (notifTypeSelect) {
    notifTypeSelect.addEventListener("change", () => {
      notifFilterEventType = notifTypeSelect.value;
      fetchNotifications();
    });
  }

  const notifPillAll = document.getElementById("notif-pill-all");
  const notifPillUnread = document.getElementById("notif-pill-unread");
  if (notifPillAll && notifPillUnread) {
    notifPillAll.addEventListener("click", () => {
      notifPillAll.classList.add("active");
      notifPillUnread.classList.remove("active");
      notifFilterUnreadOnly = false;
      fetchNotifications();
    });

    notifPillUnread.addEventListener("click", () => {
      notifPillUnread.classList.add("active");
      notifPillAll.classList.remove("active");
      notifFilterUnreadOnly = true;
      fetchNotifications();
    });
  }

  const btnMarkAllRead = document.getElementById("btn-mark-all-read");
  if (btnMarkAllRead) {
    btnMarkAllRead.addEventListener("click", markAllNotificationsRead);
  }

  const btnRefreshNotifications = document.getElementById("btn-refresh-notifications");
  if (btnRefreshNotifications) {
    btnRefreshNotifications.addEventListener("click", async () => {
      const icon = btnRefreshNotifications.querySelector(".spin-on-load");
      if (icon) icon.classList.add("spinning");
      await fetchNotifications();
      setTimeout(() => {
        if (icon) icon.classList.remove("spinning");
      }, 400);
      showToast("Notifications refreshed", "info");
    });
  }

  const btnSaveNotifPrefs = document.getElementById("btn-save-notif-prefs");
  if (btnSaveNotifPrefs) {
    btnSaveNotifPrefs.addEventListener("click", saveNotificationPreferences);
  }

  // Scheduler controls (Prompt 9)
  const dashBtnToggleAuto = document.getElementById("dash-btn-toggle-auto-checks");
  if (dashBtnToggleAuto) {
    dashBtnToggleAuto.addEventListener("click", toggleGlobalAutoChecks);
  }

  const dashBtnSchedulerSync = document.getElementById("dash-btn-scheduler-sync");
  if (dashBtnSchedulerSync) {
    dashBtnSchedulerSync.addEventListener("click", syncSchedulerJobs);
  }

  const btnSaveSchedulerPrefs = document.getElementById("btn-save-scheduler-prefs");
  if (btnSaveSchedulerPrefs) {
    btnSaveSchedulerPrefs.addEventListener("click", saveSchedulerSettings);
  }

  // 7. Authentication & User Profile Events (Prompt 10)
  const tabLogin = document.getElementById("tab-auth-login");
  const tabRegister = document.getElementById("tab-auth-register");
  if (tabLogin) tabLogin.addEventListener("click", () => switchAuthTab("login"));
  if (tabRegister) tabRegister.addEventListener("click", () => switchAuthTab("register"));

  const formLogin = document.getElementById("form-auth-login");
  if (formLogin) formLogin.addEventListener("submit", handleLoginSubmit);

  const formRegister = document.getElementById("form-auth-register");
  if (formRegister) formRegister.addEventListener("submit", handleRegisterSubmit);

  const btnFillDemo = document.getElementById("btn-fill-demo");
  if (btnFillDemo) {
    btnFillDemo.addEventListener("click", () => {
      const emailInput = document.getElementById("login-email");
      const passwordInput = document.getElementById("login-password");
      if (emailInput) emailInput.value = "testuser@example.com";
      if (passwordInput) passwordInput.value = "Password123!";
      showToast("Demo admin credentials inserted.", "info");
    });
  }

  const btnUserProfile = document.getElementById("btn-user-profile");
  if (btnUserProfile) {
    btnUserProfile.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleUserDropdown();
    });
  }

  const dropdownBtnSettings = document.getElementById("dropdown-btn-settings");
  if (dropdownBtnSettings) {
    dropdownBtnSettings.addEventListener("click", () => {
      closeUserDropdown();
      switchView("settings");
    });
  }

  const dropdownBtnLogout = document.getElementById("dropdown-btn-logout");
  if (dropdownBtnLogout) {
    dropdownBtnLogout.addEventListener("click", handleLogout);
  }

  const btnSettingsLogout = document.getElementById("btn-settings-logout");
  if (btnSettingsLogout) {
    btnSettingsLogout.addEventListener("click", handleLogout);
  }

  const formUpdateProfile = document.getElementById("form-update-profile");
  if (formUpdateProfile) {
    formUpdateProfile.addEventListener("submit", handleProfileNameUpdate);
  }

  const formChangePassword = document.getElementById("form-change-password");
  if (formChangePassword) {
    formChangePassword.addEventListener("submit", handlePasswordChange);
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#user-menu-wrapper")) {
      closeUserDropdown();
    }
  });

  // 8. Initial Authentication & Data Verification
  checkAuthStatus();
});

// Expose functions to global window scope for inline onclick handlers
window.openViewModal = openViewModal;
window.switchView = switchView;
window.fetchMonitors = fetchMonitors;
window.checkMonitorNow = checkMonitorNow;
window.openDiffModal = openDiffModal;
window.fetchChangeHistory = fetchChangeHistory;
window.openTimeMachineForSite = openTimeMachineForSite;
window.captureSnapshotNow = captureSnapshotNow;
window.initTimeMachine = initTimeMachine;
window.selectTimeMachineVersion = selectTimeMachineVersion;
window.runTimeMachineComparison = runTimeMachineComparison;
window.openAddMonitorModal = openAddMonitorModal;
window.captureVisualScreenshot = captureVisualScreenshot;
window.openVisualChangesForSite = openVisualChangesForSite;
window.loadVisualComparison = loadVisualComparison;
window.initVisualChanges = initVisualChanges;
window.initHeatmapView = initHeatmapView;
window.loadHeatmapData = loadHeatmapData;
window.renderHeatmapView = renderHeatmapView;
window.initAnalyticsView = initAnalyticsView;
window.loadAnalyticsData = loadAnalyticsData;
window.renderAnalyticsView = renderAnalyticsView;
window.populateNotificationSiteSelect = populateNotificationSiteSelect;
window.fetchUnreadCount = fetchUnreadCount;
window.fetchNotifications = fetchNotifications;
window.renderNotificationsList = renderNotificationsList;
window.handleNotificationAction = handleNotificationAction;
window.toggleNotificationRead = toggleNotificationRead;
window.markAllNotificationsRead = markAllNotificationsRead;
window.deleteNotificationItem = deleteNotificationItem;
window.resetNotificationFilters = resetNotificationFilters;
window.loadNotificationPreferences = loadNotificationPreferences;
window.saveNotificationPreferences = saveNotificationPreferences;
window.fetchSchedulerStatus = fetchSchedulerStatus;
window.renderSchedulerQueue = renderSchedulerQueue;
window.renderSchedulerOutcomes = renderSchedulerOutcomes;
window.toggleGlobalAutoChecks = toggleGlobalAutoChecks;
window.syncSchedulerJobs = syncSchedulerJobs;
window.runSchedulerJobNow = runSchedulerJobNow;
window.loadSchedulerSettings = loadSchedulerSettings;
window.saveSchedulerSettings = saveSchedulerSettings;
window.showAuthOverlay = showAuthOverlay;
window.hideAuthOverlay = hideAuthOverlay;
window.switchAuthTab = switchAuthTab;
window.handleLogout = handleLogout;


