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
  document.querySelector("#admin-shop-list").innerHTML = shops.map((shop) => `<article class="panel admin-shop-card"><div><span class="eyebrow">${safe(shop.approval_status)}</span><h3>${safe(shop.name)}</h3><p>${safe(shop.address)}</p><small>Customer QR route: /customer?shop=${shop.id}</small></div><img src="/api/shops/${shop.id}/qr" alt="QR for ${safe(shop.name)}" /><div class="actions"><a class="button-link" href="/customer?shop=${shop.id}" target="_blank">Open</a><button data-id="${shop.id}" data-status="${shop.approval_status === "approved" ? "suspended" : "approved"}" class="secondary">${shop.approval_status === "approved" ? "Suspend" : "Approve"}</button></div><div id="admin-staff-${shop.id}" class="admin-staff-list"><small>Loading staff…</small></div></article>`).join("");
  document.querySelectorAll("[data-status]").forEach((button) => button.addEventListener("click", async () => { await adminRequest(`/api/admin/shops/${button.dataset.id}/approval`, { method: "PATCH", body: JSON.stringify({ approval_status: button.dataset.status }) }); await loadAdminShops(); }));
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

if (adminToken) showAdmin().catch((reason) => error.textContent = reason.message);
