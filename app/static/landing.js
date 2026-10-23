const accessModes = {
  customer: { description: "Find nearby shops, see the live wait, join a queue or book a time.", signInLabel: "Customer sign in", signInHref: "/customer?auth=signin", signUpLabel: "New customer? Sign up", signUpHref: "/customer?auth=signup" },
  staff: { description: "Sign in to manage your shop, or register a new barber shop and owner account.", signInLabel: "Shop or staff sign in", signInHref: "/staff?auth=signin", signUpLabel: "New shop? Register now", signUpHref: "/staff?auth=signup" },
};

document.querySelectorAll("[data-access]").forEach((button) => button.addEventListener("click", () => {
  const mode = button.dataset.access, config = accessModes[mode];
  document.querySelectorAll("[data-access]").forEach((item) => { const active = item === button; item.classList.toggle("active", active); item.setAttribute("aria-selected", String(active)); });
  document.querySelector("#access-description").textContent = config.description;
  const signIn = document.querySelector("#access-signin"), signUp = document.querySelector("#access-signup");
  signIn.href = config.signInHref; signIn.innerHTML = `${config.signInLabel} <span>→</span>`;
  signUp.href = config.signUpHref; signUp.textContent = config.signUpLabel;
}));

function safe(value) { const node = document.createElement("span"); node.textContent = value ?? ""; return node.innerHTML; }
let feedback = [], feedbackIndex = 0, feedbackTimer = null;

function renderFeedback() {
  const track = document.querySelector("#feedback-track"), dots = document.querySelector("#feedback-dots");
  if (!feedback.length) return;
  const item = feedback[feedbackIndex];
  track.innerHTML = `<article class="feedback-card"><div class="feedback-stars">${"★".repeat(item.stars)}${"☆".repeat(5 - item.stars)}</div><blockquote>“${safe(item.comment)}”</blockquote><p>Verified completed service · ${safe(item.shop_name)}</p></article>`;
  dots.innerHTML = feedback.map((_, index) => `<button type="button" aria-label="Show feedback ${index + 1}" class="${index === feedbackIndex ? "active" : ""}" data-feedback-index="${index}"></button>`).join("");
  dots.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => { feedbackIndex = Number(button.dataset.feedbackIndex); renderFeedback(); restartCarousel(); }));
}

function moveFeedback(direction) { if (!feedback.length) return; feedbackIndex = (feedbackIndex + direction + feedback.length) % feedback.length; renderFeedback(); }
function restartCarousel() { clearInterval(feedbackTimer); if (feedback.length > 1) feedbackTimer = setInterval(() => moveFeedback(1), 5500); }
document.querySelector("#feedback-prev").addEventListener("click", () => { moveFeedback(-1); restartCarousel(); });
document.querySelector("#feedback-next").addEventListener("click", () => { moveFeedback(1); restartCarousel(); });

fetch("/api/feedback").then((response) => response.json()).then((items) => { feedback = items; if (feedback.length) { renderFeedback(); restartCarousel(); } }).catch(() => {});
fetch("/api/platform/banner").then((response) => response.json()).then((brand) => { document.querySelectorAll(".brand-name").forEach((item) => item.textContent = brand.software_name); document.title = `${brand.software_name} · Skip the wait. Keep every chair moving.`; }).catch(() => {});

document.querySelector("#current-year").textContent = new Date().getFullYear();
const legacyShop = new URLSearchParams(location.search).get("shop"); if (legacyShop) location.replace(`/customer?shop=${encodeURIComponent(legacyShop)}`);
