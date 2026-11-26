// Small page behaviours live here (no inline JavaScript: CSP, architecture 7).
// Data for scripts is passed with Django's json_script, never by string-building in templates.
"use strict";

// "Use my current location" (V2): fills the latitude/longitude inputs named in data attributes.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-geolocate]");
  if (!button || !navigator.geolocation) return;
  event.preventDefault();
  const status = document.getElementById(button.dataset.status);
  const say = (text) => { if (status) status.textContent = text; };
  say(button.dataset.waiting);
  navigator.geolocation.getCurrentPosition(
    (position) => {
      document.getElementById(button.dataset.lat).value = position.coords.latitude.toFixed(6);
      document.getElementById(button.dataset.lng).value = position.coords.longitude.toFixed(6);
      say(button.dataset.done);
    },
    () => say(button.dataset.failed),
    { enableHighAccuracy: true, timeout: 15000 },
  );
});

// Buttons marked data-disable-on-submit are disabled once their form is sent, so a slow network
// can't cause a double booking attempt (screens 1.3). The server is still safe if it happens.
document.addEventListener("submit", (event) => {
  event.target.querySelectorAll("[data-disable-on-submit]").forEach((button) => {
    // Let the browser include the button in the submission first, then disable it.
    setTimeout(() => { button.disabled = true; }, 0);
  });
});
