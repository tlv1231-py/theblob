// ═══════════════════════════════════════════════════════════════════════════
// YOUTUBE VERTICAL LIVE — temp design overlay
//
// TEMPORARY. A design aid, not a feature. Self-contained on purpose: it
// injects its own <style> and DOM, touches nothing else, and is removed by
// deleting this file plus the two-line hook in views/stream.py. Never let it
// reach a real capture — it renders only when the ?yt param is on.
//
// The GEOMETRY is the point; the chrome art is deliberately approximate.
//
//   Sourced — multiple independent guides agree, and it reconciles exactly:
//     380 + 1160 + 380 = 1920      90 + 900 + 90 = 1080
//     safe box   900 x 1160 @ (90, 380)
//     reserved   top 380 · bottom 380 · sides 90
//
//   Inferred — a second published reading trims 60 left / 120 right instead of
//     90/90 (the action rail is wider than the left margin). Both yield 900
//     wide at different offsets. The dashed box is the INTERSECTION, 870 wide,
//     which is safe under either reading.
//
//   Reconstructed — where each button sits INSIDE the bands. No published
//     per-element pixel map exists. Verify against a real test stream.
//
//   Uncovered — the live chat input, LIVE badge and viewer count. Shorts specs
//     do not model live chrome, because a Short is not a livestream. On live,
//     chat is PERMANENT in the bottom band, so the usable bottom edge sits
//     higher than any Shorts template implies.
// ═══════════════════════════════════════════════════════════════════════════

(function () {
  var stage = document.getElementById('stage');
  if (!stage) return;

  var css = ''
    + '#yt-ov{position:absolute;inset:0;z-index:100;pointer-events:none;'
    +   'font-family:Roboto,"Segoe UI",system-ui,Arial,sans-serif;color:#fff}'

    // ── reserved bands ──────────────────────────────────────────────────
    + '#yt-ov .yb{position:absolute;border:1px solid rgba(255,0,60,.45);'
    +   'background:repeating-linear-gradient(45deg,rgba(255,0,60,.14) 0 10px,rgba(255,0,60,.03) 10px 20px)}'
    + '#yt-ov .ylbl{position:absolute;font:700 13px Consolas,monospace;letter-spacing:.16em;'
    +   'color:#ff5c7a;background:rgba(6,0,8,.85);padding:3px 8px}'

    // ── safe geometry ───────────────────────────────────────────────────
    + '#yt-ov .ysafe{position:absolute;left:90px;top:380px;width:900px;height:1160px;'
    +   'border:2px solid #00ff9d;box-shadow:inset 0 0 40px rgba(0,255,157,.06)}'
    + '#yt-ov .ystrict{position:absolute;left:90px;top:380px;width:870px;height:1160px;'
    +   'border:2px dashed rgba(0,229,255,.75)}'
    + '#yt-ov .ytag{position:absolute;font:700 12px Consolas,monospace;letter-spacing:.14em;'
    +   'background:rgba(6,0,8,.85);padding:4px 8px}'

    // ── chrome ──────────────────────────────────────────────────────────
    + '#yt-ov .yscrim-t{position:absolute;top:0;left:0;right:0;height:300px;'
    +   'background:linear-gradient(180deg,rgba(0,0,0,.7),transparent)}'
    + '#yt-ov .yscrim-b{position:absolute;bottom:0;left:0;right:0;height:460px;'
    +   'background:linear-gradient(0deg,rgba(0,0,0,.8),transparent)}'
    + '#yt-ov .yos{position:absolute;top:0;left:0;right:0;height:60px;display:flex;'
    +   'align-items:center;justify-content:space-between;padding:0 34px;font:600 22px Roboto,sans-serif}'
    + '#yt-ov .ytop{position:absolute;top:74px;left:0;right:0;height:72px;display:flex;'
    +   'align-items:center;justify-content:space-between;padding:0 30px}'
    + '#yt-ov .yico{width:60px;height:60px;border-radius:50%;background:rgba(0,0,0,.3);'
    +   'display:flex;align-items:center;justify-content:center;font-size:26px}'
    + '#yt-ov .yrow{display:flex;gap:12px}'
    + '#yt-ov .ylive{position:absolute;top:166px;left:30px;display:flex;align-items:center;gap:12px}'
    + '#yt-ov .ypill{background:#ff0033;font:700 19px Roboto,sans-serif;letter-spacing:.08em;'
    +   'padding:6px 13px;border-radius:5px}'
    + '#yt-ov .yview{background:rgba(0,0,0,.5);font:500 20px Roboto,sans-serif;padding:6px 12px;border-radius:5px}'

    // Rail: ~120 wide against the right edge — the widest intrusion on the page.
    + '#yt-ov .yrail{position:absolute;right:0;top:1000px;width:120px;display:flex;'
    +   'flex-direction:column;align-items:center;gap:34px}'
    + '#yt-ov .yitem{display:flex;flex-direction:column;align-items:center;gap:6px}'
    + '#yt-ov .yglyph{font-size:40px;line-height:1;filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))}'
    + '#yt-ov .ycnt{font:600 17px Roboto,sans-serif}'
    + '#yt-ov .yav{width:66px;height:66px;border-radius:50%;border:2px solid #fff;position:relative;'
    +   'background:linear-gradient(135deg,#ff00cc,#9400ff);display:flex;align-items:center;'
    +   'justify-content:center;font:700 28px Consolas,monospace}'
    + '#yt-ov .yplus{position:absolute;bottom:-9px;left:50%;transform:translateX(-50%);width:26px;'
    +   'height:26px;border-radius:50%;background:#ff0033;font:700 18px Roboto,sans-serif;'
    +   'line-height:25px;text-align:center}'

    + '#yt-ov .ychat{position:absolute;left:30px;bottom:240px;width:790px;display:flex;'
    +   'flex-direction:column;gap:12px}'
    + '#yt-ov .ymsg{font:400 20px Roboto,sans-serif;text-shadow:0 1px 3px rgba(0,0,0,.85)}'
    + '#yt-ov .ymsg b{color:#b0a0c8;font-weight:600;margin-right:8px}'
    + '#yt-ov .ymeta{position:absolute;left:30px;bottom:160px;width:790px}'
    + '#yt-ov .ychan{font:700 22px Roboto,sans-serif;margin-bottom:6px}'
    + '#yt-ov .ytitle{font:400 20px Roboto,sans-serif;opacity:.94;white-space:nowrap;'
    +   'overflow:hidden;text-overflow:ellipsis}'
    + '#yt-ov .ybar{position:absolute;left:30px;right:30px;bottom:62px;height:76px;'
    +   'display:flex;align-items:center;gap:14px}'
    + '#yt-ov .ybox{flex:1;height:76px;border-radius:38px;border:1px solid rgba(255,255,255,.32);'
    +   'background:rgba(0,0,0,.42);display:flex;align-items:center;padding:0 26px;'
    +   'font:400 20px Roboto,sans-serif;color:rgba(255,255,255,.72)}'
    + '#yt-ov .yreact{width:76px;height:76px;border-radius:50%;background:rgba(0,0,0,.42);'
    +   'border:1px solid rgba(255,255,255,.32);display:flex;align-items:center;'
    +   'justify-content:center;font-size:32px}'
    + '#yt-ov .yhome{position:absolute;bottom:16px;left:50%;transform:translateX(-50%);'
    +   'width:300px;height:6px;border-radius:3px;background:rgba(255,255,255,.65)}';

  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  var ov = document.createElement('div');
  ov.id = 'yt-ov';
  ov.innerHTML = ''
    + '<div class="yscrim-t"></div><div class="yscrim-b"></div>'

    // Reserved bands — treat as destroyed.
    + '<div class="yb" style="left:0;top:0;width:1080px;height:380px"></div>'
    + '<div class="yb" style="left:0;top:1540px;width:1080px;height:380px"></div>'
    + '<div class="yb" style="left:0;top:380px;width:90px;height:1160px"></div>'
    + '<div class="yb" style="left:990px;top:380px;width:90px;height:1160px"></div>'
    + '<div class="ylbl" style="left:16px;top:16px">RESERVED · TOP 380</div>'
    + '<div class="ylbl" style="left:16px;top:1550px">RESERVED · BOTTOM 380 · CHAT IS PERMANENT</div>'

    // Safe geometry.
    + '<div class="ystrict"><span class="ytag" style="bottom:6px;left:6px;color:#00e5ff">'
    +   'STRICT 870 — SAFE UNDER BOTH READINGS</span></div>'
    + '<div class="ysafe"><span class="ytag" style="top:6px;left:6px;color:#00ff9d">'
    +   'SAFE 900 × 1160 @ (90, 380)</span></div>'

    // Chrome — approximate art, correct footprint.
    + '<div class="yos"><span>9:41</span><span>▮▮▯ ◗ 🔋</span></div>'
    + '<div class="ytop"><div class="yico">⌄</div>'
    +   '<div class="yrow"><div class="yico">⛶</div><div class="yico">⋮</div></div></div>'
    + '<div class="ylive"><span class="ypill">LIVE</span>'
    +   '<span class="yview">👁 1.2K watching</span></div>'

    + '<div class="yrail">'
    +   '<div class="yitem"><div class="yav">◈<span class="yplus">+</span></div></div>'
    +   '<div class="yitem"><div class="yglyph">👍</div><div class="ycnt">1.2K</div></div>'
    +   '<div class="yitem"><div class="yglyph">👎</div><div class="ycnt">Dislike</div></div>'
    +   '<div class="yitem"><div class="yglyph">💬</div><div class="ycnt">340</div></div>'
    +   '<div class="yitem"><div class="yglyph">↗</div><div class="ycnt">Share</div></div>'
    + '</div>'

    + '<div class="ychat">'
    +   '<div class="ymsg"><b>quantfan_88</b>is the blob ok</div>'
    +   '<div class="ymsg"><b>degenmike</b>whats the sharpe on this</div>'
    +   '<div class="ymsg"><b>ada_l</b>he looks scared lol</div>'
    + '</div>'
    + '<div class="ymeta"><div class="ychan">◈ The Blob</div>'
    +   '<div class="ytitle">momentum paper trading · live NAV</div></div>'
    + '<div class="ybar"><div class="ybox">Say something...</div><div class="yreact">😀</div></div>'
    + '<div class="yhome"></div>';

  stage.appendChild(ov);
})();
