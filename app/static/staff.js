const error = document.querySelector("#staff-error"), success = document.querySelector("#staff-success");
let errorTimer = null;
new MutationObserver(() => {
  clearTimeout(errorTimer);
  if (error.textContent.trim()) errorTimer = setTimeout(() => { error.textContent = ""; }, 4000);
}).observe(error, { childList: true, characterData: true, subtree: true });
let accessToken = sessionStorage.getItem("trimtimeStaffToken");
let shopId = Number(sessionStorage.getItem("trimtimeShopId")) || 1;
let staffRole = sessionStorage.getItem("trimtimeStaffRole") || "owner";
let staffBarberId = Number(sessionStorage.getItem("trimtimeBarberId")) || null;
let shop = null, socket = null, analytics = null;
const localToday = new Date().toLocaleDateString("en-CA");
function dateInputDisplay(value) { const [year, month, day] = value.split("-"); return `${day}/${month}/${year}`; }
function dateInputIso(value) {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value.trim());
  if (!match) throw new Error("Enter dates in DD/MM/YYYY format, for example 21/10/2026.");
  const [, day, month, year] = match, iso = `${year}-${month}-${day}`, parsed = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(parsed.getTime()) || parsed.getFullYear() !== Number(year) || parsed.getMonth() + 1 !== Number(month) || parsed.getDate() !== Number(day)) throw new Error("Enter a valid calendar date in DD/MM/YYYY format.");
  return iso;
}
document.querySelector("#analytics-start-date").value = dateInputDisplay(localToday);
document.querySelector("#analytics-end-date").value = dateInputDisplay(localToday);

function consolidateManagementSection(sectionId, childIds) {
  const section = document.querySelector(sectionId), container = document.createElement("div"); container.className = "panel management-section";
  childIds.forEach((id) => { const child = document.querySelector(id); child.classList.remove("panel"); container.appendChild(child); });
  section.appendChild(container);
}
consolidateManagementSection("#tab-services", ["#service-form", "#service-list"]);
consolidateManagementSection("#tab-team", ["#barber-form", "#barber-list", "#staff-form", "#staff-list"]);
function consolidateWholeSection(sectionId) {
  const section = document.querySelector(sectionId), container = document.createElement("div");
  container.className = "panel management-section";
  Array.from(section.children).forEach((child) => { child.classList.remove("panel"); container.appendChild(child); });
  section.appendChild(container);
}
consolidateWholeSection("#tab-analytics");
consolidateWholeSection("#tab-settings");
consolidateWholeSection("#tab-shop");

fetch("/api/platform/banner").then((response) => response.json()).then((banner) => {
  document.querySelector("#banner-eyebrow").textContent = banner.eyebrow;
  document.querySelector("#banner-title").textContent = banner.title;
  document.querySelector("#banner-message").textContent = banner.message;
  if (banner.login_image_url) document.querySelector("#register-promo-image").style.backgroundImage = `url("${banner.login_image_url}")`;
}).catch(() => {});

function formatApiError(detail) {
  if (Array.isArray(detail)) return detail.map((item) => `${(item.loc || []).filter((part) => part !== "body").join(" → ") || "Input"}: ${item.msg || "Invalid value"}`).join(" | ");
  if (detail && typeof detail === "object") return detail.message || JSON.stringify(detail);
  return detail || "Request failed";
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}`, ...(options.headers || {}) } });
  if (!response.ok) { const body = await response.json().catch(() => ({})); if (response.status === 401) logout(); throw new Error(formatApiError(body.detail)); }
  return response.json();
}
function message(text) { success.textContent = text; setTimeout(() => success.textContent = "", 3000); }
function escapeHtml(value) { const node = document.createElement("span"); node.textContent = value ?? ""; return node.innerHTML; }
function formatReportDate(value) { return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "long", year: "numeric" }); }

function acceptSession(session, identifier = "") {
  accessToken = session.access_token; shopId = session.shop_id; staffRole = session.role; staffBarberId = session.barber_id;
  sessionStorage.setItem("trimtimeStaffToken", accessToken); sessionStorage.setItem("trimtimeShopId", shopId); sessionStorage.setItem("trimtimeStaffRole", staffRole); sessionStorage.setItem("trimtimeBarberId", staffBarberId || ""); sessionStorage.setItem("trimtimeLoginIdentifier", identifier); showBoard();
  if (session.must_change_password) { document.querySelector('[data-tab="settings"]').click(); document.querySelector("#password-notice").textContent = "Your administrator issued a temporary password. Change it now before continuing."; error.textContent = "Please change your temporary password."; }
}

async function handleGoogleCredential(googleResponse) {
  error.textContent = "";
  try { const response = await fetch("/api/auth/google", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credential: googleResponse.credential }) }); const session = await response.json(); if (!response.ok) throw new Error(formatApiError(session.detail)); acceptSession(session); }
  catch (reason) { error.textContent = reason.message; }
}
window.handleGoogleCredential = handleGoogleCredential;

async function initializeGoogleLogin() {
  const config = await fetch("/api/auth/google/config").then((response) => response.json()).catch(() => ({ enabled: false }));
  if (!config.enabled) { const note = document.querySelector("#google-login-note"); note.textContent = "Google sign-in becomes available after GOOGLE_CLIENT_ID is configured."; note.classList.remove("hidden"); return; }
  if (!window.google?.accounts?.id) return;
  document.querySelector("#google-login-area").classList.remove("hidden");
  google.accounts.id.initialize({ client_id: config.client_id, callback: handleGoogleCredential });
  google.accounts.id.renderButton(document.querySelector("#google-signin-button"), { theme: "outline", size: "large", width: 320, text: "signin_with" });
}
if (window.google?.accounts?.id) initializeGoogleLogin(); else document.querySelector("#google-identity-script").addEventListener("load", initializeGoogleLogin);

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = ""; success.textContent = "";
  const button = event.submitter;
  try {
    button.disabled = true; button.textContent = "Signing in…";
    const identifier = document.querySelector("#email").value.trim();
    const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier, email: identifier, password: document.querySelector("#password").value }) });
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(formatApiError(body.detail)); }
    acceptSession(await response.json(), identifier);
  } catch (reason) { error.textContent = reason.message; }
  finally { button.disabled = false; button.textContent = "Sign in"; }
});

document.querySelector("#show-registration").addEventListener("click", () => { document.querySelector("#login-panel").classList.add("hidden"); document.querySelector("#registration-panel").classList.remove("hidden"); });
document.querySelector("#back-to-login").addEventListener("click", () => { document.querySelector("#registration-panel").classList.add("hidden"); document.querySelector("#login-panel").classList.remove("hidden"); });
if (!accessToken && new URLSearchParams(location.search).get("auth") === "signup") document.querySelector("#show-registration").click();
document.querySelector("#show-forgot-password").addEventListener("click", () => { document.querySelector("#login-panel").classList.add("hidden"); document.querySelector("#forgot-password-panel").classList.remove("hidden"); });
document.querySelectorAll(".back-to-login").forEach((button) => button.addEventListener("click", () => { document.querySelector("#forgot-password-panel").classList.add("hidden"); document.querySelector("#login-panel").classList.remove("hidden"); }));

async function requestPasswordReset(identifier, resultElement) {
  const response = await fetch("/api/auth/forgot-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier }) });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiError(body.detail));
  resultElement.replaceChildren(document.createTextNode(body.message));
  if (body.development_reset_url) { const link = document.createElement("a"); link.href = body.development_reset_url; link.textContent = " Open local reset link"; resultElement.append(link); }
}

document.querySelector("#forgot-password-form").addEventListener("submit", async (event) => { event.preventDefault(); error.textContent = ""; try { await requestPasswordReset(document.querySelector("#forgot-identifier").value.trim(), document.querySelector("#forgot-result")); } catch (reason) { error.textContent = reason.message; } });
document.querySelector("#settings-forgot-form").addEventListener("submit", async (event) => { event.preventDefault(); error.textContent = ""; try { await requestPasswordReset(document.querySelector("#settings-forgot-identifier").value.trim(), document.querySelector("#settings-forgot-result")); } catch (reason) { error.textContent = reason.message; } });
document.querySelector("#reset-password-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = ""; const newPassword = document.querySelector("#reset-new-password").value;
  if (newPassword !== document.querySelector("#reset-confirm-password").value) { error.textContent = "New password and confirmation do not match."; return; }
  try { const response = await fetch("/api/auth/reset-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: new URLSearchParams(location.search).get("reset_token"), new_password: newPassword }) }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(formatApiError(body.detail)); history.replaceState({}, "", "/staff"); document.querySelector("#reset-password-panel").classList.add("hidden"); document.querySelector("#login-panel").classList.remove("hidden"); success.textContent = body.message; } catch (reason) { error.textContent = reason.message; }
});
document.querySelector("#registration-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = ""; const button = event.submitter;
  try {
    button.disabled = true; button.textContent = "Creating shop…";
    const latitude = document.querySelector("#register-latitude").value, longitude = document.querySelector("#register-longitude").value;
    const response = await fetch("/api/auth/register-shop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: document.querySelector("#register-shop-name").value.trim(), phone: document.querySelector("#register-phone").value.trim() || null, gst_number: document.querySelector("#register-gst").value.trim().toUpperCase() || null, address: document.querySelector("#register-address").value.trim(), latitude: latitude ? Number(latitude) : null, longitude: longitude ? Number(longitude) : null, owner_name: document.querySelector("#register-owner-name").value.trim(), owner_email: document.querySelector("#register-email").value.trim().toLowerCase(), owner_password: document.querySelector("#register-password").value, terms_accepted: document.querySelector("#register-terms").checked }) });
    const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(formatApiError(body.detail));
    accessToken = body.access_token; shopId = body.shop_id; staffRole = body.role; staffBarberId = body.barber_id;
    sessionStorage.setItem("trimtimeStaffToken", accessToken); sessionStorage.setItem("trimtimeShopId", shopId); sessionStorage.setItem("trimtimeStaffRole", staffRole); sessionStorage.setItem("trimtimeBarberId", "");
    document.querySelector("#registration-panel").classList.add("hidden"); message("Shop created successfully"); await showBoard();
  } catch (reason) { error.textContent = reason.message; }
  finally { button.disabled = false; button.textContent = "Create shop and sign in"; }
});

function logout() {
  sessionStorage.clear(); accessToken = null; document.querySelector("#login-panel").classList.remove("hidden"); document.querySelector("#dashboard").classList.add("hidden");
  if (socket) socket.close();
}

async function showBoard() {
  document.querySelector("#login-panel").classList.add("hidden"); document.querySelector("#dashboard").classList.remove("hidden");
  document.querySelector("#account-management-nav").classList.add("hidden");
  document.querySelector("#settings-forgot-identifier").value = sessionStorage.getItem("trimtimeLoginIdentifier") || "";
  document.querySelector("#pause-queue").classList.toggle("hidden", staffRole === "barber");
  document.querySelectorAll(".manager-only").forEach((item) => item.classList.toggle("hidden", !["owner", "manager"].includes(staffRole)));
  try { await refreshAll(); connectRealtime(); }
  catch (reason) { error.textContent = reason.message || "Dashboard data could not be loaded. Refresh the page and sign in again."; }
}

async function refreshAll() {
  shop = await fetch(`/api/shops/${shopId}`).then((response) => response.json());
  document.querySelector("#pause-queue").textContent = shop.queue_paused ? "Resume new joins" : "Pause new joins";
  const walkInButton = document.querySelector("#staff-queue-submit");
  walkInButton.disabled = shop.queue_paused;
  walkInButton.textContent = shop.queue_paused ? "New joins are paused" : "Add to live queue";
  document.querySelector("#shop-qr").src = `/api/shops/${shopId}/qr`;
  document.querySelector("#download-qr").href = `/api/shops/${shopId}/qr`;
  const analyticsRange = new URLSearchParams({ start_date: dateInputIso(document.querySelector("#analytics-start-date").value), end_date: dateInputIso(document.querySelector("#analytics-end-date").value) });
  analytics = await request(`/api/shops/${shopId}/analytics?${analyticsRange}`);
  fillShopForm(); renderServices(); renderBarbers(); fillStaffBarberSelect();
  const queueEntries = await request(`/api/shops/${shopId}/queue`);
  const appointmentItems = await request(`/api/shops/${shopId}/appointments`);
  document.querySelector("#queue-nav-count").textContent = queueEntries.filter((entry) => ["waiting", "serving"].includes(entry.status)).length;
  document.querySelector("#appointment-nav-count").textContent = appointmentItems.length;
  renderQueue(queueEntries);
  renderAppointments(appointmentItems);
  renderRangeAnalytics(analytics);
  try { renderStaff(await request(`/api/shops/${shopId}/staff`)); } catch (_) {}
}

function renderAppointments(items) {
  const list = document.querySelector("#appointment-list");
  if (!items.length) { list.innerHTML = '<div class="panel empty">No appointments booked.</div>'; return; }
  list.innerHTML = items.map((item) => { const terminal = ["completed", "cancelled", "no_show"].includes(item.status); const actions = terminal ? "" : item.status === "queued" ? `<button data-appointment="${item.id}" data-appointment-status="cancelled" class="ghost">Cancel appointment</button>` : `<button data-appointment="${item.id}" data-appointment-status="completed">Complete</button><button data-appointment="${item.id}" data-appointment-status="cancelled" class="ghost">Cancel appointment</button>`; return `<article class="queue-item appointment-item"><div class="token">${escapeHtml(item.token)}</div><div class="customer"><strong>${escapeHtml(item.customer_name)}</strong><span>${escapeHtml(item.service_name)} · ${new Date(item.scheduled_at).toLocaleString()}</span></div><div class="position">${item.status === "queued" ? "PRIORITY · Live queue" : item.status}</div><div class="actions">${actions}</div></article>`; }).join("");
  list.querySelectorAll("[data-appointment]").forEach((button) => button.addEventListener("click", async () => { try { await request(`/api/appointments/${button.dataset.appointment}`, { method: "PATCH", body: JSON.stringify({ status: button.dataset.appointmentStatus }) }); message(button.dataset.appointmentStatus === "cancelled" ? "Appointment cancelled" : "Appointment completed"); await refreshAll(); } catch (reason) { error.textContent = reason.message; } }));
}

function renderRangeAnalytics(data) {
  const barberCards = (data.barbers || []).map((barber) => `<article class="mini-card"><span>Barber</span><strong>${escapeHtml(barber.barber_name)}</strong><small>${barber.waiting} waiting &middot; ${barber.serving} serving</small><span>${barber.completed_services} completed &middot; ${barber.appointments} appointments &middot; ${barber.cancelled_appointments || 0} cancelled</span><span>&#9733; ${barber.average_rating || 0} &middot; ${barber.review_count || 0} reviews</span><span>&#8377;${barber.estimated_revenue_rupees} revenue</span></article>`).join("");
  const dailyCards = (data.daily_revenue || []).map((day) => `<article class="mini-card"><span>${formatReportDate(day.date)}</span><strong>&#8377;${day.total_revenue_rupees}</strong>${day.barbers.map((barber) => `<small>${escapeHtml(barber.barber_name)}: &#8377;${barber.revenue_rupees}</small>`).join("")}</article>`).join("");
  const dailySection = dailyCards || '<article class="mini-card"><span>Daily revenue</span><strong>&#8377;0</strong><small>No completed services in this date range.</small></article>';
  document.querySelector("#analytics-grid").innerHTML = `<article class="mini-card"><span>Revenue</span><strong>&#8377;${data.estimated_revenue_rupees}</strong></article><article class="mini-card"><span>Completed services</span><strong>${data.completed_services}</strong></article><article class="mini-card"><span>Appointments</span><strong>${data.appointments || 0}</strong></article><article class="mini-card"><span>Cancelled appointments</span><strong>${data.cancelled_appointments || 0}</strong></article><article class="mini-card"><span>Queue entries</span><strong>${data.total_queue_entries || 0}</strong></article>${barberCards}<div class="analytics-daily"><h2>Daily revenue &middot; ${formatReportDate(data.range_start)} to ${formatReportDate(data.range_end)}</h2><div class="management-grid">${dailySection}</div></div>`;
}

function fillStaffBarberSelect() {
  document.querySelector("#staff-barber").innerHTML = `<option value="">Not applicable</option>${shop.barbers.map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("")}`;
  document.querySelector("#staff-queue-service").innerHTML = shop.services.map((item) => `<option value="${item.id}">${escapeHtml(item.name)} · ${item.duration_minutes} min</option>`).join("");
  const queueBarbers = staffRole === "barber" ? shop.barbers.filter((item) => item.id === staffBarberId) : shop.barbers;
  const queueBarberSelect = document.querySelector("#staff-queue-barber");
  queueBarberSelect.innerHTML = `${staffRole === "barber" ? "" : '<option value="">Any available barber</option>'}${queueBarbers.map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("")}`;
  queueBarberSelect.disabled = staffRole === "barber";
}

function fillShopForm() {
  document.querySelector("#shop-profile-name").value = shop.name; document.querySelector("#shop-phone").value = shop.phone || "";
  document.querySelector("#shop-gst").value = shop.gst_number || ""; document.querySelector("#shop-profile-address").value = shop.address;
  document.querySelector("#opens-at").value = shop.opens_at; document.querySelector("#closes-at").value = shop.closes_at; document.querySelector("#shop-timezone").value = shop.timezone;
  const preview = document.querySelector("#shop-photo-preview"); preview.classList.toggle("hidden", !shop.photo_url); if (shop.photo_url) preview.src = shop.photo_url;
}

function renderQueue(entries) {
  const list = document.querySelector("#queue-list"); list.replaceChildren();
  if (!entries.length) { list.innerHTML = '<div class="panel empty">No customer is currently waiting.</div>'; return; }
  entries.forEach((entry) => {
    const card = document.createElement("article"); card.className = `queue-item ${entry.status}`;
    const availableBarbers = staffRole === "barber" ? shop.barbers.filter((barber) => barber.id === staffBarberId) : shop.barbers;
    const options = availableBarbers.map((barber) => `<option value="${barber.id}" ${entry.barber_id === barber.id || (staffRole === "barber" && barber.id === staffBarberId) ? "selected" : ""}>${escapeHtml(barber.name)}</option>`).join("");
    const selectedServiceIds = new Set(entry.service_ids || (entry.service_id ? [entry.service_id] : []));
    const serviceOptions = shop.services.map((service) => `<label><input type="checkbox" value="${service.id}" ${selectedServiceIds.has(service.id) ? "checked" : ""} ${staffRole === "barber" || entry.source === "appointment" ? "disabled" : ""} /><span>${escapeHtml(service.name)} <small>₹${service.price_rupees}</small></span></label>`).join("");
    const actions = entry.status === "waiting" ? `<button data-action="start">${staffRole === "barber" ? "Claim & start" : "Start"}</button>${staffRole === "barber" ? "" : '<button data-action="skip" class="secondary">Skip</button>'}` : entry.status === "serving" ? '<button data-action="complete">Mark done</button>' : '<button data-action="restore" class="secondary">Restore to queue</button>';
    const position = entry.status === "serving" ? "In chair" : entry.availability_message || `${entry.people_ahead} ${entry.ahead_label || "people ahead"} · ~${entry.estimated_wait_minutes} min`;
    card.innerHTML = `<div class="token">${entry.token}</div><div class="customer"><strong>${escapeHtml(entry.customer_name)}</strong><span>${escapeHtml(entry.service_name)} · ${entry.source === "appointment" ? "PRIORITY APPOINTMENT" : entry.source.replace("_", " ")}</span>${entry.email ? `<small>${escapeHtml(entry.email)}</small>` : ""}<div class="queue-assignment-controls"><div class="queue-assignment-control"><span class="control-caption">Choose services</span><details class="queue-service-picker"><summary>Select services</summary><div class="queue-service-checks">${serviceOptions}</div></details></div><div class="queue-assignment-control"><span class="control-caption">Assign barber</span><select class="barber-select" ${staffRole === "barber" ? "disabled" : ""}><option value="">Assign barber</option>${options}</select></div></div><p class="queue-card-error error" aria-live="polite"></p></div><div class="position">${position}</div><div class="actions">${actions}${staffRole === "barber" ? "" : '<button data-action="cancel" class="ghost">Cancel</button>'}</div>`;
    card.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => queueAction(entry.id, button.dataset.action, card.querySelector(".barber-select").value, [...card.querySelectorAll(".queue-service-checks input:checked")].map((input) => Number(input.value)), card))); list.append(card);
  });
}

function renderServices() {
  const list = document.querySelector("#service-list"); list.innerHTML = shop.services.map((service) => `<article class="mini-card"><strong>${escapeHtml(service.name)}</strong><span>${service.duration_minutes} min · ₹${service.price_rupees}</span><div class="actions"><button data-service="${service.id}" class="secondary">Edit</button><button data-delete-service="${service.id}" class="ghost">Delete</button></div></article>`).join("");
  list.querySelectorAll("[data-service]").forEach((button) => button.addEventListener("click", () => editService(Number(button.dataset.service))));
  list.querySelectorAll("[data-delete-service]").forEach((button) => button.addEventListener("click", () => deleteService(Number(button.dataset.deleteService))));
}
function renderBarbers() {
  const list = document.querySelector("#barber-list");
  list.innerHTML = shop.barbers.map((barber) => { const counts = (analytics?.barbers || []).find((item) => item.barber_id === barber.id); return `<article class="mini-card"><strong>${escapeHtml(barber.name)}</strong><span>${counts?.waiting || 0} waiting · ${counts?.serving || 0} serving</span><small>${counts?.completed_services || 0} completed services · ★ ${counts?.average_rating || 0} (${counts?.review_count || 0} reviews)</small><div class="actions"><button data-barber="${barber.id}" class="secondary">Rename</button><button data-delete-barber="${barber.id}" class="ghost">Delete</button></div></article>`; }).join("");
  list.querySelectorAll("[data-barber]").forEach((button) => button.addEventListener("click", () => renameBarber(Number(button.dataset.barber))));
  list.querySelectorAll("[data-delete-barber]").forEach((button) => button.addEventListener("click", () => deleteBarber(Number(button.dataset.deleteBarber))));
}
function renderStaff(users) {
  const list = document.querySelector("#staff-list");
  list.innerHTML = users.map((user) => `<article class="mini-card"><strong>${escapeHtml(user.name)}</strong><span>${escapeHtml(user.email)} · ${user.role}</span><small>${user.is_active ? "Active" : "Inactive"}${user.must_change_password ? " · Password change required" : ""}</small>${user.role === "barber" ? `<label>Linked barber<select data-staff-barber="${user.id}">${shop.barbers.map((barber) => `<option value="${barber.id}" ${user.barber_id === barber.id ? "selected" : ""}>${escapeHtml(barber.name)}</option>`).join("")}</select></label><button type="button" data-save-staff-link="${user.id}" data-staff-name="${escapeHtml(user.name)}" class="secondary">Save barber link</button>` : ""}<div class="actions"><button type="button" data-reset-staff="${user.id}" class="secondary">Reset password</button><button type="button" data-toggle-staff="${user.id}" data-active="${!user.is_active}" class="secondary">${user.is_active ? "Deactivate" : "Activate"}</button>${user.role === "owner" ? "" : `<button type="button" data-delete-staff="${user.id}" class="ghost">Delete</button>`}</div></article>`).join("");
  list.querySelectorAll("[data-reset-staff]").forEach((button) => button.addEventListener("click", () => resetStaffPassword(Number(button.dataset.resetStaff))));
  list.querySelectorAll("[data-toggle-staff]").forEach((button) => button.addEventListener("click", () => setStaffStatus(Number(button.dataset.toggleStaff), button.dataset.active === "true")));
  list.querySelectorAll("[data-delete-staff]").forEach((button) => button.addEventListener("click", () => deleteStaff(Number(button.dataset.deleteStaff))));
  list.querySelectorAll("[data-save-staff-link]").forEach((button) => button.addEventListener("click", async () => { try { const staffId = Number(button.dataset.saveStaffLink); const barberId = Number(list.querySelector(`[data-staff-barber="${staffId}"]`).value); await request(`/api/staff/${staffId}/profile`, { method: "PATCH", body: JSON.stringify({ name: button.dataset.staffName, role: "barber", barber_id: barberId }) }); message("Barber login linked successfully"); await refreshAll(); } catch (reason) { error.textContent = reason.message; } }));
}

async function resetStaffPassword(staffId) {
  const temporaryPassword = prompt("Enter a temporary password (minimum 8 characters)");
  if (temporaryPassword === null) return;
  if (temporaryPassword.length < 8) { error.textContent = "Temporary password must contain at least 8 characters."; return; }
  try { await request(`/api/staff/${staffId}/password`, { method: "PATCH", body: JSON.stringify({ temporary_password: temporaryPassword }) }); message("Temporary password set. The staff member must change it after signing in."); await refreshAll(); }
  catch (reason) { error.textContent = reason.message; }
}

async function setStaffStatus(staffId, isActive) {
  try { await request(`/api/staff/${staffId}/status`, { method: "PATCH", body: JSON.stringify({ is_active: isActive }) }); message(isActive ? "Staff account activated" : "Staff account deactivated"); await refreshAll(); }
  catch (reason) { error.textContent = reason.message; }
}

async function deleteStaff(staffId) {
  if (!confirm("Delete this staff login? This action cannot be undone.")) return;
  try { await request(`/api/staff/${staffId}`, { method: "DELETE" }); message("Staff account deleted"); await refreshAll(); }
  catch (reason) { error.textContent = reason.message; }
}

async function queueAction(id, action, barberId, serviceIds, card) {
  const cardError = card?.querySelector(".queue-card-error");
  const showCardError = (text) => { if (cardError) { cardError.textContent = text; setTimeout(() => { if (cardError.textContent === text) cardError.textContent = ""; }, 5000); } else error.textContent = text; };
  if (action === "start" && !serviceIds.length && !barberId) { showCardError("Please choose a service and assign a barber before starting."); return; }
  if (action === "start" && !serviceIds.length) { showCardError("Please choose at least one service before starting."); return; }
  if (action === "start" && !barberId) { showCardError("Please assign a barber before starting."); return; }
  try { await request(`/api/queue/${id}/action`, { method: "POST", body: JSON.stringify({ action, barber_id: barberId ? Number(barberId) : null, service_ids: serviceIds }) }); await refreshAll(); }
  catch (reason) { showCardError(reason.message); }
}
async function editService(id) {
  const service = shop.services.find((item) => item.id === id); const name = prompt("Service name", service.name); if (!name) return;
  const duration = Number(prompt("Duration in minutes", service.duration_minutes)); const price = Number(prompt("Price in rupees", service.price_rupees));
  await request(`/api/services/${id}`, { method: "PATCH", body: JSON.stringify({ name, duration_minutes: duration, price_rupees: price, is_active: true }) }); message("Service updated"); await refreshAll();
}
async function deleteService(id) {
  if (!confirm("Delete this service? Historical queue and revenue records will be preserved.")) return;
  try { await request(`/api/services/${id}`, { method: "DELETE" }); message("Service deleted"); await refreshAll(); }
  catch (reason) { error.textContent = reason.message; }
}
async function renameBarber(id) {
  const barber = shop.barbers.find((item) => item.id === id); const name = prompt("Barber name", barber.name); if (!name) return;
  await request(`/api/barbers/${id}`, { method: "PATCH", body: JSON.stringify({ name, is_active: true }) }); message("Barber updated"); await refreshAll();
}
async function deleteBarber(id) {
  if (!confirm("Delete this barber? Past service history will be preserved.")) return;
  try { await request(`/api/barbers/${id}`, { method: "DELETE" }); message("Barber deleted"); await refreshAll(); }
  catch (reason) { error.textContent = reason.message; }
}

document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
  const target = button.dataset.tab;
  const fromDashboardNav = Boolean(button.closest(".dashboard-nav"));
  const managementTargets = ["services", "team", "analytics", "settings", "shop"];
  const canManage = ["owner", "manager"].includes(staffRole);
  const dashboard = document.querySelector("#dashboard");
  managementTargets.forEach((name) => dashboard.appendChild(document.querySelector(`#tab-${name}`)));
  document.querySelectorAll(".tab-section").forEach((section) => section.classList.add("hidden"));
  if (target === "account") {
    if (canManage) managementTargets.forEach((name) => document.querySelector(`#tab-${name}`).classList.remove("hidden"));
    else ["analytics", "settings"].forEach((name) => document.querySelector(`#tab-${name}`).classList.remove("hidden"));
    document.querySelector("#account-management-nav").classList.remove("hidden");
  } else if (target === "analytics" && fromDashboardNav) {
    document.querySelector("#tab-analytics").classList.remove("hidden");
    document.querySelector("#account-management-nav").classList.add("hidden");
  } else if (managementTargets.includes(target) && canManage) {
    managementTargets.forEach((name) => document.querySelector(`#tab-${name}`).classList.remove("hidden"));
    document.querySelector("#account-management-nav").classList.remove("hidden");
    setTimeout(() => document.querySelector(`#tab-${target}`).scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  } else if (["analytics", "settings"].includes(target)) {
    document.querySelector(`#tab-${target}`).classList.remove("hidden");
    document.querySelector("#account-management-nav").classList.remove("hidden");
  } else {
    document.querySelector(`#tab-${target === "account" ? "settings" : target}`).classList.remove("hidden");
    document.querySelector("#account-management-nav").classList.add("hidden");
  }
  const dashboardTarget = ["services", "team", "settings", "shop"].includes(target) ? "account" : target;
  document.querySelectorAll(".dashboard-nav [data-tab]").forEach((item) => item.classList.toggle("active", item.dataset.tab === dashboardTarget));
  document.querySelectorAll("#account-management-nav [data-tab]").forEach((item) => item.classList.toggle("active", item.dataset.tab === target));
}));
const accountSectionObserver = new IntersectionObserver((entries) => {
  if (document.querySelector("#account-management-nav").classList.contains("hidden")) return;
  const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!visible) return;
  const activeName = visible.target.id.replace("tab-", "");
  document.querySelectorAll("#account-management-nav [data-tab]").forEach((item) => item.classList.toggle("active", item.dataset.tab === activeName));
}, { rootMargin: "-190px 0px -45% 0px", threshold: [0, .1, .25, .5] });
["services", "team", "analytics", "settings", "shop"].forEach((name) => accountSectionObserver.observe(document.querySelector(`#tab-${name}`)));
document.querySelector("#logout").addEventListener("click", logout);
document.querySelector("#analytics-filter").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = "";
  let startDate, endDate;
  try { startDate = dateInputIso(document.querySelector("#analytics-start-date").value); endDate = dateInputIso(document.querySelector("#analytics-end-date").value); }
  catch (reason) { error.textContent = reason.message; return; }
  if (endDate < startDate) { error.textContent = "To date must be the same as or later than From date."; return; }
  try { await refreshAll(); message(`Report generated for ${formatReportDate(startDate)} to ${formatReportDate(endDate)}`); }
  catch (reason) { error.textContent = reason.message; }
});
document.querySelector("#pause-queue").addEventListener("click", async () => { await request(`/api/shops/${shopId}/state`, { method: "PATCH", body: JSON.stringify({ queue_paused: !shop.queue_paused }) }); await refreshAll(); });
document.querySelector("#staff-queue-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = "";
  const result = document.querySelector("#staff-queue-result"), submit = document.querySelector("#staff-queue-submit");
  result.className = "form-result"; result.textContent = "";
  const barberId = document.querySelector("#staff-queue-barber").value;
  try {
    const serviceId = Number(document.querySelector("#staff-queue-service").value);
    if (!serviceId) throw new Error("Please select a service before adding the customer.");
    submit.disabled = true; submit.textContent = "Adding customer...";
    const created = await request(`/api/shops/${shopId}/queue`, { method: "POST", body: JSON.stringify({ customer_name: document.querySelector("#staff-queue-name").value.trim(), phone: document.querySelector("#staff-queue-phone").value.trim() || null, email: document.querySelector("#staff-queue-email").value.trim().toLowerCase() || null, service_id: serviceId, barber_id: barberId ? Number(barberId) : null, source: "walk_in" }) });
    event.target.reset(); fillStaffBarberSelect();
    const queueEntries = await request(`/api/shops/${shopId}/queue`);
    renderQueue(queueEntries); document.querySelector("#queue-nav-count").textContent = queueEntries.filter((entry) => ["waiting", "serving"].includes(entry.status)).length;
    result.classList.add("success"); result.textContent = `${created.customer_name} added successfully with token ${created.token}.`;
    message("Customer added to the live queue");
    setTimeout(() => document.querySelector('.dashboard-nav [data-tab="queue"]').click(), 900);
  } catch (reason) { result.classList.add("error"); result.textContent = reason.message; error.textContent = reason.message; }
  finally { submit.disabled = Boolean(shop?.queue_paused); submit.textContent = shop?.queue_paused ? "New joins are paused" : "Add to live queue"; }
});
document.querySelector("#shop-form").addEventListener("submit", async (event) => { event.preventDefault(); await request(`/api/shops/${shopId}`, { method: "PATCH", body: JSON.stringify({ name: document.querySelector("#shop-profile-name").value, phone: document.querySelector("#shop-phone").value || null, gst_number: document.querySelector("#shop-gst").value.toUpperCase() || null, address: document.querySelector("#shop-profile-address").value, opens_at: document.querySelector("#opens-at").value, closes_at: document.querySelector("#closes-at").value, timezone: document.querySelector("#shop-timezone").value }) }); message("Shop details saved"); await refreshAll(); });
document.querySelector("#shop-photo-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = ""; const file = document.querySelector("#shop-photo").files[0]; if (!file) return;
  const form = new FormData(); form.append("photo", file);
  try { const response = await fetch(`/api/shops/${shopId}/photo`, { method: "POST", headers: { Authorization: `Bearer ${accessToken}` }, body: form }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(formatApiError(body.detail)); event.target.reset(); message("Shop photo uploaded"); await refreshAll(); }
  catch (reason) { error.textContent = reason.message; }
});
document.querySelector("#service-template").addEventListener("change", (event) => { const option = event.target.selectedOptions[0]; if (!option.dataset.name) return; document.querySelector("#service-name").value = option.dataset.name; document.querySelector("#service-duration").value = option.dataset.duration; document.querySelector("#service-price").value = option.dataset.price; });
document.querySelector("#service-form").addEventListener("submit", async (event) => { event.preventDefault(); await request(`/api/shops/${shopId}/services`, { method: "POST", body: JSON.stringify({ name: document.querySelector("#service-name").value, duration_minutes: Number(document.querySelector("#service-duration").value), price_rupees: Number(document.querySelector("#service-price").value) }) }); event.target.reset(); message("Service added"); await refreshAll(); });
document.querySelector("#barber-form").addEventListener("submit", async (event) => { event.preventDefault(); await request(`/api/shops/${shopId}/barbers`, { method: "POST", body: JSON.stringify({ name: document.querySelector("#barber-name").value }) }); event.target.reset(); message("Barber added"); await refreshAll(); });
document.querySelector("#staff-form").addEventListener("submit", async (event) => { event.preventDefault(); const role = document.querySelector("#staff-role").value; const barberId = document.querySelector("#staff-barber").value; try { await request(`/api/shops/${shopId}/staff`, { method: "POST", body: JSON.stringify({ name: document.querySelector("#staff-name").value, email: document.querySelector("#staff-email").value, phone: document.querySelector("#staff-phone").value.trim() || null, password: document.querySelector("#staff-password").value, role, barber_id: role === "barber" && barberId ? Number(barberId) : null }) }); event.target.reset(); message("Staff login created"); await refreshAll(); } catch (reason) { error.textContent = reason.message; } });
document.querySelector("#change-password-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = "";
  const currentPassword = document.querySelector("#current-password").value;
  const newPassword = document.querySelector("#new-password").value;
  if (newPassword !== document.querySelector("#confirm-password").value) { error.textContent = "New password and confirmation do not match."; return; }
  try { await request("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }); event.target.reset(); document.querySelector("#password-notice").textContent = "Your password is up to date."; error.textContent = ""; message("Password changed successfully"); }
  catch (reason) { error.textContent = reason.message; }
});

function connectRealtime() { if (socket) socket.close(); const protocol = location.protocol === "https:" ? "wss" : "ws"; socket = new WebSocket(`${protocol}://${location.host}/ws/staff/${shopId}?token=${encodeURIComponent(accessToken)}`); socket.onmessage = refreshAll; socket.onclose = () => { if (accessToken) setTimeout(connectRealtime, 2000); }; }
if (new URLSearchParams(location.search).get("reset_token")) { document.querySelector("#login-panel").classList.add("hidden"); document.querySelector("#reset-password-panel").classList.remove("hidden"); }
else if (accessToken) showBoard();
