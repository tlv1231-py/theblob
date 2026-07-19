// ═══════════════════════════════════════════════════════════════════════════
// STREAM 2 — scaffold renderer for a second vertical stream app.
//
// ⚠ THE ONE RULE THAT BREAKS EVERYTHING IF YOU FORGET IT:
//   requestAnimationFrame and CSS transitions/animations are INERT inside this
//   component iframe. They do not throw, they do not warn — they simply never
//   advance, so a CSS animation written here renders as a still frame and a
//   rAF loop never ticks. ANYTHING THAT MUST MOVE USES setInterval.
//   This is not a preference; it cost the Blob stream real debugging time.
//
// Everything below is deliberately minimal. It exists to prove the plumbing —
// the stage letterboxes, the page paints, config reaches it, and the shared
// event bus reaches it — so you can delete the placeholder content and build.
// ═══════════════════════════════════════════════════════════════════════════
(function () {
  var S = window._TND_STREAM2 || {};
  var $ = function (id) { return document.getElementById(id); };

  // ── Letterbox ────────────────────────────────────────────────────────────
  // The stage is always 1080x1920 in its own coordinates; only --s changes.
  // At a true 1080x1920 capture this resolves to exactly 1 and nothing is
  // resampled. Recomputed on resize AND on an interval, because the component
  // iframe is sized by Streamlit after first paint and a one-shot measurement
  // lands on the wrong number.
  function fit() {
    var w = window.innerWidth || 1080, h = window.innerHeight || 1920;
    var s = Math.min(w / 1080, h / 1920);
    document.documentElement.style.setProperty('--s', s.toFixed(4));
  }
  fit();
  window.addEventListener('resize', fit);
  setInterval(fit, 1000);

  // ── Heartbeat ────────────────────────────────────────────────────────────
  // Something must visibly move. The failure mode this guards against is the
  // one the Blob stream's watchdog was built around: ffmpeg cheerfully encodes
  // a FROZEN page at a perfect 24fps and every health signal reads green, so a
  // dead render is invisible from every metric except the picture itself.
  var beat = 0;
  setInterval(function () {
    beat++;
    var el = $('s2-beat');
    if (el) {
      el.textContent = String(beat % 100).padStart(2, '0');
      // Interval-driven, NOT a CSS pulse — see the rule at the top.
      var k = 1 + 0.06 * Math.sin(beat / 3);
      el.style.transform = 'scale(' + k.toFixed(3) + ')';
    }
    var t = $('s2-foot');
    if (t) t.textContent = new Date().toISOString().slice(11, 19) + ' UTC';
  }, 250);

  // ── Config ───────────────────────────────────────────────────────────────
  // NAMESPACED. Every setting for this app lives under its own `strategy` key
  // so it cannot collide with the Blob's (`stream:blob`). strategy_params' PK
  // is (strategy, param), so this costs nothing and needs no migration.
  // See CLAUDE.md "Stream Infrastructure Is Multi-App".
  var NS = S.ns || 'stream:app2';

  function pollConfig() {
    if (!S.supa || !S.supa.url) return;
    fetch(S.supa.url + '/rest/v1/strategy_params?strategy=eq.' +
          encodeURIComponent(NS) + '&select=param,value',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        if (!Array.isArray(rows)) return;
        var cfg = {};
        rows.forEach(function (r) { cfg[r.param] = r.value; });
        window._TND_S2_CFG = cfg;                 // read it from wherever you need
        var t = $('s2-sub');
        if (t && cfg.headline) t.textContent = cfg.headline;
      })
      .catch(function () {});                     // a blip is not a reason to stop
  }
  setInterval(pollConfig, 3000);                  // 3s reads as "instant" in HQ
  pollConfig();

  // ── Viewer events ────────────────────────────────────────────────────────
  // The bus is SHARED with every other stream app, on purpose: a tip is a tip
  // regardless of which app is on screen, so donations keep working straight
  // through a channel switch with zero infrastructure change. streamlabs.py and
  // chat.py have no idea this page exists.
  //
  // Each client tracks its own position rather than consuming exclusively —
  // which is why two open pages both react to the same event. That is expected.
  var seenTs = null;

  function pollEvents() {
    if (!S.supa || !S.supa.url) return;
    var since = new Date(Date.now() - 5 * 60000).toISOString();
    fetch(S.supa.url + '/rest/v1/stream_events?select=event_type,payload,created_at' +
          '&created_at=gte.' + since + '&order=created_at.desc&limit=10',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        var newest = rows[0];
        if (seenTs === newest.created_at) return;
        var first = seenTs === null;
        seenTs = newest.created_at;
        if (first) return;                        // don't replay history on load
        var p = newest.payload || {};
        var who = p.from || 'SOMEONE';
        var amt = (p.amount != null) ? ' $' + Number(p.amount).toFixed(2) : '';
        var el = $('s2-event');
        if (el) el.textContent = who + ' — ' + newest.event_type + amt;
      })
      .catch(function () {});
  }
  setInterval(pollEvents, 2000);
  pollEvents();

  // Debug handle, same convention as the Blob stream's _TND_DBG.
  window._TND_S2 = {
    cfg: function () { return window._TND_S2_CFG || {}; },
    beat: function () { return beat; },
    ns: NS
  };
})();
