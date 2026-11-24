/* Page d'accueil BookMyCoiff : filtres auto, géolocalisation, fiche salon en fenêtre. */
(function () {
  "use strict";

  const form = document.getElementById("search-form");
  const modal = document.getElementById("salon-modal");
  const modalBody = document.getElementById("modal-body");
  const currency = document.body.dataset.currency || "";

  // --- Petit utilitaire DOM (textContent partout : pas d'injection HTML) ---
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "style") el.style.cssText = value;
      else el.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  const hhmm = (t) => (t || "").slice(0, 5);
  const price = (value) =>
    Number(value).toLocaleString("fr-FR", { maximumFractionDigits: 0 }) + (currency ? " " + currency : "");
  const duration = (min) => (min >= 60 ? `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}` : `${min} min`);
  const initial = (name) => (name || "?").trim().charAt(0).toUpperCase();

  function stars(rating) {
    if (rating === null || rating === undefined) return h("span", { class: "tag-new" }, "Nouveau");
    const pct = (Number(rating) / 5) * 100;
    return h("span", { class: "rating" },
      h("span", { class: "stars", style: `--pct:${pct}%` }), Number(rating).toFixed(1));
  }


  // --- Panneau « Filtres » : on coche, puis « Appliquer » envoie le formulaire ---
  const filtersToggle = document.getElementById("filters-toggle");
  const filtersPanel = document.getElementById("filters-panel");
  const setPanel = (open) => {
    filtersPanel.hidden = !open;
    filtersToggle.setAttribute("aria-expanded", String(open));
    if (open) (filtersPanel.querySelector("input:checked") || filtersPanel.querySelector("input")).focus();
  };
  filtersToggle.addEventListener("click", () => setPanel(filtersPanel.hidden));
  document.addEventListener("click", (event) => {
    if (!filtersPanel.hidden && !filtersPanel.contains(event.target) && !filtersToggle.contains(event.target)) setPanel(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !filtersPanel.hidden) {
      setPanel(false);
      filtersToggle.focus();
    }
  });
  document.getElementById("filters-clear").addEventListener("click", () => {
    for (const input of filtersPanel.querySelectorAll("input")) {
      input.checked = input.type === "radio" && input.value === "";
    }
  });

  // Ne pas envoyer de paramètres vides dans l'URL
  form.addEventListener("submit", () => {
    for (const input of form.querySelectorAll("input")) {
      if ((input.type === "hidden" || input.type === "search" || input.type === "radio") && !input.value) input.disabled = true;
    }
  });

  window.addEventListener("pageshow", () => {
    for (const input of form.querySelectorAll("input:disabled")) input.disabled = false;
  });

  // --- Géolocalisation ---
  const locateBtn = document.getElementById("locate-btn");
  locateBtn.addEventListener("click", () => {
    // Déjà localisé : un second clic retire le filtre
    if (locateBtn.classList.contains("is-on")) {
      form.elements.lat.value = "";
      form.elements.lng.value = "";
      form.requestSubmit();
      return;
    }
    if (!navigator.geolocation) {
      alert("La géolocalisation n'est pas disponible sur ce navigateur.");
      return;
    }
    const label = locateBtn.querySelector("span");
    label.textContent = "Localisation…";
    locateBtn.disabled = true;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        form.elements.lat.value = pos.coords.latitude.toFixed(6);
        form.elements.lng.value = pos.coords.longitude.toFixed(6);
        form.requestSubmit();
      },
      () => {
        label.textContent = "Autour de moi";
        locateBtn.disabled = false;
        alert("Impossible d'obtenir votre position. Vérifiez l'autorisation de localisation.");
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 }
    );
  });

  // --- Carrousel horizontal des salons ---
  const rail = document.getElementById("salon-rail");
  if (rail) {
    const prev = document.querySelector('[data-rail="prev"]');
    const next = document.querySelector('[data-rail="next"]');
    const nav = prev.parentElement;
    const step = () => {
      const card = rail.querySelector(".card");
      const gap = parseFloat(getComputedStyle(rail).columnGap) || 0;
      const cardWidth = card ? card.offsetWidth + gap : 300;
      // avance d'autant de cartes entières que la largeur visible en contient
      return Math.max(cardWidth, Math.floor(rail.clientWidth / cardWidth) * cardWidth);
    };
    const update = () => {
      const max = rail.scrollWidth - rail.clientWidth;
      nav.classList.toggle("hidden", max <= 1);
      prev.disabled = rail.scrollLeft <= 1;
      next.disabled = rail.scrollLeft >= max - 1;
    };
    prev.addEventListener("click", () => rail.scrollBy({ left: -step() }));
    next.addEventListener("click", () => rail.scrollBy({ left: step() }));
    rail.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  // --- Fiche salon ---
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-salon]");
    if (trigger) openSalon(trigger.dataset.salon);
  });

  modal.querySelector(".modal-close").addEventListener("click", () => modal.close());
  modal.addEventListener("click", (event) => {
    if (event.target === modal) modal.close(); // clic sur le fond
  });
  modal.addEventListener("close", () => setSalonParam(null));

  function setSalonParam(slug) {
    const url = new URL(window.location.href);
    if (slug) url.searchParams.set("salon", slug);
    else url.searchParams.delete("salon");
    history.replaceState(null, "", url);
  }

  async function openSalon(slug) {
    modalBody.replaceChildren(h("p", { class: "modal-loading" }, "Chargement…"));
    if (!modal.open) modal.showModal();
    setSalonParam(slug);
    try {
      const response = await fetch(`/api/salons/${encodeURIComponent(slug)}/`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(response.status);
      const salon = await response.json();
      modalBody.replaceChildren(renderSalon(salon));
      modal.scrollTop = 0;
      loadAvailability(salon.professionals);
    } catch (err) {
      modalBody.replaceChildren(h("p", { class: "modal-error" }, "Impossible de charger ce salon. Réessayez plus tard."));
    }
  }

  function renderSalon(s) {
    const settingPhotos = s.photos.filter((p) => p.kind === "setting");
    // La couverture passe en premier dans la galerie (sans doublon si c'est déjà une photo « cadre »)
    if (s.cover_photo && !settingPhotos.some((p) => p.image === s.cover_photo)) {
      settingPhotos.unshift({ image: s.cover_photo, caption: s.name });
    }
    const workPhotos = s.photos.filter((p) => p.kind === "work");
    const today = (new Date().getDay() + 6) % 7; // lundi = 0, comme Django

    const gallery = settingPhotos.length
      ? h("div", { class: "gallery" }, settingPhotos.map((p) => h("img", { src: p.image, alt: p.caption || s.name, loading: "lazy" })))
      : h("div", { class: "gallery" }, h("div", { class: "gallery-empty", style: "width:100%" }, initial(s.name)));

    const phoneDigits = (s.whatsapp || "").replace(/\D/g, "");
    const head = h("div", { class: "m-section m-head" },
      h("h2", { id: "modal-title" }, s.name),
      h("div", { class: "m-head-meta" },
        stars(s.base_rating),
        h("span", null, `${s.address} · ${s.city}`),
        h("span", { class: s.is_accepting_bookings ? "status" : "status off" },
          s.is_accepting_bookings ? "Accepte les réservations" : "Fermé pour le moment"),
        s.offers_home_service && h("span", { class: "badge" }, "Services à domicile")
      ),
      s.description && h("p", { class: "m-desc" }, s.description),
      h("div", { class: "m-actions" },
        h("a", { class: "btn btn-primary", href: `tel:${s.phone}` }, "Appeler le salon"),
        phoneDigits && h("a", { class: "btn btn-light", href: `https://wa.me/${phoneDigits}`, target: "_blank", rel: "noopener" }, "WhatsApp"),
        h("a", {
          class: "btn btn-ghost", target: "_blank", rel: "noopener",
          href: `https://www.google.com/maps/search/?api=1&query=${s.latitude},${s.longitude}`,
        }, "Itinéraire")
      ),
      h("p", { class: "notice" },
        "La réservation en ligne arrive bientôt. En attendant, consultez les disponibilités ci-dessous et contactez le salon.")
    );

    const services = s.services.length > 0 && h("div", { class: "m-section" },
      h("h3", null, "Services et tarifs"),
      h("table", { class: "services" }, h("tbody", null, s.services.map((sv) =>
        h("tr", null,
          h("td", null,
            h("div", { class: "s-name" }, sv.name),
            h("div", { class: "s-desc" }, [sv.category_display, sv.available_at_home ? "à domicile possible" : null].filter(Boolean).join(" · ")),
            sv.description && h("div", { class: "s-desc" }, sv.description)
          ),
          h("td", { class: "s-time" }, duration(sv.duration_minutes)),
          h("td", { class: "s-price" }, price(sv.price))
        )
      )))
    );

    const pros = s.professionals.length > 0 && h("div", { class: "m-section" },
      h("h3", null, "Les coiffeurs · disponibilités du jour"),
      h("div", { class: "pros" }, s.professionals.map((p) =>
        h("div", { class: "pro" },
          h("div", { class: "avatar" }, p.photo ? h("img", { src: p.photo, alt: "" }) : initial(p.display_name)),
          h("div", null,
            h("div", { class: "pro-name" }, p.display_name),
            h("div", { class: "muted" }, p.years_of_experience
              ? `${p.years_of_experience} an${p.years_of_experience > 1 ? "s" : ""} d'expérience` : "Coiffeur"),
            h("div", { class: "slots", "data-pro": p.id }, h("span", { class: "slot none" }, "…"))
          )
        )
      ))
    );

    const equipment = s.equipment.length > 0 && h("div", { class: "m-section" },
      h("h3", null, "Équipements"),
      h("div", { class: "tags" }, s.equipment.map((e) => h("span", { class: "tag", title: e.description || null }, e.name)))
    );

    const works = workPhotos.length > 0 && h("div", { class: "m-section" },
      h("h3", null, "Réalisations"),
      h("div", { class: "works" }, workPhotos.map((p) => h("img", { src: p.image, alt: p.caption || "", loading: "lazy" })))
    );

    const days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
    const byDay = days.map((_, i) => s.opening_hours.filter((o) => o.weekday === i));
    const hours = s.opening_hours.length > 0 && h("div", { class: "m-section" },
      h("h3", null, "Horaires"),
      h("div", { class: "hours" }, days.flatMap((day, i) => {
        const cls = i === today ? "today" : null;
        const text = byDay[i].length ? byDay[i].map((o) => `${hhmm(o.start_time)}–${hhmm(o.end_time)}`).join(", ") : "Fermé";
        return [h("span", { class: cls }, day), h("span", { class: cls }, text)];
      }))
    );

    return h("div", null, gallery, head, services, pros, works, equipment, hours);
  }

  async function loadAvailability(professionals) {
    await Promise.all(professionals.map(async (p) => {
      const box = modalBody.querySelector(`[data-pro="${p.id}"]`);
      if (!box) return;
      try {
        const response = await fetch(`/api/professionals/${p.id}/availability/?days=1`);
        if (!response.ok) throw new Error(response.status);
        const data = await response.json();
        const ranges = data.days[0] ? data.days[0].ranges : [];
        box.replaceChildren(...(ranges.length
          ? ranges.map((r) => h("span", { class: "slot" }, `${r.start}–${r.end}`))
          : [h("span", { class: "slot none" }, "Indisponible aujourd'hui")]));
      } catch (err) {
        box.replaceChildren(h("span", { class: "slot none" }, "—"));
      }
    }));
  }

  // Lien partageable : /?salon=<slug> ouvre directement la fiche
  const initialSlug = new URLSearchParams(window.location.search).get("salon");
  if (initialSlug) openSalon(initialSlug);
})();
