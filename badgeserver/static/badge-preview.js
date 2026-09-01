/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev> */
/* Live preview for a composed badge: POST the current form values to the
   preview endpoint and swap the <img>. No-op when JS is disabled. */
(function () {
  "use strict";

  var form = document.getElementById("badge-form");
  if (!form) return;

  var img = document.getElementById("badge-preview");
  var wrap = document.getElementById("preview-wrap");
  var scaleOut = document.getElementById("logo-scale-out");
  var url = form.getAttribute("data-preview-url");
  var tokenEl = form.querySelector('input[name="csrf_token"]');
  var token = tokenEl ? tokenEl.value : "";

  var FIELDS = ["name", "art_shape", "art_bg", "art_accent", "art_logo_scale"];
  var lastUrl = null;
  var timer = null;
  var busy = false;
  var again = false;

  function mode() {
    var el = form.querySelector('input[name="art_mode"]:checked');
    return el ? el.value : "upload";
  }

  function buildData() {
    var fd = new FormData();
    FIELDS.forEach(function (name) {
      var el = form.elements[name];
      if (el) fd.append(name, el.value);
    });
    var slug = form.querySelector('input[name="slug"]');
    if (slug) fd.append("slug", slug.value);
    var logo = form.elements.logo;
    if (logo && logo.files && logo.files[0]) fd.append("logo", logo.files[0]);
    return fd;
  }

  function refresh() {
    if (mode() !== "compose" || !img) return;
    if (busy) { again = true; return; }
    busy = true;
    fetch(url, { method: "POST", headers: { "X-CSRFToken": token }, body: buildData() })
      .then(function (r) { return r.ok ? r.blob() : Promise.reject(r.status); })
      .then(function (blob) {
        var next = URL.createObjectURL(blob);
        img.src = next;
        if (lastUrl) URL.revokeObjectURL(lastUrl);
        lastUrl = next;
      })
      .catch(function () { /* keep the previous good preview */ })
      .finally(function () {
        busy = false;
        if (again) { again = false; refresh(); }
      });
  }

  function debounced() {
    clearTimeout(timer);
    timer = setTimeout(refresh, 250);
  }

  function toggle() {
    var composing = mode() === "compose";
    if (wrap) wrap.hidden = !composing;
    if (composing) refresh();
  }

  var scaleEl = form.elements.art_logo_scale;
  if (scaleEl && scaleOut) {
    scaleEl.addEventListener("input", function () {
      scaleOut.textContent = scaleEl.value + "%";
    });
  }
  FIELDS.forEach(function (name) {
    var el = form.elements[name];
    if (el) {
      el.addEventListener("input", debounced);
      el.addEventListener("change", debounced);
    }
  });
  if (form.elements.logo) form.elements.logo.addEventListener("change", debounced);
  form.querySelectorAll('input[name="art_mode"]').forEach(function (el) {
    el.addEventListener("change", toggle);
  });

  toggle();
})();
