let adminToken = sessionStorage.getItem("trimtimeAdminToken");
const error = document.querySelector("#admin-error"), success = document.querySelector("#admin-success");

function formatApiError(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const location = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(" → ") : "Input";
      return `${location || "Input"}: ${item.msg || "Invalid value"}`;
    }).join(" | ");
  }
  if (detail && typeof detail === "object") return detail.message || JSON.stringify(detail);
  return detail || "Request failed";
}

async function adminRequest(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${adminToken}`, ...(options.headers || {}) } });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(formatApiError(body.detail)); }
  return response.json();
}
function value(id) { return document.querySelector(id).value; }
function safe(text) { const node = document.createElement("span"); node.textContent = text ?? ""; return node.innerHTML; }

document.querySelector("#admin-login-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = "";
  try {
    const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: value("#admin-email"), password: value("#admin-password") }) });
    const session = await response.json(); if (!response.ok) throw new Error(formatApiError(session.detail));
    if (!session.is_platform_admin) throw new Error("This account is not a platform administrator");
    adminToken = session.access_token; sessionStorage.setItem("trimtimeAdminToken", adminToken); showAdmin();
  } catch (reason) { error.textContent = reason.message; }
});

async function showAdmin() {
  document.querySelector("#admin-login").classList.add("hidden"); document.querySelector("#admin-dashboard").classList.remove("hidden");
  const banner = await fetch("/api/platform/banner").then((response) => response.json());
  document.querySelector("#banner-admin-eyebrow").value = banner.eyebrow; document.querySelector("#banner-admin-title").value = banner.title; document.querySelector("#banner-admin-message").value = banner.message;
  document.querySelector("#software-name").value = banner.software_name;
  const imagePreview = document.querySelector("#admin-login-image-preview"); imagePreview.classList.toggle("hidden", !banner.login_image_url); if (banner.login_image_url) imagePreview.src = banner.login_image_url;
  await loadAdminShops();
}

document.querySelector("#banner-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = "";
  try { await adminRequest("/api/admin/banner", { method: "PUT", body: JSON.stringify({ software_name: value("#software-name").trim(), eyebrow: value("#banner-admin-eyebrow").trim(), title: value("#banner-admin-title").trim(), message: value("#banner-admin-message").trim() }) }); success.textContent = "Software branding and advertisement updated."; }
  catch (reason) { error.textContent = reason.message; }
});

document.querySelector("#login-image-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = ""; const file = document.querySelector("#admin-login-image").files[0]; if (!file) return;
  const form = new FormData(); form.append("image", file);
  try { const response = await fetch("/api/admin/login-image", { method: "POST", headers: { Authorization: `Bearer ${adminToken}` }, body: form }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(formatApiError(body.detail)); document.querySelector("#admin-login-image-preview").src = body.login_image_url; document.querySelector("#admin-login-image-preview").classList.remove("hidden"); event.target.reset(); success.textContent = "Staff sign-in image updated."; }
  catch (reason) { error.textContent = reason.message; }
});

async function loadAdminShops() {
  const shops = await adminRequest("/api/admin/shops");
  document.querySelector("#admin-shop-list").innerHTML = shops.map((shop) => `<article class="panel admin-shop-card"><div><span class="eyebrow">${safe(shop.approval_status)}</span><h3>${safe(shop.name)}</h3><p>${safe(shop.address)}</p><small>Customer QR route: /customer?shop=${shop.id}</small><div class="shop-admin-features" style="margin-top:10px;display:flex;align-items:center;gap:10px;"><strong style="font-size:0.85rem;">Book Appointment:</strong><button type="button" data-appointment-toggle="${shop.id}" data-enabled="${shop.appointments_enabled ? "true" : "false"}" class="${shop.appointments_enabled ? "secondary" : "ghost"}" style="padding:4px 10px;font-size:0.82rem;">${shop.appointments_enabled ? "✓ Enabled" : "✕ Disabled"}</button></div></div><img src="/api/shops/${shop.id}/qr" alt="QR for ${safe(shop.name)}" /><div class="actions"><a class="button-link" href="/customer?shop=${shop.id}" target="_blank">Open</a><button data-id="${shop.id}" data-status="${shop.approval_status === "approved" ? "suspended" : "approved"}" class="secondary">${shop.approval_status === "approved" ? "Suspend" : "Approve"}</button></div><div id="admin-staff-${shop.id}" class="admin-staff-list"><small>Loading staff…</small></div></article>`).join("");
  document.querySelectorAll("[data-status]").forEach((button) => button.addEventListener("click", async () => { await adminRequest(`/api/admin/shops/${button.dataset.id}/approval`, { method: "PATCH", body: JSON.stringify({ approval_status: button.dataset.status }) }); await loadAdminShops(); }));
  document.querySelectorAll("[data-appointment-toggle]").forEach((button) => button.addEventListener("click", async () => {
    const nextState = button.dataset.enabled !== "true";
    await adminRequest(`/api/admin/shops/${button.dataset.appointmentToggle}/appointments-feature`, {
      method: "PATCH",
      body: JSON.stringify({ appointments_enabled: nextState })
    });
    await loadAdminShops();
  }));
  await Promise.all(shops.map(async (shop) => renderAdminStaff(shop.id, await adminRequest(`/api/shops/${shop.id}/staff`))));
}

function renderAdminStaff(shopId, users) {
  const list = document.querySelector(`#admin-staff-${shopId}`);
  list.innerHTML = `<h4>Staff accounts</h4>${users.map((user) => `<div class="admin-staff-row"><span><strong>${safe(user.name)}</strong><small>${safe(user.email)} · ${safe(user.role)} · ${user.is_active ? "Active" : "Inactive"}${user.must_change_password ? " · Password change required" : ""}</small></span><div class="actions"><button type="button" data-admin-reset="${user.id}" class="secondary">Reset password</button><button type="button" data-admin-toggle="${user.id}" data-active="${!user.is_active}" class="ghost">${user.is_active ? "Deactivate" : "Activate"}</button></div></div>`).join("")}`;
  list.querySelectorAll("[data-admin-reset]").forEach((button) => button.addEventListener("click", () => adminResetPassword(Number(button.dataset.adminReset))));
  list.querySelectorAll("[data-admin-toggle]").forEach((button) => button.addEventListener("click", () => adminSetStatus(Number(button.dataset.adminToggle), button.dataset.active === "true")));
}

async function adminResetPassword(staffId) {
  const temporaryPassword = prompt("Enter a temporary password (minimum 8 characters)");
  if (temporaryPassword === null) return;
  if (temporaryPassword.length < 8) { error.textContent = "Temporary password must contain at least 8 characters."; return; }
  try { await adminRequest(`/api/staff/${staffId}/password`, { method: "PATCH", body: JSON.stringify({ temporary_password: temporaryPassword }) }); success.textContent = "Temporary password set. The staff member must change it after signing in."; await loadAdminShops(); }
  catch (reason) { error.textContent = reason.message; }
}

async function adminSetStatus(staffId, isActive) {
  try { await adminRequest(`/api/staff/${staffId}/status`, { method: "PATCH", body: JSON.stringify({ is_active: isActive }) }); success.textContent = isActive ? "Staff account activated." : "Staff account deactivated."; await loadAdminShops(); }
  catch (reason) { error.textContent = reason.message; }
}

document.querySelector("#new-shop-form").addEventListener("submit", async (event) => {
  event.preventDefault(); error.textContent = ""; success.textContent = "";
  const submitButton = event.submitter;
  try {
    submitButton.disabled = true; submitButton.textContent = "Creating…";
    const latitude = value("#new-shop-latitude").trim(), longitude = value("#new-shop-longitude").trim();
    const shop = await adminRequest("/api/admin/shops", { method: "POST", body: JSON.stringify({ name: value("#new-shop-name").trim(), phone: value("#new-shop-phone").trim() || null, gst_number: value("#new-shop-gst").trim().toUpperCase() || null, address: value("#new-shop-address").trim(), latitude: latitude ? Number(latitude) : null, longitude: longitude ? Number(longitude) : null, owner_name: value("#new-owner-name").trim(), owner_email: value("#new-owner-email").trim().toLowerCase(), owner_password: value("#new-owner-password") }) });
    event.target.reset(); success.textContent = `${shop.name} was created. Its unique QR code is shown below.`; await loadAdminShops();
  } catch (reason) {
    error.textContent = reason.message;
    error.scrollIntoView({ behavior: "smooth", block: "center" });
  } finally {
    submitButton.disabled = false; submitButton.textContent = "Create shop and unique QR";
  }
});

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
          statusEl.textContent = "Browser geolocation is not supported on this device.";
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
            statusEl.textContent = `Location unavailable (${err.message}).`;
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
          statusEl.textContent = "Please enter an address first.";
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
        if (!list || !list.length) throw new Error("Could not find coordinates for this address.");
        setCoordinates(parseFloat(list[0].lat), parseFloat(list[0].lon), "Coordinates found for address");
      } catch (e) {
        if (statusEl) {
          statusEl.className = "geo-status-msg error";
          statusEl.textContent = e.message || "Failed to locate address.";
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
        statusEl.textContent = "Google Maps opened. Locate shop, copy coordinates/link, and paste below.";
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
          statusEl.textContent = "Interactive map tile service is loading or unavailable.";
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

setupGeoHelper({
  latInputId: "#new-shop-latitude",
  lngInputId: "#new-shop-longitude",
  addressInputId: "#new-shop-address",
  statusId: "#admin-geo-status",
  pasteInputId: "#admin-geo-paste",
  applyPasteBtnId: "#admin-geo-apply-paste",
  detectBtnId: "#admin-geo-detect",
  fromAddressBtnId: "#admin-geo-from-address",
  openGmapsBtnId: "#admin-open-gmaps",
  toggleMapBtnId: "#admin-toggle-map",
  mapContainerId: "#admin-map-container",
  mapCloseBtnId: "#admin-map-close",
  mapViewId: "admin-map-view"
});

if (adminToken) showAdmin().catch((reason) => error.textContent = reason.message);
