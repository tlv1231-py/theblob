// ═══════════════════════════════════════════════════════════════════════════
// RETRONEWS — fake 90s cable channel renderer.
//
// THE ERA RULE (CLAUDE.md) is binding here and it agrees with the hardware:
//   * tiles change by HARD CUT (display none/block). Never a fade or slide —
//     both because the WeatherSTAR swapped pages on a timer, and because a
//     24fps software compositor cannot tween anything smoothly anyway.
//   * ambient motion is palette-based (blink/colour), never positional.
//   * setInterval for everything. rAF and CSS animations are INERT in this
//     component iframe and fail SILENTLY.
// ═══════════════════════════════════════════════════════════════════════════
(function () {
  var S = window._TND_RETRONEWS || {};
  var $ = function (id) { return document.getElementById(id); };

  // ── Letterbox ────────────────────────────────────────────────────────────
  function fit() {
    var w = window.innerWidth || 1080, h = window.innerHeight || 1920;
    document.documentElement.style.setProperty(
      '--s', Math.min(w / 1080, h / 1920).toFixed(4));
  }
  fit();
  window.addEventListener('resize', fit);
  setInterval(fit, 1000);

  // ── Broadcast preview: double-tap the top-left corner ────────────────────
  // Fullscreen frames the stage at a true 9:16 — the aspect a YouTube vertical
  // live stream gives you — and switches the reserved-band guides on, so you
  // can see exactly what YouTube's own chrome will cover. That is the whole
  // point of the gesture: not "make it big", but "show me the real frame".
  //
  // NOTE ON FIDELITY, so the preview is not trusted for the wrong thing: your
  // phone renders this at the phone's own resolution, while the broadcast is
  // 810x1440. LAYOUT and framing are exact here; sharpness is optimistic.
  var DTAP_MS = 400;
  var lastTap = 0;

  function fsToggle() {
    try {
      var d = document;
      if (d.fullscreenElement || d.webkitFullscreenElement) {
        (d.exitFullscreen || d.webkitExitFullscreen || function () {}).call(d);
      } else {
        var el = d.documentElement;
        var req = el.requestFullscreen || el.webkitRequestFullscreen;
        if (req) {
          // navigationUI:'hide' asks mobile to drop its bars — advisory, and
          // harmless as an unknown key where unsupported.
          var p = req.call(el, { navigationUI: 'hide' });
          // requestFullscreen REJECTS rather than throws; without this the
          // failure is an unhandled rejection in a console nobody is watching.
          if (p && p.catch) p.catch(function (e) {
            console.warn('[retronews] fullscreen refused:', e);
          });
        }
      }
    } catch (e) {
      console.warn('[retronews] fullscreen refused:', e);
    }
  }

  var hit = $('fs-hit');
  if (hit) {
    // pointerdown, not click: one handler covers touch and mouse, and it fires
    // early enough to still carry the transient activation requestFullscreen
    // demands. Deliberately NOT preventDefault-ed — touch-action in the CSS
    // already kills double-tap zoom, and cancelling here risks the activation.
    hit.addEventListener('pointerdown', function () {
      var now = Date.now();
      if (now - lastTap > 0 && now - lastTap < DTAP_MS) {
        lastTap = 0;                 // consume, so a third tap starts a fresh pair
        fsToggle();
      } else {
        lastTap = now;
      }
    });
  }

  // Entering fullscreen resizes the wrap, but the box is not final on the event
  // itself — re-fit over the next few frames. setTimeout, never rAF.
  function fsChange() {
    var on = !!(document.fullscreenElement || document.webkitFullscreenElement);
    var stage = $('stage');
    // Guides ride fullscreen: preview mode shows what YouTube covers. ?guides=1
    // still forces them on outside fullscreen.
    if (stage && !S.guidesPinned) stage.classList.toggle('guides-on', on);
    fit(); setTimeout(fit, 60); setTimeout(fit, 250);
  }
  document.addEventListener('fullscreenchange', fsChange);
  document.addEventListener('webkitfullscreenchange', fsChange);

  // If the page was loaded with ?guides=1 the class is already on; remember that
  // so leaving fullscreen does not strip a guide the operator explicitly asked for.
  S.guidesPinned = !!(document.getElementById('stage') &&
                      document.getElementById('stage').classList.contains('guides-on'));

  // The iframe's own resize event does NOT reliably fire when the frame is
  // resized from outside, and rAF/ResizeObserver ride the inert rendering loop.
  // A timer is the only thing that can be trusted to notice. Cheap: one rect
  // read, and it only refits when the box actually changed.
  var lastBox = '';
  setInterval(function () {
    var wrap = $('stage-wrap');
    if (!wrap) return;
    var r = wrap.getBoundingClientRect();
    var k = Math.round(r.width) + 'x' + Math.round(r.height);
    if (k === lastBox) return;
    lastBox = k;
    fit();
  }, 500);

  // ── Broadcast clock ──────────────────────────────────────────────────────
  // A channel always knows what time it is. Also doubles as proof-of-life: a
  // frozen clock on air is the tell that the render died while ffmpeg happily
  // kept encoding the dead frame at a perfect 24fps.
  function clock() {
    var d = new Date();
    var h = d.getHours(), m = d.getMinutes();
    var ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12; if (h === 0) h = 12;
    var el = $('rn-clock');
    if (el) el.textContent = h + ':' + String(m).padStart(2, '0') + ' ' + ap;
  }
  clock();
  setInterval(clock, 1000);

  // ── National weather ─────────────────────────────────────────────────────
  // Open-Meteo: free, NO API KEY, CORS-enabled, and it takes comma-separated
  // coordinates so ten cities cost ONE request. That matters twice over — the
  // free-tier rule, and not hammering a public endpoint from a 24/7 stream.
  var CITIES = [
    ['SEATTLE',       47.61, -122.33], ['CHICAGO',   41.88,  -87.63],
    ['SAN FRANCISCO', 37.77, -122.42], ['ATLANTA',   33.75,  -84.39],
    ['LOS ANGELES',   34.05, -118.24], ['MIAMI',     25.76,  -80.19],
    ['DENVER',        39.74, -104.99], ['NEW YORK',  40.71,  -74.01],
    ['PHOENIX',       33.45, -112.07], ['BOSTON',    42.36,  -71.06]
  ];

  // WMO weather codes -> the short, all-caps labels a 90s CG would have shown.
  function condOf(c) {
    if (c === 0) return 'CLEAR';
    if (c === 1) return 'FAIR';
    if (c === 2) return 'P CLOUDY';
    if (c === 3) return 'CLOUDY';
    if (c === 45 || c === 48) return 'FOG';
    if (c >= 51 && c <= 57) return 'DRIZZLE';
    if (c >= 61 && c <= 67) return 'RAIN';
    if (c >= 71 && c <= 77) return 'SNOW';
    if (c >= 80 && c <= 82) return 'SHOWERS';
    if (c === 85 || c === 86) return 'SNOW SHWRS';
    if (c >= 95) return 'T-STORM';
    return '--';
  }

  function renderWx(rows) {
    var g = $('rn-wx-grid');
    if (!g) return;
    g.innerHTML = '';
    rows.forEach(function (r) {
      var cell = document.createElement('div');
      cell.className = 'wx-cell';
      var city = document.createElement('div');
      city.className = 'wx-city'; city.textContent = r.city;
      var temp = document.createElement('div');
      temp.className = 'wx-temp';
      temp.textContent = (r.t == null ? '--' : Math.round(r.t)) + '°';
      var cond = document.createElement('div');
      cond.className = 'wx-cond'; cond.textContent = r.cond;
      cell.appendChild(city); cell.appendChild(temp); cell.appendChild(cond);
      g.appendChild(cell);
    });
    var sub = $('rn-wx-sub');
    if (sub) sub.textContent = 'UPDATED ' + new Date().toLocaleTimeString('en-US',
      { hour: 'numeric', minute: '2-digit' });
  }

  function pollWeather() {
    var lat = CITIES.map(function (c) { return c[1]; }).join(',');
    var lon = CITIES.map(function (c) { return c[2]; }).join(',');
    fetch('https://api.open-meteo.com/v1/forecast?latitude=' + lat +
          '&longitude=' + lon +
          '&current=temperature_2m,weather_code&temperature_unit=fahrenheit')
      .then(function (r) { return r.json(); })
      .then(function (j) {
        // One coord returns an object, many return an array. Normalise.
        var arr = Array.isArray(j) ? j : [j];
        renderWx(CITIES.map(function (c, i) {
          var cur = (arr[i] && arr[i].current) || {};
          return { city: c[0], t: cur.temperature_2m, cond: condOf(cur.weather_code) };
        }));
      })
      .catch(function () { /* a blip is not a reason to blank the board */ });
  }
  pollWeather();
  setInterval(pollWeather, 10 * 60 * 1000);   // 10min — weather does not sprint

  // ── Tile rotation ────────────────────────────────────────────────────────
  // The schedule IS the aesthetic ("Local on the 8s"). Cuts only.
  var order = ['wx', 'donors', 'market', 'nowplaying'];
  var dwell = 15000;
  var idx = 0, lastCut = 0;

  function showTile(id) {
    var tiles = document.querySelectorAll('.rn-tile');
    for (var i = 0; i < tiles.length; i++) {
      tiles[i].classList.toggle('on', tiles[i].getAttribute('data-tile') === id);
    }
  }

  // ── THE DISSOLVE ─────────────────────────────────────────────────────────
  // Tiles never fade — they dissolve in chunky blocks, cover, swap behind a
  // one-frame gold flash, uncover. That is the GBA's own transition vocabulary
  // (hardware MOSAIC + window wipes), and it is quantised BY CONSTRUCTION:
  // every step is a discrete cut, so there is nothing for a 24fps software
  // compositor to fail to interpolate.
  //
  // 8 steps x 55ms each way + the flash = ~935ms, about 22 frames. CLAUDE.md's
  // floor is 6 frames to be seen; this is comfortably a beat you watch happen.
  // ── FRAME BUDGET — every timed visual on this page obeys it ────────────
  // ffmpeg captures at 24fps, so ONE BROADCAST FRAME IS ~42ms and nothing
  // shorter can appear on the stream at all. Worse, a duration that is not a
  // whole MULTIPLE of the frame period beats against the capture clock: the
  // first version of this dissolve used 55ms = 1.32 frames, so steps drifted in
  // and out of phase and some were merged into a single captured frame and
  // simply never appeared.
  //
  // TWO frames per step, not one. The render paints ~22-23.6 unique fps against
  // a 24fps capture (measured on the host), so a 1-frame step can be dropped
  // entirely. Two frames is the smallest unit that is guaranteed to survive.
  var FRAME_MS = 42;
  var WIPE_COLS = 18, WIPE_ROWS = 14, WIPE_STEPS = 6, WIPE_MS = FRAME_MS * 2;
  var blocks = [], order2 = [], wiping = false;

  function buildWipe() {
    var host = $('rn-wipe');
    if (!host) return;
    var frag = document.createDocumentFragment();
    var n = WIPE_COLS * WIPE_ROWS;
    for (var i = 0; i < n; i++) {
      var b = document.createElement('div');
      b.className = 'wipe-b';
      frag.appendChild(b);
      blocks.push(b);
      order2.push(i);
    }
    host.appendChild(frag);
    // Scatter the reveal order. A raster fill reads as a wipe; a scatter reads
    // as a DISSOLVE, which is the mosaic feel we want.
    for (var j = order2.length - 1; j > 0; j--) {
      var k = Math.floor(Math.random() * (j + 1));
      var t = order2[j]; order2[j] = order2[k]; order2[k] = t;
    }
  }
  buildWipe();

  function cutTo(id) {
    var host = $('rn-wipe');
    // No overlapping dissolves: a second one mid-flight would strand blocks
    // visible forever. Same reasoning as the Blob stream's lane arbiter.
    if (!host || !blocks.length || wiping) { showTile(id); return; }
    wiping = true;
    host.classList.add('on');
    var n = blocks.length, step = 0;

    var cover = setInterval(function () {
      step++;
      var upto = Math.round(n * step / WIPE_STEPS);
      for (var i = 0; i < upto; i++) blocks[order2[i]].classList.add('on');
      if (step < WIPE_STEPS) return;
      clearInterval(cover);

      // Full cover: swap the tile behind it, flash gold for one frame.
      host.classList.add('flash');
      showTile(id);
      setTimeout(function () {
        host.classList.remove('flash');
        var back = WIPE_STEPS;
        var uncover = setInterval(function () {
          back--;
          var from = Math.round(n * back / WIPE_STEPS);
          for (var i = from; i < n; i++) blocks[order2[i]].classList.remove('on');
          if (back > 0) return;
          clearInterval(uncover);
          host.classList.remove('on');
          wiping = false;
        }, WIPE_MS);
      }, WIPE_MS);            /* flash held 2 frames — see FRAME_MS */
    }, WIPE_MS);
  }

  function rotate() {
    if (!order.length || wiping) return;
    var now = Date.now();
    if (now - lastCut < dwell) return;
    lastCut = now;
    idx = (idx + 1) % order.length;
    cutTo(order[idx]);
  }
  showTile(order[0]);
  lastCut = Date.now();
  setInterval(rotate, 250);

  // ── Config (namespaced to THIS app) ──────────────────────────────────────
  // strategy_params' PK is (strategy, param), so 'stream:retronews' is a free
  // namespace and cannot collide with the Blob's settings.
  function pollConfig() {
    if (!S.supa || !S.supa.url) return;
    fetch(S.supa.url + '/rest/v1/strategy_params?strategy=eq.' +
          encodeURIComponent(S.ns) + '&select=param,value',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        if (!Array.isArray(rows)) return;
        var c = {};
        rows.forEach(function (r) { c[r.param] = r.value; });
        window._TND_RN_CFG = c;

        if (c.dwell_s) dwell = Math.max(4, parseInt(c.dwell_s, 10) || 15) * 1000;
        if (c.rotation) {
          try {
            var o = JSON.parse(c.rotation);
            if (Array.isArray(o) && o.length) {
              var changed = o.join(',') !== order.join(',');
              order = o;
              if (changed) { idx = 0; showTile(order[0]); lastCut = Date.now(); }
            }
          } catch (e) {}
        }
        var np = $('rn-nameplate');
        if (np) np.textContent = c.host_name || 'YOUR HOST';
        var say = $('rn-say');
        if (say && !say._locked) say.textContent = c.host_say || '';

        // Alert bar. Empty string = off. Blink is a class toggle, no transition.
        var al = $('rn-alert');
        if (al) {
          var txt = (c.alert || '').trim();
          al.classList.toggle('on', !!txt);
          if (txt) al.firstChild ? (al.textContent = txt) : (al.textContent = txt);
        }
      })
      .catch(function () {});
  }
  pollConfig();
  setInterval(pollConfig, 3000);

  // Alert blink — palette-based ambient motion, ~2 cuts/sec.
  setInterval(function () {
    var al = $('rn-alert');
    if (al && al.classList.contains('on')) al.classList.toggle('blink');
  }, FRAME_MS * 12);      /* 504ms = 12 frames exactly, not 500 */

  // ── Viewer events (the SHARED bus) ───────────────────────────────────────
  // streamlabs.py / chat.py have no idea this page exists; they just write
  // stream_events and whatever is rendering reacts. A tip therefore works here
  // with zero infrastructure change.
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
        var top = rows[0];
        if (seenTs === top.created_at) return;
        var first = seenTs === null;
        seenTs = top.created_at;
        if (first) return;                       // never replay history on load
        var p = top.payload || {};
        var who = (p.from || 'SOMEONE').toUpperCase();
        var amt = (p.amount != null) ? ' $' + Number(p.amount).toFixed(2) : '';
        // "We interrupt this broadcast" — the interruption IS the format.
        var say = $('rn-say');
        if (say) {
          say.textContent = who + amt + ' — THANK YOU!';
          say._locked = true;
          setTimeout(function () { say._locked = false; }, 12000);
        }
      })
      .catch(function () {});
  }
  pollEvents();
  setInterval(pollEvents, 2000);

  window._TND_RN = {
    cfg: function () { return window._TND_RN_CFG || {}; },
    tile: function () { return order[idx]; },
    order: function () { return order.slice(); },
    cut: function (id) { cutTo(id); lastCut = Date.now(); },
    wiping: function () { return wiping; },
    blocks: function () { return blocks.length; }
  };
})();
