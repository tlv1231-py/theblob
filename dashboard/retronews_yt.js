// ═══════════════════════════════════════════════════════════════════════════
// YOUTUBE VERTICAL LIVE — measuring overlay for RetroNews
//
// TEMPORARY. A design aid, not a feature. Self-contained: it injects its own
// <style> and DOM, touches nothing else, and is removed by deleting this file
// plus the two-line hook in views/retronews.py. Never let it reach a real
// capture — it renders only when toggled on.
//
// ── THIS IS NOW MEASURED, NOT RECONSTRUCTED ─────────────────────────────────
// Calibrated 2026-07-20 against a real YouTube mobile livestream screenshot
// (1080x2340 phone, immersive layout, chat expanded). Every number in CAL below
// came off that image. The previous version drew three published SHORTS
// readings that disagreed by 260px on the top margin; all three turned out to
// be wrong about live, in the same direction and by a lot.
//
// WHAT THE MEASUREMENT OVERTURNED:
//   * There is NO vertical action rail on live. Shorts stacks like / dislike /
//     comment / share down the right edge; a livestream does not. The right side
//     carries ONE react button. The old overlay drew a 130px rail that does not
//     exist, which is the single biggest error it had.
//   * The reserved bands are FAR smaller than any Shorts guide claims. The top
//     chrome row ends at stage y111 (guides said 120-380). The chat INPUT starts
//     at y1786 (guides said the bottom 300-390 was gone).
//   * The real bottom constraint is not the input, it is the CHAT MESSAGES,
//     which climb to y1529 when chat is expanded.
//   * The dangerous intrusions are on the LEFT, and no guide mentions them: the
//     back arrow (x57-110) and a crown/membership button (x68-111) sit in the
//     left margin, which is exactly where the layout was pushed to reclaim room.
//   * The app's bottom nav bar sits BELOW the video, not over it, so it costs
//     nothing. Same for the phone's status bar above.
//
// HOW SCREEN PIXELS BECAME STAGE PIXELS. The reference video occupied screen
// y81-2051 (1970 tall, 1080 wide = 1:1.824). Ours is a true 9:16 (1:1.778), so
// positions are mapped as a FRACTION of the player box height rather than
// copied: chrome anchors to the player container's edges, so the fraction is
// what transfers. x maps 1:1 — both are 1080 wide.
//
// STILL ASSUMED, in honesty:
//   * One device, one screenshot, chat EXPANDED. Collapsed chat almost certainly
//     frees the y1529-1786 band; that is the next thing worth a screenshot.
//   * The reference stream is 1:1.824, not a true 9:16 — hence the fractional
//     mapping rather than direct copy.
// ═══════════════════════════════════════════════════════════════════════════
(function () {
  var stage = document.getElementById('stage');
  if (!stage) return;

  // ── Measured, in STAGE px on the 1080x1920 canvas ────────────────────────
  var CAL = {
    backArrow:  { x: 57,  y: 47,   w: 53,  h: 46 },
    channel:    { x: 302, y: 31,   w: 261, h: 85 },
    subscribe:  { x: 667, y: 23,   w: 232, h: 92 },
    overflow:   { x: 962, y: 63,   w: 55,  h: 13 },
    crown:      { x: 68,  y: 214,  w: 43,  h: 38 },
    heart:      { x: 945, y: 1665, w: 64,  h: 61 },
    chatPill:   { x: 86,  y: 1786, w: 379, h: 93 },
    emoji:      { x: 660, y: 1810, w: 59,  h: 57 },
    gift:       { x: 804, y: 1814, w: 55,  h: 50 },
    dollar:     { x: 945, y: 1816, w: 65,  h: 46 },
    chatMsgTop: 1529          // chat text climbs to here with chat EXPANDED
  };

  // The verdict bands, derived from the measurements above rather than typed.
  var RES = {
    top:    CAL.crown.y + CAL.crown.h,             // 252 — crown is the deepest
    bottom: 1920 - CAL.chatMsgTop,                 // 391 — expanded chat
    left:   Math.max(CAL.backArrow.x + CAL.backArrow.w,
                     CAL.crown.x + CAL.crown.w),   // 111
    right:  1080 - Math.min(CAL.heart.x, CAL.dollar.x)  // 135
  };

  function px(o) { return 'left:' + o.x + 'px;top:' + o.y + 'px;width:' + o.w
                        + 'px;height:' + o.h + 'px'; }

  var css = ''
    + '#ryt{position:absolute;inset:0;z-index:100;pointer-events:none;'
    +   'font-family:Roboto,"Segoe UI",system-ui,Arial,sans-serif;color:#fff}'
    + '#ryt .ryb{position:absolute;background:repeating-linear-gradient(45deg,'
    +   'rgba(255,45,85,.17) 0 12px,transparent 12px 24px);'
    +   'outline:1px solid rgba(255,45,85,.35)}'
    + '#ryt .rtag{position:absolute;font:700 15px Consolas,monospace;letter-spacing:.1em;'
    +   'background:rgba(4,2,10,.9);padding:5px 10px;white-space:nowrap}'
    // Measured chrome footprints — solid, because these are real.
    + '#ryt .rel{position:absolute;border:2px solid #ffd23f;'
    +   'background:rgba(255,210,63,.14)}'
    + '#ryt .rel span{position:absolute;left:0;top:100%;font:700 12px Consolas,monospace;'
    +   'color:#ffd23f;background:rgba(4,2,10,.88);padding:2px 5px;white-space:nowrap}'
    + '#ryt .rusable{position:absolute;left:' + RES.left + 'px;top:' + RES.top + 'px;'
    +   'width:' + (1080 - RES.left - RES.right) + 'px;'
    +   'height:' + (1920 - RES.top - RES.bottom) + 'px;border:3px solid #ff2d55}'
    + '#ryt .rours{position:absolute;border:3px dashed #00ff9d}'
    + '#ryt .rscrim-t{position:absolute;top:0;left:0;right:0;height:300px;'
    +   'background:linear-gradient(180deg,rgba(0,0,0,.55),transparent)}'
    + '#ryt .rscrim-b{position:absolute;bottom:0;left:0;right:0;height:460px;'
    +   'background:linear-gradient(0deg,rgba(0,0,0,.62),transparent)}'
    + '#ryt .rpill{position:absolute;background:#fff;color:#0d0d0d;border-radius:46px;'
    +   'display:flex;align-items:center;justify-content:center;'
    +   'font:700 34px Roboto,sans-serif}'
    + '#ryt .rinput{position:absolute;border-radius:46px;border:2px solid rgba(255,255,255,.5);'
    +   'background:rgba(0,0,0,.4);display:flex;align-items:center;padding:0 26px;'
    +   'font:400 30px Roboto,sans-serif;color:rgba(255,255,255,.78)}'
    + '#ryt .rglyph{position:absolute;display:flex;align-items:center;'
    +   'justify-content:center;font-size:44px;line-height:1}'
    + '#ryt .rchat{position:absolute;left:60px;top:' + CAL.chatMsgTop + 'px;width:800px;'
    +   'font:400 30px Roboto,sans-serif;text-shadow:0 1px 3px rgba(0,0,0,.9);'
    +   'display:flex;flex-direction:column;gap:12px}'
    + '#ryt .rchat b{color:#b9c8ea;font-weight:600;margin-right:8px}';

  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  // Reserved bands, drawn from the derived verdict.
  var bands = ''
    + '<div class="ryb" style="left:0;top:0;width:1080px;height:' + RES.top + 'px"></div>'
    + '<div class="ryb" style="left:0;top:' + (1920 - RES.bottom) + 'px;width:1080px;height:'
    +   RES.bottom + 'px"></div>'
    + '<div class="ryb" style="left:0;top:' + RES.top + 'px;width:' + RES.left + 'px;height:'
    +   (1920 - RES.top - RES.bottom) + 'px"></div>'
    + '<div class="ryb" style="right:0;top:' + RES.top + 'px;width:' + RES.right + 'px;height:'
    +   (1920 - RES.top - RES.bottom) + 'px"></div>';

  function el(o, label) {
    return '<div class="rel" style="' + px(o) + '"><span>' + label + '</span></div>';
  }

  var ov = document.createElement('div');
  ov.id = 'ryt';
  ov.innerHTML = ''
    + '<div class="rscrim-t"></div><div class="rscrim-b"></div>'
    + bands

    // Real chrome, drawn at measured size and position.
    + '<div class="rglyph" style="' + px(CAL.backArrow) + '">←</div>'
    + '<div class="rpill" style="' + px(CAL.subscribe) + '">Subscribe</div>'
    + '<div class="rglyph" style="' + px(CAL.channel) + ';justify-content:flex-start;'
    +   'font:700 34px Roboto,sans-serif">@yourchannel</div>'
    + '<div class="rglyph" style="' + px(CAL.overflow) + '">···</div>'
    + '<div class="rglyph" style="' + px(CAL.crown) + '">♛</div>'
    + '<div class="rchat"><div><b>quantfan_88</b>whats the weather in denver</div>'
    +   '<div><b>degenmike</b>this channel is so comfy</div>'
    +   '<div><b>ada_l</b>the anchor blinked at me</div></div>'
    + '<div class="rglyph" style="' + px(CAL.heart) + '">❤</div>'
    + '<div class="rinput" style="' + px(CAL.chatPill) + '">Chat...</div>'
    + '<div class="rglyph" style="' + px(CAL.emoji) + '">☺</div>'
    + '<div class="rglyph" style="' + px(CAL.gift) + '">🎁</div>'
    + '<div class="rglyph" style="' + px(CAL.dollar) + '">$</div>'

    + el(CAL.backArrow, 'back ' + CAL.backArrow.x + '-' + (CAL.backArrow.x + CAL.backArrow.w))
    + el(CAL.crown, 'crown ' + CAL.crown.x + '-' + (CAL.crown.x + CAL.crown.w))
    + el(CAL.heart, 'react')
    + el(CAL.chatPill, 'chat input y' + CAL.chatPill.y)

    + '<div class="rusable"><span class="rtag" style="top:8px;left:8px;color:#ff2d55">'
    +   'MEASURED USABLE ' + (1080 - RES.left - RES.right) + ' x '
    +   (1920 - RES.top - RES.bottom) + ' @ (' + RES.left + ',' + RES.top + ')</span></div>'
    + '<div class="rours"><span class="rtag" style="bottom:8px;left:8px;color:#00ff9d">'
    +   'RETRONEWS</span></div>';

  stage.appendChild(ov);

  // Our box is read from the LIVE --safe-* variables, never re-typed here. A
  // measuring tool that carries its own copy of the thing it measures will
  // eventually disagree with it, and then it lies with a ruler in its hand.
  function syncOurs() {
    var box = ov.querySelector('.rours');
    var cs = getComputedStyle(document.documentElement);
    var v = function (n) { return parseFloat(cs.getPropertyValue(n)) || 0; };
    var x = v('--safe-x'), y = v('--safe-y'), w = v('--safe-w'), h = v('--safe-h');
    if (!w || !h) return;
    box.style.cssText += ';left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;height:' + h + 'px';

    var bad = [];
    if (y < RES.top) bad.push('top by ' + (RES.top - y));
    if (x < RES.left) bad.push('left by ' + (RES.left - x));
    if (1080 - x - w < RES.right) bad.push('right by ' + (RES.right - (1080 - x - w)));
    if (1920 - y - h < RES.bottom) bad.push('bottom by ' + (RES.bottom - (1920 - y - h)));

    var tag = box.querySelector('.rtag');
    tag.textContent = 'RETRONEWS ' + w + 'x' + h + ' @ (' + x + ',' + y + ')  '
      + (bad.length ? '⚠ OVER ' + bad.join(', ') : '✓ CLEARS MEASURED CHROME');
    tag.style.color = bad.length ? '#ffd23f' : '#00ff9d';
    box.style.borderColor = bad.length ? '#ffd23f' : '#00ff9d';
  }
  syncOurs();
  setInterval(syncOurs, 2000);

  // Runtime switch — retronews.js polls the setting and calls this; RetroNews HQ
  // writes it. Toggled at RUNTIME rather than gated server-side because HQ and
  // the stream page are different browsers: a server-side gate could only apply
  // on a reload, which is useless when you are designing against it live.
  var on = null;
  window._rnYtToggle = function (show) {
    show = !!show;
    if (show === on) return;
    on = show;
    ov.style.display = show ? '' : 'none';
  };
  window._rnYtToggle(!!window._TND_RN_YT_INITIAL);
})();
