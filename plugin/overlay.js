(function () {
  if (window.__dshDeskPetMounted) return;
  window.__dshDeskPetMounted = true;
  function mount() {
    if (document.getElementById("dsh-desk-pet-root")) return;
    var skins = [
      { id: "whale", color: "#2f6feb", label: "鲸" },
      { id: "threadcore", color: "#d9822b", label: "线核" },
      { id: "nautilus", color: "#b56b3a", label: "鹦鹉螺" },
      { id: "jellyfish", color: "#7c5cbf", label: "水母" },
    ];
    var skin = "whale";
    var root = document.createElement("div");
    root.id = "dsh-desk-pet-root";
    root.style.cssText =
      "position:fixed;right:24px;bottom:24px;z-index:2147483647;width:200px;font:12px/1.3 system-ui,sans-serif;color:#1a1a1a;";
    var label = document.createElement("div");
    label.textContent = "DSH Desk Pet";
    label.style.cssText = "margin-bottom:6px;font-weight:700;";
    var stage = document.createElement("div");
    stage.style.cssText =
      "cursor:grab;border-radius:16px;overflow:hidden;box-shadow:0 10px 28px rgba(0,0,0,.25);background:#f4efe6;";
    var dots = document.createElement("div");
    dots.style.cssText = "display:flex;gap:10px;justify-content:center;margin-top:8px;";
    skins.forEach(function (item) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.title = item.label;
      btn.style.cssText =
        "width:18px;height:18px;border-radius:50%;border:2px solid #fff;background:" +
        item.color +
        ";box-shadow:0 0 0 1px #1a1a1a;cursor:pointer;";
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        skin = item.id;
        paint();
      });
      dots.appendChild(btn);
    });
    root.appendChild(label);
    root.appendChild(stage);
    root.appendChild(dots);
    (document.body || document.documentElement).appendChild(root);
    function face() {
      var body =
        skin === "whale"
          ? '<ellipse cx="84" cy="88" rx="52" ry="38" fill="#2f6feb"/><ellipse cx="96" cy="100" rx="28" ry="16" fill="#dce9ff"/><polygon points="18,88 48,78 48,98" fill="#2f6feb"/>'
          : skin === "threadcore"
            ? '<circle cx="84" cy="90" r="46" fill="none" stroke="#d9822b" stroke-width="6"/><circle cx="84" cy="90" r="32" fill="none" stroke="#b45309" stroke-width="6"/><circle cx="84" cy="90" r="14" fill="#f3c77a"/>'
            : skin === "nautilus"
              ? '<circle cx="88" cy="96" r="44" fill="#e8c39e" stroke="#b56b3a" stroke-width="3"/><circle cx="92" cy="100" r="24" fill="#f6e6d0" stroke="#b56b3a"/>'
              : '<ellipse cx="84" cy="70" rx="40" ry="28" fill="#c7b4f0"/><path d="M56 92 C50 130 52 140 48 148" stroke="#9b84d6" fill="none" stroke-width="3"/><path d="M84 96 C84 140 84 148 84 152" stroke="#9b84d6" fill="none" stroke-width="3"/><path d="M110 92 C118 130 120 140 124 148" stroke="#9b84d6" fill="none" stroke-width="3"/>';
      return (
        '<svg viewBox="0 0 168 168" width="200" height="168" xmlns="http://www.w3.org/2000/svg">' +
        body +
        '<ellipse cx="72" cy="78" rx="7" ry="8" fill="#fff8ee" stroke="#1a1a1a"/><circle cx="73" cy="79" r="2.5" fill="#1a1a1a"/>' +
        '<ellipse cx="96" cy="78" rx="7" ry="8" fill="#fff8ee" stroke="#1a1a1a"/><circle cx="97" cy="79" r="2.5" fill="#1a1a1a"/>' +
        "</svg>"
      );
    }
    function paint() {
      stage.innerHTML = face();
    }
    var drag = null;
    stage.addEventListener("pointerdown", function (ev) {
      drag = { x: ev.clientX - root.getBoundingClientRect().left, y: ev.clientY - root.getBoundingClientRect().top };
      stage.style.cursor = "grabbing";
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
    paint();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
