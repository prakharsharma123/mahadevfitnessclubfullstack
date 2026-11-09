// Enable / test / disable browser notifications for the admin (used on the Attendance page).
(function () {
  var stateEl = document.getElementById('pushState');
  var bEnable = document.getElementById('pushEnable');
  var bTest = document.getElementById('pushTest');
  var bDisable = document.getElementById('pushDisable');
  if (!stateEl) return;

  var cfg = null, reg = null;

  function show(on, off1, off2) {
    bEnable.style.display = on ? 'inline-flex' : 'none';
    bTest.style.display = off1 ? 'inline-flex' : 'none';
    bDisable.style.display = off2 ? 'inline-flex' : 'none';
  }
  function say(t) { stateEl.textContent = t; }

  function keyToBytes(b64url) {
    var pad = '='.repeat((4 - b64url.length % 4) % 4);
    var raw = atob((b64url + pad).replace(/-/g, '+').replace(/_/g, '/'));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function post(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json(); });
  }

  function refresh() {
    return reg.pushManager.getSubscription().then(function (sub) {
      if (Notification.permission === 'denied') {
        say('Blocked. Tap the lock icon next to the web address, open Site settings, and set Notifications to Allow. Then reload.');
        show(false, false, false);
      } else if (sub) {
        say('✅ Notifications are ON for this device.');
        show(false, true, true);
      } else {
        say('Notifications are OFF for this device.');
        show(true, false, false);
      }
    });
  }

  function init() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      say('This browser cannot receive notifications. On iPhone, first add this site to the Home Screen (Share, Add to Home Screen) and open it from there. On Android or laptop, use Chrome.');
      show(false, false, false);
      return;
    }
    fetch('/admin/push/config').then(function (r) { return r.json(); }).then(function (c) {
      cfg = c;
      if (!c.enabled) {
        say('Not set up on the server yet. The owner needs to add VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY (see docs/CHROME_PUSH_GUIDE.md).');
        show(false, false, false);
        return;
      }
      return navigator.serviceWorker.register('/sw.js').then(function (r) { reg = r; return navigator.serviceWorker.ready; })
        .then(function (r) { reg = r; return refresh(); });
    }).catch(function () { say('Could not check notification status. Reload the page.'); });
  }

  bEnable.onclick = function () {
    say('Asking for permission...');
    Notification.requestPermission().then(function (perm) {
      if (perm !== 'granted') { return refresh(); }
      return reg.pushManager.getSubscription().then(function (old) { return old ? old.unsubscribe() : null; })
        .then(function () {
          return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyToBytes(cfg.key) });
        })
        .then(function (sub) {
          return post('/admin/push/subscribe', { subscription: sub.toJSON(), label: navigator.userAgent.slice(0, 140) });
        })
        .then(function () { return refresh(); });
    }).catch(function (e) { say('Could not turn on: ' + (e && e.message ? e.message : e)); });
  };

  bTest.onclick = function () {
    say('Sending test...');
    post('/admin/push/test').then(function (r) {
      say(r.ok ? '✅ Test sent. You should see a notification in a few seconds.' : 'Test failed. ' + (r.message || 'Turn notifications off and on again on this device.'));
    }).catch(function () { say('Test failed. Check your internet.'); });
  };

  bDisable.onclick = function () {
    reg.pushManager.getSubscription().then(function (sub) {
      if (!sub) return;
      return post('/admin/push/unsubscribe', { endpoint: sub.endpoint }).then(function () { return sub.unsubscribe(); });
    }).then(refresh);
  };

  init();
})();
