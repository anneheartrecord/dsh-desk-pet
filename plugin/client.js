/* DSH web client: floating pet in the page (what you see at :3080). */
window.__ModuleLoader__.load({
  id: "dsh-desk-pet",
  factory: function () {
    var SKINS = [
      { id: "whale", color: "#2f6feb", label: "鲸" },
      { id: "threadcore", color: "#d9822b", label: "线核" },
      { id: "nautilus", color: "#b56b3a", label: "鹦鹉螺" },
      { id: "jellyfish", color: "#7c5cbf", label: "水母" },
    ];

    function face(skin, state) {
      var look = state === "waiting" ? 4 : 0;
      var body =
        skin === "whale"
          ? '<ellipse cx="84" cy="88" rx="52" ry="38" fill="#2f6feb"/><ellipse cx="96" cy="100" rx="28" ry="16" fill="#dce9ff"/><polygon points="18,88 48,78 48,98" fill="#2f6feb"/>'
          : skin === "threadcore"
            ? '<circle cx="84" cy="90" r="46" fill="none" stroke="#d9822b" stroke-width="6"/><circle cx="84" cy="90" r="32" fill="none" stroke="#b45309" stroke-width="6"/><circle cx="84" cy="90" r="14" fill="#f3c77a"/>'
            : skin === "nautilus"
              ? '<circle cx="88" cy="96" r="44" fill="#e8c39e" stroke="#b56b3a" stroke-width="3"/><circle cx="92" cy="100" r="24" fill="#f6e6d0" stroke="#b56b3a"/>'
              : '<ellipse cx="84" cy="70" rx="40" ry="28" fill="#c7b4f0"/><path d="M56 92 C50 130 52 140 48 148" stroke="#9b84d6" fill="none" stroke-width="3"/><path d="M84 96 C84 140 84 148 84 152" stroke="#9b84d6" fill="none" stroke-width="3"/><path d="M110 92 C118 130 120 140 124 148" stroke="#9b84d6" fill="none" stroke-width="3"/>';
      var brows =
        state === "error"
          ? '<line x1="62" y1="68" x2="74" y2="72" stroke="#1a1a1a" stroke-width="2"/><line x1="94" y1="72" x2="106" y2="68" stroke="#1a1a1a" stroke-width="2"/>'
          : "";
      return (
        '<svg viewBox="0 0 168 168" width="168" height="168" xmlns="http://www.w3.org/2000/svg">' +
        '<rect width="168" height="168" fill="#f4efe6" rx="16"/>' +
        body +
        brows +
        '<ellipse cx="' +
        (72 + look) +
        '" cy="78" rx="7" ry="8" fill="#fff8ee" stroke="#1a1a1a"/><circle cx="' +
        (73 + look) +
        '" cy="79" r="2.5" fill="#1a1a1a"/>' +
        '<ellipse cx="' +
        (96 + look) +
        '" cy="78" rx="7" ry="8" fill="#fff8ee" stroke="#1a1a1a"/><circle cx="' +
        (97 + look) +
        '" cy="79" r="2.5" fill="#1a1a1a"/>' +
        "</svg>"
      );
    }

    function mount() {
      if (document.getElementById("dsh-desk-pet-root")) return;
      var skin = "whale";
      var state = "idle";
      var root = document.createElement("div");
      root.id = "dsh-desk-pet-root";
      root.style.cssText =
        "position:fixed;right:20px;bottom:20px;z-index:2147483646;width:180px;font:12px/1.3 system-ui,sans-serif;color:#1a1a1a;user-select:none;";
      var stage = document.createElement("div");
      stage.style.cssText = "cursor:grab;border-radius:16px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,.18);";
      var dots = document.createElement("div");
      dots.style.cssText = "display:flex;gap:10px;justify-content:center;margin-top:8px;";
      SKINS.forEach(function (item) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.title = item.label;
        btn.dataset.skin = item.id;
        btn.style.cssText =
          "width:16px;height:16px;border-radius:50%;border:1px solid #c8c0b4;background:" +
          item.color +
          ";padding:0;cursor:pointer;";
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          skin = item.id;
          paint();
        });
        dots.appendChild(btn);
      });
      root.appendChild(stage);
      root.appendChild(dots);
      document.body.appendChild(root);

      var drag = null;
      stage.addEventListener("pointerdown", function (ev) {
        drag = { x: ev.clientX - root.offsetLeft, y: ev.clientY - root.offsetTop };
        stage.style.cursor = "grabbing";
        ev.preventDefault();
      });
      window.addEventListener("pointermove", function (ev) {
        if (!drag) return;
        root.style.left = ev.clientX - drag.x + "px";
        root.style.top = ev.clientY - drag.y + "px";
        root.style.right = "auto";
        root.style.bottom = "auto";
      });
      window.addEventListener("pointerup", function () {
        drag = null;
        stage.style.cursor = "grab";
      });

      function paint() {
        stage.innerHTML = face(skin, state);
        Array.prototype.forEach.call(dots.children, function (btn) {
          btn.style.outline = btn.dataset.skin === skin ? "3px solid #1a1a1a" : "none";
        });
      }

      function refresh() {
        fetch("/dsh-desk-pet/state", { cache: "no-store" })
          .then(function (res) {
            return res.ok ? res.json() : null;
          })
          .then(function (body) {
            if (!body) return;
            if (body.state) state = body.state;
            paint();
          })
          .catch(function () {});
      }

      paint();
      refresh();
      setInterval(refresh, 1500);
    }

    function apply() {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mount);
      } else {
        mount();
      }
    }

    return { name: "dsh-desk-pet", apply: apply };
  },
});
