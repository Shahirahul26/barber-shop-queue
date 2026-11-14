function getInitialShopId() {
  const urlShop = Number(new URLSearchParams(location.search).get("shop"));
  if (urlShop) {
    sessionStorage.setItem("trimtimeScannedShopId", String(urlShop));
    sessionStorage.setItem("trimtimeActiveShopId", String(urlShop));
    return urlShop;
  }
  sessionStorage.removeItem("trimtimeScannedShopId");
  sessionStorage.removeItem("trimtimeActiveShopId");
  return null;
}
let shopId = getInitialShopId();
let activeTicketShopId = null;
let currentShop = null, socket = null, connectedSocketShopId = null, allShops = [];
let currentCustomer = null, pendingIdentifier = "", pendingOtp = "", firstTimeCustomer = true, customerMpinMode = "setup", customerMpinVerification = "", resetCustomerMpin = false;
let customerToken = sessionStorage.getItem("trimtimeCustomerToken");
const customerDeviceId = localStorage.getItem("trimtimeCustomerDeviceId") || crypto.randomUUID();
localStorage.setItem("trimtimeCustomerDeviceId", customerDeviceId);
let activeToken = localStorage.getItem("trimtimeQueueToken");
let activeAppointmentToken = localStorage.getItem("trimtimeAppointmentToken");
let lastPeopleAhead = null;
let historyRatingTarget = null;
let customerHistoryItems = [], activeAppointmentDetails = null;
const customerAuthMode = new URLSearchParams(location.search).get("auth");
let customerHistoryDrafts = {};
try { customerHistoryDrafts = JSON.parse(sessionStorage.getItem("trimtimeHistoryRatingDrafts") || "{}"); } catch { customerHistoryDrafts = {}; }
let customerNoticeTimer = null;
function formatAppDate(value) {
  if (!value) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:$|T00:00:00)/.exec(String(value).trim());
  if (match) return `${match[3]}/${match[2]}/${match[1]}`;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const year = d.getFullYear();
  return `${day}/${month}/${year}`;
}
function formatAppDateTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const year = d.getFullYear();
  let hours = d.getHours();
  const minutes = String(d.getMinutes()).padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  hours = hours ? hours : 12;
  const strHours = String(hours).padStart(2, "0");
  return `${day}/${month}/${year}, ${strHours}:${minutes} ${ampm}`;
}
const joinPanel = document.querySelector("#join-panel");
const ticketPanel = document.querySelector("#ticket-panel");
const customerHero = document.querySelector("#customer-app .hero");
document.querySelectorAll("#history-rating-form button[type=submit],#rating-form button[type=submit]").forEach((button) => { button.textContent = "Submit"; });
document.querySelector("#history-shop-rating").closest(".star-field").insertAdjacentHTML("afterend", '<fieldset class="star-field"><legend>Barber rating</legend><input id="history-barber-rating" type="hidden" /><div class="star-rating" data-rating-input="history-barber-rating" aria-label="Barber rating"><button type="button" data-rating-value="1">★</button><button type="button" data-rating-value="2">★</button><button type="button" data-rating-value="3">★</button><button type="button" data-rating-value="4">★</button><button type="button" data-rating-value="5">★</button></div></fieldset>');
document.querySelector("#shop-rating").closest(".star-field").insertAdjacentHTML("afterend", '<fieldset class="star-field"><legend>Barber rating</legend><input id="barber-rating" type="hidden" /><div class="star-rating" data-rating-input="barber-rating" aria-label="Barber rating"><button type="button" data-rating-value="1">★</button><button type="button" data-rating-value="2">★</button><button type="button" data-rating-value="3">★</button><button type="button" data-rating-value="4">★</button><button type="button" data-rating-value="5">★</button></div></fieldset>');
customerHero.insertAdjacentElement("afterend", joinPanel);
joinPanel.insertAdjacentElement("afterend", document.querySelector("#appointment-panel"));
document.querySelector("#customer-app").appendChild(document.querySelector(".marketplace-section"));
let currentCustomerAuthMode = customerAuthMode === "signup" ? "signup" : "signin";

function setCustomerAuthMode(mode) {
  currentCustomerAuthMode = mode;
  document.querySelector("#auth-tab-signin")?.classList.toggle("active", mode === "signin");
  document.querySelector("#auth-tab-signup")?.classList.toggle("active", mode === "signup");
  document.querySelector("#auth-tab-signin")?.setAttribute("aria-selected", String(mode === "signin"));
  document.querySelector("#auth-tab-signup")?.setAttribute("aria-selected", String(mode === "signup"));

  const eyebrow = document.querySelector("#customer-auth-eyebrow");
  const title = document.querySelector("#customer-auth-title");
  const copy = document.querySelector("#customer-auth-copy");
  const submitBtn = document.querySelector("#send-otp-button");

  if (mode === "signup") {
    if (eyebrow) eyebrow.textContent = "NEW CUSTOMER";
    if (title) title.textContent = "Create customer account";
    if (copy) copy.textContent = "Enter your email address. We will verify it with a 10-minute OTP, then complete your profile.";
    if (submitBtn) submitBtn.innerHTML = "Get started with OTP <span>→</span>";
  } else {
    if (eyebrow) eyebrow.textContent = "CUSTOMER ACCESS";
    if (title) title.textContent = "Sign in with email";
    if (copy) copy.textContent = "Enter your email address to receive a secure OTP code. You only need to verify once on this device.";
    if (submitBtn) submitBtn.innerHTML = "Send verification code <span>→</span>";
  }
}

document.querySelector("#auth-tab-signin")?.addEventListener("click", () => setCustomerAuthMode("signin"));
document.querySelector("#auth-tab-signup")?.addEventListener("click", () => setCustomerAuthMode("signup"));
if (customerAuthMode === "signup") {
  setCustomerAuthMode("signup");
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
  const urlShop = Number(new URLSearchParams(location.search).get("shop"));
  if (!urlShop) {
    shopId = null;
    sessionStorage.removeItem("trimtimeScannedShopId");
    sessionStorage.removeItem("trimtimeActiveShopId");
  }
  loadShops().then(() => Promise.all([restoreActiveQueue(), refreshAppointment()])).catch((reason) => showCustomerNotice(reason.message));
}
function showCustomerNotice(message, success = false) {
  const notice = document.querySelector("#customer-notice"); clearTimeout(customerNoticeTimer);
  notice.textContent = message; notice.classList.toggle("success", success); notice.classList.remove("hidden");
  notice.scrollIntoView({ behavior: "smooth", block: "start" });
  customerNoticeTimer = setTimeout(() => notice.classList.add("hidden"), 8000);
}
document.querySelector("#customer-logout").addEventListener("click", () => {
  sessionStorage.removeItem("trimtimeCustomerToken");
  sessionStorage.removeItem("trimtimeScannedShopId");
  sessionStorage.removeItem("trimtimeActiveShopId");
  customerToken = null;
  location.href = "/customer";
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
const customerDetailsTab = document.querySelector("#customer-details-tab");
customerDetailsTab.insertAdjacentHTML("afterbegin", '<div class="section-heading"><h3>Your details</h3><button id="edit-customer-details" type="button" class="secondary">Edit details</button></div>');
customerDetailsTab.insertAdjacentHTML("beforeend", '<form id="customer-details-form" class="single-column-form hidden"><label>Name<input id="edit-customer-name" minlength="2" maxlength="100" autocomplete="name" required /></label><label>Age<input id="edit-customer-age" type="number" min="5" max="110" required /></label><label>Gender<select id="edit-customer-gender" required><option value="male">Male</option><option value="female">Female</option><option value="non_binary">Non-binary</option><option value="prefer_not_to_say">Prefer not to say</option></select></label><p class="muted small-note">Your verified email and mobile number cannot be changed here.</p><div class="actions"><button type="submit">Save changes</button><button id="cancel-customer-details" type="button" class="ghost">Cancel</button></div><p id="customer-details-result" class="success" aria-live="polite"></p></form>');
function setCustomerDetailsEdit(open) {
  document.querySelector(".profile-details").classList.toggle("hidden", open);
  document.querySelector("#customer-details-form").classList.toggle("hidden", !open);
  document.querySelector("#edit-customer-details").classList.toggle("hidden", open);
  if (open && currentCustomer) {
    document.querySelector("#edit-customer-name").value = currentCustomer.name || "";
    document.querySelector("#edit-customer-age").value = currentCustomer.age || "";
    document.querySelector("#edit-customer-gender").value = currentCustomer.gender || "prefer_not_to_say";
    document.querySelector("#customer-details-result").textContent = "";
  }
}
document.querySelector("#edit-customer-details").addEventListener("click", () => setCustomerDetailsEdit(true));
document.querySelector("#cancel-customer-details").addEventListener("click", () => setCustomerDetailsEdit(false));
document.querySelector("#customer-details-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = document.querySelector("#customer-details-result"); result.textContent = "";
  try {
    const customer = await api("/api/customer-auth/me", { method: "PATCH", body: JSON.stringify({ name: document.querySelector("#edit-customer-name").value.trim(), age: Number(document.querySelector("#edit-customer-age").value), gender: document.querySelector("#edit-customer-gender").value }) });
    showCustomerApp(customer); setCustomerDetailsEdit(false); showCustomerNotice("Your customer details were updated.", true);
  } catch (reason) { result.textContent = reason.message; }
});
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
  body.innerHTML = visibleItems.map((item, index) => { const draft = customerHistoryDrafts[historyDraftKey(item)] || {}; return `<article class="service-history-card"><header><div><h3>${escapeHtml(item.shop)}</h3><p>${escapeHtml(item.service)} <span>·</span> ${escapeHtml(item.barber)}</p></div><span class="completed-badge">Completed ✓</span></header><div class="service-summary"><span>${escapeHtml(item.token)}</span><strong>${escapeHtml(item.service)}</strong><b>&#8377;${item.price_rupees}</b></div>${item.rated ? '<div class="rating-submitted">✓ Rating and feedback submitted</div>' : `<div class="history-rating-grid">${historyStars(`history-shop-${index}`, "Shop rating", draft.shopStars)}${item.barber_id ? historyStars(`history-barber-${index}`, "Barber rating", draft.barberStars) : ""}</div><label class="history-feedback">Feedback (optional)<textarea id="history-feedback-${index}" maxlength="500" placeholder="Share your experience">${escapeHtml(draft.feedback || "")}</textarea></label><button type="button" class="history-submit" data-history-submit="${index}">Submit</button><p id="history-result-${index}" class="history-result" aria-live="polite"></p>`}<button type="button" class="rebook-service" data-rebook-service="${index}">Rebook service <span>›</span></button><button type="button" class="view-shop-services" data-view-services="${index}">View more services</button><footer>Visited ${formatAppDateTime(item.date)} <span>·</span> Total &#8377;${item.price_rupees}</footer></article>`; }).join("");
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
  await selectAndShowShop(targetShopId);
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
  if (customerToken) {
    try {
      const response = await fetch("/api/customer-auth/me", { headers: { Authorization: `Bearer ${customerToken}` } });
      if (response.ok) {
        showCustomerApp(await response.json());
        return;
      }
    } catch {}
    sessionStorage.removeItem("trimtimeCustomerToken");
    customerToken = null;
  }

  // Device-level fast MPIN login if customer previously logged in on this device
  const savedEmail = localStorage.getItem("trimtimeCustomerEmail");
  if (savedEmail && customerDeviceId && customerAuthMode !== "signup") {
    try {
      const check = await fetch("/api/customer-auth/check-device", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier: savedEmail, device_id: customerDeviceId })
      }).then((r) => r.json());
      if (check.mpin_login) {
        pendingIdentifier = savedEmail;
        showCustomerMpin("login", check.name || null);
      }
    } catch (err) {
      console.warn("Device check failed:", err);
    }
  }
}

async function requestOtp(identifier, resetMpin = false) {
  resetCustomerMpin = resetMpin;
  const cleanEmail = identifier.trim().toLowerCase();
  const response = await fetch("/api/customer-auth/request-otp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: cleanEmail, device_id: customerDeviceId })
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiError(body.detail));
  firstTimeCustomer = body.first_time;
  if (currentCustomerAuthMode === "signin" && firstTimeCustomer) {
    setCustomerAuthMode("signup");
  } else if (currentCustomerAuthMode === "signup" && !firstTimeCustomer) {
    setCustomerAuthMode("signin");
  }
  pendingIdentifier = cleanEmail;
  document.querySelector("#otp-request-step").classList.add("hidden");
  document.querySelector("#otp-verify-step").classList.remove("hidden");
  document.querySelector("#otp-message").textContent = body.message || `Verification code sent to ${cleanEmail}. Check your inbox.`;
  const statusEl = document.querySelector("#customer-auth-status");
  if (statusEl) statusEl.textContent = "Verification code has been dispatched to your email.";
}

function showCustomerMpin(mode, accountName = null) {
  customerMpinMode = mode;
  ["#otp-request-step", "#otp-verify-step", "#customer-profile-step"].forEach((id) => document.querySelector(id).classList.add("hidden"));
  document.querySelector("#customer-mpin-step").classList.remove("hidden");
  const enteringExisting = mode === "login" || mode === "verify", needsConfirm = mode === "setup";
  const titleEl = document.querySelector("#customer-mpin-title");
  if (titleEl) {
    titleEl.textContent = enteringExisting
      ? (accountName ? `Welcome back, ${accountName}!` : "Enter your MPIN")
      : (resetCustomerMpin ? "Create a new MPIN" : "Create your 6-digit MPIN");
  }
  const copyEl = document.querySelector("#customer-mpin-copy");
  if (copyEl) {
    copyEl.textContent = enteringExisting
      ? "Enter your 6-digit MPIN to sign in on this trusted device."
      : "Use this MPIN for instant sign-ins on this device in the future.";
  }
  const banner = document.querySelector("#customer-saved-device-banner");
  const badge = document.querySelector("#customer-saved-email-badge");
  if (banner && badge) {
    if (mode === "login" && pendingIdentifier) {
      badge.textContent = pendingIdentifier;
      banner.classList.remove("hidden");
    } else {
      banner.classList.add("hidden");
    }
  }
  document.querySelector("#customer-confirm-mpin-label").classList.toggle("hidden", !needsConfirm);
  document.querySelector("#customer-confirm-mpin").required = needsConfirm;
  document.querySelector("#customer-mpin-submit").textContent = enteringExisting ? "Sign in →" : "Save MPIN and continue →";
  document.querySelector("#forgot-customer-mpin").classList.toggle("hidden", !enteringExisting);
}

const switchAccountBtn = document.querySelector("#switch-account-btn");
if (switchAccountBtn) {
  switchAccountBtn.addEventListener("click", () => {
    localStorage.removeItem("trimtimeCustomerEmail");
    pendingIdentifier = "";
    document.querySelector("#customer-mpin-step").classList.add("hidden");
    document.querySelector("#otp-request-step").classList.remove("hidden");
    const identInput = document.querySelector("#customer-identifier");
    if (identInput) {
      identInput.value = "";
      identInput.focus();
    }
  });
}

document.querySelector("#otp-request-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const authError = document.querySelector("#customer-auth-error");
  authError.textContent = "";
  pendingIdentifier = document.querySelector("#customer-identifier").value.trim().toLowerCase();
  try {
    const check = await fetch("/api/customer-auth/check-device", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier: pendingIdentifier, device_id: customerDeviceId })
    }).then((r) => r.json());
    if (check.mpin_login && customerAuthMode !== "signup") {
      showCustomerMpin("login", check.name || null);
    } else {
      await requestOtp(pendingIdentifier);
    }
  } catch (reason) {
    authError.textContent = reason.message;
  }
});

document.querySelector("#resend-customer-otp").addEventListener("click", async () => {
  const authError = document.querySelector("#customer-auth-error");
  authError.textContent = "";
  try {
    await requestOtp(pendingIdentifier);
  } catch (reason) {
    authError.textContent = reason.message;
  }
});

async function completeOtpVerification(profile = {}) {
  const response = await fetch("/api/customer-auth/verify-otp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: pendingIdentifier, otp: pendingOtp, reset_mpin: resetCustomerMpin, ...profile })
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiError(body.detail));
  customerMpinVerification = body.verification_token;
  showCustomerMpin(body.requires_mpin_setup ? "setup" : "verify", body.customer ? body.customer.name : null);
}

document.querySelector("#otp-verify-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const authError = document.querySelector("#customer-auth-error");
  authError.textContent = "";
  pendingOtp = document.querySelector("#customer-otp").value.trim();
  try {
    if (firstTimeCustomer) {
      document.querySelector("#otp-verify-step").classList.add("hidden");
      document.querySelector("#customer-profile-step").classList.remove("hidden");
    } else {
      await completeOtpVerification();
    }
  } catch (reason) {
    authError.textContent = reason.message || "Invalid OTP code";
  }
});

document.querySelector("#customer-profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const authError = document.querySelector("#customer-auth-error");
  authError.textContent = "";
  try {
    await completeOtpVerification({
      name: document.querySelector("#verified-customer-name").value.trim(),
      age: Number(document.querySelector("#verified-customer-age").value),
      gender: document.querySelector("#verified-customer-gender").value,
      terms_accepted: document.querySelector("#customer-terms").checked
    });
  } catch (reason) {
    authError.textContent = reason.message;
  }
});

document.querySelector("#customer-mpin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const authError = document.querySelector("#customer-auth-error");
  authError.textContent = "";
  const mpin = document.querySelector("#customer-mpin").value;
  try {
    const path = customerMpinMode === "login" ? "/api/customer-auth/login-mpin" : "/api/customer-auth/complete-mpin";
    const payload = customerMpinMode === "login"
      ? { identifier: pendingIdentifier, mpin, device_id: customerDeviceId, device_name: navigator.userAgent.slice(0, 160) }
      : { verification_token: customerMpinVerification, mpin, confirm_mpin: document.querySelector("#customer-confirm-mpin").value || null, device_id: customerDeviceId, device_name: navigator.userAgent.slice(0, 160) };
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(formatApiError(body.detail));
    customerToken = body.access_token;
    sessionStorage.setItem("trimtimeCustomerToken", customerToken);
    localStorage.setItem("trimtimeCustomerEmail", pendingIdentifier);
    showCustomerApp(body.customer);
  } catch (reason) {
    authError.textContent = reason.message;
  }
});

document.querySelector("#forgot-customer-mpin").addEventListener("click", async () => {
  const authError = document.querySelector("#customer-auth-error");
  authError.textContent = "";
  try {
    document.querySelector("#customer-mpin-step").classList.add("hidden");
    await requestOtp(pendingIdentifier, true);
  } catch (reason) {
    authError.textContent = reason.message;
  }
});
fetch("/api/platform/banner").then((response) => response.json()).then((banner) => { document.querySelectorAll(".brand-name").forEach((item) => item.textContent = banner.software_name); if (banner.login_image_url) { document.querySelector("#customer-auth-image").style.backgroundImage = `linear-gradient(135deg,#173c35cc,#245c5277),url("${banner.login_image_url}")`; document.querySelector("#customer-profile-ad").style.backgroundImage = `url("${banner.login_image_url}")`; } }).catch(() => {});

function fillSelect(selector, items, label) {
  const select = document.querySelector(selector); select.replaceChildren();
  items.forEach((item) => { const option = document.createElement("option"); option.value = item.id; option.textContent = label(item); select.append(option); });
}
function selectedAppointmentServiceIds() { return [...document.querySelectorAll("[data-appointment-service]:checked")].map((input) => Number(input.value)); }
function updateAppointmentServiceLabel() {
  const selected = [...document.querySelectorAll("[data-appointment-service]:checked")];
  const services = selected.map((input) => currentShop?.services.find((item) => item.id === Number(input.value))).filter(Boolean);
  const duration = services.reduce((total, item) => total + item.duration_minutes, 0), price = services.reduce((total, item) => total + item.price_rupees, 0);
  document.querySelector("#appointment-service-toggle span").textContent = selected.length ? `${selected.map((input) => input.dataset.serviceName).join(", ")} · ${duration} min · ₹${price}` : "Choose services";
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

function updateScannedShopBadge() {
  const badge = document.querySelector("#scanned-shop-badge");
  if (!badge) return;
  const scannedId = Number(sessionStorage.getItem("trimtimeScannedShopId"));
  const isScanned = Boolean(scannedId && shopId === scannedId);
  badge.classList.toggle("hidden", !isScanned);
}

function showOtherShopTicketBanner(entry) {
  const banner = document.querySelector("#other-shop-banner");
  if (!banner) return;
  if (!shopId || !entry || ["completed", "cancelled"].includes(entry.status)) {
    banner.classList.add("hidden");
    return;
  }
  activeTicketShopId = entry.shop_id;
  const shopName = entry.shop_name || allShops.find((s) => s.id === entry.shop_id)?.name || "another shop";
  const bannerText = document.querySelector("#other-shop-banner-text");
  if (bannerText) bannerText.textContent = `🎟️ You have an active queue ticket (#${entry.token}) at ${shopName}.`;
  banner.classList.remove("hidden");
}

function hideOtherShopTicketBanner() {
  const banner = document.querySelector("#other-shop-banner");
  if (banner) banner.classList.add("hidden");
}

function showAllShopsView(shops = allShops) {
  shopId = null;
  customerHero.classList.add("hidden");
  joinPanel.classList.add("hidden");
  const apptPanel = document.querySelector("#appointment-panel");
  if (apptPanel) apptPanel.classList.add("hidden");
  const apptTicket = document.querySelector("#appointment-ticket-panel");
  if (apptTicket) apptTicket.classList.add("hidden");
  ticketPanel.classList.add("hidden");
  hideOtherShopTicketBanner();

  const marketplaceSec = document.querySelector("#marketplace-section");
  if (marketplaceSec) {
    const customerApp = document.querySelector("#customer-app");
    if (customerApp && customerHero) {
      customerApp.insertBefore(marketplaceSec, customerHero);
    }
    marketplaceSec.classList.remove("hidden");
    const eyebrow = document.querySelector("#marketplace-eyebrow");
    if (eyebrow) eyebrow.textContent = "BARBER SHOPS NEAR YOU";
    const title = document.querySelector("#marketplace-title");
    if (title) title.textContent = "Choose a barber shop";
    const subtitle = document.querySelector("#marketplace-subtitle");
    if (subtitle) subtitle.classList.remove("hidden");
  }
  renderShopCards(shops || allShops, true);
  if (marketplaceSec) {
    marketplaceSec.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

async function selectAndShowShop(targetShopId, options = {}) {
  const nextId = Number(targetShopId);
  if (!nextId) return;
  shopId = nextId;
  sessionStorage.setItem("trimtimeActiveShopId", String(shopId));
  localStorage.setItem("trimtimeLastShopId", String(shopId));
  history.replaceState({}, "", `/customer?shop=${shopId}`);
  if (document.querySelector("#shop")) document.querySelector("#shop").value = shopId;
  if (document.querySelector("#shop-switcher")) document.querySelector("#shop-switcher").value = shopId;

  customerHero.classList.remove("hidden");
  const backBtn = document.querySelector("#back-to-all-shops");
  if (backBtn) backBtn.classList.remove("hidden");

  const marketplaceSec = document.querySelector("#marketplace-section");
  if (marketplaceSec) {
    const customerApp = document.querySelector("#customer-app");
    if (customerApp) {
      customerApp.appendChild(marketplaceSec);
    }
    const eyebrow = document.querySelector("#marketplace-eyebrow");
    if (eyebrow) eyebrow.textContent = "NEAR YOU";
    const title = document.querySelector("#marketplace-title");
    if (title) title.textContent = "Other barber shops";
    const subtitle = document.querySelector("#marketplace-subtitle");
    if (subtitle) subtitle.classList.add("hidden");
  }

  updateScannedShopBadge();
  await loadShop();

  if (options.join) {
    await joinCurrentShop();
  } else if (options.book) {
    const target = document.querySelector("#appointment-panel");
    if (target && currentShop?.appointments_enabled !== false) {
      target.classList.remove("hidden");
      target.scrollIntoView({ behavior: "smooth" });
    }
  } else {
    if (activeToken) {
      await refreshTicket();
    }
    if (activeAppointmentToken) {
      await refreshAppointment();
    }
    customerHero.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function renderShopCards(shops, showAll = false) {
  const cards = document.querySelector("#nearby-shop-cards");
  const displayShops = showAll ? shops : shops.filter((item) => item.id !== shopId);
  if (!displayShops.length) {
    cards.innerHTML = '<p class="muted">No other shops are currently available.</p>';
    return;
  }
  cards.innerHTML = displayShops.map((item) => {
    const dest = (item.latitude && item.longitude)
      ? `${item.latitude},${item.longitude}`
      : encodeURIComponent(`${item.name}, ${item.address}`);
    const bookButtonHtml = item.appointments_enabled !== false
      ? `<button type="button" data-book-shop="${item.id}" class="secondary">Book appointment</button>`
      : "";
    return `<article class="shop-market-card clickable-shop-card" data-shop-id="${item.id}" tabindex="0" role="button" aria-label="View ${escapeHtml(item.name)} details">${item.photo_url ? `<img src="${item.photo_url}" alt="${escapeHtml(item.name)}" />` : '<div class="shop-card-placeholder">TRIMTIME</div>'}<div class="shop-market-content"><div class="shop-card-header"><h3>${escapeHtml(item.name)}</h3><span class="view-details-pill">View shop ›</span></div><p class="shop-rating-summary">${ratingSummary(item)}</p><p>${escapeHtml(item.address)}</p><small>${item.opens_at}–${item.closes_at} · ${item.waiting_count} waiting · ${item.estimated_wait_minutes} estimated minutes</small><p class="card-services">${(item.services || []).slice(0, 3).map((service) => `${escapeHtml(service.name)} ₹${service.price_rupees}`).join(" · ")}</p><div class="actions"><button type="button" class="view-shop-btn" data-view-shop="${item.id}">View shop details</button><button type="button" data-open-shop="${item.id}">Join live queue</button>${bookButtonHtml}<a href="https://www.google.com/maps/dir/?api=1&destination=${dest}" target="_blank" rel="noopener" class="card-direction-btn" title="Navigate with Google Maps" onclick="event.stopPropagation()">🧭 Directions</a></div></div></article>`;
  }).join("");

  cards.querySelectorAll(".clickable-shop-card").forEach((card) => {
    const targetShopId = Number(card.dataset.shopId);
    card.addEventListener("click", async (event) => {
      if (event.target.closest("[data-open-shop],[data-book-shop],[data-view-shop],.card-direction-btn")) return;
      await selectAndShowShop(targetShopId);
    });
    card.addEventListener("keydown", async (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        await selectAndShowShop(targetShopId);
      }
    });
  });

  cards.querySelectorAll("[data-view-shop]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await selectAndShowShop(Number(button.dataset.viewShop));
    });
  });

  cards.querySelectorAll("[data-open-shop]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await selectAndShowShop(Number(button.dataset.openShop), { join: true });
    });
  });

  cards.querySelectorAll("[data-book-shop]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await selectAndShowShop(Number(button.dataset.bookShop), { book: true });
    });
  });
}

async function loadShops() {
  const shops = await api("/api/shops");
  allShops = shops;
  if (!shops.length) {
    showCustomerNotice("No active barber shops are available right now.");
    return;
  }
  fillSelect("#shop", shops, (shop) => `${shop.name} · ${shop.address}`);
  if (document.querySelector("#shop-switcher")) {
    fillSelect("#shop-switcher", shops, (shop) => `${shop.name} · ${shop.address}`);
  }

  const urlShop = Number(new URLSearchParams(location.search).get("shop"));
  if (urlShop && shops.some((s) => s.id === urlShop)) {
    shopId = urlShop;
    sessionStorage.setItem("trimtimeScannedShopId", String(shopId));
    sessionStorage.setItem("trimtimeActiveShopId", String(shopId));
    await selectAndShowShop(shopId);
  } else {
    // Customer did not scan any shop -> Show all listed shops directory!
    shopId = null;
    sessionStorage.removeItem("trimtimeScannedShopId");
    sessionStorage.removeItem("trimtimeActiveShopId");
    showAllShopsView(shops);
  }
}

async function loadShop() {
  const previousShopId = currentShop?.id, previousAppointmentServices = selectedAppointmentServiceIds();
  currentShop = await api(`/api/shops/${shopId}`);
  document.querySelector("#shop-name").textContent = currentShop.name;
  document.querySelector("#shop-average-rating").textContent = ratingSummary(currentShop);
  document.querySelector("#shop-address").textContent = `${currentShop.address} · ${currentShop.opens_at}–${currentShop.closes_at}`;
  const navLink = document.querySelector("#shop-navigation-link");
  if (navLink) {
    const dest = (currentShop.latitude && currentShop.longitude)
      ? `${currentShop.latitude},${currentShop.longitude}`
      : encodeURIComponent(`${currentShop.name}, ${currentShop.address}`);
    navLink.href = `https://www.google.com/maps/dir/?api=1&destination=${dest}`;
    navLink.classList.remove("hidden");
  }
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
  const shopChanged = previousShopId !== currentShop.id;
  const optionsEl = document.querySelector("#appointment-service-options");
  if (shopChanged || !optionsEl || !optionsEl.hasChildNodes()) {
    renderAppointmentServiceOptions(currentShop.services);
    if (previousShopId === currentShop.id) {
      const selectedIds = new Set(previousAppointmentServices); document.querySelectorAll("[data-appointment-service]").forEach((input) => { input.checked = selectedIds.has(Number(input.value)); }); updateAppointmentServiceLabel();
    }
    fillSelect("#appointment-barber", [{ id: "", name: "Any available barber" }, ...currentShop.barbers], (item) => item.id ? `${item.name} · ★ ${item.career_rating || 0} · ${item.experience_years || 0} years` : item.name);
    const appointmentDate = document.querySelector("#appointment-date");
    const today = new Date().toLocaleDateString("en-CA"); appointmentDate.min = today; if (!appointmentDate.value) appointmentDate.value = today;
    await loadAppointmentSlots();
  }
  const appointmentsAllowed = currentShop.appointments_enabled !== false;
  const bookApptBtn = document.querySelector("#show-appointment-options");
  if (bookApptBtn) bookApptBtn.classList.toggle("hidden", !appointmentsAllowed);
  if (!appointmentsAllowed) {
    const apptPanel = document.querySelector("#appointment-panel");
    if (apptPanel) apptPanel.classList.add("hidden");
  }
  if (activeAppointmentDetails && activeAppointmentDetails.shop_id === shopId) {
    showAppointment(activeAppointmentDetails);
  } else {
    const apptTicket = document.querySelector("#appointment-ticket-panel");
    if (apptTicket) apptTicket.classList.add("hidden");
  }
  renderShopCards(allShops);
  updateScannedShopBadge();
  connectRealtime();
}

document.querySelector("#shop").addEventListener("change", async (event) => {
  await selectAndShowShop(Number(event.target.value));
});

const shopSwitcher = document.querySelector("#shop-switcher");
if (shopSwitcher) {
  shopSwitcher.addEventListener("change", async (event) => {
    await selectAndShowShop(Number(event.target.value));
  });
}

const switchTicketBtn = document.querySelector("#switch-to-ticket-shop");
if (switchTicketBtn) {
  switchTicketBtn.addEventListener("click", async () => {
    if (activeTicketShopId) {
      await selectAndShowShop(activeTicketShopId);
      if (activeToken) await refreshTicket();
    }
  });
}

function populateJoinForm() {
  const nameInput = document.querySelector("#customer-name");
  if (nameInput && currentCustomer && currentCustomer.name) {
    nameInput.value = currentCustomer.name;
  }
  const phoneInput = document.querySelector("#phone");
  if (phoneInput && currentCustomer && currentCustomer.phone) {
    phoneInput.value = currentCustomer.phone;
  }
  if (currentShop && currentShop.services) {
    fillSelect("#service", [{ id: "", name: "-- Select a service (mandatory) --" }, ...currentShop.services], (item) => item.id ? `${item.name} · ${item.duration_minutes} min · ₹${item.price_rupees}` : item.name);
    renderJoinServiceCards(currentShop.services);
  }
  if (currentShop && currentShop.barbers) {
    fillSelect("#barber", [{ id: "", name: "Any available barber" }, ...currentShop.barbers], (item) => item.name);
  }
}

function renderJoinServiceCards(services) {
  const container = document.querySelector("#join-services-grid");
  if (!container) return;
  const select = document.querySelector("#service");

  if (!services || !services.length) {
    container.innerHTML = '<p class="muted">No services currently listed for this shop.</p>';
    return;
  }

  container.innerHTML = services.map((s) => `
    <div class="service-card-choice" data-service-id="${s.id}" data-duration="${s.duration_minutes}" data-price="${s.price_rupees}" data-name="${escapeHtml(s.name)}">
      <div class="choice-check">✓</div>
      <div class="choice-main">
        <strong>${escapeHtml(s.name)}</strong>
        <div class="choice-badges">
          <span class="choice-duration">⏱️ ${s.duration_minutes} min</span>
          <span class="choice-price">₹${s.price_rupees}</span>
        </div>
      </div>
    </div>
  `).join("");

  container.querySelectorAll(".service-card-choice").forEach((card) => {
    card.addEventListener("click", () => {
      container.querySelectorAll(".service-card-choice").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      const serviceId = card.dataset.serviceId;
      select.value = serviceId;

      const banner = document.querySelector("#join-selected-service-banner");
      if (banner) {
        banner.classList.remove("hidden");
        document.querySelector("#join-selected-service-name").textContent = card.dataset.name;
        document.querySelector("#join-selected-service-meta").textContent = `${card.dataset.duration} mins · ₹${card.dataset.price}`;
        const baseWait = Number(currentShop?.estimated_wait_minutes || 0);
        document.querySelector("#join-service-est-wait").textContent = `~${baseWait} min wait`;
      }
      document.querySelector("#form-error").textContent = "";
    });
  });
}

document.querySelector("#show-join-options").addEventListener("click", () => {
  if (currentQueueEntry && (currentQueueEntry.status === "waiting" || currentQueueEntry.status === "serving") && currentQueueEntry.shop_id === shopId) {
    showCustomerNotice(`You already have an active ticket in the live queue.`);
    showTicket(currentQueueEntry);
    ticketPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  const apptPanel = document.querySelector("#appointment-panel");
  if (apptPanel) apptPanel.classList.add("hidden");
  joinPanel.classList.remove("hidden");
  populateJoinForm();
  joinPanel.scrollIntoView({ behavior: "smooth", block: "start" });
});

const closeJoinBtn = document.querySelector("#close-join-panel");
if (closeJoinBtn) {
  closeJoinBtn.addEventListener("click", () => {
    joinPanel.classList.add("hidden");
  });
}

document.querySelector("#show-appointment-options").addEventListener("click", () => {
  const appointmentPanel = document.querySelector("#appointment-panel");
  appointmentPanel.classList.remove("hidden");
  joinPanel.classList.add("hidden");
  appointmentPanel.scrollIntoView({ behavior: "smooth", block: "start" });
});
const closeAppointmentBtn = document.querySelector("#close-appointment-panel");
if (closeAppointmentBtn) {
  closeAppointmentBtn.addEventListener("click", () => {
    document.querySelector("#appointment-panel").classList.add("hidden");
  });
}
const backToAllShopsBtn = document.querySelector("#back-to-all-shops");
if (backToAllShopsBtn) {
  backToAllShopsBtn.addEventListener("click", () => {
    sessionStorage.removeItem("trimtimeScannedShopId");
    sessionStorage.removeItem("trimtimeActiveShopId");
    history.replaceState({}, "", "/customer");
    showAllShopsView(allShops);
  });
}
const topBrandLink = document.querySelector(".topbar a.brand");
if (topBrandLink) {
  topBrandLink.addEventListener("click", (event) => {
    if (currentCustomer && !document.querySelector("#customer-app").classList.contains("hidden")) {
      event.preventDefault();
      sessionStorage.removeItem("trimtimeScannedShopId");
      sessionStorage.removeItem("trimtimeActiveShopId");
      history.replaceState({}, "", "/customer");
      showAllShopsView(allShops);
    }
  });
}

let currentAvailableSlots = [];
let currentSlotFilter = "all";

function getSlotPeriod(isoString) {
  try {
    const d = new Date(isoString);
    const hours = d.getHours();
    if (hours < 12) return "morning";
    if (hours < 17) return "afternoon";
    return "evening";
  } catch {
    return "all";
  }
}

function renderSlotCards(slots, selectedBarberName = null) {
  const cardsContainer = document.querySelector("#appointment-slot-cards");
  const statusContainer = document.querySelector("#appointment-slot-status");
  const countBadge = document.querySelector("#slot-count-badge");
  const filterTabs = document.querySelector("#slot-period-filters");
  const slotInput = document.querySelector("#appointment-slot");
  const summaryBox = document.querySelector("#appointment-selected-slot-summary");

  if (!cardsContainer) return;

  const currentVal = slotInput ? slotInput.value : "";

  // Filter by period
  const filtered = currentSlotFilter === "all"
    ? slots
    : slots.filter((slot) => getSlotPeriod(slot.value) === currentSlotFilter);

  if (countBadge) {
    countBadge.textContent = `${slots.length} slot${slots.length === 1 ? "" : "s"} available`;
    countBadge.classList.toggle("hidden", slots.length === 0);
  }

  if (filterTabs) {
    filterTabs.classList.toggle("hidden", slots.length === 0);
  }

  if (slots.length === 0) {
    cardsContainer.classList.add("hidden");
    if (statusContainer) {
      statusContainer.innerHTML = `
        <div class="slots-empty-card">
          <span class="empty-icon">📅</span>
          <strong>No available slots for this date</strong>
          <p>Please select another date or choose "Any available barber" to see more time options.</p>
        </div>
      `;
      statusContainer.classList.remove("hidden");
    }
    if (slotInput) slotInput.value = "";
    if (summaryBox) summaryBox.classList.add("hidden");
    return;
  }

  if (filtered.length === 0) {
    cardsContainer.classList.add("hidden");
    if (statusContainer) {
      statusContainer.innerHTML = `
        <div class="slots-empty-card">
          <span class="empty-icon">🕒</span>
          <strong>No ${currentSlotFilter} slots found</strong>
          <p>Try switching to another time period tab above or choosing a different date.</p>
        </div>
      `;
      statusContainer.classList.remove("hidden");
    }
    return;
  }

  if (statusContainer) statusContainer.classList.add("hidden");
  cardsContainer.classList.remove("hidden");

  cardsContainer.innerHTML = filtered.map((slot) => {
    const isSelected = slot.value === currentVal;
    const barberNames = slot.barber_names || [];
    const barberCount = Number(slot.available_barbers || barberNames.length || 0);
    const period = getSlotPeriod(slot.value);
    const periodIcon = period === "morning" ? "🌅" : period === "afternoon" ? "☀️" : "🌙";

    // Build barber badges
    const barberHtml = barberNames.length > 0
      ? barberNames.map((bName) => {
          const isTarget = selectedBarberName && bName.toLowerCase() === selectedBarberName.toLowerCase();
          return `<span class="slot-barber-pill ${isTarget ? "highlighted" : ""}"><span class="barber-pill-bullet">✂</span> ${escapeHtml(bName)}</span>`;
        }).join("")
      : `<span class="slot-barber-pill muted-pill"><span class="barber-pill-bullet">✓</span> Barber available</span>`;

    const barberCountLabel = selectedBarberName
      ? `<span class="barber-availability-badge ready">Confirmed barber</span>`
      : barberCount > 1
        ? `<span class="barber-availability-badge multiple">${barberCount} barbers free</span>`
        : `<span class="barber-availability-badge single">1 barber free</span>`;

    return `
      <article class="slot-card ${isSelected ? "selected" : ""}" data-slot-val="${escapeHtml(slot.value)}" tabindex="0" role="radio" aria-checked="${isSelected}">
        <div class="slot-card-header">
          <div class="slot-time-group">
            <span class="slot-period-emoji" aria-hidden="true">${periodIcon}</span>
            <strong class="slot-time-text">${escapeHtml(slot.label)}</strong>
          </div>
          ${barberCountLabel}
        </div>
        <div class="slot-card-body">
          <span class="slot-barber-caption">${selectedBarberName ? "Assigned barber:" : (barberCount > 1 ? "Available barbers for this slot:" : "Available barber:")}</span>
          <div class="slot-barbers-wrap">
            ${barberHtml}
          </div>
        </div>
        <div class="slot-card-footer">
          <span class="slot-select-radio" aria-hidden="true">
            <span class="radio-dot"></span>
          </span>
          <span class="slot-select-label">${isSelected ? "Selected" : "Select this slot"}</span>
        </div>
      </article>
    `;
  }).join("");

  cardsContainer.querySelectorAll(".slot-card").forEach((card) => {
    const val = card.dataset.slotVal;
    const slotObj = slots.find((s) => s.value === val);

    const selectThisSlot = () => {
      if (!slotObj) return;
      if (slotInput) slotInput.value = slotObj.value;

      cardsContainer.querySelectorAll(".slot-card").forEach((c) => {
        const isThis = c === card;
        c.classList.toggle("selected", isThis);
        c.setAttribute("aria-checked", String(isThis));
        const label = c.querySelector(".slot-select-label");
        if (label) label.textContent = isThis ? "Selected" : "Select this slot";
      });

      // Hide available slot cards and filters when a slot is chosen
      cardsContainer.classList.add("hidden");
      if (filterTabs) filterTabs.classList.add("hidden");
      if (countBadge) countBadge.classList.add("hidden");

      if (summaryBox) {
        document.querySelector("#summary-slot-time").textContent = `${slotObj.label} · ${formatAppDate(document.querySelector("#appointment-date").value)}`;
        const bNames = (slotObj.barber_names || []).join(", ");
        document.querySelector("#summary-slot-barbers").textContent = bNames ? `Barbers: ${bNames}` : "Any available barber";
        summaryBox.classList.remove("hidden");
      }
    };

    card.addEventListener("click", selectThisSlot);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectThisSlot();
      }
    });
  });

  if (currentVal) {
    const currentObj = slots.find((s) => s.value === currentVal);
    if (currentObj && summaryBox) {
      document.querySelector("#summary-slot-time").textContent = `${currentObj.label} · ${formatAppDate(document.querySelector("#appointment-date").value)}`;
      const bNames = (currentObj.barber_names || []).join(", ");
      document.querySelector("#summary-slot-barbers").textContent = bNames ? `Barbers: ${bNames}` : "Any available barber";
      summaryBox.classList.remove("hidden");
    }
  }
}

async function loadAppointmentSlots() {
  const slotInput = document.querySelector("#appointment-slot");
  const date = document.querySelector("#appointment-date").value;
  const serviceIds = selectedAppointmentServiceIds();
  const barberSelect = document.querySelector("#appointment-barber");
  const barberId = barberSelect ? barberSelect.value : "";
  const selectedBarberName = barberId && barberSelect.selectedIndex > 0
    ? barberSelect.options[barberSelect.selectedIndex].text.split(" · ")[0]
    : null;

  const statusContainer = document.querySelector("#appointment-slot-status");
  const cardsContainer = document.querySelector("#appointment-slot-cards");
  const filterTabs = document.querySelector("#slot-period-filters");
  const countBadge = document.querySelector("#slot-count-badge");
  const summaryBox = document.querySelector("#appointment-selected-slot-summary");

  if (!date || !serviceIds.length) {
    if (statusContainer) {
      statusContainer.innerHTML = '<div class="slot-helper-note">Select one or more services and a date above to view available time slots</div>';
      statusContainer.classList.remove("hidden");
    }
    if (cardsContainer) cardsContainer.classList.add("hidden");
    if (filterTabs) filterTabs.classList.add("hidden");
    if (countBadge) countBadge.classList.add("hidden");
    if (summaryBox) summaryBox.classList.add("hidden");
    if (slotInput) slotInput.value = "";
    currentAvailableSlots = [];
    return;
  }

  const hadExistingSlots = currentAvailableSlots && currentAvailableSlots.length > 0;
  if (!hadExistingSlots) {
    if (statusContainer) {
      statusContainer.innerHTML = '<div class="slot-loading-state"><span class="slot-loading-spinner"></span> Checking available appointment slots…</div>';
      statusContainer.classList.remove("hidden");
    }
    if (cardsContainer) cardsContainer.classList.add("hidden");
  }

  try {
    const query = new URLSearchParams({ appointment_date: date });
    serviceIds.forEach((serviceId) => query.append("service_ids", serviceId));
    if (barberId) query.set("barber_id", barberId);

    const availability = await api(`/api/shops/${shopId}/appointment-slots?${query}`);
    currentAvailableSlots = availability.slots || [];
    renderSlotCards(currentAvailableSlots, selectedBarberName);
  } catch (reason) {
    currentAvailableSlots = [];
    if (statusContainer) {
      statusContainer.innerHTML = `<div class="slots-empty-card error"><span class="empty-icon">⚠️</span><p>${escapeHtml(reason.message)}</p></div>`;
      statusContainer.classList.remove("hidden");
    }
    if (cardsContainer) cardsContainer.classList.add("hidden");
    if (slotInput) slotInput.value = "";
    if (summaryBox) summaryBox.classList.add("hidden");
  }
}

document.querySelectorAll(".slot-filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".slot-filter-btn").forEach((b) => b.classList.toggle("active", b === btn));
    currentSlotFilter = btn.dataset.period || "all";
    const barberSelect = document.querySelector("#appointment-barber");
    const barberId = barberSelect ? barberSelect.value : "";
    const selectedBarberName = barberId && barberSelect.selectedIndex > 0
      ? barberSelect.options[barberSelect.selectedIndex].text.split(" · ")[0]
      : null;
    renderSlotCards(currentAvailableSlots, selectedBarberName);
  });
});

const clearSlotBtn = document.querySelector("#clear-selected-slot");
if (clearSlotBtn) {
  clearSlotBtn.addEventListener("click", () => {
    const slotInput = document.querySelector("#appointment-slot");
    if (slotInput) slotInput.value = "";
    const summaryBox = document.querySelector("#appointment-selected-slot-summary");
    if (summaryBox) summaryBox.classList.add("hidden");
    const cardsContainer = document.querySelector("#appointment-slot-cards");
    const filterTabs = document.querySelector("#slot-period-filters");
    const countBadge = document.querySelector("#slot-count-badge");
    if (cardsContainer) cardsContainer.classList.remove("hidden");
    if (filterTabs) filterTabs.classList.remove("hidden");
    if (countBadge) countBadge.classList.remove("hidden");
    document.querySelectorAll(".slot-card").forEach((card) => {
      card.classList.remove("selected");
      card.setAttribute("aria-checked", "false");
      const label = card.querySelector(".slot-select-label");
      if (label) label.textContent = "Select this slot";
    });
  });
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
    allShops = shops;
    fillSelect("#shop", shops, (shop) => `${shop.name} · ${shop.address} · ★ ${shop.average_rating}`);
    if (document.querySelector("#shop-switcher")) {
      fillSelect("#shop-switcher", shops, (shop) => `${shop.name} · ${shop.address} · ★ ${shop.average_rating}`);
    }
    if (shopId === null) {
      showAllShopsView(allShops);
    } else {
      renderShopCards(allShops, false);
    }
  }, () => document.querySelector("#form-error").textContent = "Location permission is needed to find nearby shops.");
});

let liveWaitTimer = null;
let lastTicketEntry = null;
let ticketSnapshotTime = null;

function updateLiveWaitDisplay() {
  if (!lastTicketEntry || lastTicketEntry.status !== "waiting") return;
  const baseWait = Number(lastTicketEntry.estimated_wait_minutes) || 0;
  if (baseWait <= 0) {
    const waitEl = document.querySelector("#ticket-wait");
    if (waitEl) waitEl.textContent = "0";
    return;
  }
  const elapsedMs = ticketSnapshotTime ? Date.now() - ticketSnapshotTime : 0;
  const elapsedMinutes = Math.floor(elapsedMs / 60000);
  const liveWait = Math.max(1, baseWait - elapsedMinutes);
  const waitEl = document.querySelector("#ticket-wait");
  if (waitEl) waitEl.textContent = String(liveWait);
  const heroWaitEl = document.querySelector("#wait-time");
  if (heroWaitEl && !heroWaitEl.closest(".hero.hidden")) {
    heroWaitEl.textContent = String(liveWait);
  }
}

function startLiveWaitCountdown(entry) {
  lastTicketEntry = entry;
  ticketSnapshotTime = Date.now();
  updateLiveWaitDisplay();
  if (liveWaitTimer) clearInterval(liveWaitTimer);
  liveWaitTimer = setInterval(updateLiveWaitDisplay, 10000);
}

async function sendAlert(entry) {
  if (entry.availability_message || !("Notification" in window) || Notification.permission !== "granted" || entry.people_ahead === lastPeopleAhead) return;
  if (entry.people_ahead === 2) new Notification("TrimTime", { body: entry.ahead_label === "turns ahead" ? "Only two turns remain before you." : "Only two customers are ahead of you." });
  if (entry.people_ahead === 0 && entry.status === "waiting") new Notification("TrimTime", { body: "You are next. Please reach the shop now." });
  if (entry.status === "serving") new Notification("TrimTime", { body: "Your barber is ready." });
}

function showTicket(entry) {
  if (!entry) return;
  sendAlert(entry);
  lastPeopleAhead = entry.people_ahead;
  const completed = entry.status === "completed", cancelled = entry.status === "cancelled";
  if (cancelled) {
    localStorage.removeItem("trimtimeQueueToken");
    activeToken = null;
    hideOtherShopTicketBanner();
  }

  if (completed || cancelled) {
    if (liveWaitTimer) clearInterval(liveWaitTimer);
    liveWaitTimer = null;
  }

  if (!shopId) {
    ticketPanel.classList.add("hidden");
    hideOtherShopTicketBanner();
    return;
  }

  if (entry.shop_id !== shopId) {
    ticketPanel.classList.add("hidden");
    if (!completed && !cancelled) {
      showOtherShopTicketBanner(entry);
    } else {
      hideOtherShopTicketBanner();
    }
    return;
  }

  hideOtherShopTicketBanner();
  joinPanel.classList.add("hidden");
  ticketPanel.classList.remove("hidden");
  document.querySelector("#ticket-token").textContent = entry.token;
  document.querySelector("#ticket-status").textContent = entry.status;
  document.querySelector("#people-ahead").textContent = entry.people_ahead ?? "—";
  document.querySelector("#ahead-label").textContent = entry.ahead_label || "people ahead";
  document.querySelector("#ticket-wait").textContent = entry.estimated_wait_minutes;
  document.querySelector("#ticket-barber").textContent = entry.barber_name || "First available barber";
  document.querySelector("#ticket-status").textContent = entry.availability_message || entry.status;
  document.querySelector("#notify").classList.toggle("hidden", completed || cancelled);
  document.querySelector("#leave-queue").classList.toggle("hidden", completed || cancelled);
  document.querySelector("#rating-form").classList.toggle("hidden", !completed);

  if (!completed && !cancelled && entry.status === "waiting") {
    startLiveWaitCountdown(entry);
  }
}

async function refreshTicket() {
  if (!activeToken) {
    hideOtherShopTicketBanner();
    return;
  }
  try {
    const entry = await api(`/api/my-queue/${activeToken}`);
    showTicket(entry);
  } catch {
    localStorage.removeItem("trimtimeQueueToken");
    activeToken = null;
    hideOtherShopTicketBanner();
  }
}

async function restoreActiveQueue() {
  let entry = null;
  try {
    entry = await api("/api/customer-auth/active-queue");
  } catch {
    entry = null;
  }
  if (!entry) {
    if (activeToken) await refreshTicket();
    else hideOtherShopTicketBanner();
    return;
  }
  activeToken = entry.public_token;
  localStorage.setItem("trimtimeQueueToken", activeToken);

  if (entry.shop_id === shopId) {
    hideOtherShopTicketBanner();
    showTicket(entry);
    const appointmentPanel = document.querySelector("#appointment-panel");
    const isApptOpen = appointmentPanel && !appointmentPanel.classList.contains("hidden");
    if (!isApptOpen) {
      ticketPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } else {
    ticketPanel.classList.add("hidden");
    if (shopId) {
      showOtherShopTicketBanner(entry);
    } else {
      hideOtherShopTicketBanner();
    }
  }
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
  event.preventDefault();
  const error = document.querySelector("#form-error");
  error.textContent = "";
  const serviceVal = document.querySelector("#service").value;
  if (!serviceVal) {
    error.textContent = "Selecting a service is mandatory to join the live queue and calculate wait time.";
    return;
  }
  try {
    const barber = document.querySelector("#barber").value;
    const entry = await api(`/api/shops/${shopId}/queue`, {
      method: "POST",
      body: JSON.stringify({
        customer_name: document.querySelector("#customer-name").value.trim(),
        phone: document.querySelector("#phone").value.trim() || null,
        service_id: Number(serviceVal),
        barber_id: barber ? Number(barber) : null,
        source: "online"
      })
    });
    activeToken = entry.public_token;
    localStorage.setItem("trimtimeQueueToken", activeToken);
    joinPanel.classList.add("hidden");
    showTicket(entry);
    await loadShop();
    ticketPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (message) {
    error.textContent = message.message;
    showCustomerNotice(message.message);
    if (message.message && (message.message.includes("active ticket") || message.message.includes("already have an active"))) {
      joinPanel.classList.add("hidden");
      await loadShop();
      if (activeToken) await refreshTicket();
      ticketPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
});

let appointmentTarget = "self";
const targetSelfBtn = document.querySelector("#target-self-btn");
const targetOtherBtn = document.querySelector("#target-other-btn");
const otherFields = document.querySelector("#appointment-other-fields");
if (targetSelfBtn && targetOtherBtn) {
  targetSelfBtn.addEventListener("click", () => {
    appointmentTarget = "self";
    targetSelfBtn.classList.add("active");
    targetOtherBtn.classList.remove("active");
    if (otherFields) otherFields.classList.add("hidden");
  });
  targetOtherBtn.addEventListener("click", () => {
    appointmentTarget = "other";
    targetOtherBtn.classList.add("active");
    targetSelfBtn.classList.remove("active");
    if (otherFields) otherFields.classList.remove("hidden");
  });
}

document.querySelector("#book-appointment").addEventListener("click", async () => {
  const result = document.querySelector("#appointment-result");
  result.innerHTML = "";
  try {
    const time = document.querySelector("#appointment-slot").value;
    if (!time) throw new Error("Please select an available appointment time slot.");
    const barber = document.querySelector("#appointment-barber").value;
    const serviceIds = selectedAppointmentServiceIds();
    if (!serviceIds.length) throw new Error("Please select at least one service.");

    let custName = "";
    let custPhone = null;
    let custAge = null;
    const isOther = appointmentTarget === "other";

    if (isOther) {
      const otherNameEl = document.querySelector("#appointment-other-name");
      const otherAgeEl = document.querySelector("#appointment-other-age");
      const otherPhoneEl = document.querySelector("#appointment-other-phone");
      if (!otherNameEl || otherNameEl.value.trim().length < 2) {
        throw new Error("Please enter the full name of the person for this booking.");
      }
      if (!otherAgeEl || !otherAgeEl.value || Number(otherAgeEl.value) < 1) {
        throw new Error("Please enter a valid age for the person.");
      }
      custName = otherNameEl.value.trim();
      custAge = Number(otherAgeEl.value);
      custPhone = otherPhoneEl && otherPhoneEl.value.trim() ? otherPhoneEl.value.trim() : (document.querySelector("#phone").value.trim() || null);
    } else {
      custName = document.querySelector("#customer-name").value.trim() || "Customer";
      custPhone = document.querySelector("#phone").value.trim() || null;
    }

    const payload = {
      customer_name: custName,
      phone: custPhone,
      age: custAge,
      book_for_other: isOther,
      service_ids: serviceIds,
      barber_id: barber ? Number(barber) : null,
      scheduled_at: time
    };

    const appointment = await api(`/api/shops/${shopId}/appointments`, {
      method: "POST",
      body: JSON.stringify(payload)
    });

    activeAppointmentToken = appointment.public_token;
    localStorage.setItem("trimtimeAppointmentToken", activeAppointmentToken);
    showAppointment(appointment);
    document.querySelector("#appointment-panel").classList.add("hidden");

    result.innerHTML = `
      <div class="appointment-success-box">
        <strong>✓ Appointment confirmed!</strong>
        <p>Booking token: <b>${appointment.token}</b> for ${formatAppDateTime(appointment.scheduled_at)}.</p>
      </div>
    `;
    await loadAppointmentSlots();
  } catch (reason) {
    console.error("Appointment booking error:", reason);
    const msg = reason.message || "Failed to book appointment.";
    if (msg.toLowerCase().includes("already have an active appointment")) {
      result.innerHTML = `
        <div class="appointment-conflict-card">
          <span class="conflict-icon">⚠️</span>
          <div class="conflict-body">
            <strong>Active appointment already exists</strong>
            <p>${escapeHtml(msg)}</p>
            <div class="conflict-buttons">
              <button type="button" id="conflict-change-slot-btn" class="secondary small">Pick another time slot</button>
              <button type="button" id="conflict-view-ticket-btn" class="primary small">View existing booking</button>
            </div>
          </div>
        </div>
      `;
      const changeBtn = document.querySelector("#conflict-change-slot-btn");
      if (changeBtn) {
        changeBtn.addEventListener("click", () => {
          const clearBtn = document.querySelector("#clear-selected-slot");
          if (clearBtn) clearBtn.click();
          result.innerHTML = "";
        });
      }
      const viewBtn = document.querySelector("#conflict-view-ticket-btn");
      if (viewBtn) {
        viewBtn.addEventListener("click", async () => {
          await restoreActiveAppointment();
          result.innerHTML = "";
        });
      }
    } else {
      result.innerHTML = `<p class="error">${escapeHtml(msg)}</p>`;
    }
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("Appointment notice", { body: msg });
    }
  }
});

function showAppointment(appointment) {
  activeAppointmentDetails = appointment;
  const panel = document.querySelector("#appointment-ticket-panel");
  if (!shopId || appointment.shop_id !== shopId) {
    if (panel) panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  document.querySelector("#appointment-ticket-token").textContent = appointment.token;
  document.querySelector("#appointment-ticket-status").textContent = appointment.status.replace("_", " ");
  document.querySelector("#appointment-ticket-details").textContent = `${appointment.service_name} · ${formatAppDateTime(appointment.scheduled_at)} · ${appointment.barber_name || "Any available barber"}`;
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
  localStorage.removeItem("trimtimeQueueToken");
  activeToken = null;
  hideOtherShopTicketBanner();
  ticketPanel.classList.add("hidden");
  await loadShop();
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

async function updateLiveQueueStats() {
  if (!shopId) return;
  try {
    const data = await api(`/api/shops/${shopId}`);
    currentShop = { ...currentShop, ...data };
    const waitingEl = document.querySelector("#waiting-count");
    if (waitingEl) waitingEl.textContent = currentShop.waiting_count;
    const waitTimeEl = document.querySelector("#wait-time");
    if (waitTimeEl) waitTimeEl.textContent = currentShop.estimated_wait_minutes;
    const prejoinEl = document.querySelector("#prejoin-wait");
    if (prejoinEl) prejoinEl.textContent = currentShop.estimated_wait_minutes;
    const submit = document.querySelector("#join-form button[type=submit]");
    if (submit) {
      submit.disabled = currentShop.queue_paused;
      submit.firstChild.textContent = currentShop.queue_paused ? "Queue temporarily paused " : "Join live queue ";
    }
  } catch (err) {
    console.warn("Failed to update queue stats:", err);
  }
}

function connectRealtime() {
  if (socket && connectedSocketShopId === shopId && socket.readyState === WebSocket.OPEN) {
    return;
  }
  if (socket) {
    try { socket.close(); } catch {}
  }
  connectedSocketShopId = shopId;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws/shops/${shopId}`);
  socket.onmessage = () => {
    updateLiveQueueStats().catch(console.error);
    refreshTicket();
    refreshAppointment();
  };
  socket.onclose = () => {
    if (connectedSocketShopId === shopId) {
      connectedSocketShopId = null;
    }
  };
}

restoreCustomerSession().catch(console.error);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
