fetch("/api/platform/banner").then((response) => response.json()).then((branding) => {
  document.querySelectorAll(".brand").forEach((element) => {
    element.textContent = branding.software_name || "TrimTime";
    element.setAttribute("aria-label", branding.software_name || "TrimTime");
  });
  document.querySelectorAll("[data-software-name]").forEach((element) => { element.textContent = branding.software_name || "TrimTime"; });
}).catch(() => {});
