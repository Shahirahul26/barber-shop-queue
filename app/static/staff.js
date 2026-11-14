const error = document.querySelector("#staff-error"), success = document.querySelector("#staff-success");
let errorTimer = null;
new MutationObserver(() => {
  clearTimeout(errorTimer);
  if (error.textContent.trim()) errorTimer = setTimeout(() => { error.textContent = ""; }, 4000);
}).observe(error, { childList: true, characterData: true, subtree: true });
let accessToken = sessionStorage.getItem("trimtimeStaffToken");
const staffDeviceId = localStorage.getItem("trimtimeStaffDeviceId") || crypto.randomUUID();
localStorage.setItem("trimtimeStaffDeviceId", staffDeviceId);
let shopId = Number(sessionStorage.getItem("trimtimeShopId")) || 1;
let staffRole = sessionStorage.getItem("trimtimeStaffRole") || "owner";
let staffBarberId = Number(sessionStorage.getItem("trimtimeBarberId")) || null;
let shop = null, socket = null, analytics = null, requiresMpinSetup = false;
const localToday = new Date().toLocaleDateString("en-CA");
function dateInputDisplay(value) { const [year, month, day] = value.split("-"); return `${day}/${month}/${year}`; }
function dateInputIso(value) {
  if (!value) throw new Error("Please select a date.");
  const trimmed = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
    const parsed = new Date(`${trimmed}T00:00:00`);
    if (!Number.isNaN(parsed.getTime())) return trimmed;
  }
  const match = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(trimmed);
  if (match) {
    const [, d, m, year] = match;
    const day = d.padStart(2, "0");
    const month = m.padStart(2, "0");
    const iso = `${year}-${month}-${day}`;
    const parsed = new Date(`${iso}T00:00:00`);
    if (!Number.isNaN(parsed.getTime()) && parsed.getFullYear() === Number(year) && parsed.getMonth() + 1 === Number(month) && parsed.getDate() === Number(day)) return iso;
  }
  throw new Error("Enter a valid calendar date in DD/MM/YYYY format.");
}
document.querySelector("#analytics-start-date").value = localToday;
document.querySelector("#analytics-end-date").value = localToday;
["#analytics-start-date", "#analytics-end-date"].forEach((selector) => {
  const input = document.querySelector(selector);
  if (input) {
    input.addEventListener("click", () => {
      if (typeof input.showPicker === "function") {
        try { input.showPicker(); } catch (_) {}
      }
    });
  }
});

function consolidateManagementSection(sectionId, childIds) {
  const section = document.querySelector(sectionId), container = document.createElement("div"); container.className = "panel management-section";
  childIds.forEach((id) => { const child = document.querySelector(id); child.classList.remove("panel"); container.appendChild(child); });
  section.appendChild(container);
}
consolidateManagementSection("#tab-services", ["#service-form", "#service-list"]);
consolidateManagementSection("#tab-team", ["#barber-form", "#barber-list", "#staff-form", "#staff-list"]);
document.querySelector("#barber-form button[type=submit]").insertAdjacentHTML("beforebegin", `<label>Email (optional)<input id="barber-email" type="email" /></label><label>Phone (optional)<input id="barber-phone" inputmode="tel" /></label><label>Career started (DD/MM/YYYY)<div class="career-date-input-wrap"><input id="barber-career-start" type="text" placeholder="DD/MM/YYYY" maxlength="10" inputmode="numeric" autocomplete="off" /><button type="button" id="barber-career-calendar-btn" class="calendar-btn" title="Choose date from calendar" aria-label="Choose date from calendar">📅</button><input id="barber-career-picker" type="date" max="${localToday}" class="sr-only-picker" tabindex="-1" aria-hidden="true" /></div></label><label>Specialities (comma separated)<input id="barber-specialities" placeholder="Fades, beard styling" /></label>`);
const barberCareerInput = document.querySelector("#barber-career-start");
const barberCareerPicker = document.querySelector("#barber-career-picker");
const barberCalendarBtn = document.querySelector("#barber-career-calendar-btn");
if (barberCareerInput && barberCareerPicker) {
  barberCareerPicker.max = localToday;
  barberCareerInput.addEventListener("input", (e) => {
    let val = barberCareerInput.value.replace(/[^\d/]/g, "");
    if (e.inputType !== "deleteContentBackward") {
      if (/^\d{2}$/.test(val)) val = val + "/";
      else if (/^\d{2}\/\d{2}$/.test(val)) val = val + "/";
    }
    barberCareerInput.value = val;
    try {
      const iso = dateInputIso(val);
      if (iso) barberCareerPicker.value = iso;
    } catch (_) {}
  });
  if (barberCalendarBtn) {
    barberCalendarBtn.addEventListener("click", () => {
      try {
        if (barberCareerInput.value) {
          try { barberCareerPicker.value = dateInputIso(barberCareerInput.value); } catch (_) {}
        }
        if (typeof barberCareerPicker.showPicker === "function") {
          barberCareerPicker.showPicker();
        } else {
          barberCareerPicker.focus();
        }
      } catch (_) {}
    });
  }
  barberCareerPicker.addEventListener("change", () => {
    if (barberCareerPicker.value) {
      barberCareerInput.value = formatAppDate(barberCareerPicker.value);
    }
  });
}
document.querySelector("#barber-list").insertAdjacentHTML("afterend", `<section class="team-profile-tools"><form id="invite-barber-form" class="compact-form"><h2>Invite existing barber</h2><p class="muted">Search by permanent barber number. The barber must approve before transfer.</p><label>Barber number<input id="invite-barber-number" placeholder="BRB-K7M4P2" required /></label><button type="button" id="preview-barber">Preview</button><button type="submit" class="secondary">Send invitation</button><p id="invite-barber-preview" class="muted"></p></form><section id="barber-profile-panel" class="hidden"><div class="section-heading"><div><p class="eyebrow">PERMANENT BARBER PROFILE</p><h2 id="barber-profile-heading">Barber profile</h2></div><button type="button" id="close-barber-profile" class="ghost">Close</button></div><div id="barber-profile-summary"></div><form id="barber-services-form"><h3>Shop services</h3><div id="barber-profile-services" class="barber-services-checklist"></div><button>Save services</button></form><form id="barber-availability-form"><div><h3>Weekly availability</h3><p class="muted">Toggle availability day-wise and customize working hours. Defaults to shop hours.</p></div><div class="availability-quick-actions"><button type="button" id="avail-all-on">All days available</button><button type="button" id="avail-weekdays">Mon – Fri only</button><button type="button" id="avail-reset-shop">Reset all to shop hours</button></div><div id="barber-availability-rows" class="availability-schedule"></div><button type="submit">Save schedule</button></form><form id="barber-leave-form"><h3>Leave or calendar exception</h3><label>Type<select id="barber-exception-type"><option value="leave">Leave</option><option value="unavailable">Unavailable</option><option value="emergency">Emergency</option><option value="extra_hours">Extra working hours</option></select></label><label>Starts<input id="barber-exception-start" type="datetime-local" required /></label><label>Ends<input id="barber-exception-end" type="datetime-local" required /></label><label>Reason<input id="barber-exception-reason" /></label><button>Add calendar exception</button></form><div id="barber-membership-history"></div></section></section>`);
let activeBarberProfileId = null, activeBarberProfile = null;
function consolidateWholeSection(sectionId) {
  const section = document.querySelector(sectionId), container = document.createElement("div");
  container.className = "panel management-section";
  Array.from(section.children).forEach((child) => { child.classList.remove("panel"); container.appendChild(child); });
  section.appendChild(container);
}
consolidateWholeSection("#tab-analytics");
consolidateWholeSection("#tab-settings");
document.querySelector("#tab-settings .management-section").insertAdjacentHTML("afterbegin", '<section id="barber-invitations-panel" class="hidden"><h2>Shop invitations</h2><p class="muted">Only you can approve moving your permanent barber profile to another shop.</p><div id="barber-invitations-list"></div></section>');
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
function formatReportDate(value) { return formatAppDate(value); }

function setupGeoHelper({
  latInputId,
  lngInputId,
  addressInputId,
  statusId,
  pasteInputId,
  applyPasteBtnId,
  detectBtnId,
  fromAddressBtnId,
  openGmapsBtnId,
  toggleMapBtnId,
  mapContainerId,
  mapCloseBtnId,
  mapViewId
}) {
  const latInput = document.querySelector(latInputId);
  const lngInput = document.querySelector(lngInputId);
  const addressInput = document.querySelector(addressInputId);
  const statusEl = document.querySelector(statusId);
  const pasteInput = document.querySelector(pasteInputId);
  const applyPasteBtn = document.querySelector(applyPasteBtnId);
  const detectBtn = document.querySelector(detectBtnId);
  const fromAddressBtn = document.querySelector(fromAddressBtnId);
  const openGmapsBtn = document.querySelector(openGmapsBtnId);
  const toggleMapBtn = document.querySelector(toggleMapBtnId);
  const mapContainer = document.querySelector(mapContainerId);
  const mapCloseBtn = document.querySelector(mapCloseBtnId);

  if (!latInput || !lngInput) return;
  let mapInstance = null, marker = null;

  function setCoordinates(lat, lng, sourceLabel) {
    latInput.value = Number(lat.toFixed(6));
    lngInput.value = Number(lng.toFixed(6));
    if (statusEl) {
      statusEl.className = "geo-status-msg success";
      statusEl.textContent = `✓ ${sourceLabel}: ${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    }
    if (mapInstance && marker) {
      marker.setLatLng([lat, lng]);
      mapInstance.setView([lat, lng], 16);
    }
  }

  function parseCoordinatesOrUrl(input) {
    if (!input) return null;
    const str = input.trim();
    const directMatch = /^(-?\d{1,2}(?:\.\d+)?)[,\s]+(-?\d{1,3}(?:\.\d+)?)$/.exec(str);
    if (directMatch) {
      const lat = parseFloat(directMatch[1]), lng = parseFloat(directMatch[2]);
      if (lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) return { latitude: lat, longitude: lng };
    }
    const atMatch = /@(-?\d{1,2}(?:\.\d+)?),(-?\d{1,3}(?:\.\d+)?)/.exec(str);
    if (atMatch) {
      const lat = parseFloat(atMatch[1]), lng = parseFloat(atMatch[2]);
      if (lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) return { latitude: lat, longitude: lng };
    }
    const queryMatch = /[?&](?:q|query|ll|destination)=(-?\d{1,2}(?:\.\d+)?)[,\s]+(-?\d{1,3}(?:\.\d+)?)/.exec(str);
    if (queryMatch) {
      const lat = parseFloat(queryMatch[1]), lng = parseFloat(queryMatch[2]);
      if (lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) return { latitude: lat, longitude: lng };
    }
    const genericMatch = /(-?\d{1,2}\.\d{3,})[,\s]+(-?\d{1,3}\.\d{3,})/.exec(str);
    if (genericMatch) {
      const lat = parseFloat(genericMatch[1]), lng = parseFloat(genericMatch[2]);
      if (lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) return { latitude: lat, longitude: lng };
    }
    return null;
  }

  if (detectBtn) {
    detectBtn.addEventListener("click", () => {
      if (!navigator.geolocation) {
        if (statusEl) {
          statusEl.className = "geo-status-msg error";
          statusEl.textContent = "Browser geolocation is not supported on this device. Try locating from address.";
        }
        return;
      }
      if (statusEl) {
        statusEl.className = "geo-status-msg";
        statusEl.textContent = "Detecting GPS location…";
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => setCoordinates(pos.coords.latitude, pos.coords.longitude, "Current GPS location captured"),
        (err) => {
          if (statusEl) {
            statusEl.className = "geo-status-msg error";
            statusEl.textContent = `Location unavailable (${err.message}). Try finding from address or opening Google Maps.`;
          }
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      );
    });
  }

  if (fromAddressBtn && addressInput) {
    fromAddressBtn.addEventListener("click", async () => {
      const address = addressInput.value.trim();
      if (!address || address.length < 3) {
        if (statusEl) {
          statusEl.className = "geo-status-msg error";
          statusEl.textContent = "Please enter a shop address first.";
        }
        return;
      }
      if (statusEl) {
        statusEl.className = "geo-status-msg";
        statusEl.textContent = "Searching coordinates for address…";
      }
      try {
        const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(address)}&limit=1`, { headers: { "Accept-Language": "en" } });
        const list = await res.json();
        if (!list || !list.length) throw new Error("Could not find coordinates for this address. Try typing city/pincode or use current location.");
        setCoordinates(parseFloat(list[0].lat), parseFloat(list[0].lon), "Coordinates found for address");
      } catch (e) {
        if (statusEl) {
          statusEl.className = "geo-status-msg error";
          statusEl.textContent = e.message || "Failed to locate address. Try opening Google Maps.";
        }
      }
    });
  }

  if (openGmapsBtn) {
    openGmapsBtn.addEventListener("click", () => {
      const address = addressInput ? addressInput.value.trim() : "";
      const url = address
        ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`
        : (latInput.value && lngInput.value)
          ? `https://www.google.com/maps/search/?api=1&query=${latInput.value},${lngInput.value}`
          : "https://www.google.com/maps";
      window.open(url, "_blank");
      if (statusEl) {
        statusEl.className = "geo-status-msg";
        statusEl.textContent = "Google Maps opened. Locate your shop, copy its link or coordinates, and paste below.";
      }
    });
  }

  function applyPaste() {
    if (!pasteInput) return;
    const parsed = parseCoordinatesOrUrl(pasteInput.value);
    if (parsed) {
      setCoordinates(parsed.latitude, parsed.longitude, "Google Maps coordinates applied");
      pasteInput.value = "";
    } else {
      if (statusEl) {
        statusEl.className = "geo-status-msg error";
        statusEl.textContent = "Could not parse coordinates. Example: 19.0760, 72.8777 or paste full Google Maps URL.";
      }
    }
  }
  if (applyPasteBtn) applyPasteBtn.addEventListener("click", applyPaste);
  if (pasteInput) {
    pasteInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        applyPaste();
      }
    });
  }

  if (toggleMapBtn && mapContainer) {
    toggleMapBtn.addEventListener("click", () => {
      mapContainer.classList.toggle("hidden");
      if (mapContainer.classList.contains("hidden")) return;
      if (typeof window.L === "undefined") {
        if (statusEl) {
          statusEl.className = "geo-status-msg error";
          statusEl.textContent = "Interactive map tile service is loading or unavailable. You can use 'Detect location' or 'Open Google Maps'.";
        }
        return;
      }
      const currentLat = parseFloat(latInput.value) || 20.5937;
      const currentLng = parseFloat(lngInput.value) || 78.9629;
      const hasCoords = Boolean(latInput.value && lngInput.value);

      if (!mapInstance) {
        mapInstance = window.L.map(mapViewId).setView([currentLat, currentLng], hasCoords ? 15 : 5);
        window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          attribution: "&copy; OpenStreetMap"
        }).addTo(mapInstance);
        marker = window.L.marker([currentLat, currentLng], { draggable: true }).addTo(mapInstance);
        const onPinChange = (pos) => setCoordinates(pos.lat, pos.lng, "Map pin placed");
        marker.on("dragend", () => onPinChange(marker.getLatLng()));
        mapInstance.on("click", (e) => {
          marker.setLatLng(e.latlng);
          onPinChange(e.latlng);
        });
      } else {
        if (hasCoords) {
          marker.setLatLng([currentLat, currentLng]);
          mapInstance.setView([currentLat, currentLng], 15);
        }
      }
      setTimeout(() => mapInstance.invalidateSize(), 200);
    });
  }
  if (mapCloseBtn && mapContainer) {
    mapCloseBtn.addEventListener("click", () => mapContainer.classList.add("hidden"));
  }
}

function acceptSession(session, identifier = "") {
  requiresMpinSetup = Boolean(session.requires_mpin_setup);
  accessToken = session.access_token; shopId = session.shop_id; staffRole = session.role; staffBarberId = session.barber_id;
  sessionStorage.setItem("trimtimeStaffToken", accessToken); sessionStorage.setItem("trimtimeShopId", shopId); sessionStorage.setItem("trimtimeStaffRole", staffRole); sessionStorage.setItem("trimtimeBarberId", staffBarberId || ""); sessionStorage.setItem("trimtimeLoginIdentifier", identifier);
  if (session.requires_mpin_setup && !session.must_change_password) { document.querySelector("#login-panel").classList.add("hidden"); document.querySelector("#staff-mpin-setup-panel").classList.remove("hidden"); return; }
  showBoard();
  if (session.must_change_password) { document.querySelector('[data-tab="settings"]').click(); document.querySelector("#password-notice").textContent = "Your administrator issued a temporary password. Change it now before continuing."; error.textContent = "Please change your temporary password."; }
}

async function handleGoogleCredential(googleResponse) {
  error.textContent = "";
  try { const response = await fetch("/api/auth/google", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credential: googleResponse.credential, device_id: staffDeviceId, device_name: navigator.userAgent.slice(0, 160) }) }); const session = await response.json(); if (!response.ok) throw new Error(formatApiError(session.detail)); acceptSession(session); }
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
    const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier, email: identifier, password: document.querySelector("#password").value, device_id: staffDeviceId, device_name: navigator.userAgent.slice(0, 160) }) });
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(formatApiError(body.detail)); }
    acceptSession(await response.json(), identifier);
  } catch (reason) { error.textContent = reason.message; }
  finally { button.disabled = false; button.textContent = "Sign in"; }
});

document.querySelector("#show-registration").addEventListener("click", () => {
  document.querySelector("#login-panel").classList.add("hidden");
  document.querySelector("#registration-panel").classList.remove("hidden");
  document.querySelector("#tab-staff-register")?.classList.add("active");
  document.querySelector("#tab-staff-signin")?.classList.remove("active");
});
document.querySelector("#back-to-login").addEventListener("click", () => {
  document.querySelector("#registration-panel").classList.add("hidden");
  document.querySelector("#login-panel").classList.remove("hidden");
  document.querySelector("#tab-staff-signin")?.classList.add("active");
  document.querySelector("#tab-staff-register")?.classList.remove("active");
});
document.querySelector("#tab-staff-signin")?.addEventListener("click", () => {
  document.querySelector("#registration-panel").classList.add("hidden");
  document.querySelector("#login-panel").classList.remove("hidden");
  document.querySelector("#tab-staff-signin")?.classList.add("active");
  document.querySelector("#tab-staff-register")?.classList.remove("active");
});
document.querySelector("#tab-staff-register")?.addEventListener("click", () => {
  document.querySelector("#login-panel").classList.add("hidden");
  document.querySelector("#registration-panel").classList.remove("hidden");
  document.querySelector("#tab-staff-register")?.classList.add("active");
  document.querySelector("#tab-staff-signin")?.classList.remove("active");
});
if (!accessToken && new URLSearchParams(location.search).get("auth") === "signup") document.querySelector("#show-registration").click();
document.querySelector("#show-forgot-password").addEventListener("click", () => { document.querySelector("#login-panel").classList.add("hidden"); document.querySelector("#forgot-password-panel").classList.remove("hidden"); });
document.querySelectorAll(".back-to-login").forEach((button) => button.addEventListener("click", () => { document.querySelector("#forgot-password-panel").classList.add("hidden"); document.querySelector("#staff-mpin-login-panel").classList.add("hidden"); document.querySelector("#login-panel").classList.remove("hidden"); }));
document.querySelector("#show-mpin-login").addEventListener("click", () => { document.querySelector("#staff-mpin-identifier").value = document.querySelector("#email").value; document.querySelector("#login-panel").classList.add("hidden"); document.querySelector("#staff-mpin-login-panel").classList.remove("hidden"); });
document.querySelector("#staff-forgot-mpin").addEventListener("click", () => { document.querySelector("#staff-mpin-login-panel").classList.add("hidden"); document.querySelector("#forgot-password-panel").classList.remove("hidden"); document.querySelector("#forgot-identifier").value = document.querySelector("#staff-mpin-identifier").value; });
document.querySelector("#staff-mpin-login-form").addEventListener("submit", async (event) => { event.preventDefault(); error.textContent = ""; const identifier = document.querySelector("#staff-mpin-identifier").value.trim(); try { const response = await fetch("/api/auth/login-mpin", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier, mpin: document.querySelector("#staff-login-mpin").value, device_id: staffDeviceId, device_name: navigator.userAgent.slice(0, 160) }) }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(formatApiError(body.detail)); document.querySelector("#staff-mpin-login-panel").classList.add("hidden"); acceptSession(body, identifier); } catch (reason) { error.textContent = reason.message; } });
document.querySelector("#staff-mpin-setup-form").addEventListener("submit", async (event) => { event.preventDefault(); error.textContent = ""; const mpin = document.querySelector("#staff-new-mpin").value, confirm = document.querySelector("#staff-confirm-mpin").value; try { const response = await request("/api/auth/set-mpin", { method: "POST", body: JSON.stringify({ mpin, confirm_mpin: confirm, device_id: staffDeviceId, device_name: navigator.userAgent.slice(0, 160) }) }); document.querySelector("#staff-mpin-setup-panel").classList.add("hidden"); message(response.message); showBoard(); } catch (reason) { error.textContent = reason.message; } });

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
    document.querySelector("#registration-panel").classList.add("hidden"); message("Shop created successfully"); acceptSession(body, document.querySelector("#register-email").value.trim().toLowerCase());
  } catch (reason) { error.textContent = reason.message; }
  finally { button.disabled = false; button.textContent = "Create shop and sign in"; }
});

function resetDashboardTabs() {
  document.querySelectorAll(".tab-section").forEach((section) => {
    section.classList.toggle("hidden", section.id !== "tab-queue");
  });
  document.querySelectorAll(".dashboard-nav [data-tab]").forEach((item) => {
    item.classList.toggle("active", item.dataset.tab === "queue");
  });
  const accountNav = document.querySelector("#account-management-nav");
  if (accountNav) {
    accountNav.classList.add("hidden");
    accountNav.querySelectorAll("[data-tab]").forEach((item) => item.classList.remove("active"));
  }
  document.querySelector("#barber-profile-panel")?.classList.add("hidden");
  document.querySelector("#barber-invitations-panel")?.classList.add("hidden");
  activeBarberProfileId = null;
  activeBarberProfile = null;
}

function logout() {
  sessionStorage.clear();
  accessToken = null;
  resetDashboardTabs();
  document.querySelector("#login-panel").classList.remove("hidden");
  document.querySelector("#dashboard").classList.add("hidden");
  if (socket) socket.close();
}

async function showBoard() {
  document.querySelector("#login-panel").classList.add("hidden");
  document.querySelector("#registration-panel").classList.add("hidden");
  document.querySelector("#staff-banner")?.classList.add("hidden");
  document.querySelector("#staff-auth-tabs-wrap")?.classList.add("hidden");
  document.querySelector("#dashboard").classList.remove("hidden");
  resetDashboardTabs();
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
  if (staffRole === "barber") await loadBarberInvitations();
  renderRangeAnalytics(analytics);
  try { renderStaff(await request(`/api/shops/${shopId}/staff`)); } catch (_) {}
}

async function loadBarberInvitations() { const panel = document.querySelector("#barber-invitations-panel"), list = document.querySelector("#barber-invitations-list"); panel.classList.remove("hidden"); const items = await request("/api/my-barber/invitations"); list.innerHTML = items.length ? items.map((item) => `<article class="mini-card"><strong>${escapeHtml(item.shop_name)}</strong><span>${item.status}</span>${item.message ? `<p>${escapeHtml(item.message)}</p>` : ""}${item.status === "pending" ? `<div class="actions"><button data-invite-action="approve" data-invite-id="${item.id}">Approve</button><button data-invite-action="reject" data-invite-id="${item.id}" class="ghost">Reject</button></div>` : ""}</article>`).join("") : '<p class="muted">No shop invitations.</p>'; list.querySelectorAll("[data-invite-action]").forEach((button) => button.onclick = async () => { try { await request(`/api/barber-invitations/${button.dataset.inviteId}/action`, {method:"POST",body:JSON.stringify({action:button.dataset.inviteAction})}); message(`Invitation ${button.dataset.inviteAction}d`); await loadBarberInvitations(); } catch (reason) { error.textContent = reason.message; } }); }

function renderAppointments(items) {
  const list = document.querySelector("#appointment-list");
  if (!items.length) { list.innerHTML = '<div class="panel empty">No appointments booked.</div>'; return; }
  list.innerHTML = items.map((item) => { const terminal = ["completed", "cancelled", "no_show"].includes(item.status); const actions = terminal ? "" : item.status === "queued" ? `<button data-appointment="${item.id}" data-appointment-status="cancelled" class="ghost">Cancel appointment</button>` : `<button data-appointment="${item.id}" data-appointment-status="completed">Complete</button><button data-appointment="${item.id}" data-appointment-status="cancelled" class="ghost">Cancel appointment</button>`; return `<article class="queue-item appointment-item"><div class="token">${escapeHtml(item.token)}</div><div class="customer"><strong>${escapeHtml(item.customer_name)}</strong><span>${escapeHtml(item.service_name)} · ${formatAppDateTime(item.scheduled_at)}</span></div><div class="position">${item.status === "queued" ? "PRIORITY · Live queue" : item.status}</div><div class="actions">${actions}</div></article>`; }).join("");
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
  document.querySelector("#staff-queue-service").innerHTML = (shop.services && shop.services.length) ? shop.services.map((item) => `<option value="${item.id}">${escapeHtml(item.name)} · ${item.duration_minutes} min</option>`).join("") : '<option value="">No services available (add a service first)</option>';
  const queueBarbers = staffRole === "barber" ? shop.barbers.filter((item) => item.id === staffBarberId) : shop.barbers;
  const queueBarberSelect = document.querySelector("#staff-queue-barber");
  queueBarberSelect.innerHTML = `${staffRole === "barber" ? "" : '<option value="">Any available barber</option>'}${queueBarbers.map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("")}`;
  queueBarberSelect.disabled = staffRole === "barber";
}

function fillShopForm() {
  document.querySelector("#shop-profile-name").value = shop.name; document.querySelector("#shop-phone").value = shop.phone || "";
  document.querySelector("#shop-gst").value = shop.gst_number || ""; document.querySelector("#shop-profile-address").value = shop.address;
  const latEl = document.querySelector("#shop-profile-latitude");
  if (latEl) latEl.value = (shop.latitude !== null && shop.latitude !== undefined) ? shop.latitude : "";
  const lngEl = document.querySelector("#shop-profile-longitude");
  if (lngEl) lngEl.value = (shop.longitude !== null && shop.longitude !== undefined) ? shop.longitude : "";
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
  const list = document.querySelector("#service-list");
  if (!shop.services || !shop.services.length) {
    list.innerHTML = '<div class="panel empty">No services added yet. Add a service above.</div>';
    return;
  }
  list.innerHTML = shop.services.map((service) => `<article class="mini-card"><strong>${escapeHtml(service.name)}</strong><span>${service.duration_minutes} min · ₹${service.price_rupees}</span><div class="actions"><button data-service="${service.id}" class="secondary">Edit</button><button data-delete-service="${service.id}" class="ghost">Delete</button></div></article>`).join("");
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
  if (["queue", "appointments", "walkin"].includes(target)) {
    document.querySelector("#barber-profile-panel")?.classList.add("hidden");
  }
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
document.querySelector("#shop-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const latVal = document.querySelector("#shop-profile-latitude")?.value?.trim();
  const lngVal = document.querySelector("#shop-profile-longitude")?.value?.trim();
  await request(`/api/shops/${shopId}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: document.querySelector("#shop-profile-name").value,
      phone: document.querySelector("#shop-phone").value || null,
      gst_number: document.querySelector("#shop-gst").value.toUpperCase() || null,
      address: document.querySelector("#shop-profile-address").value,
      latitude: latVal ? Number(latVal) : null,
      longitude: lngVal ? Number(lngVal) : null,
      opens_at: document.querySelector("#opens-at").value,
      closes_at: document.querySelector("#closes-at").value,
      timezone: document.querySelector("#shop-timezone").value
    })
  });
  message("Shop details saved");
  await refreshAll();
});
document.querySelector("#shop-photo-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = ""; const file = document.querySelector("#shop-photo").files[0]; if (!file) return;
  const form = new FormData(); form.append("photo", file);
  try { const response = await fetch(`/api/shops/${shopId}/photo`, { method: "POST", headers: { Authorization: `Bearer ${accessToken}` }, body: form }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(formatApiError(body.detail)); event.target.reset(); message("Shop photo uploaded"); await refreshAll(); }
  catch (reason) { error.textContent = reason.message; }
});
document.querySelector("#service-template").addEventListener("change", (event) => { const option = event.target.selectedOptions[0]; if (!option.dataset.name) return; document.querySelector("#service-name").value = option.dataset.name; document.querySelector("#service-duration").value = option.dataset.duration; document.querySelector("#service-price").value = option.dataset.price; });
document.querySelector("#service-form").addEventListener("submit", async (event) => { event.preventDefault(); await request(`/api/shops/${shopId}/services`, { method: "POST", body: JSON.stringify({ name: document.querySelector("#service-name").value, duration_minutes: Number(document.querySelector("#service-duration").value), price_rupees: Number(document.querySelector("#service-price").value) }) }); event.target.reset(); message("Service added"); await refreshAll(); });
document.querySelector("#barber-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = "";
  const careerStartRaw = (document.querySelector("#barber-career-start")?.value || "").trim();
  let careerStart = null;
  if (careerStartRaw) {
    try {
      careerStart = dateInputIso(careerStartRaw);
    } catch (err) {
      error.textContent = "Please enter a valid career start date in DD/MM/YYYY format.";
      return;
    }
  }
  if (careerStart && careerStart > localToday) {
    error.textContent = "Career start date cannot be in the future.";
    return;
  }
  try {
    await request(`/api/shops/${shopId}/barbers`, {
      method: "POST",
      body: JSON.stringify({
        name: document.querySelector("#barber-name").value,
        email: document.querySelector("#barber-email").value || null,
        phone: document.querySelector("#barber-phone").value || null,
        career_started_on: careerStart || null,
        specialities: document.querySelector("#barber-specialities").value.split(",").map((item) => item.trim()).filter(Boolean),
        service_ids: shop.services.map((item) => item.id)
      })
    });
    event.target.reset();
    if (barberCareerPicker) barberCareerPicker.max = localToday;
    message("Permanent barber profile created");
    await refreshAll();
  } catch (reason) {
    error.textContent = reason.message;
  }
});
document.querySelector("#staff-form").addEventListener("submit", async (event) => { event.preventDefault(); const role = document.querySelector("#staff-role").value; const barberId = document.querySelector("#staff-barber").value; try { await request(`/api/shops/${shopId}/staff`, { method: "POST", body: JSON.stringify({ name: document.querySelector("#staff-name").value, email: document.querySelector("#staff-email").value, phone: document.querySelector("#staff-phone").value.trim() || null, password: document.querySelector("#staff-password").value, role, barber_id: role === "barber" && barberId ? Number(barberId) : null }) }); event.target.reset(); message("Staff login created"); await refreshAll(); } catch (reason) { error.textContent = reason.message; } });
document.querySelector("#change-password-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = "";
  const currentPassword = document.querySelector("#current-password").value;
  const newPassword = document.querySelector("#new-password").value;
  if (newPassword !== document.querySelector("#confirm-password").value) { error.textContent = "New password and confirmation do not match."; return; }
  try { await request("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }); event.target.reset(); document.querySelector("#password-notice").textContent = "Your password is up to date."; error.textContent = ""; message("Password changed successfully"); if (requiresMpinSetup) { document.querySelector("#dashboard").classList.add("hidden"); document.querySelector("#staff-mpin-setup-panel").classList.remove("hidden"); } }
  catch (reason) { error.textContent = reason.message; }
});
document.querySelector("#settings-mpin-form").addEventListener("submit", async (event) => { event.preventDefault(); error.textContent = ""; const secret = document.querySelector("#settings-current-secret").value, mpin = document.querySelector("#settings-new-mpin").value, confirm = document.querySelector("#settings-confirm-mpin").value; const payload = { mpin, confirm_mpin: confirm, device_id: staffDeviceId, device_name: navigator.userAgent.slice(0, 160) }; if (/^[0-9]{6}$/.test(secret)) payload.current_mpin = secret; else payload.password = secret; try { const body = await request("/api/auth/set-mpin", { method: "POST", body: JSON.stringify(payload) }); event.target.reset(); message(body.message); } catch (reason) { error.textContent = reason.message; } });

function connectRealtime() { if (socket) socket.close(); const protocol = location.protocol === "https:" ? "wss" : "ws"; socket = new WebSocket(`${protocol}://${location.host}/ws/staff/${shopId}?token=${encodeURIComponent(accessToken)}`); socket.onmessage = refreshAll; socket.onclose = () => { if (accessToken) setTimeout(connectRealtime, 2000); }; }
if (new URLSearchParams(location.search).get("reset_token")) { document.querySelector("#login-panel").classList.add("hidden"); document.querySelector("#reset-password-panel").classList.remove("hidden"); }
else if (accessToken) showBoard();

// Permanent barber profiles, shop memberships, services and calendar controls.
function renderBarbers() {
  const list = document.querySelector("#barber-list");
  list.innerHTML = shop.barbers.map((barber) => { const counts = (analytics?.barbers || []).find((item) => item.barber_id === barber.id); return `<article class="mini-card barber-profile-card"><strong>${escapeHtml(barber.name)}</strong><span>${escapeHtml(barber.barber_number || "Profile pending")} · ${barber.experience_years || 0} years</span><small>★ ${barber.career_rating || 0} career (${barber.career_rating_count || 0}) · ★ ${barber.shop_rating || 0} here (${barber.shop_rating_count || 0})</small><span>${counts?.waiting || 0} waiting · ${counts?.serving || 0} serving · ${counts?.completed_services || 0} completed</span><div class="actions"><button data-view-barber="${barber.id}">Profile & calendar</button><button data-barber="${barber.id}" class="secondary">Rename</button><button data-delete-barber="${barber.id}" class="ghost">End membership</button></div></article>`; }).join("");
  list.querySelectorAll("[data-view-barber]").forEach((button) => button.addEventListener("click", () => openBarberProfile(Number(button.dataset.viewBarber))));
  list.querySelectorAll("[data-barber]").forEach((button) => button.addEventListener("click", () => renameBarber(Number(button.dataset.barber))));
  list.querySelectorAll("[data-delete-barber]").forEach((button) => button.addEventListener("click", () => deleteBarber(Number(button.dataset.deleteBarber))));
}
const WEEKDAYS = [
  { id: 0, name: "Monday" },
  { id: 1, name: "Tuesday" },
  { id: 2, name: "Wednesday" },
  { id: 3, name: "Thursday" },
  { id: 4, name: "Friday" },
  { id: 5, name: "Saturday" },
  { id: 6, name: "Sunday" }
];

function renderWeeklyAvailability(availabilityList = []) {
  const container = document.querySelector("#barber-availability-rows");
  const shopOpens = shop?.opens_at || "09:00";
  const shopCloses = shop?.closes_at || "20:00";

  container.innerHTML = WEEKDAYS.map((day) => {
    const existing = (availabilityList || []).find((item) => Number(item.weekday) === day.id);
    const isActive = existing ? Boolean(existing.is_active) : true;
    const startsAt = (existing && existing.starts_at) || shopOpens;
    const endsAt = (existing && existing.ends_at) || shopCloses;

    return `<div class="availability-day-card ${isActive ? "active" : "inactive"}" data-day-card="${day.id}">
      <div class="availability-day-header">
        <div class="availability-day-info">
          <span class="availability-day-name">${day.name}</span>
          <span class="day-status-pill ${isActive ? "active" : "inactive"}" data-status-pill="${day.id}">
            ${isActive ? "Available" : "Not available"}
          </span>
        </div>
        <label class="switch-toggle" title="Toggle ${day.name} availability">
          <input type="checkbox" class="day-active-toggle" data-day="${day.id}" ${isActive ? "checked" : ""} />
          <span class="switch-slider"></span>
        </label>
      </div>
      <div class="availability-time-slots ${isActive ? "" : "disabled"}" data-time-slots="${day.id}">
        <div class="time-field">
          <label for="day-start-${day.id}">From</label>
          <input id="day-start-${day.id}" type="time" data-day-start="${day.id}" value="${startsAt}" ${isActive ? "" : "disabled"} required />
        </div>
        <span class="time-separator">–</span>
        <div class="time-field">
          <label for="day-end-${day.id}">To</label>
          <input id="day-end-${day.id}" type="time" data-day-end="${day.id}" value="${endsAt}" ${isActive ? "" : "disabled"} required />
        </div>
        <button type="button" class="reset-hours-btn" data-reset-day="${day.id}" title="Reset to shop hours (${shopOpens} – ${shopCloses})">Shop hours</button>
      </div>
    </div>`;
  }).join("");

  container.querySelectorAll(".day-active-toggle").forEach((toggle) => {
    toggle.addEventListener("change", () => {
      const dayId = Number(toggle.dataset.day);
      const isChecked = toggle.checked;
      const card = container.querySelector(`[data-day-card="${dayId}"]`);
      const pill = container.querySelector(`[data-status-pill="${dayId}"]`);
      const slots = container.querySelector(`[data-time-slots="${dayId}"]`);
      const startInput = container.querySelector(`[data-day-start="${dayId}"]`);
      const endInput = container.querySelector(`[data-day-end="${dayId}"]`);

      if (card) {
        card.classList.toggle("active", isChecked);
        card.classList.toggle("inactive", !isChecked);
      }
      if (pill) {
        pill.textContent = isChecked ? "Available" : "Not available";
        pill.classList.toggle("active", isChecked);
        pill.classList.toggle("inactive", !isChecked);
      }
      if (slots) slots.classList.toggle("disabled", !isChecked);
      if (startInput) {
        startInput.disabled = !isChecked;
        if (isChecked && !startInput.value) startInput.value = shopOpens;
      }
      if (endInput) {
        endInput.disabled = !isChecked;
        if (isChecked && !endInput.value) endInput.value = shopCloses;
      }
    });
  });

  container.querySelectorAll(".reset-hours-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dayId = Number(btn.dataset.resetDay);
      const startInput = container.querySelector(`[data-day-start="${dayId}"]`);
      const endInput = container.querySelector(`[data-day-end="${dayId}"]`);
      if (startInput) startInput.value = shopOpens;
      if (endInput) endInput.value = shopCloses;
    });
  });
}

function setDayAvailability(dayId, active) {
  const container = document.querySelector("#barber-availability-rows");
  if (!container) return;
  const toggle = container.querySelector(`.day-active-toggle[data-day="${dayId}"]`);
  if (toggle && toggle.checked !== active) {
    toggle.checked = active;
    toggle.dispatchEvent(new Event("change"));
  }
}

const btnAllOn = document.querySelector("#avail-all-on");
if (btnAllOn) btnAllOn.onclick = () => WEEKDAYS.forEach((d) => setDayAvailability(d.id, true));
const btnWeekdays = document.querySelector("#avail-weekdays");
if (btnWeekdays) btnWeekdays.onclick = () => WEEKDAYS.forEach((d) => setDayAvailability(d.id, d.id < 5));
const btnResetShop = document.querySelector("#avail-reset-shop");
if (btnResetShop) btnResetShop.onclick = () => {
  const shopOpens = shop?.opens_at || "09:00", shopCloses = shop?.closes_at || "20:00";
  const container = document.querySelector("#barber-availability-rows");
  if (!container) return;
  WEEKDAYS.forEach((d) => {
    const s = container.querySelector(`[data-day-start="${d.id}"]`);
    const e = container.querySelector(`[data-day-end="${d.id}"]`);
    if (s) s.value = shopOpens;
    if (e) e.value = shopCloses;
  });
};

async function openBarberProfile(barberId) {
  activeBarberProfileId = barberId;
  activeBarberProfile = await request(`/api/barbers/${barberId}/profile`);
  document.querySelector("#barber-profile-heading").textContent = `${activeBarberProfile.full_name} · ${activeBarberProfile.barber_number || ""}`;
  document.querySelector("#barber-profile-summary").innerHTML = `<div class="profile-stat-grid"><span><b>★ ${activeBarberProfile.career_rating}</b>Career · ${activeBarberProfile.career_rating_count}</span><span><b>★ ${activeBarberProfile.shop_rating}</b>This shop · ${activeBarberProfile.shop_rating_count}</span><span><b>${activeBarberProfile.experience_years} years</b>Experience</span></div><p>${escapeHtml(activeBarberProfile.biography || "No biography added yet.")}</p><p>${(activeBarberProfile.specialities || []).map(escapeHtml).join(" · ")}</p>`;
  const selected = new Set(activeBarberProfile.services);
  document.querySelector("#barber-profile-services").innerHTML = shop.services.map((service) => `<label><span>${escapeHtml(service.name)}</span><input type="checkbox" value="${service.id}" ${selected.has(service.id) ? "checked" : ""} /></label>`).join("");
  renderWeeklyAvailability(activeBarberProfile.weekly_availability);
  document.querySelector("#barber-membership-history").innerHTML = `<h3>Membership history</h3>${activeBarberProfile.memberships.map((item) => `<p>${escapeHtml(item.shop_name)} · ${formatAppDate(item.joined_on)} to ${item.left_on ? formatAppDate(item.left_on) : "present"} · ${item.status}</p>`).join("")}`;
  const panel = document.querySelector("#barber-profile-panel");
  panel.classList.remove("hidden");
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}
document.querySelector("#close-barber-profile").onclick = () => document.querySelector("#barber-profile-panel").classList.add("hidden");
document.querySelector("#barber-services-form").onsubmit = async (event) => { event.preventDefault(); try { const service_ids = [...document.querySelectorAll("#barber-profile-services input:checked")].map((item) => Number(item.value)); await request(`/api/barbers/${activeBarberProfileId}/services`, {method:"PUT",body:JSON.stringify({service_ids})}); message("Barber services updated"); await openBarberProfile(activeBarberProfileId); } catch (reason) { error.textContent = reason.message; } };
document.querySelector("#barber-availability-form").onsubmit = async (event) => {
  event.preventDefault();
  error.textContent = "";
  try {
    const shopOpens = shop?.opens_at || "09:00";
    const shopCloses = shop?.closes_at || "20:00";
    const container = document.querySelector("#barber-availability-rows");
    const periods = WEEKDAYS.map((day) => {
      const toggle = container.querySelector(`.day-active-toggle[data-day="${day.id}"]`);
      const isActive = toggle ? toggle.checked : false;
      const startInput = container.querySelector(`[data-day-start="${day.id}"]`);
      const endInput = container.querySelector(`[data-day-end="${day.id}"]`);
      const startsAt = (startInput && startInput.value) || shopOpens;
      const endsAt = (endInput && endInput.value) || shopCloses;
      if (isActive && startsAt >= endsAt) {
        throw new Error(`End time must be after start time on ${day.name}.`);
      }
      return {
        weekday: day.id,
        starts_at: startsAt,
        ends_at: endsAt,
        is_active: isActive
      };
    });
    await request(`/api/barbers/${activeBarberProfileId}/availability`, {
      method: "PUT",
      body: JSON.stringify({ periods })
    });
    message("Weekly availability saved");
    await openBarberProfile(activeBarberProfileId);
  } catch (reason) {
    error.textContent = reason.message;
  }
};
document.querySelector("#barber-leave-form").onsubmit = async (event) => { event.preventDefault(); try { await request(`/api/barbers/${activeBarberProfileId}/exceptions`, {method:"POST",body:JSON.stringify({exception_type:document.querySelector("#barber-exception-type").value,starts_at:new Date(document.querySelector("#barber-exception-start").value).toISOString(),ends_at:new Date(document.querySelector("#barber-exception-end").value).toISOString(),reason:document.querySelector("#barber-exception-reason").value || null,approval_status:"approved"})}); event.target.reset(); message("Calendar exception added"); await openBarberProfile(activeBarberProfileId); } catch (reason) { error.textContent = reason.message; } };
document.querySelector("#preview-barber").onclick = async () => { try { const profile = await request(`/api/barber-profiles/search?barber_number=${encodeURIComponent(document.querySelector("#invite-barber-number").value.trim())}`); document.querySelector("#invite-barber-preview").textContent = `${profile.full_name} · ★ ${profile.career_rating} (${profile.career_rating_count}) · ${profile.experience_years} years`; } catch (reason) { error.textContent = reason.message; } };
document.querySelector("#invite-barber-form").onsubmit = async (event) => { event.preventDefault(); try { const body = await request(`/api/shops/${shopId}/barber-invitations`, {method:"POST",body:JSON.stringify({barber_number:document.querySelector("#invite-barber-number").value.trim()})}); message(`Invitation sent (${body.status})`); } catch (reason) { error.textContent = reason.message; } };

setupGeoHelper({
  latInputId: "#register-latitude",
  lngInputId: "#register-longitude",
  addressInputId: "#register-address",
  statusId: "#register-geo-status",
  pasteInputId: "#register-geo-paste",
  applyPasteBtnId: "#register-geo-apply-paste",
  detectBtnId: "#register-geo-detect",
  fromAddressBtnId: "#register-geo-from-address",
  openGmapsBtnId: "#register-open-gmaps",
  toggleMapBtnId: "#register-toggle-map",
  mapContainerId: "#register-map-container",
  mapCloseBtnId: "#register-map-close",
  mapViewId: "register-map-view"
});

setupGeoHelper({
  latInputId: "#shop-profile-latitude",
  lngInputId: "#shop-profile-longitude",
  addressInputId: "#shop-profile-address",
  statusId: "#shop-profile-geo-status",
  pasteInputId: "#shop-profile-geo-paste",
  applyPasteBtnId: "#shop-profile-geo-apply-paste",
  detectBtnId: "#shop-profile-geo-detect",
  fromAddressBtnId: "#shop-profile-geo-from-address",
  openGmapsBtnId: "#shop-profile-open-gmaps",
  toggleMapBtnId: "#shop-profile-toggle-map",
  mapContainerId: "#shop-profile-map-container",
  mapCloseBtnId: "#shop-profile-map-close",
  mapViewId: "shop-profile-map-view"
});
