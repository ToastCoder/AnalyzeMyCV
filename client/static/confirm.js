(function() {
  if (window.location.hash && window.location.hash.includes('access_token=')) {
    var params = new URLSearchParams(window.location.hash.replace('#', '?'));
    var data = JSON.stringify({
      access_token: params.get('access_token'),
      refresh_token: params.get('refresh_token')
    });
    fetch('/auth/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: data
    })
    .then(function(r) { return r.json(); })
    .then(function(j) {
      if (j.success) {
        window.location.hash = '';
        window.location.reload();
      }
    });
  }
})();
