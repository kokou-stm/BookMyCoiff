// Bouton « Afficher / Masquer » sur chaque champ mot de passe
(function () {
  document.querySelectorAll('input[type="password"]').forEach(function (input) {
    const wrap = document.createElement("div");
    wrap.className = "pw-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pw-toggle";
    btn.textContent = "Afficher";
    btn.setAttribute("aria-label", "Afficher le mot de passe");
    btn.addEventListener("click", function () {
      const hidden = input.type === "password";
      input.type = hidden ? "text" : "password";
      btn.textContent = hidden ? "Masquer" : "Afficher";
      btn.setAttribute("aria-label", (hidden ? "Masquer" : "Afficher") + " le mot de passe");
      input.focus();
    });
    wrap.appendChild(btn);
  });
})();
