// ═══════════════════════════════════════════════════════════════════════════
// YOUTUBE VERTICAL LIVE — measuring overlay for RetroNews
//
// TEMPORARY. A design aid, not a feature. Self-contained on purpose: it injects
// its own <style> and DOM, touches nothing else, and is removed by deleting this
// file plus the two-line hook in views/retronews.py. Never let it reach a real
// capture — it renders only when toggled on.
//
// ── WHAT "ACCURATE" CAN AND CANNOT MEAN HERE ────────────────────────────────
// It CANNOT mean one confident rectangle. Measured against the public guides in
// July 2026, they disagree by 260px on the top margin alone:
//
//     reading        top   bottom   left   right   safe box
//     A (strict)     380      380     60     120    900 x 1160
//     B (loose)      120      300     60      96    888 x 1500
//     C (mid)        180      390     60      60    900 x 1350
//
// Worse, ALL THREE describe SHORTS, and a Short is not a livestream. None of
// them model the chrome that only exists on live and that never goes away: the
// chat input, the LIVE badge, the viewer count. A Shorts template will therefore
// always be optimistic about the bottom band.
//
// So this overlay draws the DISAGREEMENT instead of hiding it. Three reserved
// bands, layered; where they overlap, the hatching compounds and the region is
// unsafe under every reading. The UNION (top 380 / bottom 390 / left 60 /
// right 120) is drawn as the solid red line: content outside it is safe no
// matter which guide is right. That is the only honest "safe" on offer without
// a real measurement.
//
// ── HOW TO MAKE IT ACTUALLY ACCURATE ────────────────────────────────────────
// Screenshot any YouTube vertical LIVE stream on the phone you watch on, and
// measure it. Every number below is a CSS variable on #ryt for exactly this
// reason — calibration is editing YT.cal, not rewriting the file. Until that
// happens the CHROME ART is honest-but-reconstructed: the footprints are right,
// the pixel placement inside them is not published anywhere.
// ═══════════════════════════════════════════════════════════════════════════
(function () {
  var stage = document.getElementById('stage');
  if (!stage) return;

  // ── The calibration table ────────────────────────────────────────────────
  // Stage px on the 1080x1920 canvas. Replace with real measurements the moment
  // a screenshot exists; nothing else in this file needs to change.
  var CAL = {
    // Reserved-band readings. `u` is the union used for the verdict line.
    strict: { top: 380, bot: 380, left: 60, right: 120 },
    loose:  { top: 120, bot: 300, left: 60, right: 96 },
    mid:    { top: 180, bot: 390, left: 60, right: 60 },
    // Live-only chrome, which no Shorts guide covers. Reconstructed.
    osBar:      60,     // carrier/clock strip
    topRow:     150,    // collapse chevron + cast + overflow
    liveBadge:  250,    // LIVE pill + viewer count baseline
    railTop:    980,    // first rail item
    railW:      130,    // action rail footprint against the right edge
    chatTop:    1560,   // first visible chat message
    metaTop:    1700,   // channel row + title
    inputTop:   1790,   // chat input — PERMANENT on live, the real bottom edge
    inputH:     84
  };
  var U = {
    top:   Math.max(CAL.strict.top,   CAL.loose.top,   CAL.mid.top),
    bot:   Math.max(CAL.strict.bot,   CAL.loose.bot,   CAL.mid.bot),
    left:  Math.max(CAL.strict.left,  CAL.loose.left,  CAL.mid.left),
    right: Math.max(CAL.strict.right, CAL.loose.right, CAL.mid.right)
  };

  function band(o, hue, a) {
    // Four rects rather than one inverted box, so overlapping readings COMPOUND
    // visually — that compounding is the whole point.
    return ''
      + '<div class="ryb" style="left:0;top:0;width:1080px;height:' + o.top + 'px;'
      +   '--h:' + hue + ';--a:' + a + '"></div>'
      + '<div class="ryb" style="left:0;top:' + (1920 - o.bot) + 'px;width:1080px;height:'
      +   o.bot + 'px;--h:' + hue + ';--a:' + a + '"></div>'
      + '<div class="ryb" style="left:0;top:' + o.top + 'px;width:' + o.left + 'px;height:'
      +   (1920 - o.top - o.bot) + 'px;--h:' + hue + ';--a:' + a + '"></div>'
      + '<div class="ryb" style="right:0;top:' + o.top + 'px;width:' + o.right + 'px;height:'
      +   (1920 - o.top - o.bot) + 'px;--h:' + hue + ';--a:' + a + '"></div>';
  }

  var css = ''
    + '#ryt{position:absolute;inset:0;z-index:100;pointer-events:none;'
    +   'font-family:Roboto,"Segoe UI",system-ui,Arial,sans-serif;color:#fff}'
    + '#ryt .ryb{position:absolute;background:repeating-linear-gradient(45deg,'
    +   'hsla(var(--h),100%,55%,var(--a)) 0 12px,transparent 12px 24px)}'
    + '#ryt .rline{position:absolute;pointer-events:none}'
    + '#ryt .rtag{position:absolute;font:700 15px Consolas,monospace;letter-spacing:.12em;'
    +   'background:rgba(4,2,10,.9);padding:5px 10px;white-space:nowrap}'

    // Verdict box — the union. Outside this is safe under EVERY reading.
    + '#ryt .runion{position:absolute;left:' + U.left + 'px;top:' + U.top + 'px;'
    +   'width:' + (1080 - U.left - U.right) + 'px;height:' + (1920 - U.top - U.bot) + 'px;'
    +   'border:3px solid #ff2d55}'
    // Where OUR box actually is, read live from the page's own variables.
    + '#ryt .rours{position:absolute;border:3px dashed #00ff9d}'

    // ── chrome ──────────────────────────────────────────────────────────────
    + '#ryt .rscrim-t{position:absolute;top:0;left:0;right:0;height:340px;'
    +   'background:linear-gradient(180deg,rgba(0,0,0,.72),transparent)}'
    + '#ryt .rscrim-b{position:absolute;bottom:0;left:0;right:0;height:520px;'
    +   'background:linear-gradient(0deg,rgba(0,0,0,.82),transparent)}'
    + '#ryt .ros{position:absolute;top:0;left:0;right:0;height:' + CAL.osBar + 'px;'
    +   'display:flex;align-items:center;justify-content:space-between;padding:0 36px;'
    +   'font:600 23px Roboto,sans-serif}'
    + '#ryt .rtop{position:absolute;top:' + (CAL.topRow - 36) + 'px;left:0;right:0;height:72px;'
    +   'display:flex;align-items:center;justify-content:space-between;padding:0 30px}'
    + '#ryt .rico{width:62px;height:62px;border-radius:50%;background:rgba(0,0,0,.32);'
    +   'display:flex;align-items:center;justify-content:center;font-size:27px}'
    + '#ryt .rrow{display:flex;gap:14px}'
    + '#ryt .rlive{position:absolute;top:' + CAL.liveBadge + 'px;left:30px;'
    +   'display:flex;align-items:center;gap:12px}'
    + '#ryt .rpill{background:#ff0033;font:700 20px Roboto,sans-serif;letter-spacing:.08em;'
    +   'padding:7px 14px;border-radius:5px}'
    + '#ryt .rview{background:rgba(0,0,0,.5);font:500 21px Roboto,sans-serif;'
    +   'padding:7px 13px;border-radius:5px}'
    + '#ryt .rrail{position:absolute;right:0;top:' + CAL.railTop + 'px;width:' + CAL.railW + 'px;'
    +   'display:flex;flex-direction:column;align-items:center;gap:36px}'
    + '#ryt .ritem{display:flex;flex-direction:column;align-items:center;gap:7px}'
    + '#ryt .rglyph{font-size:42px;line-height:1;filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))}'
    + '#ryt .rcnt{font:600 18px Roboto,sans-serif}'
    + '#ryt .rav{width:68px;height:68px;border-radius:50%;border:2px solid #fff;position:relative;'
    +   'background:linear-gradient(135deg,#2c4494,#46dcff);display:flex;align-items:center;'
    +   'justify-content:center;font:700 26px Consolas,monospace}'
    + '#ryt .rchat{position:absolute;left:30px;top:' + CAL.chatTop + 'px;width:780px;'
    +   'display:flex;flex-direction:column;gap:13px}'
    + '#ryt .rmsg{font:400 21px Roboto,sans-serif;text-shadow:0 1px 3px rgba(0,0,0,.85)}'
    + '#ryt .rmsg b{color:#b9c8ea;font-weight:600;margin-right:8px}'
    + '#ryt .rmeta{position:absolute;left:30px;top:' + CAL.metaTop + 'px;width:780px}'
    + '#ryt .rchan{font:700 23px Roboto,sans-serif;margin-bottom:6px}'
    + '#ryt .rtitle{font:400 21px Roboto,sans-serif;opacity:.94;white-space:nowrap;'
    +   'overflow:hidden;text-overflow:ellipsis}'
    + '#ryt .rbar{position:absolute;left:30px;right:30px;top:' + CAL.inputTop + 'px;'
    +   'height:' + CAL.inputH + 'px;display:flex;align-items:center;gap:14px}'
    + '#ryt .rbox{flex:1;height:100%;border-radius:42px;border:1px solid rgba(255,255,255,.34);'
    +   'background:rgba(0,0,0,.45);display:flex;align-items:center;padding:0 28px;'
    +   'font:400 21px Roboto,sans-serif;color:rgba(255,255,255,.74)}'
    + '#ryt .rreact{width:84px;height:84px;border-radius:50%;background:rgba(0,0,0,.45);'
    +   'border:1px solid rgba(255,255,255,.34);display:flex;align-items:center;'
    +   'justify-content:center;font-size:34px}';

  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  var ov = document.createElement('div');
  ov.id = 'ryt';
  ov.innerHTML = ''
    + '<div class="rscrim-t"></div><div class="rscrim-b"></div>'

    // Three readings, layered. Overlap compounds; solid hatch = unsafe under all.
    + band(CAL.loose, 190, 0.10)
    + band(CAL.mid, 40, 0.10)
    + band(CAL.strict, 350, 0.10)

    + '<div class="runion"><span class="rtag" style="top:8px;left:8px;color:#ff2d55">'
    +   'UNION OF ALL READINGS — ' + (1080 - U.left - U.right) + ' x '
    +   (1920 - U.top - U.bot) + ' @ (' + U.left + ',' + U.top + ')</span></div>'
    + '<div class="rours"><span class="rtag" style="bottom:8px;left:8px;color:#00ff9d">'
    +   'RETRONEWS SAFE BOX</span></div>'

    // Live chrome. Footprints are the point; art inside them is reconstructed.
    + '<div class="ros"><span>9:41</span><span>▮▮▯ ◗ 🔋</span></div>'
    + '<div class="rtop"><div class="rico">⌄</div>'
    +   '<div class="rrow"><div class="rico">⛶</div><div class="rico">⋮</div></div></div>'
    + '<div class="rlive"><span class="rpill">LIVE</span>'
    +   '<span class="rview">👁 1.2K watching</span></div>'
    + '<div class="rrail">'
    +   '<div class="ritem"><div class="rav">◈</div></div>'
    +   '<div class="ritem"><div class="rglyph">👍</div><div class="rcnt">1.2K</div></div>'
    +   '<div class="ritem"><div class="rglyph">👎</div><div class="rcnt">Dislike</div></div>'
    +   '<div class="ritem"><div class="rglyph">💬</div><div class="rcnt">340</div></div>'
    +   '<div class="ritem"><div class="rglyph">↗</div><div class="rcnt">Share</div></div>'
    + '</div>'
    + '<div class="rchat">'
    +   '<div class="rmsg"><b>quantfan_88</b>whats the weather in denver</div>'
    +   '<div class="rmsg"><b>degenmike</b>this channel is so comfy</div>'
    +   '<div class="rmsg"><b>ada_l</b>the anchor blinked at me</div>'
    + '</div>'
    + '<div class="rmeta"><div class="rchan">◈ RetroNews</div>'
    +   '<div class="rtitle">channel 4 · national conditions · 24/7</div></div>'
    + '<div class="rbar"><div class="rbox">Say something...</div>'
    +   '<div class="rreact">😀</div></div>';

  stage.appendChild(ov);

  // Our own box is read from the LIVE computed variables, never re-typed here.
  // A measuring tool that carries its own copy of the thing it measures will
  // eventually disagree with it, and then it is lying with a ruler in its hand.
  function syncOurs() {
    var el = ov.querySelector('.rours');
    var cs = getComputedStyle(document.documentElement);
    var v = function (n) { return parseFloat(cs.getPropertyValue(n)) || 0; };
    var x = v('--safe-x'), y = v('--safe-y'), w = v('--safe-w'), h = v('--safe-h');
    if (!w || !h) return;
    el.style.cssText += ';left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;height:' + h + 'px';
    var tag = el.querySelector('.rtag');
    var risk = (y < U.top) || (x < U.left) ||
               (1080 - x - w < U.right) || (1920 - y - h < U.bot);
    tag.textContent = 'RETRONEWS ' + w + ' x ' + h + ' @ (' + x + ',' + y + ')'
      + (risk ? '  ⚠ OUTSIDE THE UNION' : '  ✓ INSIDE EVERY READING');
    tag.style.color = risk ? '#ffd23f' : '#00ff9d';
    el.style.borderColor = risk ? '#ffd23f' : '#00ff9d';
  }
  syncOurs();
  setInterval(syncOurs, 2000);          // vars can change under a live edit

  // Runtime switch — retronews.js polls the setting and calls this; RetroNews HQ
  // writes it. Idempotent, so polling every few seconds is free. Toggled at
  // RUNTIME rather than gated server-side because HQ and the stream page are
  // different browsers: a server-side gate could only apply on a reload, which
  // is useless when you are designing against the filter in the next window.
  var on = null;
  window._rnYtToggle = function (show) {
    show = !!show;
    if (show === on) return;
    on = show;
    ov.style.display = show ? '' : 'none';
  };
  window._rnYtToggle(!!window._TND_RN_YT_INITIAL);
})();
