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
//   * One device, one screenshot, chat EXPANDED. The y1529-1786 band is
//     therefore drawn as VARIABLE, not reserved — it is chat's message feed, and
//     collapsing chat should free all 257px of it. That "should" is the last
//     unverified thing here and wants a chat-collapsed screenshot.
//   * The top row may also auto-hide after a few idle seconds, which would make
//     it variable too. NOT modelled: there is no measurement for it, and
//     inventing a second variable zone would undo the point of measuring.
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

  // ── HARD vs VARIABLE ─────────────────────────────────────────────────────
  // Not all covered area is covered all the time, and treating it as if it were
  // throws away 257px of height. Two classes:
  //
  //   HARD     — chrome that is always there. The top row, the two left buttons,
  //              the react button, and the chat INPUT, which is pinned to the
  //              bottom of a live player and never goes away.
  //   VARIABLE — the chat MESSAGE feed, y1529-1786. Present in the reference
  //              screenshot because chat was expanded; gone when it is collapsed.
  //
  // So there are two honest safe boxes, not one. Content that must ALWAYS read
  // stays out of the variable band; content that can afford to be occluded some
  // of the time may use it. That is a design choice, and the overlay's job is to
  // show the choice rather than make it.
  var HARD = {
    top:    CAL.crown.y + CAL.crown.h,                  // 252 — crown is deepest
    bottom: 1920 - CAL.chatPill.y,                      // 134 — chat input only
    left:   Math.max(CAL.backArrow.x + CAL.backArrow.w,
                     CAL.crown.x + CAL.crown.w),        // 111
    right:  1080 - Math.min(CAL.heart.x, CAL.dollar.x)  // 135
  };
  var VAR = { top: CAL.chatMsgTop, bottom: CAL.chatPill.y };   // 1529 -> 1786

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
    + '#ryt .ryv{position:absolute;background:repeating-linear-gradient(-45deg,'
    +   'rgba(255,170,40,.20) 0 12px,transparent 12px 24px);'
    +   'outline:1px dashed rgba(255,170,40,.55)}'
    + '#ryt .rusable{position:absolute;left:' + HARD.left + 'px;top:' + HARD.top + 'px;'
    +   'width:' + (1080 - HARD.left - HARD.right) + 'px;'
    +   'height:' + (VAR.top - HARD.top) + 'px;border:3px solid #ff2d55}'
    + '#ryt .rmax{position:absolute;left:' + HARD.left + 'px;top:' + HARD.top + 'px;'
    +   'width:' + (1080 - HARD.left - HARD.right) + 'px;'
    +   'height:' + (1920 - HARD.top - HARD.bottom) + 'px;border:3px dashed #ffaa28}'
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

  // Hard bands wrap the MAXIMUM box (chat collapsed); the variable strip is
  // drawn separately on top of it, so the two are never confused for each other.
  var bands = ''
    + '<div class="ryb" style="left:0;top:0;width:1080px;height:' + HARD.top + 'px"></div>'
    + '<div class="ryb" style="left:0;top:' + (1920 - HARD.bottom) + 'px;width:1080px;height:'
    +   HARD.bottom + 'px"></div>'
    + '<div class="ryb" style="left:0;top:' + HARD.top + 'px;width:' + HARD.left + 'px;height:'
    +   (1920 - HARD.top - HARD.bottom) + 'px"></div>'
    + '<div class="ryb" style="right:0;top:' + HARD.top + 'px;width:' + HARD.right + 'px;height:'
    +   (1920 - HARD.top - HARD.bottom) + 'px"></div>'
    + '<div class="ryv" style="left:' + HARD.left + 'px;top:' + VAR.top + 'px;width:'
    +   (1080 - HARD.left - HARD.right) + 'px;height:' + (VAR.bottom - VAR.top) + 'px">'
    +   '</div>';

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

    + '<div class="rmax"><span class="rtag" style="top:8px;right:8px;color:#ffaa28">'
    +   'IF CHAT COLLAPSED — ' + (1080 - HARD.left - HARD.right) + ' x '
    +   (1920 - HARD.top - HARD.bottom) + '  (+' + (VAR.bottom - VAR.top) + ' tall)</span></div>'
    + '<div class="rusable"><span class="rtag" style="top:8px;left:8px;color:#ff2d55">'
    +   'ALWAYS SAFE — ' + (1080 - HARD.left - HARD.right) + ' x '
    +   (VAR.top - HARD.top) + ' @ (' + HARD.left + ',' + HARD.top + ')</span></div>'
    + '<div class="rtag" style="left:' + (HARD.left + 12) + 'px;top:' + (VAR.top + 12)
    +   'px;color:#ffaa28">CHAT MESSAGES — y' + VAR.top + '-' + VAR.bottom
    +   ', ONLY WHEN EXPANDED</div>'
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

    // Three states. "Over" only ever means the HARD chrome — entering the
    // variable band is a trade-off, not an error, and calling it one would push
    // the layout into giving up 257px it does not have to.
    var bad = [];
    if (y < HARD.top) bad.push('top by ' + (HARD.top - y));
    if (x < HARD.left) bad.push('left by ' + (HARD.left - x));
    if (1080 - x - w < HARD.right) bad.push('right by ' + (HARD.right - (1080 - x - w)));
    if (1920 - y - h < HARD.bottom) bad.push('bottom by ' + (HARD.bottom - (1920 - y - h)));

    var intoVar = (y + h) - VAR.top;          // how far we reach into chat's band
    var tag = box.querySelector('.rtag');
    var msg, col;
    if (bad.length) {
      msg = '⚠ OVER HARD CHROME — ' + bad.join(', ');
      col = '#ff2d55';
    } else if (intoVar > 0) {
      msg = '◐ USES ' + intoVar + 'px OF THE CHAT BAND — occluded when chat is open';
      col = '#ffaa28';
    } else {
      msg = '✓ ALWAYS SAFE  (' + (-intoVar) + 'px of chat band unused)';
      col = '#00ff9d';
    }
    tag.textContent = 'RETRONEWS ' + w + 'x' + h + ' @ (' + x + ',' + y + ')  ' + msg;
    tag.style.color = col;
    box.style.borderColor = col;
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
