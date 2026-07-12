(function () {
  function extractToken() {
    var sources = [];
    try { sources.push(window.location); } catch (e) {}
    try { sources.push(window.parent.location); } catch (e) {}
    try { sources.push(window.top.location); } catch (e) {}

    for (var i = 0; i < sources.length; i++) {
      var hash = sources[i].hash || "";
      if (hash.indexOf("access_token=") !== -1) {
        var params = new URLSearchParams(hash.replace("#", "?"));
        var token = params.get("access_token");
        if (token) return token;
      }
    }

    var search = "";
    try { search = window.parent.location.search || ""; } catch (e) {}
    if (search.indexOf("access_token=") !== -1) {
      var p = new URLSearchParams(search);
      var t = p.get("access_token");
      if (t) return t;
    }

    return null;
  }

  function redirect(token) {
    var url = "/?confirm_token=" + encodeURIComponent(token);
    try { window.top.location.href = url; } catch (e) {
      try { window.parent.location.href = url; } catch (e2) {
        try { window.location.href = url; } catch (e3) {}
      }
    }
  }

  function check() {
    var token = extractToken();
    if (token) redirect(token);
  }

  check();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", check);
  }
  setTimeout(check, 150);
  setTimeout(check, 500);
  setTimeout(check, 1000);
})();
