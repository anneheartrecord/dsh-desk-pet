/**
 * DSH web-client module.
 *
 * Deliberately thin. There are two ways this plugin can reach the page — this
 * client module and the `tapIndex` injection in `index.mjs` — and an earlier
 * version of this file carried its own hand-drawn SVG pet, which promptly
 * drifted out of sync with the real one. Both paths now load the same
 * `overlay.js` off the same route, and `overlay.js` refuses to mount twice.
 *
 * The factory has to return a module object whose `apply` is a function. That is
 * the whole contract, and returning descriptive metadata instead — an `{ id,
 * root }` object, which reads like the right thing — is what made DSH refuse the
 * whole plugin with "invalid plugin, expect function or object with an 'apply'
 * method, received object" and drop the page's pet along with it.
 */
window.__ModuleLoader__.load({
  id: "dsh-desk-pet",
  factory: function () {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    var SRC = "/dsh-desk-pet/overlay.js";
    var MARK = "data-dsh-desk-pet";

    function mount() {
      if (window.__dshDeskPetMounted) return;
      if (document.querySelector("script[" + MARK + "]")) return;
      var script = document.createElement("script");
      script.src = SRC;
      script.async = true;
      script.setAttribute(MARK, "1");
      script.onerror = function () {
        console.warn("[dsh-desk-pet] overlay script did not load from " + SRC);
      };
      (document.body || document.documentElement).appendChild(script);
    }

    function apply(ctx) {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mount, { once: true });
      } else {
        mount();
      }

      // Leave the page as we found it when the plugin is disabled, so
      // re-enabling it mounts again instead of tripping the guard above and
      // silently doing nothing.
      var dispose = function () {
        document.removeEventListener("DOMContentLoaded", mount);
        var script = document.querySelector("script[" + MARK + "]");
        if (script && script.parentNode) script.parentNode.removeChild(script);
        var root = document.getElementById("dsh-desk-pet-root");
        if (root && root.parentNode) root.parentNode.removeChild(root);
        window.__dshDeskPetMounted = false;
      };
      if (ctx && typeof ctx.on === "function") ctx.on("dispose", dispose);
      return dispose;
    }

    exports.apply = apply;
    exports.name = "dsh-desk-pet";
    return module.exports;
  },
});
