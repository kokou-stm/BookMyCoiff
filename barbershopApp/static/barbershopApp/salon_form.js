// Inscription d'un salon : carte pour placer le salon + horaires.
(function () {
  "use strict";

  const latInput = document.getElementById("id_latitude");
  const lngInput = document.getElementById("id_longitude");
  const mapEl = document.getElementById("salon-map");
  const status = document.getElementById("map-status");
  const locateBtn = document.getElementById("map-locate");
  const LOME = [6.1375, 1.2123];

  function setStatus(text) { status.textContent = text; }

  // --- Carte (Leaflet + OpenStreetMap) ---
  let map = null, marker = null;

  function place(lat, lng, zoom) {
    latInput.value = lat.toFixed(6);
    lngInput.value = lng.toFixed(6);
    mapEl.closest(".map-block").classList.remove("has-error");
    setStatus("Salon placé. Déplacez le repère si besoin.");
    if (!map) return;
    if (marker) marker.setLatLng([lat, lng]);
    else {
      marker = L.marker([lat, lng], { draggable: true }).addTo(map);
      marker.on("dragend", function () {
        const p = marker.getLatLng();
        place(p.lat, p.lng);
      });
    }
    if (zoom) map.setView([lat, lng], zoom);
  }

  if (window.L) {
    const lat = parseFloat(mapEl.dataset.lat), lng = parseFloat(mapEl.dataset.lng);
    const hasPoint = !isNaN(lat) && !isNaN(lng);
    map = L.map(mapEl, { scrollWheelZoom: false }).setView(hasPoint ? [lat, lng] : LOME, hasPoint ? 17 : 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    map.on("click", function (e) { place(e.latlng.lat, e.latlng.lng); });
    if (hasPoint) place(lat, lng);
  } else {
    mapEl.hidden = true;
    setStatus("Carte indisponible : utilisez votre position depuis le salon.");
  }

  // --- Position actuelle ---
  locateBtn.addEventListener("click", function () {
    if (!navigator.geolocation) {
      setStatus("Votre navigateur ne permet pas la géolocalisation.");
      return;
    }
    setStatus("Recherche de votre position…");
    navigator.geolocation.getCurrentPosition(
      function (pos) { place(pos.coords.latitude, pos.coords.longitude, 17); },
      function () { setStatus("Position refusée ou indisponible. Cliquez sur la carte à la place."); },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  });

  // --- Horaires : grise les heures des jours fermés ---
  document.querySelectorAll(".hours-row").forEach(function (row) {
    const box = row.querySelector('input[type="checkbox"]');
    const times = row.querySelectorAll('input[type="time"]');
    function sync() {
      times.forEach(function (t) { t.disabled = !box.checked; });
      row.classList.toggle("is-closed", !box.checked);
    }
    box.addEventListener("change", sync);
    sync();
  });

  // --- Étapes : une section à la fois, Précédent / Suivant ---
  // Sans JavaScript, toutes les sections restent visibles et le formulaire marche quand même.
  const form = mapEl.closest("form");
  const steps = Array.from(form.querySelectorAll(".step"));
  const stepper = form.querySelector(".stepper");
  const prevBtn = form.querySelector("[data-prev]");
  const nextBtn = form.querySelector("[data-next]");
  const submitBtn = form.querySelector("[data-submit]");
  const counter = form.querySelector(".step-count");
  let current = 0;

  form.classList.add("is-wizard");
  stepper.hidden = false;
  counter.hidden = false;
  const dots = steps.map(function (step, i) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    const num = document.createElement("span");
    num.className = "stepper-num";
    num.textContent = String(i + 1);
    const label = document.createElement("span");
    label.className = "stepper-label";
    label.textContent = step.dataset.step;
    btn.append(num, label);
    btn.addEventListener("click", function () { goTo(i); });
    li.appendChild(btn);
    stepper.appendChild(li);
    return li;
  });

  function show(index) {
    current = index;
    steps.forEach(function (step, i) { step.classList.toggle("is-current", i === index); });
    dots.forEach(function (dot, i) {
      dot.classList.toggle("is-current", i === index);
      dot.classList.toggle("is-done", i < index);
      if (i === index) dot.querySelector("button").setAttribute("aria-current", "step");
      else dot.querySelector("button").removeAttribute("aria-current");
    });
    const last = index === steps.length - 1;
    prevBtn.hidden = index === 0;
    nextBtn.hidden = last;
    submitBtn.hidden = !last;
    counter.textContent = "Étape " + (index + 1) + " sur " + steps.length;
    // La carte est créée dans une section masquée : il faut lui redonner sa taille
    if (map && steps[index].contains(mapEl)) {
      map.invalidateSize();
      if (marker) map.panTo(marker.getLatLng());
    }
  }

  function stepIsValid(step) {
    const pw1 = step.querySelector('[name="account-password1"]');
    const pw2 = step.querySelector('[name="account-password2"]');
    if (pw1 && pw2) pw2.setCustomValidity(pw2.value && pw1.value !== pw2.value ? "Les deux mots de passe ne correspondent pas." : "");

    const fields = step.querySelectorAll("input, textarea, select");
    for (const field of fields) {
      if (!field.disabled && !field.checkValidity()) {
        field.reportValidity();
        return false;
      }
    }
    if (step.contains(mapEl) && !(latInput.value && lngInput.value)) {
      mapEl.closest(".map-block").classList.add("has-error");
      setStatus("Placez votre salon sur la carte avant de continuer.");
      mapEl.scrollIntoView({ behavior: "smooth", block: "center" });
      return false;
    }
    return true;
  }

  // On peut revenir en arrière librement ; pour avancer, chaque étape franchie doit être valide.
  function goTo(index) {
    if (index < 0 || index >= steps.length || index === current) return;
    for (let i = current; i < index; i++) {
      if (!stepIsValid(steps[i])) { if (i !== current) show(i); return; }
    }
    show(index);
    form.scrollIntoView({ behavior: "smooth", block: "start" });
    const first = steps[index].querySelector("input:not([type=hidden]):not([type=checkbox]), textarea");
    if (first) first.focus({ preventScroll: true });
  }

  prevBtn.addEventListener("click", function () { goTo(current - 1); });
  nextBtn.addEventListener("click", function () { goTo(current + 1); });

  // Entrée dans un champ = Suivant (et non envoi du formulaire avant la dernière étape)
  form.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.tagName === "INPUT" && current < steps.length - 1) {
      e.preventDefault();
      goTo(current + 1);
    }
  });
  // Flèches gauche / droite quand on n'est pas en train d'écrire dans un champ
  document.addEventListener("keydown", function (e) {
    const tag = document.activeElement && document.activeElement.tagName;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.altKey || e.ctrlKey || e.metaKey) return;
    if (mapEl.contains(document.activeElement)) return;  // les flèches déplacent la carte
    if (e.key === "ArrowRight") goTo(current + 1);
    if (e.key === "ArrowLeft") goTo(current - 1);
  });

  // Un seul envoi : l'envoi (photo comprise) peut prendre quelques secondes sur mobile, et un
  // 2e appui ferait abandonner la 1re réponse par le navigateur (« compte existe déjà »).
  const submitLabel = submitBtn.textContent;
  form.addEventListener("submit", function (e) {
    if (form.dataset.sending) { e.preventDefault(); return; }
    form.dataset.sending = "1";
    submitBtn.disabled = true;
    submitBtn.textContent = "Création en cours…";
  });
  // Retour arrière vers une page gardée en cache : le bouton doit redevenir utilisable
  window.addEventListener("pageshow", function () {
    delete form.dataset.sending;
    submitBtn.disabled = false;
    submitBtn.textContent = submitLabel;
  });

  // Après un envoi refusé par le serveur : ouvrir la première étape qui contient une erreur
  const firstError = steps.findIndex(function (step) { return step.querySelector(".error, .has-error, .form-errors"); });
  show(firstError === -1 ? 0 : firstError);
})();
