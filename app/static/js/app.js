/* UPeU Internado 360 — shared UI behaviours (vanilla JS, no dependencies). */
(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  // ---- Sidebar toggle (desktop collapse + mobile drawer) ----
  function initSidebar() {
    var toggle = byId("sidebarToggle");
    var mobileToggle = byId("mobileMenuBtn");
    var backdrop = byId("backdrop");

    if (toggle) {
      toggle.addEventListener("click", function () {
        document.body.classList.toggle("sidebar-collapsed");
        try {
          localStorage.setItem(
            "sidebarCollapsed",
            document.body.classList.contains("sidebar-collapsed") ? "1" : "0"
          );
        } catch (e) {}
      });
    }
    if (mobileToggle) {
      mobileToggle.addEventListener("click", function () {
        document.body.classList.toggle("sidebar-open");
      });
    }
    if (backdrop) {
      backdrop.addEventListener("click", function () {
        document.body.classList.remove("sidebar-open");
      });
    }
    try {
      if (localStorage.getItem("sidebarCollapsed") === "1" && window.innerWidth > 820) {
        document.body.classList.add("sidebar-collapsed");
      }
    } catch (e) {}
  }

  // ---- Generic dropdown menus (notifications, user, ...) ----
  function initDropdowns() {
    var triggers = document.querySelectorAll("[data-dropdown]");
    triggers.forEach(function (t) {
      t.addEventListener("click", function (e) {
        e.stopPropagation();
        var menu = byId(t.getAttribute("data-dropdown"));
        if (!menu) return;
        document.querySelectorAll(".dropdown-menu.open").forEach(function (m) {
          if (m !== menu) m.classList.remove("open");
        });
        menu.classList.toggle("open");
      });
    });
    document.addEventListener("click", function () {
      document.querySelectorAll(".dropdown-menu.open").forEach(function (m) {
        m.classList.remove("open");
      });
    });
  }

  // ---- Notifications feed ----
  function initNotifications() {
    var list = byId("notifList");
    if (!list) return;
    fetch("/api/notifications")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var badge = byId("notifBadge");
        if (badge) {
          if (data.count > 0) { badge.textContent = data.count; badge.style.display = ""; }
          else { badge.style.display = "none"; }
        }
        if (!data.items || data.items.length === 0) {
          list.innerHTML = '<div class="notif-item"><div class="n-msg">Sin notificaciones.</div></div>';
          return;
        }
        list.innerHTML = data.items.map(function (i) {
          return '<div class="notif-item"><div class="n-title">' + esc(i.title) +
            '</div><div class="n-msg">' + esc(i.message) + "</div></div>";
        }).join("");
      })
      .catch(function () {
        list.innerHTML = '<div class="notif-item"><div class="n-msg">No se pudieron cargar.</div></div>';
      });
  }

  // ---- Login: password reveal + demo credential autofill ----
  function initLogin() {
    var toggle = byId("togglePass");
    var pass = byId("password");
    if (toggle && pass) {
      toggle.addEventListener("click", function () {
        var show = pass.type === "password";
        pass.type = show ? "text" : "password";
        toggle.innerHTML = show ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
      });
    }
    document.querySelectorAll(".demo-cred").forEach(function (row) {
      row.addEventListener("click", function () {
        var email = row.getAttribute("data-email");
        var pw = row.getAttribute("data-password");
        var e = byId("email"); var p = byId("password");
        if (e) e.value = email;
        if (p) p.value = pw;
      });
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---- Tabs (detail pages) ----
  function initTabs() {
    var groups = document.querySelectorAll("[data-tabs]");
    groups.forEach(function (group) {
      var tabs = group.querySelectorAll(".tab");
      tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
          var target = tab.getAttribute("data-tab");
          tabs.forEach(function (t) { t.classList.remove("active"); });
          tab.classList.add("active");
          document.querySelectorAll("[data-panel]").forEach(function (p) {
            p.style.display = p.getAttribute("data-panel") === target ? "" : "none";
          });
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initSidebar();
    initDropdowns();
    initNotifications();
    initLogin();
    initTabs();
  });
})();
