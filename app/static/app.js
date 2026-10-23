let shopId = Number(new URLSearchParams(location.search).get("shop")) || 1;
let currentShop = null, socket = null, allShops = [];
let currentCustomer = null, pendingIdentifier = "", pendingOtp = "", firstTimeCustomer = true;
let customerToken = localStorage.getItem("trimtimeCustomerToken");
let activeToken = localStorage.getItem("trimtimeQueueToken");
let activeAppointmentToken = localStorage.getItem("trimtimeAppointmentToken");
let lastPeopleAhead = null;
let historyRatingTarget = null;
let customerHistoryItems = [], activeAppointmentDetails = null;
const customerAuthMode = new URLSearchParams(location.search).get("auth");
let customerHistoryDrafts = {};
try { customerHistoryDrafts = JSON.parse(sessionStorage.getItem("trimtimeHistoryRatingDrafts") || "{}"); } catch { customerHistoryDrafts = {}; }
let customerNoticeTimer = null;
const joinPanel = document.querySelector("#join-panel");
const ticketPanel = document.querySelector("#ticket-panel");
const customerHero = document.querySelector("#customer-app .hero");
document.querySelectorAll("#history-rating-form button[type=submit],#rating-form button[type=submit]").forEach((button) => { button.textContent = "Submit"; });
document.querySelector("#history-shop-rating").closest(".star-field").insertAdjacentHTML("afterend", '<fieldset class="star-field"><legend>Barber rating</legend><input id="history-barber-rating" type="hidden" /><div class="star-rating" data-rating-input="history-barber-rating" aria-label="Barber rating"><button type="button" data-rating-value="1">★</button><button type="button" data-rating-value="2">★</button><button type="button" data-rating-value="3">★</button><button type="button" data-rating-value="4">★</button><button type="button" data-rating-value="5">★</button></div></fieldset>');
document.querySelector("#shop-rating").closest(".star-field").insertAdjacentHTML("afterend", '<fieldset class="star-field"><legend>Barber rating</legend><input id="barber-rating" type="hidden" /><div class="star-rating" data-rating-input="barber-rating" aria-label="Barber rating"><button type="button" data-rating-value="1">★</button><button type="button" data-rating-value="2">★</button><button type="button" data-rating-value="3">★</button><button type="button" data-rating-value="4">★</button><button type="button" data-rating-value="5">★</button></div></fieldset>');
customerHero.insertAdjacentElement("afterend", joinPanel);
joinPanel.insertAdjacentElement("afterend", document.querySelector("#appointment-panel"));
document.querySelector("#customer-app").appendChild(document.querySelector(".marketplace-section"));
if (customerAuthMode === "signup") {
  document.querySelector("#customer-auth-eyebrow").textContent = "NEW CUSTOMER";
  document.querySelector("#customer-auth-title").textContent = "Create your customer account";
  document.querySelector("#customer-auth-copy").textContent = "Enter your email or phone number. We will verify it with a 10-minute OTP, then create your profile.";
}

function formatApiError(detail) {
  if (Array.isArray(detail)) return detail.map((item) => `${(item.loc || []).filter((part) => part !== "body").join(" → ") || "Input"}: ${item.msg || "Invalid value"}`).join(" | ");
  if (detail && typeof detail === "object") return detail.message || JSON.stringify(detail);
  return detail || "Something went wrong";
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(customerToken ? { Authorization: `Bearer ${customerToken}` } : {}), ...(options.headers || {}) } });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(formatApiError(body.detail)); }
  return response.json();
}

function showCustomerApp(customer) {
  currentCustomer = customer;
  const storedCustomerId = localStorage.getItem("trimtimeCustomerOwnerId");
  if (storedCustomerId !== String(customer.id)) {
    localStorage.removeItem("trimtimeQueueToken"); localStorage.removeItem("trimtimeAppointmentToken"); localStorage.removeItem("trimtimeRatedAppointmentToken");
    activeToken = null; activeAppointmentToken = null; activeAppointmentDetails = null; lastPeopleAhead = null;
    ticketPanel.classList.add("hidden"); document.querySelector("#appointment-ticket-panel").classList.add("hidden");
  }
  localStorage.setItem("trimtimeCustomerOwnerId", String(customer.id));
  document.querySelector("#customer-auth").classList.add("hidden"); document.querySelector("#customer-app").classList.remove("hidden");
  document.querySelector("#show-customer-profile").classList.remove("hidden");
  document.querySelector("#customer-name").value = customer.name || ""; if (customer.phone) document.querySelector("#phone").value = customer.phone;
  document.querySelector("#profile-name").textContent = customer.name || "Not provided";
  document.querySelector("#profile-email").textContent = customer.email || "Not provided";
  document.querySelector("#profile-phone").textContent = customer.phone || "Not provided";
  document.querySelector("#profile-age").textContent = customer.age ?? "Not provided";
  document.querySelector("#profile-gender").textContent = (customer.gender || "Not provided").replaceAll("_", " ");
  loadShops().then(() => Promise.all([restoreActiveQueue(), refreshAppointment()])).catch((reason) => showCustomerNotice(reason.message));
}
function showCustomerNotice(message, success = false) {
  const notice = document.querySelector("#customer-notice"); clearTimeout(customerNoticeTimer);
  notice.textContent = message; notice.classList.toggle("success", success); notice.classList.remove("hidden");
  notice.scrollIntoView({ behavior: "smooth", block: "start" });
  customerNoticeTimer = setTimeout(() => notice.classList.add("hidden"), 8000);
}
document.querySelector("#customer-logout").addEventListener("click", () => {
  localStorage.removeItem("trimtimeCustomerToken"); customerToken = null; location.reload();
});
document.querySelector("#show-customer-profile").addEventListener("click", async () => {
  const panel = document.querySelector("#customer-profile-panel"); panel.classList.toggle("hidden");
  if (!panel.classList.contains("hidden")) { await loadCustomerHistory(); panel.scrollIntoView({ behavior: "smooth", block: "start" }); }
});
document.querySelectorAll("[data-profile-tab]").forEach((button) => button.addEventListener("click", async () => {
  const target = button.dataset.profileTab;
  document.querySelectorAll("[data-profile-tab]").forEach((item) => item.classList.toggle("active", item === button));
  document.querySelector("#customer-details-tab").classList.toggle("hidden", target !== "details");
  document.querySelector("#customer-history-tab").classList.toggle("hidden", target !== "history");
  if (target === "history") await loadCustomerHistory();
}));
async function loadCustomerHistory() {
  const body = document.querySelector("#customer-history-body");
  try {
    customerHistoryItems = await api("/api/customer-auth/history"); renderCustomerHistory();
  } catch (reason) { body.innerHTML = `<div class="history-empty">${escapeHtml(reason.message)}</div>`; }
}

function historyDraftKey(item) { return `${item.rating_type}:${item.public_token}`; }
function persistHistoryDrafts() { sessionStorage.setItem("trimtimeHistoryRatingDrafts", JSON.stringify(customerHistoryDrafts)); }
function historyStars(inputId, label, selected = 0) {
  return `<fieldset class="star-field"><legend>${label}</legend><input id="${inputId}" type="hidden" value="${selected || ""}" /><div class="star-rating" data-rating-input="${inputId}" aria-label="${label}">${[1,2,3,4,5].map((value) => `<button type="button" class="${value <= selected ? "selected" : ""}" aria-pressed="${value <= selected}" data-rating-value="${value}" aria-label="${value} star${value === 1 ? "" : "s"}">★</button>`).join("")}</div></fieldset>`;
}
function saveHistoryDraft(index) {
  const item = customerHistoryItems.slice(0, 5)[index]; if (!item || item.rated) return;
  customerHistoryDrafts[historyDraftKey(item)] = { shopStars: Number(document.querySelector(`#history-shop-${index}`)?.value) || 0, barberStars: Number(document.querySelector(`#history-barber-${index}`)?.value) || 0, feedback: document.querySelector(`#history-feedback-${index}`)?.value || "" };
  persistHistoryDrafts();
}

function renderCustomerHistory() {
  const body = document.querySelector("#customer-history-body"), more = document.querySelector("#view-more-services");
  const visibleItems = customerHistoryItems.slice(0, 5);
  if (!visibleItems.length) { body.innerHTML = '<div class="history-empty">No completed services yet.</div>'; more.classList.add("hidden"); return; }
  body.innerHTML = visibleItems.map((item, index) => { const draft = customerHistoryDrafts[historyDraftKey(item)] || {}; return `<article class="service-history-card"><header><div><h3>${escapeHtml(item.shop)}</h3><p>${escapeHtml(item.service)} <span>·</span> ${escapeHtml(item.barber)}</p></div><span class="completed-badge">Completed ✓</span></header><div class="service-summary"><span>${escapeHtml(item.token)}</span><strong>${escapeHtml(item.service)}</strong><b>&#8377;${item.price_rupees}</b></div>${item.rated ? '<div class="rating-submitted">✓ Rating and feedback submitted</div>' : `<div class="history-rating-grid">${historyStars(`history-shop-${index}`, "Shop rating", draft.shopStars)}${item.barber_id ? historyStars(`history-barber-${index}`, "Barber rating", draft.barberStars) : ""}</div><label class="history-feedback">Feedback (optional)<textarea id="history-feedback-${index}" maxlength="500" placeholder="Share your experience">${escapeHtml(draft.feedback || "")}</textarea></label><button type="button" class="history-submit" data-history-submit="${index}">Submit</button><p id="history-result-${index}" class="history-result" aria-live="polite"></p>`}<button type="button" class="rebook-service" data-rebook-service="${index}">Rebook service <span>›</span></button><button type="button" class="view-shop-services" data-view-services="${index}">View more services</button><footer>Visited ${new Date(item.date).toLocaleString("en-IN")} <span>·</span> Total &#8377;${item.price_rupees}</footer></article>`; }).join("");
  wireStarRatings(body);
  body.querySelectorAll(".star-rating button").forEach((button) => button.addEventListener("click", () => saveHistoryDraft(Number(button.closest(".service-history-card").querySelector("[data-history-submit]").dataset.historySubmit))));
  body.querySelectorAll(".history-feedback textarea").forEach((field) => field.addEventListener("input", () => saveHistoryDraft(Number(field.closest(".service-history-card").querySelector("[data-history-submit]").dataset.historySubmit))));
  body.querySelectorAll("[data-history-submit]").forEach((button) => button.addEventListener("click", () => submitHistoryRating(Number(button.dataset.historySubmit))));
  body.querySelectorAll("[data-rebook-service]").forEach((button) => button.addEventListener("click", () => rebookHistoryService(Number(button.dataset.rebookService))));
  body.querySelectorAll("[data-view-services]").forEach((button) => button.addEventListener("click", () => viewHistoryShopServices(Number(button.dataset.viewServices))));
  more.classList.add("hidden");
}

async function submitHistoryRating(index) {
  const item = customerHistoryItems.slice(0, 5)[index], result = document.querySelector(`#history-result-${index}`);
  const shopStars = Number(document.querySelector(`#history-shop-${index}`).value), barberStars = item.barber_id ? Number(document.querySelector(`#history-barber-${index}`).value) : null;
  if (!shopStars || (item.barber_id && !barberStars)) { result.textContent = "Select both shop and barber ratings from 1 to 5 stars."; return; }
  const tokenField = item.rating_type === "appointment" ? "appointment_public_token" : "queue_public_token";
  try { await api("/api/ratings", { method: "POST", body: JSON.stringify({ [tokenField]: item.public_token, stars: shopStars, barber_stars: barberStars, comment: document.querySelector(`#history-feedback-${index}`).value.trim() || null, barber_comment: null }) }); delete customerHistoryDrafts[historyDraftKey(item)]; persistHistoryDrafts(); result.textContent = "Thank you. Your rating was submitted."; await loadCustomerHistory(); await loadShops(); }
  catch (reason) { result.textContent = reason.message; }
}

async function rebookHistoryService(index) {
  const item = customerHistoryItems.slice(0, 5)[index]; await openShopBooking(item.shop_id, item.service_ids || [item.service_id], item.barber_id);
}

async function viewHistoryShopServices(index) { const item = customerHistoryItems.slice(0, 5)[index]; await openShopBooking(item.shop_id, null, null); }
async function openShopBooking(targetShopId, serviceIds, barberId) {
  shopId = targetShopId; history.replaceState({}, "", `/customer?shop=${shopId}`); await loadShops();
  const requestedServiceIds = new Set((Array.isArray(serviceIds) ? serviceIds : serviceIds ? [serviceIds] : []).map(Number));
  document.querySelectorAll("[data-appointment-service]").forEach((input) => { input.checked = requestedServiceIds.has(Number(input.value)); }); updateAppointmentServiceLabel();
  if (barberId && [...document.querySelector("#appointment-barber").options].some((option) => Number(option.value) === barberId)) document.querySelector("#appointment-barber").value = barberId;
  await loadAppointmentSlots(); document.querySelector("#customer-profile-panel").classList.add("hidden"); document.querySelector("#appointment-panel").classList.remove("hidden"); document.querySelector("#appointment-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function openHistoryRating(type, token, label) {
  historyRatingTarget = { type, token };
  const panel = document.querySelector("#history-rating-panel");
  document.querySelector("#history-rating-service").textContent = label;
  document.querySelector("#history-rating-result").textContent = "";
  panel.classList.remove("hidden"); panel.scrollIntoView({ behavior: "smooth", block: "start" });
}
document.querySelector("#close-history-rating").addEventListener("click", () => document.querySelector("#history-rating-panel").classList.add("hidden"));
document.querySelector("#history-rating-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const result = document.querySelector("#history-rating-result"), barberStars = Number(document.querySelector("#history-barber-rating").value);
  if (!historyRatingTarget) return;
  if (!document.querySelector("#history-shop-rating").value) { result.textContent = "Select a shop rating from 1 to 5 stars, or close this optional feedback form."; return; }
  const tokenField = historyRatingTarget.type === "appointment" ? "appointment_public_token" : "queue_public_token";
  try {
    await api("/api/ratings", { method: "POST", body: JSON.stringify({ [tokenField]: historyRatingTarget.token, stars: Number(document.querySelector("#history-shop-rating").value), comment: document.querySelector("#history-shop-review").value.trim() || null, barber_stars: barberStars || null, barber_comment: null }) });
    result.textContent = "Thank you. Your feedback was submitted."; event.target.reset(); await loadCustomerHistory(); await loadShops();
  } catch (reason) { result.textContent = reason.message; }
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
  firstTimeCustomer = body.first_time;
  if (customerAuthMode === "signin" && firstTimeCustomer) throw new Error("No customer account was found. Please return to the home page and choose New customer? Sign up.");
  if (customerAuthMode === "signup" && !firstTimeCustomer) throw new Error("This customer account already exists. Please return to the home page and choose Customer sign in.");
  pendingIdentifier = identifier; document.querySelector("#otp-request-step").classList.add("hidden"); document.querySelector("#otp-verify-step").classList.remove("hidden"); document.querySelector("#otp-message").textContent = body.message;
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
function selectedAppointmentServiceIds() { return [...document.querySelectorAll("[data-appointment-service]:checked")].map((input) => Number(input.value)); }
function updateAppointmentServiceLabel() {
  const selected = [...document.querySelectorAll("[data-appointment-service]:checked")];
  document.querySelector("#appointment-service-toggle span").textContent = selected.length ? selected.map((input) => input.dataset.serviceName).join(", ") : "Choose services";
}
function renderAppointmentServiceOptions(services) {
  const options = document.querySelector("#appointment-service-options");
  options.innerHTML = services.map((service) => `<label><span>${escapeHtml(service.name)} <small>₹${service.price_rupees}</small></span><input type="checkbox" value="${service.id}" data-service-name="${escapeHtml(service.name)}" data-appointment-service /></label>`).join("");
  updateAppointmentServiceLabel();
}
function escapeHtml(value) { const node = document.createElement("span"); node.textContent = value ?? ""; return node.innerHTML; }
function ratingSummary(shop) { const count = Number(shop.rating_count || 0); return `★ ${Number(shop.average_rating || 0).toFixed(1)} (${count} ${count === 1 ? "rating" : "ratings"})`; }

function wireStarRatings(root = document) {
  root.querySelectorAll(".star-rating").forEach((rating) => {
    if (rating.dataset.bound) return; rating.dataset.bound = "true";
    rating.querySelectorAll("[data-rating-value]").forEach((star) => star.addEventListener("click", () => {
    const value = Number(star.dataset.ratingValue);
    document.querySelector(`#${rating.dataset.ratingInput}`).value = value;
    rating.querySelectorAll("[data-rating-value]").forEach((item) => {
      const selected = Number(item.dataset.ratingValue) <= value;
      item.classList.toggle("selected", selected); item.setAttribute("aria-pressed", String(selected));
    });
    }));
  });
}
wireStarRatings();

function renderShopCards(shops) {
  const cards = document.querySelector("#nearby-shop-cards");
  cards.innerHTML = shops.filter((item) => item.id !== shopId).map((item) => `<article class="shop-market-card">${item.photo_url ? `<img src="${item.photo_url}" alt="${escapeHtml(item.name)}" />` : '<div class="shop-card-placeholder">TRIMTIME</div>'}<div class="shop-market-content"><h3>${escapeHtml(item.name)}</h3><p class="shop-rating-summary">${ratingSummary(item)}</p><p>${escapeHtml(item.address)}</p><small>${item.opens_at}–${item.closes_at} · ${item.waiting_count} waiting · ${item.estimated_wait_minutes} estimated minutes</small><p>${item.services.slice(0, 3).map((service) => `${escapeHtml(service.name)} ₹${service.price_rupees}`).join(" · ")}</p><div class="actions"><button type="button" data-open-shop="${item.id}">Join live queue</button><button type="button" data-book-shop="${item.id}" class="secondary">Book appointment</button></div></div></article>`).join("") || '<p class="muted">No other shops are currently available.</p>';
  cards.querySelectorAll("[data-open-shop],[data-book-shop]").forEach((button) => button.addEventListener("click", async () => { shopId = Number(button.dataset.openShop || button.dataset.bookShop); document.querySelector("#shop").value = shopId; history.replaceState({}, "", `/customer?shop=${shopId}`); await loadShop(); if (button.dataset.openShop) await joinCurrentShop(); else { const target = document.querySelector("#appointment-panel"); target.classList.remove("hidden"); target.scrollIntoView({ behavior: "smooth" }); } }));
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
  const previousShopId = currentShop?.id, previousAppointmentServices = selectedAppointmentServiceIds();
  currentShop = await api(`/api/shops/${shopId}`);
  document.querySelector("#shop-name").textContent = currentShop.name;
  document.querySelector("#shop-average-rating").textContent = ratingSummary(currentShop);
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
  renderAppointmentServiceOptions(currentShop.services);
  if (previousShopId === currentShop.id) {
    const selectedIds = new Set(previousAppointmentServices); document.querySelectorAll("[data-appointment-service]").forEach((input) => { input.checked = selectedIds.has(Number(input.value)); }); updateAppointmentServiceLabel();
  }
  fillSelect("#appointment-barber", [{ id: "", name: "Any available barber" }, ...currentShop.barbers], (item) => item.name);
  const appointmentDate = document.querySelector("#appointment-date");
  const today = new Date().toLocaleDateString("en-CA"); appointmentDate.min = today; if (!appointmentDate.value) appointmentDate.value = today;
  await loadAppointmentSlots();
  renderShopCards(allShops);
  connectRealtime();
}

document.querySelector("#shop").addEventListener("change", async (event) => {
  shopId = Number(event.target.value); history.replaceState({}, "", `/customer?shop=${shopId}`); await loadShop();
});

async function joinCurrentShop() {
  const error = document.querySelector("#form-error"); error.textContent = "";
  try {
    if (currentShop.queue_paused) throw new Error("This shop has temporarily paused new queue joins.");
    const entry = await api(`/api/shops/${shopId}/queue`, { method: "POST", body: JSON.stringify({ customer_name: currentCustomer.name, phone: currentCustomer.phone || null, service_id: null, barber_id: null, source: "online" }) });
    activeToken = entry.public_token; localStorage.setItem("trimtimeQueueToken", activeToken); showTicket(entry); await loadShop(); ticketPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (reason) {
    error.textContent = reason.message; showCustomerNotice(reason.message);
    if (reason.message.includes("three non-completed live-queue joins") && "Notification" in window && Notification.permission === "granted") new Notification("Queue limit reached", { body: reason.message });
  }
}
document.querySelector("#show-join-options").addEventListener("click", joinCurrentShop);
document.querySelector("#show-appointment-options").addEventListener("click", () => {
  const appointmentPanel = document.querySelector("#appointment-panel"); appointmentPanel.classList.toggle("hidden"); joinPanel.classList.add("hidden");
  if (!appointmentPanel.classList.contains("hidden")) appointmentPanel.scrollIntoView({ behavior: "smooth", block: "start" });
});

async function loadAppointmentSlots() {
  const slotSelect = document.querySelector("#appointment-slot"), date = document.querySelector("#appointment-date").value;
  const serviceIds = selectedAppointmentServiceIds(), barberId = document.querySelector("#appointment-barber").value;
  slotSelect.innerHTML = '<option value="">Loading available slots…</option>'; slotSelect.disabled = true;
  if (!date || !serviceIds.length) { slotSelect.innerHTML = '<option value="">Select one or more services and a date first</option>'; slotSelect.disabled = false; return; }
  try {
    const query = new URLSearchParams({ appointment_date: date }); serviceIds.forEach((serviceId) => query.append("service_ids", serviceId)); if (barberId) query.set("barber_id", barberId);
    const availability = await api(`/api/shops/${shopId}/appointment-slots?${query}`);
    slotSelect.innerHTML = availability.slots.length ? `<option value="">Choose a slot</option>${availability.slots.map((slot) => `<option value="${slot.value}">${escapeHtml(slot.label)} · ${slot.available_barbers} barber${slot.available_barbers === 1 ? "" : "s"} available</option>`).join("")}` : '<option value="">No slots available for this date</option>';
  } catch (reason) { slotSelect.innerHTML = `<option value="">${escapeHtml(reason.message)}</option>`; }
  finally { slotSelect.disabled = false; }
}
document.querySelector("#appointment-service-toggle").addEventListener("click", () => { const options = document.querySelector("#appointment-service-options"), opening = options.classList.contains("hidden"); options.classList.toggle("hidden"); document.querySelector("#appointment-service-toggle").setAttribute("aria-expanded", String(opening)); });
document.querySelector("#appointment-service-options").addEventListener("change", () => { updateAppointmentServiceLabel(); loadAppointmentSlots(); });
document.addEventListener("click", (event) => { if (!event.target.closest("#appointment-service-picker")) { document.querySelector("#appointment-service-options").classList.add("hidden"); document.querySelector("#appointment-service-toggle").setAttribute("aria-expanded", "false"); } });
document.querySelector("#appointment-barber").addEventListener("change", loadAppointmentSlots);
document.querySelector("#appointment-date").addEventListener("change", loadAppointmentSlots);

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
  if (entry.availability_message || !("Notification" in window) || Notification.permission !== "granted" || entry.people_ahead === lastPeopleAhead) return;
  if (entry.people_ahead === 2) new Notification("TrimTime", { body: entry.ahead_label === "turns ahead" ? "Only two turns remain before you." : "Only two customers are ahead of you." });
  if (entry.people_ahead === 0 && entry.status === "waiting") new Notification("TrimTime", { body: "You are next. Please reach the shop now." });
  if (entry.status === "serving") new Notification("TrimTime", { body: "Your barber is ready." });
}

function showTicket(entry) {
  sendAlert(entry); lastPeopleAhead = entry.people_ahead;
  joinPanel.classList.add("hidden"); document.querySelector("#appointment-panel").classList.add("hidden"); ticketPanel.classList.remove("hidden");
  document.querySelector("#ticket-token").textContent = entry.token;
  document.querySelector("#ticket-status").textContent = entry.status;
  document.querySelector("#people-ahead").textContent = entry.people_ahead ?? "—";
  document.querySelector("#ahead-label").textContent = entry.ahead_label || "people ahead";
  document.querySelector("#ticket-wait").textContent = entry.estimated_wait_minutes;
  document.querySelector("#ticket-barber").textContent = entry.barber_name || "First available barber";
  document.querySelector("#ticket-status").textContent = entry.availability_message || entry.status;
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

async function restoreActiveQueue() {
  const entry = await api("/api/customer-auth/active-queue");
  if (!entry) { if (activeToken) await refreshTicket(); return; }
  activeToken = entry.public_token; localStorage.setItem("trimtimeQueueToken", activeToken);
  if (entry.shop_id !== shopId) {
    shopId = entry.shop_id; history.replaceState({}, "", `/customer?shop=${shopId}`);
    document.querySelector("#shop").value = shopId; await loadShop();
  }
  showTicket(entry); ticketPanel.scrollIntoView({ behavior: "smooth", block: "start" });
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
  } catch (message) { error.textContent = message.message; showCustomerNotice(message.message); }
});

document.querySelector("#book-appointment").addEventListener("click", async () => {
  const result = document.querySelector("#appointment-result"); result.textContent = "";
  try {
    const time = document.querySelector("#appointment-slot").value;
    if (!time) throw new Error("Choose an available appointment slot.");
    const barber = document.querySelector("#appointment-barber").value;
    const serviceIds = selectedAppointmentServiceIds();
    if (!serviceIds.length) throw new Error("Choose at least one service.");
    const appointment = await api(`/api/shops/${shopId}/appointments`, { method: "POST", body: JSON.stringify({ customer_name: document.querySelector("#customer-name").value, phone: document.querySelector("#phone").value.trim() || null, service_ids: serviceIds, barber_id: barber ? Number(barber) : null, scheduled_at: time }) });
    activeAppointmentToken = appointment.public_token; localStorage.setItem("trimtimeAppointmentToken", activeAppointmentToken); showAppointment(appointment);
    result.textContent = `Appointment booked for ${appointment.service_name}. Your booking token is ${appointment.token}. Scheduled for ${new Date(appointment.scheduled_at).toLocaleString()}. It will enter the live queue as PRIORITY ${appointment.total_duration_minutes} minutes before the slot.`;
    await loadAppointmentSlots();
  } catch (reason) {
    result.textContent = reason.message;
    if ("Notification" in window && Notification.permission === "granted") new Notification("Appointment unavailable", { body: reason.message });
  }
});

function showAppointment(appointment) {
  activeAppointmentDetails = appointment;
  const panel = document.querySelector("#appointment-ticket-panel"); panel.classList.remove("hidden");
  document.querySelector("#appointment-ticket-token").textContent = appointment.token;
  document.querySelector("#appointment-ticket-status").textContent = appointment.status.replace("_", " ");
  document.querySelector("#appointment-ticket-details").textContent = `${appointment.service_name} · ${new Date(appointment.scheduled_at).toLocaleString()} · ${appointment.barber_name || "Any available barber"}`;
  const terminal = ["cancelled", "completed", "no_show"].includes(appointment.status);
  document.querySelector("#cancel-appointment").classList.toggle("hidden", terminal || appointment.status === "serving");
  document.querySelector("#rate-appointment").classList.add("hidden");
  const ratingSubmitted = localStorage.getItem("trimtimeRatedAppointmentToken") === appointment.public_token;
  document.querySelector("#appointment-rating-form").classList.toggle("hidden", appointment.status !== "completed" || ratingSubmitted);
  document.querySelector("#appointment-rebook").classList.toggle("hidden", appointment.status !== "completed");
  document.querySelector("#appointment-ticket-message").textContent = appointment.status === "cancelled" ? "This appointment was cancelled." : appointment.status === "completed" ? "This appointment has been completed." : appointment.status === "queued" ? "Your appointment is now in the live queue as PRIORITY." : "Keep this booking token for your visit.";
}

document.querySelector("#rate-appointment").addEventListener("click", () => {
  if (activeAppointmentToken) openHistoryRating("appointment", activeAppointmentToken, document.querySelector("#appointment-ticket-details").textContent);
});
document.querySelector("#appointment-rating-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const result = document.querySelector("#appointment-rating-result"); result.textContent = "";
  const shopStars = Number(document.querySelector("#appointment-shop-rating").value), barberStars = Number(document.querySelector("#appointment-barber-rating").value);
  if (!shopStars || !barberStars) { result.textContent = "Select both shop and barber ratings from 1 to 5 stars."; return; }
  try {
    await api("/api/ratings", { method: "POST", body: JSON.stringify({ appointment_public_token: activeAppointmentToken, stars: shopStars, barber_stars: barberStars, comment: document.querySelector("#appointment-feedback").value.trim() || null, barber_comment: null }) });
    localStorage.setItem("trimtimeRatedAppointmentToken", activeAppointmentToken); event.target.reset(); event.target.classList.add("hidden"); await loadShops();
  } catch (reason) {
    result.textContent = reason.message;
    if (reason.message.toLowerCase().includes("already rated")) {
      localStorage.setItem("trimtimeRatedAppointmentToken", activeAppointmentToken);
      event.target.classList.add("hidden");
    }
  }
});
document.querySelector("#appointment-rebook").addEventListener("click", async () => { if (activeAppointmentDetails) await openShopBooking(activeAppointmentDetails.shop_id, activeAppointmentDetails.service_ids, activeAppointmentDetails.barber_id); });

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
  if (!document.querySelector("#shop-rating").value) { result.textContent = "Select a shop rating from 1 to 5 stars, or skip this optional feedback."; return; }
  try {
    const barberStars = Number(document.querySelector("#barber-rating").value);
    await api("/api/ratings", { method: "POST", body: JSON.stringify({ queue_public_token: activeToken, stars: Number(document.querySelector("#shop-rating").value), comment: document.querySelector("#shop-review").value.trim() || null, barber_stars: barberStars || null, barber_comment: null }) });
    event.target.classList.add("hidden"); result.textContent = "Thank you. Your feedback was submitted.";
    await loadShops();
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
