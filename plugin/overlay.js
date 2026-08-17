/**
 * In-page mirror of the desktop pet.
 *
 * Draws the same generated frames, on the same timeline, at the same state as
 * the Tk window — because all three come off the wire (`/dsh-desk-pet/*`)
 * rather than being reinvented here. Hand-drawn SVG stand-ins were the previous
 * version of this file and they drifted from the real pet immediately.
 *
 * If the desktop pet is not running, `/state` reports `live: false` and this
 * quietly parks on idle instead of showing a lie.
 */
(function () {
  if (window.__dshDeskPetMounted) return;
  window.__dshDeskPetMounted = true;

  var BASE = "/dsh-desk-pet";
  var POLL_MS = 700;
  // Dot colours for the shipped skins. Anything else discovered in the
  // manifest — a skin generated from a user's own photo, say — still gets a
  // dot, just a neutral one, so the overlay never has to be edited to
  // acknowledge a new skin exists.
  var SKIN_COLORS = {
    deepseek: "#12161f",
    bluewhale: "#2f6feb",
    threadcore: "#d9822b",
    nautilus: "#b56b3a",
    jellyfish: "#7c5cbf",
  };
  var SKIN_LABELS = {
    deepseek: "深索鲸 DeepSeek Whale",
    bluewhale: "蓝鲸 Blue Whale",
    threadcore: "线核 Threadcore",
    nautilus: "鹦鹉螺 Nautilus",
    jellyfish: "水母 Jellyfish",
  };
  var FALLBACK_COLOR = "#8b8f9a";
  // Mirrors anim._BREATH. Amplitude in px, period in ms.
  var BREATH = {
    idle: [2.6, 2900],
    working: [1.6, 1100],
    waiting: [3.2, 2000],
    error: [1.1, 5200],
    happy: [4.0, 620],
    sleeping: [3.4, 4600],
  };
  var FALLBACK = { happy: "idle", sleeping: "idle", working: "idle", waiting: "idle", error: "idle" };

  var manifest = null;
  var skin = "deepseek";
  var state = "idle";
  var stateSince = performance.now();
  var followDesktop = true;
  var hopUntil = 0;
  var pointerDx = null;

  function framesFor(skinId, stateName) {
    if (!manifest || !manifest.skins || !manifest.skins[skinId]) return null;
    var entry = manifest.skins[skinId];
    var seen = {};
    var current = stateName;
    while (current && !seen[current]) {
      seen[current] = 1;
      var names = entry.states && entry.states[current];
      if (names && names.length) {
        return { state: current, names: names, timeline: (entry.timelines || {})[current] || null };
      }
      current = FALLBACK[current];
    }
    return null;
  }

  function frameIndex(timeline, count, elapsed) {
    if (!timeline || !timeline.length) return 0;
    var total = 0;
    for (var i = 0; i < timeline.length; i++) total += timeline[i][1];
    if (total <= 0) return 0;
    var t = elapsed % total;
    for (var j = 0; j < timeline.length; j++) {
      if (t < timeline[j][1]) return timeline[j][0] % count;
      t -= timeline[j][1];
    }
    return timeline[timeline.length - 1][0] % count;
  }

  function mount() {
    if (document.getElementById("dsh-desk-pet-root")) return;

    var root = document.createElement("div");
    root.id = "dsh-desk-pet-root";
    root.style.cssText =
      "position:fixed;right:24px;bottom:24px;z-index:2147483647;width:160px;" +
      "font:12px/1.3 system-ui,-apple-system,sans-serif;user-select:none;";

    var stage = document.createElement("div");
    stage.style.cssText = "cursor:grab;width:160px;height:160px;position:relative;";

    var img = document.createElement("img");
    img.alt = "DSH desk pet";
    img.draggable = false;
    img.style.cssText =
      "width:100%;height:100%;object-fit:contain;image-rendering:auto;" +
      "will-change:transform;pointer-events:none;";
    stage.appendChild(img);

    var dots = document.createElement("div");
    dots.style.cssText = "display:flex;gap:9px;justify-content:center;margin-top:4px;opacity:0;transition:opacity .18s;";
    root.addEventListener("mouseenter", function () { dots.style.opacity = "1"; });
    root.addEventListener("mouseleave", function () { dots.style.opacity = "0"; });

    Object.keys((manifest && manifest.skins) || {}).sort().forEach(function (id) {
      var label = SKIN_LABELS[id] || id;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.title = label;
      btn.setAttribute("aria-label", label);
      btn.style.cssText =
        "width:16px;height:16px;border-radius:50%;border:2px solid #fff;background:" +
        (SKIN_COLORS[id] || FALLBACK_COLOR) +
        ";box-shadow:0 1px 4px rgba(0,0,0,.35);cursor:pointer;padding:0;";
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        skin = id;
        // A manual pick means the page pet stops following the desktop skin.
        followDesktop = false;
      });
      dots.appendChild(btn);
    });

    root.appendChild(stage);
    root.appendChild(dots);
    (document.body || document.documentElement).appendChild(root);

    var drag = null;
    var moved = false;
    stage.addEventListener("pointerdown", function (ev) {
      var box = root.getBoundingClientRect();
      drag = { x: ev.clientX - box.left, y: ev.clientY - box.top };
      moved = false;
      stage.style.cursor = "grabbing";
      stage.setPointerCapture && stage.setPointerCapture(ev.pointerId);
    });
    stage.addEventListener("pointermove", function (ev) {
      var box = stage.getBoundingClientRect();
      pointerDx = ev.clientX - (box.left + box.width / 2);
    });
    stage.addEventListener("pointerleave", function () { pointerDx = null; });
    window.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      moved = true;
      root.style.left = ev.clientX - drag.x + "px";
      root.style.top = ev.clientY - drag.y + "px";
      root.style.right = "auto";
      root.style.bottom = "auto";
    });
    window.addEventListener("pointerup", function () {
      if (drag && !moved) hopUntil = performance.now() + 520;
      drag = null;
      stage.style.cursor = "grab";
    });

    var lastSrc = "";
    function paint(now) {
      var resolved = framesFor(skin, state);
      if (resolved) {
        var elapsed = now - stateSince;
        var index = frameIndex(resolved.timeline, resolved.names.length, elapsed);
        var src = BASE + "/frames/" + skin + "/" + resolved.state + "/" +
          resolved.names[index].replace(/\.gif$/, ".png");
        if (src !== lastSrc) {
          img.src = src;
          lastSrc = src;
        }
        // Keyed on the requested state, not `resolved.state`: a state that has
        // no art yet borrows idle's frames, and borrowing idle's breath as well
        // would make it wholly indistinguishable from idle.
        var breath = BREATH[state] || BREATH.idle;
        var dy = breath[0] * Math.sin((2 * Math.PI * (elapsed % breath[1])) / breath[1]);
        var dx = pointerDx == null ? 0 : Math.max(-5, Math.min(5, (pointerDx / 480) * 5));
        var hop = 0;
        if (now < hopUntil) {
          var remaining = (hopUntil - now) / 520;
          hop = -14 * Math.sin(Math.PI * remaining) * remaining;
        }
        img.style.transform = "translate(" + dx.toFixed(2) + "px," + (dy + hop).toFixed(2) + "px)";
      }
      requestAnimationFrame(paint);
    }
    requestAnimationFrame(paint);
  }

  function poll() {
    fetch(BASE + "/state", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        if (payload.state && payload.state !== state) {
          state = payload.state;
          stateSince = performance.now();
        }
        if (followDesktop && payload.live && payload.skin) skin = payload.skin;
      })
      .catch(function () { /* DSH restarting; keep showing the last known pose */ });
  }

  function boot() {
    fetch(BASE + "/manifest.json", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        manifest = payload;
        mount();
        poll();
        setInterval(poll, POLL_MS);
      })
      .catch(function (err) {
        console.warn("[dsh-desk-pet] overlay disabled:", err);
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
