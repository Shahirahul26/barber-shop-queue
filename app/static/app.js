let shopId = Number(new URLSearchParams(location.search).get("shop")) || 1;
let currentShop = null, socket = null, allShops = [];
let currentCustomer = null, pendingIdentifier = "", pendingOtp = "", firstTimeCustomer = true;
let customerToken = localStorage.getItem("trimtimeCustomerToken");
let activeToken = localStorage.getItem("trimtimeQueueToken");
let activeAppointmentToken = localStorage.getItem("trimtimeAppointmentToken");
let lastPeopleAhead = null;
const joinPanel = document.querySelector("#join-panel");
const ticketPanel = document.querySelector("#ticket-panel");
const customerHero = document.querySelector("#customer-app .hero");
customerHero.insertAdjacentElement("afterend", joinPanel);
joinPanel.insertAdjacentElement("afterend", document.querySelector("#appointment-panel"));
document.querySelector("#customer-app").appendChild(document.querySelector(".marketplace-section"));

function formatApiError(detail) {
  if (Array.isArray(detail)) return detail.map((item) => `${(item.loc || []).filter((part) => part !== "body").join(" → ") || "Input"}: ${item.msg || "Invalid value"}`).join(" | ");
  if (detail && typeof detail === "object") return detail.message || JSON.stringify(detail);
  return detail || "Something went wrong";
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(formatApiError(body.detail)); }
  return response.json();
}

function showCustomerApp(customer) {
  currentCustomer = customer;
  document.querySelector("#customer-auth").classList.add("hidden"); document.querySelector("#customer-app").classList.remove("hidden");
  document.querySelector("#customer-logout").classList.remove("hidden");
  document.querySelector("#customer-name").value = customer.name || ""; if (customer.phone) document.querySelector("#phone").value = customer.phone;
  loadShops().then(() => Promise.all([refreshTicket(), refreshAppointment()])).catch((reason) => document.querySelector("#form-error").textContent = reason.message);
}
document.querySelector("#customer-logout").addEventListener("click", () => {
  localStorage.removeItem("trimtimeCustomerToken"); customerToken = null; location.reload();
});
async function restoreCustomerSession() {
  if (!customerToken) return;
  const response = await fetch("/api/customer-auth/me", { headers: { Authorization: `Bearer ${customerToken}` } });
  if (!response.ok) { localStorage.removeItem("trimtimeCustomerToken"); customerToken = null; return; }
  showCustomerApp(await response.json());
}
async function requestOtp(identifier) {
  const response = await fetch("/api/customer-auth/request-otp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier }) });
  const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(formatApiError(body.detail));
  pendingIdentifier = identifier; document.querySelector("#otp-request-step").classList.add("hidden"); document.querySelector("#otp-verify-step").classList.remove("hidden"); document.querySelector("#otp-message").textContent = body.message;
  firstTimeCustomer = body.first_time;
  document.querySelector("#development-otp").textContent = body.development_otp ? `Local test OTP: ${body.development_otp}` : "";
}
document.querySelector("#otp-request-form").addEventListener("submit", async (event) => { event.preventDefault(); const authError = document.querySelector("#customer-auth-error"); authError.textContent = ""; try { await requestOtp(document.querySelector("#customer-identifier").value.trim()); } catch (reason) { authError.textContent = reason.message; } });
document.querySelector("#resend-customer-otp").addEventListener("click", async () => { const authError = document.querySelector("#customer-auth-error"); authError.textContent = ""; try { await requestOtp(pendingIdentifier); } catch (reason) { authError.textContent = reason.message; } });
async function completeOtpVerification(profile = {}) { const response = await fetch("/api/customer-auth/verify-otp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier: pendingIdentifier, otp: pendingOtp, ...profile }) }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(formatApiError(body.detail)); customerToken = body.access_token; localStorage.setItem("trimtimeCustomerToken", customerToken); showCustomerApp(body.customer); }
document.querySelector("#otp-verify-form").addEventListener("submit", async (event) => { event.preventDefault(); const authError = document.querySelector("#customer-auth-error"); authError.textContent = ""; pendingOtp = document.querySelector("#customer-otp").value; try { if (firstTimeCustomer) { document.querySelector("#otp-verify-step").classList.add("hidden"); document.querySelector("#customer-profile-step").classList.remove("hidden"); } else await completeOtpVerification(); } catch (reason) { authError.textContent = reason.message; } });
document.querySelector("#customer-profile-form").addEventListener("submit", async (event) => { event.preventDefault(); const authError = document.querySelector("#customer-auth-error"); authError.textContent = ""; try { await completeOtpVerification({ name: document.querySelector("#verified-customer-name").value.trim(), age: Number(document.querySelector("#verified-customer-age").value), gender: document.querySelector("#verified-customer-gender").value, terms_accepted: document.querySelector("#customer-terms").checked }); } catch (reason) { authError.textContent = reason.message; } });
fetch("/api/platform/banner").then((response) => response.json()).then((banner) => { document.querySelectorAll(".brand-name").forEach((item) => item.textContent = banner.software_name); if (banner.login_image_url) { document.querySelector("#customer-auth-image").style.backgroundImage = `linear-gradient(135deg,#173c35cc,#245c5277),url("${banner.login_image_url}")`; document.querySelector("#customer-profile-ad").style.backgroundImage = `url("${banner.login_image_url}")`; } }).catch(() => {});

function fillSelect(selector, items, label) {
  const select = document.querySelector(selector); select.replaceChildren();
  items.forEach((item) => { const option = document.createElement("option"); option.value = item.id; option.textContent = label(item); select.append(option); });
}
function escapeHtml(value) { const node = document.createElement("span"); node.textContent = value ?? ""; return node.innerHTML; }

function renderShopCards(shops) {
  const cards = document.querySelector("#nearby-shop-cards");
  cards.innerHTML = shops.filter((item) => item.id !== shopId).map((item) => `<article class="shop-market-card">${item.photo_url ? `<img src="${item.photo_url}" alt="${escapeHtml(item.name)}" />` : '<div class="shop-card-placeholder">TRIMTIME</div>'}<div class="shop-market-content"><h3>${escapeHtml(item.name)}</h3><p>${escapeHtml(item.address)}</p><small>${item.opens_at}–${item.closes_at} · ${item.waiting_count} waiting · ${item.estimated_wait_minutes} estimated minutes</small><p>${item.services.slice(0, 3).map((service) => `${escapeHtml(service.name)} ₹${service.price_rupees}`).join(" · ")}</p><div class="actions"><button type="button" data-open-shop="${item.id}">Join live queue</button><button type="button" data-book-shop="${item.id}" class="secondary">Book appointment</button></div></div></article>`).join("") || '<p class="muted">No other shops are currently available.</p>';
  cards.querySelectorAll("[data-open-shop],[data-book-shop]").forEach((button) => button.addEventListener("click", async () => { shopId = Number(button.dataset.openShop || button.dataset.bookShop); document.querySelector("#shop").value = shopId; history.replaceState({}, "", `/?shop=${shopId}`); await loadShop(); if (button.dataset.openShop) await joinCurrentShop(); else { const target = document.querySelector("#appointment-panel"); target.classList.remove("hidden"); target.scrollIntoView({ behavior: "smooth" }); } }));
}

async function loadShops() {
  const shops = await api("/api/shops");
  allShops = shops;
  fillSelect("#shop", shops, (shop) => `${shop.name} · ${shop.address}`);
  if (!shops.some((shop) => shop.id === shopId) && shops.length) shopId = shops[0].id;
  document.querySelector("#shop").value = shopId;
  await loadShop();
}

async function loadShop() {
  currentShop = await api(`/api/shops/${shopId}`);
  document.querySelector("#shop-name").textContent = currentShop.name;
  document.querySelector("#shop-address").textContent = `${currentShop.address} · ${currentShop.opens_at}–${currentShop.closes_at}`;
  document.querySelector("#appointment-guidance").textContent = `Choose a time during shop opening hours: ${currentShop.opens_at} to ${currentShop.closes_at} (${currentShop.timezone}). Selecting a barber is optional.`;
  document.querySelector("#waiting-count").textContent = currentShop.waiting_count;
  document.querySelector("#wait-time").textContent = currentShop.estimated_wait_minutes;
  document.querySelector("#prejoin-wait").textContent = currentShop.estimated_wait_minutes;
  const photo = document.querySelector("#customer-shop-photo"); photo.classList.toggle("hidden", !currentShop.photo_url); if (currentShop.photo_url) photo.src = currentShop.photo_url;
  const submit = document.querySelector("#join-form button[type=submit]");
  submit.disabled = currentShop.queue_paused;
  submit.firstChild.textContent = currentShop.queue_paused ? "Queue temporarily paused " : "Join live queue ";
  fillSelect("#service", currentShop.services, (item) => `${item.name} · ${item.duration_minutes} min · ₹${item.price_rupees}`);
  fillSelect("#barber", [{ id: "", name: "Any available barber" }, ...currentShop.barbers], (item) => item.name);
  fillSelect("#appointment-service", currentShop.services, (item) => `${item.name} · ${item.duration_minutes} min · ₹${item.price_rupees}`);
  fillSelect("#appointment-barber", [{ id: "", name: "Any available barber" }, ...currentShop.barbers], (item) => item.name);
  renderShopCards(allShops);
  connectRealtime();
}

document.querySelector("#shop").addEventListener("change", async (event) => {
  shopId = Number(event.target.value); history.replaceState({}, "", `/?shop=${shopId}`); await loadShop();
});

async function joinCurrentShop() {
  const error = document.querySelector("#form-error"); error.textContent = "";
  try {
    if (currentShop.queue_paused) throw new Error("This shop has temporarily paused new queue joins.");
    const service = currentShop.services[0]; if (!service) throw new Error("This shop has no active service available.");
    const entry = await api(`/api/shops/${shopId}/queue`, { method: "POST", body: JSON.stringify({ customer_name: currentCustomer.name, phone: currentCustomer.phone || null, service_id: service.id, barber_id: null, source: "online" }) });
    activeToken = entry.public_token; localStorage.setItem("trimtimeQueueToken", activeToken); showTicket(entry); await loadShop(); ticketPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (reason) { error.textContent = reason.message; error.scrollIntoView({ behavior: "smooth", block: "center" }); }
}
document.querySelector("#show-join-options").addEventListener("click", joinCurrentShop);
document.querySelector("#show-appointment-options").addEventListener("click", () => {
  const appointmentPanel = document.querySelector("#appointment-panel"); appointmentPanel.classList.toggle("hidden"); joinPanel.classList.add("hidden");
  if (!appointmentPanel.classList.contains("hidden")) appointmentPanel.scrollIntoView({ behavior: "smooth", block: "start" });
});

document.querySelector("#nearby-shops").addEventListener("click", () => {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(async ({ coords }) => {
    const shops = await api(`/api/marketplace/nearby?latitude=${coords.latitude}&longitude=${coords.longitude}&radius_km=25`);
    if (!shops.length) { document.querySelector("#form-error").textContent = "No registered shop was found within 25 km."; return; }
    allShops = shops; fillSelect("#shop", shops, (shop) => `${shop.name} · ${shop.address} · ★ ${shop.average_rating}`);
    shopId = shops[0].id; document.querySelector("#shop").value = shopId; await loadShop();
  }, () => document.querySelector("#form-error").textContent = "Location permission is needed to find nearby shops.");
});

async function sendAlert(entry) {
  if (!("Notification" in window) || Notification.permission !== "granted" || entry.people_ahead === lastPeopleAhead) return;
  if (entry.people_ahead === 2) new Notification("TrimTime", { body: "Only two customers are ahead of you." });
  if (entry.people_ahead === 0 && entry.status === "waiting") new Notification("TrimTime", { body: "You are next. Please reach the shop now." });
  if (entry.status === "serving") new Notification("TrimTime", { body: "Your barber is ready." });
}

function showTicket(entry) {
  sendAlert(entry); lastPeopleAhead = entry.people_ahead;
  joinPanel.classList.add("hidden"); document.querySelector("#appointment-panel").classList.add("hidden"); ticketPanel.classList.remove("hidden");
  document.querySelector("#ticket-token").textContent = entry.token;
  document.querySelector("#ticket-status").textContent = entry.status;
  document.querySelector("#people-ahead").textContent = entry.people_ahead ?? "—";
  document.querySelector("#ticket-wait").textContent = entry.estimated_wait_minutes;
  document.querySelector("#ticket-barber").textContent = entry.barber_name || "First available barber";
  const completed = entry.status === "completed", cancelled = entry.status === "cancelled";
  document.querySelector("#notify").classList.toggle("hidden", completed || cancelled);
  document.querySelector("#leave-queue").classList.toggle("hidden", completed || cancelled);
  document.querySelector("#rating-form").classList.toggle("hidden", !completed);
  if (cancelled) { localStorage.removeItem("trimtimeQueueToken"); activeToken = null; }
}

async function refreshTicket() {
  if (!activeToken) return;
  try { showTicket(await api(`/api/my-queue/${activeToken}`)); }
  catch { localStorage.removeItem("trimtimeQueueToken"); activeToken = null; }
}

function urlBase64ToUint8Array(value) {
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const raw = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((character) => character.charCodeAt(0)));
}

document.querySelector("#notify").addEventListener("click", async () => {
  if (!activeToken || !("Notification" in window) || !("serviceWorker" in navigator)) return;
  if (await Notification.requestPermission() !== "granted") return;
  const { public_key: publicKey } = await api("/api/push/public-key");
  if (!publicKey) return;
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(publicKey) });
  await api("/api/push/subscribe", { method: "POST", body: JSON.stringify({ public_token: activeToken, ...subscription.toJSON() }) });
  document.querySelector("#notify").textContent = "Live alerts enabled";
});

document.querySelector("#join-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const error = document.querySelector("#form-error"); error.textContent = "";
  try {
    const barber = document.querySelector("#barber").value;
    const entry = await api(`/api/shops/${shopId}/queue`, { method: "POST", body: JSON.stringify({ customer_name: document.querySelector("#customer-name").value, phone: document.querySelector("#phone").value || null, service_id: Number(document.querySelector("#service").value), barber_id: barber ? Number(barber) : null, source: "online" }) });
    activeToken = entry.public_token; localStorage.setItem("trimtimeQueueToken", activeToken); showTicket(entry); await loadShop();
  } catch (message) { error.textContent = message.message; }
});

document.querySelector("#book-appointment").addEventListener("click", async () => {
  const result = document.querySelector("#appointment-result"); result.textContent = "";
  try {
    const time = document.querySelector("#appointment-time").value;
    if (!time) throw new Error("Choose an appointment date and time.");
    const barber = document.querySelector("#appointment-barber").value;
    const appointment = await api(`/api/shops/${shopId}/appointments`, { method: "POST", body: JSON.stringify({ customer_name: document.querySelector("#customer-name").value, phone: document.querySelector("#phone").value.trim() || null, service_id: Number(document.querySelector("#appointment-service").value), barber_id: barber ? Number(barber) : null, scheduled_at: new Date(time).toISOString() }) });
    activeAppointmentToken = appointment.public_token; localStorage.setItem("trimtimeAppointmentToken", activeAppointmentToken); showAppointment(appointment);
    result.textContent = `Appointment booked. Your booking token is ${appointment.token}. Scheduled for ${new Date(appointment.scheduled_at).toLocaleString()}. It will automatically enter the live queue as PRIORITY at that time.`;
  } catch (reason) {
    result.textContent = reason.message;
    if ("Notification" in window && Notification.permission === "granted") new Notification("Appointment unavailable", { body: reason.message });
  }
});

function showAppointment(appointment) {
  const panel = document.querySelector("#appointment-ticket-panel"); panel.classList.remove("hidden");
  document.querySelector("#appointment-ticket-token").textContent = appointment.token;
  document.querySelector("#appointment-ticket-status").textContent = appointment.status.replace("_", " ");
  document.querySelector("#appointment-ticket-details").textContent = `${appointment.service_name} · ${new Date(appointment.scheduled_at).toLocaleString()} · ${appointment.barber_name || "Any available barber"}`;
  const terminal = ["cancelled", "completed", "no_show"].includes(appointment.status);
  document.querySelector("#cancel-appointment").classList.toggle("hidden", terminal || appointment.status === "serving");
  document.querySelector("#appointment-ticket-message").textContent = appointment.status === "cancelled" ? "This appointment was cancelled." : appointment.status === "completed" ? "This appointment has been completed." : appointment.status === "queued" ? "Your appointment is now in the live queue as PRIORITY." : "Keep this booking token for your visit.";
}

async function refreshAppointment() {
  if (!activeAppointmentToken) return;
  try { showAppointment(await api(`/api/my-appointment/${activeAppointmentToken}`)); }
  catch { localStorage.removeItem("trimtimeAppointmentToken"); activeAppointmentToken = null; }
}

document.querySelector("#cancel-appointment").addEventListener("click", async () => {
  if (!activeAppointmentToken || !confirm("Cancel this appointment?")) return;
  try { showAppointment(await api("/api/my-appointment/cancel", { method: "POST", body: JSON.stringify({ public_token: activeAppointmentToken }) })); }
  catch (reason) { document.querySelector("#appointment-ticket-message").textContent = reason.message; }
});

document.querySelector("#leave-queue").addEventListener("click", async () => {
  if (!activeToken) return;
  await api("/api/my-queue/cancel", { method: "POST", body: JSON.stringify({ public_token: activeToken }) });
  localStorage.removeItem("trimtimeQueueToken"); location.reload();
});

document.querySelector("#rating-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const result = document.querySelector("#rating-result"); result.textContent = "";
  if (!activeToken) { result.textContent = "This completed visit can no longer be found."; return; }
  try {
    await api("/api/ratings", { method: "POST", body: JSON.stringify({ queue_public_token: activeToken, stars: Number(document.querySelector("#shop-rating").value), comment: document.querySelector("#shop-review").value.trim() || null, barber_stars: Number(document.querySelector("#barber-rating").value), barber_comment: document.querySelector("#barber-review").value.trim() || null }) });
    event.target.classList.add("hidden"); result.textContent = "Thank you. Your shop and barber reviews were submitted.";
    localStorage.removeItem("trimtimeQueueToken"); activeToken = null;
  } catch (reason) { result.textContent = reason.message; }
});

function connectRealtime() {
  if (socket) socket.close();
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws/shops/${shopId}`);
  socket.onmessage = () => { loadShop().catch(console.error); refreshTicket(); refreshAppointment(); };
}

restoreCustomerSession().catch(console.error);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
