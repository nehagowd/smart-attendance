/**
 * Simple popup toasts from server flash messages or client-side notify().
 */
function notify(message, type) {
  type = type || "info";
  var box = document.getElementById("toast");
  if (!box) {
    box = document.createElement("div");
    box.id = "toast";
    document.body.appendChild(box);
  }
  var el = document.createElement("div");
  el.className = "toast-item " + type;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(function () {
    el.remove();
  }, 4500);
}

document.addEventListener("DOMContentLoaded", function () {
  var data = document.body.getAttribute("data-flash");
  if (!data) return;
  try {
    var items = JSON.parse(data);
    items.forEach(function (pair) {
      notify(pair[1], pair[0] === "error" ? "error" : pair[0] === "warning" ? "warning" : "success");
    });
  } catch (e) {}
});
