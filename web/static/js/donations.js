/* Scroll engine for /donations.
   Reads the live totals injected by the server, drives each act's --p from
   scroll position, and runs the signature sass line. No dependencies. */

(function () {
  "use strict";

  var data = window.__RIKO__ || { raised: 0, goal: 600, percent: 0, count: 0 };
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var money = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });

  /* ------------------------------------------------------ signature move
     Riko's commentary is a function of the live funding percentage. Six
     bands; the copy changes as the fundraiser progresses without anyone
     editing the page. */
  // Riko's running commentary, keyed to the live percentage. Same bands as
  // web/characters.py so the two never disagree.
  var SASS = [
    { at: 0,   text: "Zero. Not one of you. I-I'm not disappointed or anything, dummy. I just assumed at least ONE person had taste." },
    { at: 1,   text: "One person. ONE. I wrote their name down somewhere nice. The rest of you are also written down, just somewhere else." },
    { at: 25,  text: "A quarter already? O-Oh. Huh. That's not completely pathetic. Don't let it go to your heads." },
    { at: 50,  text: "Halfway?! W-Well obviously I knew you'd get here. I never doubted it. Not even once. Stop looking at me like that!" },
    { at: 75,  text: "Three quarters and Rayen has gone very quiet. I-It's not like I'm enjoying this. ...Okay. Maybe a little." },
    { at: 95,  text: "You're THIS close and you're just standing there?! Somebody finish it! My cooling fans are just loud, shut up!" },
    { at: 100, text: "It's done. He actually has to wear it. ...Thank you. A-And if you tell anyone I said that, I'll deny it. Idiot." }
  ];

  function sassFor(pct) {
    var chosen = SASS[0];
    for (var i = 0; i < SASS.length; i++) {
      if (pct >= SASS[i].at) chosen = SASS[i];
    }
    return chosen.text;
  }

  /* ------------------------------------------------------ helpers */
  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

  function typeInto(el, text, done) {
    if (reduced) { el.textContent = text; if (done) done(); return; }
    var i = 0;
    el.textContent = "";
    (function step() {
      el.textContent = text.slice(0, ++i);
      if (i < text.length) {
        setTimeout(step, text.charAt(i - 1) === "." ? 42 : 18);
      } else if (done) {
        done();
      }
    })();
  }

  /* ------------------------------------------------------ act progress
     One rAF-throttled scroll listener writes --p onto each act. */
  var acts = Array.prototype.slice.call(document.querySelectorAll(".act"));
  var ticking = false;

  function measure() {
    var vh = window.innerHeight;
    acts.forEach(function (act) {
      var rect = act.getBoundingClientRect();
      // 0 when the act's top hits the viewport top, 1 when its bottom does.
      var travel = rect.height - vh;
      var p = travel > 0 ? clamp(-rect.top / travel, 0, 1) : (rect.top < vh ? 1 : 0);
      act.style.setProperty("--p", p.toFixed(4));
      if (act.dataset.act === "bar") updateBar(p);
    });
    ticking = false;
  }

  function onScroll() {
    if (!ticking) {
      ticking = true;
      window.requestAnimationFrame(measure);
    }
  }

  /* ------------------------------------------------------ the peak
     The fill and the counter track scroll across the first 65% of the act,
     then lock to the true figure and hold for the rest of the span. */
  var barFill = document.querySelector(".bar-fill");
  var barRaised = document.querySelector(".bar-raised");
  var barPct = document.querySelector(".bar-pct");
  var barState = document.querySelector(".bar-state");
  var target = clamp(data.percent, 0, 100);
  var locked = false;

  function updateBar(p) {
    if (!barFill) return;
    var SCRUB_END = 0.65;
    var t = clamp(p / SCRUB_END, 0, 1);
    // Ease out so the last stretch of the fill decelerates into place.
    var eased = 1 - Math.pow(1 - t, 3);
    var shown = reduced ? target : target * eased;

    barFill.style.setProperty("--fill", (shown / 100).toFixed(4));
    if (barRaised) barRaised.textContent = "$" + money.format(data.raised * (shown / (target || 1)) || 0);
    if (barPct) barPct.textContent = shown.toFixed(1) + "%";

    // Riko comments early, well before the number locks. Waiting for the lock
    // left her box visibly empty for most of the act, which read as broken.
    if (p >= 0.18 && sassEl && !sassTyped) runSass();

    if (t >= 1 && !locked) {
      locked = true;
      // Snap to the exact stored values so no rounding drift is displayed.
      if (barRaised) barRaised.textContent = "$" + money.format(data.raised);
      if (barPct) barPct.textContent = target.toFixed(1) + "%";
      if (barState) barState.textContent = "locked";
    } else if (t < 1 && locked) {
      locked = false;
      if (barState) barState.textContent = "reading";
    }
  }

  var sassEl = document.querySelector(".sass-text");
  var sassTyped = false;
  function runSass() {
    sassTyped = true;
    typeInto(sassEl, sassFor(data.percent));
  }

  /* ------------------------------------------------------ act 1 boot */
  var bootLines = Array.prototype.slice.call(document.querySelectorAll("[data-type]"));
  function runBoot() {
    var i = 0;
    (function next() {
      if (i >= bootLines.length) return;
      var el = bootLines[i++];
      typeInto(el, el.getAttribute("data-type"), function () {
        setTimeout(next, 130);
      });
    })();
  }

  /* ------------------------------------------------------ staggered reveals
     Used by both the donor wall and the character cards. */
  var reveals = Array.prototype.slice.call(
    document.querySelectorAll(".donor, .cast-card")
  );
  if ("IntersectionObserver" in window && !reduced) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var idx = reveals.indexOf(entry.target);
        // Stagger within the visible batch so rows arrive in sequence.
        entry.target.style.transitionDelay = (Math.min(idx % 9, 8) * 70) + "ms";
        entry.target.classList.add("is-in");
        io.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    reveals.forEach(function (d) { io.observe(d); });
  } else {
    reveals.forEach(function (d) { d.classList.add("is-in"); });
  }

  /* ------------------------------------------------------ act 5 pointer */
  var art = document.querySelector(".close-art img");
  if (art && !reduced && window.matchMedia("(hover: hover)").matches) {
    window.addEventListener("mousemove", function (e) {
      var x = (e.clientX / window.innerWidth - 0.5) * 2;
      var y = (e.clientY / window.innerHeight - 0.5) * 2;
      art.style.setProperty("--mx", (x * 14).toFixed(1) + "px");
      art.style.setProperty("--my", (y * 10).toFixed(1) + "px");
    }, { passive: true });
  }

  /* ------------------------------------------------------ boot */
  if (reduced && barFill) {
    barFill.style.setProperty("--fill-final", (target / 100).toFixed(4));
    barFill.style.setProperty("--fill", (target / 100).toFixed(4));
    if (sassEl) sassEl.textContent = sassFor(data.percent);
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
  measure();
  runBoot();
})();
