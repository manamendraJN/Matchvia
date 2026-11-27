// Map pin for the venue location (V2, V25). Leaflet is vendored (static/vendor/README.md) and
// tiles come from OpenStreetMap, with attribution (architecture 10). The latitude and longitude
// inputs stay the source of truth: the pin writes to them, and typing in them moves the pin.
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const box = document.querySelector("[data-venue-map]");
  if (!box || !window.L) return;
  const lat = document.getElementById(box.dataset.lat);
  const lng = document.getElementById(box.dataset.lng);
  const status = document.getElementById(box.dataset.status);
  // Sri Lanka, roughly (the same limits the server checks).
  const bounds = L.latLngBounds([5.85, 79.5], [9.9, 81.95]);
  const colombo = [6.9271, 79.8612];

  const map = L.map(box, { maxBounds: bounds.pad(0.2) });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
    // The OSM tile policy refuses requests without a Referer, and the site's policy is
    // "same-origin" (none sent to other sites). For tiles only, send just our origin, never the
    // page path (it holds venue ids).
    referrerPolicy: "strict-origin-when-cross-origin",
  }).addTo(map);

  const current = () => {
    const a = parseFloat(lat.value);
    const b = parseFloat(lng.value);
    return Number.isFinite(a) && Number.isFinite(b) ? L.latLng(a, b) : null;
  };
  const start = current();
  map.setView(start || colombo, start ? 16 : 11);
  const pin = L.marker(start || colombo, { draggable: true, opacity: start ? 1 : 0.5 }).addTo(map);

  const place = (point) => {
    if (!bounds.contains(point)) {
      if (status) status.textContent = box.dataset.outside;
      return;
    }
    pin.setLatLng(point).setOpacity(1);
    lat.value = point.lat.toFixed(6);
    lng.value = point.lng.toFixed(6);
  };
  map.on("click", (event) => place(event.latlng));
  pin.on("dragend", () => place(pin.getLatLng()));

  // Typed numbers, or "Use my current location", move the pin.
  const follow = () => {
    const point = current();
    if (point) {
      pin.setLatLng(point).setOpacity(1);
      map.setView(point, Math.max(map.getZoom(), 16));
    }
  };
  lat.addEventListener("change", follow);
  lng.addEventListener("change", follow);
});
