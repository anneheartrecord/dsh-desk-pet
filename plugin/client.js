/**
 * DSH web-client module.
 *
 * Deliberately thin. There are two ways this plugin can reach the page — the
 * client module loader below, and the `tapIndex` injection in `index.mjs` —
 * and an earlier version of this file carried its own hand-drawn SVG pet, which
 * promptly drifted out of sync with the real one. Both paths now load the same
 * `overlay.js` off the same route, and `overlay.js` refuses to mount twice.
 */
window.__ModuleLoader__.load({
  id: "dsh-desk-pet",
  factory: function () {
    var SRC = "/dsh-desk-pet/overlay.js";

    function mount() {
      if (window.__dshDeskPetMounted) return;
      if (document.querySelector('script[data-dsh-desk-pet]')) return;
      var script = document.createElement("script");
      script.src = SRC;
      script.async = true;
      script.setAttribute("data-dsh-desk-pet", "1");
      script.onerror = function () {
        console.warn("[dsh-desk-pet] overlay script did not load from " + SRC);
      };
      (document.body || document.documentElement).appendChild(script);
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", mount);
    } else {
      mount();
    }

    return { id: "dsh-desk-pet", root: "dsh-desk-pet-root" };
  },
});
