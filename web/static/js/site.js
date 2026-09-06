/* Site-wide header behaviour: scroll state and the mobile drawer.
   Loaded on every page. No dependencies. */

(function () {
  "use strict";

  var nav = document.querySelector("[data-nav]");
  var burger = document.querySelector("[data-burger]");
  var drawer = document.querySelector("[data-drawer]");
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------- scroll state
     Condenses the header once you leave the top, and gets it out of the way
     when scrolling down. It always comes straight back on an upward scroll,
     so the nav is never more than a flick away. */
  if (nav) {
    var lastY = window.scrollY;
    var ticking = false;

    function onScroll() {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () {
        var y = window.scrollY;
        nav.classList.toggle("is-scrolled", y > 16);
        // Never hide while the drawer is open, or near the top.
        var open = document.body.classList.contains("drawer-open");
        if (!open && y > 260 && y > lastY + 4) {
          nav.classList.add("is-hidden");
        } else if (y < lastY - 4 || y <= 260) {
          nav.classList.remove("is-hidden");
        }
        lastY = y;
        ticking = false;
      });
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ---------------------------------------------------- drawer */
  if (burger && drawer) {
    var panel = drawer.querySelector(".drawer-panel");
    var lastFocused = null;

    function focusables() {
      return Array.prototype.slice.call(
        panel.querySelectorAll('a[href], button:not([disabled])')
      ).filter(function (el) { return el.offsetParent !== null; });
    }

    function open() {
      lastFocused = document.activeElement;
      drawer.hidden = false;
      // Force a frame so the transition runs from the closed state.
      void drawer.offsetWidth;
      document.body.classList.add("drawer-open");
      drawer.classList.add("is-open");
      burger.setAttribute("aria-expanded", "true");
      burger.setAttribute("aria-label", "Close menu");
      var first = focusables()[0];
      if (first) first.focus();
    }

    function close() {
      document.body.classList.remove("drawer-open");
      drawer.classList.remove("is-open");
      burger.setAttribute("aria-expanded", "false");
      burger.setAttribute("aria-label", "Open menu");
      var done = function () { drawer.hidden = true; };
      if (reduced) done();
      else setTimeout(done, 260);
      if (lastFocused && lastFocused.focus) lastFocused.focus();
    }

    burger.addEventListener("click", function () {
      if (document.body.classList.contains("drawer-open")) close();
      else open();
    });

    Array.prototype.forEach.call(
      drawer.querySelectorAll("[data-drawer-close]"),
      function (el) { el.addEventListener("click", close); }
    );

    // Navigating away should not leave the drawer open behind the new page.
    Array.prototype.forEach.call(
      drawer.querySelectorAll("a[href]"),
      function (a) { a.addEventListener("click", close); }
    );

    document.addEventListener("keydown", function (e) {
      if (!document.body.classList.contains("drawer-open")) return;
      if (e.key === "Escape") { close(); return; }
      if (e.key !== "Tab") return;
      // Keep focus inside the panel while it is modal.
      var items = focusables();
      if (!items.length) return;
      var first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    });

    // Rotating to a wide viewport hides the drawer in CSS; clear the lock too.
    window.matchMedia("(min-width: 881px)").addEventListener("change", function (e) {
      if (e.matches && document.body.classList.contains("drawer-open")) close();
    });
  }

  /* ---------------------------------------------------- reveal on scroll
     Opt-in via [data-reveal]. Cheap, and skipped entirely under
     prefers-reduced-motion. */
  var reveals = document.querySelectorAll("[data-reveal]");
  if (reveals.length) {
    if (reduced || !("IntersectionObserver" in window)) {
      Array.prototype.forEach.call(reveals, function (el) { el.classList.add("is-in"); });
    } else {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-in");
          io.unobserve(entry.target);
        });
      }, { rootMargin: "0px 0px -10% 0px", threshold: 0.08 });
      Array.prototype.forEach.call(reveals, function (el) { io.observe(el); });
    }
  }
})();
