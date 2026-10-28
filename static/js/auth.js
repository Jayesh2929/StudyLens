// StudyLens login / register: client-side validation (the server validates again).
(function () {
  var EMAIL = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$/;
  var form = document.querySelector(".auth-form");
  if (!form) return;
  var isRegister = form.id === "registerForm";
  var $ = function (id) { return document.getElementById(id); };

  function setError(input, msg) {
    var f = input.closest(".field");
    f.classList.toggle("has-error", !!msg);
    f.classList.toggle("is-valid", !msg && input.value !== "");
    f.querySelector(".field-err").textContent = msg || "";
    if (msg) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid");
    return !msg;
  }

  var checks = {
    name: function (v) {
      v = v.replace(/\s+/g, " ").trim();
      if (!v) return "Please enter your name.";
      if (v.length < 2) return "Name must be at least 2 characters.";
      if (v.length > 60) return "Name must be 60 characters or fewer.";
      if (!/^[A-Za-z][A-Za-z .'\-]*$/.test(v)) return "Name can only contain letters, spaces, . ' and -.";
    },
    email: function (v) {
      v = v.trim();
      if (!v) return "Please enter your email.";
      if (v.length > 254 || !EMAIL.test(v)) return "Enter a valid email address.";
    },
    password: function (v) {
      if (!v) return "Please enter your password.";
      if (!isRegister) return v.length > 128 ? "Password is too long." : "";
      var miss = rules(v).filter(function (r) { return !r.ok; }).map(function (r) { return r.text; });
      if (v.length > 72) miss.push("no more than 72 characters");
      if (/\s/.test(v)) miss.push("no spaces");
      if (miss.length) return "Password needs " + miss.join(", ") + ".";
    },
    confirm: function (v) {
      if (!v) return "Please confirm your password.";
      if (v !== $("password").value) return "Passwords do not match.";
    }
  };

  function rules(v) {
    return [
      { key: "len", ok: v.length >= 8, text: "at least 8 characters" },
      { key: "lower", ok: /[a-z]/.test(v), text: "a lowercase letter" },
      { key: "upper", ok: /[A-Z]/.test(v), text: "an uppercase letter" },
      { key: "num", ok: /\d/.test(v), text: "a number" },
      { key: "sym", ok: /[^A-Za-z0-9]/.test(v), text: "a special character" }
    ];
  }

  function updateMeter() {
    var bar = $("meterBar"); if (!bar) return;
    var v = $("password").value, r = rules(v), score = r.filter(function (x) { return x.ok; }).length;
    if (v.length >= 12 && score === 5) score = 6;
    r.forEach(function (x) { var li = document.querySelector('[data-rule="' + x.key + '"]'); if (li) li.classList.toggle("ok", x.ok); });
    bar.style.width = (v ? Math.max(score, 1) / 6 * 100 : 0) + "%";
    bar.style.background = score <= 2 ? "#dc2626" : score <= 4 ? "#f59e0b" : "#16a34a";
  }

  var fields = Object.keys(checks).filter(function (k) { return $(k); });
  fields.forEach(function (k) {
    var input = $(k), touched = !!input.closest(".has-error");
    input.addEventListener("blur", function () { touched = true; setError(input, checks[k](input.value)); });
    input.addEventListener("input", function () {
      if (k === "password") { updateMeter(); if ($("confirm") && $("confirm").value) setError($("confirm"), checks.confirm($("confirm").value)); }
      if (touched) setError(input, checks[k](input.value));
      else input.closest(".field").classList.remove("has-error");
    });
  });
  updateMeter();

  // Show / hide password
  document.querySelectorAll(".toggle-pw").forEach(function (b) {
    b.addEventListener("click", function () {
      var i = $(b.dataset.target), show = i.type === "password";
      i.type = show ? "text" : "password";
      b.setAttribute("aria-pressed", show); b.setAttribute("aria-label", show ? "Hide password" : "Show password");
      var c = $("confirm"); if (c && b.dataset.target === "password") c.type = i.type;
    });
  });

  // Caps Lock warning
  var caps = $("capsWarn");
  if (caps) document.querySelectorAll("input[type=password]").forEach(function (i) {
    i.addEventListener("keydown", function (e) { if (e.getModifierState) caps.hidden = !e.getModifierState("CapsLock"); });
    i.addEventListener("blur", function () { caps.hidden = true; });
  });

  // Submit: validate everything, focus the first problem, block double submits
  form.addEventListener("submit", function (e) {
    var first = null;
    fields.forEach(function (k) {
      var msg = checks[k]($(k).value);
      if (msg && !first) first = $(k);
      setError($(k), msg);
    });
    if (first) { e.preventDefault(); first.focus(); return; }
    var btn = $("submitBtn"); btn.classList.add("loading"); btn.disabled = true;
    var email = $("email"); email.value = email.value.trim();
  });

  // Focus the first field with a server error, else the first field
  var bad = form.querySelector(".has-error input");
  (bad || (document.activeElement === document.body ? $(fields[0]) : null) || {focus: function(){}}).focus();
  window.addEventListener("pageshow", function (e) { if (e.persisted) { var b = $("submitBtn"); b.classList.remove("loading"); b.disabled = false; } });
})();
