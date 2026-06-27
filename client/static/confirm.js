(function() {
  var hash = window.parent.location.hash;
  if (hash && hash.includes('access_token=')) {
    var params = new URLSearchParams(hash.replace('#', '?'));
    var token = params.get('access_token');
    if (token) {
      window.parent.location.href = '/?confirm_token=' + encodeURIComponent(token);
    }
  }
})();
