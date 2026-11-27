{% load static %}// Matchvia service worker (screens 1.3). Pages always come from the network; only when the
// network fails is the cached offline page shown. Nothing personal is ever cached.
"use strict";

const CACHE = "matchvia-offline-v1";
const OFFLINE_URL = "{% url 'offline' %}";
const ASSETS = [OFFLINE_URL, "{% static 'css/app.css' %}"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE_URL)));
});
