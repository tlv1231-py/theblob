// ═══════════════════════════════════════════════════════════════════════════
// THE BLOB — procedural 8-bit pilot character
//
// Renders to a low-res canvas grid. No image assets, no sprite sheets.
// Every frame is computed from live state, so reactions are continuous
// rather than bucketed into a fixed number of hand-drawn frames.
//
// Usage (inside the home_nav iframe):
//   var blob = TNDBlob.create(document.getElementById('blobCanvas'));
//   blob.start();
//   blob.setPnl(0.4);           // percent, drives shape continuously
//   blob.setMood('ALERT', 12);  // transient — decays back to IDLE
//
// See dashboard/BLOB.md for the design contract before changing anything.
// ═══════════════════════════════════════════════════════════════════════════

(function(global) {

  // ── Palette — locked to the dashboard's existing cyberpunk ramp ───────────
  // MID is his identity colour. He does not change body colour with mood;
  // mood reads through the rim accent instead. See BLOB.md "Always pink".
  var P = {
    OUT : [ 42,  0, 61],
    LO  : [138,  0,108],
    MID : [255,  0,204],   // #ff00cc
    HI  : [255,110,226],
    SPEC: [255,200,248],
    EYE : [ 10,  0, 16],
    GRN : [  0,255,157],   // #00ff9d — up
    RED : [255, 51,102],   // #ff3366 — down
    CYN : [  0,229,255],   // #00e5ff — activity
    WHT : [255,255,255]
  };
  var BODY = [P.OUT, P.LO, P.MID, P.HI, P.SPEC];

  // 4x4 Bayer ordered dither. Stipples the shading into bands instead of a
  // smooth gradient — this is what makes it read as period-correct 8-bit.
  var BAYER = [0,8,2,10, 12,4,14,6, 3,11,1,9, 15,7,13,5]
    .map(function(v) { return v / 16 - 0.5; });

  // BRACE is the anticipation beat — he winds up BEFORE a trade lands, so the
  // impact has something to release. Anticipation is what separates a
  // performance from a twitch; without it every reaction starts at full volume
  // from nothing and reads as a flinch.
  var MOODS = ['IDLE','HAPPY','SCARED','ALERT','SLEEP','SMUG','BRACE'];

  // ── Brows ──────────────────────────────────────────────────────────────────
  // He had eyes and a mouth and NO BROWS, which is why every mood had to be
  // carried by swapping the whole eye for a preset shape — the eye was doing
  // work that isn't its job. An eye is a shape; a brow is an OPINION. Angle
  // carries more emotion than size ever will: anger is not a rounder eye, it is
  // a brow driven down and in. Two pixels of slope out-act a whole redesign.
  //
  // `tilt` drives the INNER end: + is down (anger, focus), - is up (worry).
  // Inner means the right end of the left brow and the left end of the right
  // brow, so the right brow takes the negated slope and starts where the left
  // one ended. Mirroring the NUMBER rather than the geometry is what keeps them
  // reading as one pair of brows instead of two independent marks.
  //
  // Brows do NOT track `look`. They sit on the head, not the eyeball — the eye
  // sliding under a held brow is most of what makes a glance read as a glance.
  var BROWS = {
    IDLE:   { drop:  0, tilt:  0.00, th: 1, on: true  },
    HAPPY:  { drop: -2, tilt: -0.15, th: 1, on: true  },  // lifted, relaxed
    SCARED: { drop: -3, tilt: -0.55, th: 1, on: true  },  // inner ends UP — worry
    ALERT:  { drop: -3, tilt:  0.00, th: 2, on: true  },  // high and hard
    SMUG:   { drop:  0, tilt:  0.15, th: 1, on: true  },  // ONE lifts — see draw()
    BRACE:  { drop:  1, tilt:  0.55, th: 2, on: true  },  // down and in — focus
    SLEEP:  { drop:  2, tilt:  0.00, th: 1, on: false }   // a sleeping face is slack
  };

  function create(canvas, opts) {
    opts = opts || {};
    var W = opts.grid || 48;
    var H = W;
    var FPS = opts.fps || 10;   // Do not raise. See BLOB.md "Framerate".

    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    var img = ctx.createImageData(W, H);

    var self = {
      mood: 'IDLE',
      pnl: 0,          // percent, e.g. 1.4 for +1.4%
      visor: !!opts.visor,
      tick: 0,
      timer: null,
      onAccent: opts.onAccent || null   // cb(rgbArray) — for outer bloom
    };
    var blinkUntil = -1, nextBlink = 30, moodUntil = -1, fx = [];
    // Transient gaze. Same shape as a transient mood: takes ticks and decays
    // back to the P&L-driven drift. He needs to be able to look AT something
    // (a tile he is about to place) and not only toward the move.
    var lookX = 0, lookUntil = -1;

    function px(x, y, c) {
      if (x < 0 || y < 0 || x >= W || y >= H) return;
      var i = ((y|0) * W + (x|0)) * 4;
      img.data[i]=c[0]; img.data[i+1]=c[1]; img.data[i+2]=c[2]; img.data[i+3]=255;
    }
    function rect(x, y, w, h, c) {
      for (var j = 0; j < h; j++) for (var i = 0; i < w; i++) px(x+i, y+j, c);
    }
    // A brow is a run of 1px columns stepped by `slope` — NOT a rotated line.
    // Rounding each column to a whole pixel is what keeps it on the grid and
    // jagged; a real diagonal here would anti-alias and stop reading as 8-bit.
    function brow(x0, y0, w, slope, th) {
      for (var i = 0; i < w; i++) rect(x0 + i, y0 + Math.round(i * slope), 1, th, P.EYE);
    }

    function draw() {
      for (var i = 0; i < img.data.length; i++) img.data[i] = 0;

      var t = self.tick / FPS;                              // quantized clock
      var p = Math.max(-1, Math.min(1, self.pnl / 4));      // ±4% saturates
      var mood = self.mood;

      // ── Continuous state → shape ──────────────────────────────────────────
      var breathe = Math.sin(t * 2.1) * 0.035;
      var bob = Math.round(Math.sin(t * 1.7) * 1.6);   // integer px only
      var sx = 1.0, sy = 1.0, R = W * 0.323, jx = 0, jy = 0;
      var accent = P.MID;

      sy += p * 0.10 + breathe;
      sx -= p * 0.07 - breathe * 0.5;
      accent = p > 0.05 ? P.GRN : (p < -0.05 ? P.RED : P.MID);

      if (mood === 'HAPPY')  { bob = Math.round(Math.abs(Math.sin(t*5.5)) * -4);
                               sy += 0.10; sx -= 0.05; accent = P.GRN; }
      if (mood === 'SCARED') { sy -= 0.16; sx += 0.13; accent = P.RED;
                               jx = (self.tick % 2 ? 1 : -1); jy = (self.tick % 3 ? 0 : 1); }
      if (mood === 'ALERT')  { var pop = Math.max(0, 1 - (self.tick - (moodUntil - 12)) / 12);
                               R += pop * 2.5; accent = P.CYN; }
      if (mood === 'SLEEP')  { sy -= 0.12; sx += 0.08; R -= 0.5;
                               bob = Math.round(Math.sin(t * 0.8) * 1.2); }
      if (mood === 'SMUG')   { sx += 0.06; sy -= 0.03; }
      // BRACE — the wind-up. He crouches and squats wide, holding still (the
      // bob is killed) so the release has something to spring from. Deliberately
      // the OPPOSITE deformation to HAPPY/ALERT: compressing before the impact
      // is what makes the impact read as a release rather than a jolt.
      if (mood === 'BRACE')  { sy -= 0.13; sx += 0.10; R -= 0.6;
                               bob = Math.round(Math.sin(t * 1.7) * 0.4);
                               accent = P.CYN; }

      var cx = W/2 + jx, cy = H/2 + 1 + bob + jy;
      var LX = -0.55, LY = -0.68, LZ = 0.48;   // single light source, upper-left

      for (var y = 0; y < H; y++) for (var x = 0; x < W; x++) {
        var dx = (x + 0.5 - cx) / sx, dy = (y + 0.5 - cy) / sy;
        var d = Math.sqrt(dx*dx + dy*dy), th = Math.atan2(dy, dx);

        // Sine harmonics aliasing against the grid — the aliasing is the look.
        var wob = 1
          + 0.055 * Math.sin(3*th + t*1.10)
          + 0.038 * Math.sin(5*th - t*0.80)
          + 0.026 * Math.sin(2*th + t*0.55);
        if (mood === 'SCARED') wob += 0.03 * Math.sin(9*th + t*9);
        var r = R * wob;
        if (d > r) continue;

        // Outline drawn inside the silhouette so edges stay crisp.
        if (d > r - 1.15) { px(x, y, P.OUT); continue; }

        var nd = d / r, nz = Math.sqrt(Math.max(0, 1 - nd*nd));
        var lam = (dx/r)*LX + (dy/r)*LY + nz*LZ;
        var v = Math.max(0, Math.min(1, lam * 0.92 + 0.30));
        var rim = Math.pow(nd, 3.2) * 0.9;
        var bay = BAYER[(y % 4) * 4 + (x % 4)];

        var idx = Math.round(v * (BODY.length - 1) + bay * 1.05);
        idx = Math.max(1, Math.min(BODY.length - 1, idx));
        var c = BODY[idx].slice();

        if (rim > 0.30 + bay * 0.30) {
          var k = Math.min(0.72, rim);
          c[0] += (accent[0]-c[0])*k; c[1] += (accent[1]-c[1])*k; c[2] += (accent[2]-c[2])*k;
        }
        px(x, y, c);
      }

      // ── Face ──────────────────────────────────────────────────────────────
      var fy = Math.round(cy) - 2;
      var CX = Math.round(cx);
      // A lid that TRAVELS. It was a hard cut — full eye, 1px line, full eye —
      // which at 10fps reads as the eye vanishing for two frames rather than as
      // a blink. Half-closed on the way down and again on the way up is the
      // entire difference, and at this framerate those are the only frames a
      // blink even has. 3 ticks = 300ms, the whole gesture.
      var blinkLeft = blinkUntil - self.tick;      // 3 closing, 2 shut, 1 opening
      var blinking = blinkLeft > 0;
      var lidShut = blinkLeft === 2;
      var lidHalf = blinking && !lidShut;
      // Eyes drift toward the move — unless he is deliberately looking at
      // something, in which case the glance wins until it decays.
      var look = Math.round(p * 1.6);
      if (self.tick < lookUntil) look = Math.round(lookX * 2.4);

      if (self.visor) {
        rect(CX-9, fy-2, 18, 5, P.OUT);
        var vc = (mood === 'SCARED') ? P.RED
               : ((mood === 'HAPPY' || p > 0.05) ? P.GRN : P.CYN);
        var sweep = Math.round(Math.sin(t * 2.2) * 5);
        for (var i = -8; i <= 8; i++) {
          rect(CX+i, fy-1, 1, 3, Math.abs(i - sweep) < 2 ? P.WHT : vc);
        }
        if (mood === 'SLEEP') rect(CX-9, fy-2, 18, 5, P.LO);
      } else if (lidShut || mood === 'SLEEP') {
        rect(CX-7+look, fy+1, 5, 1, P.EYE); rect(CX+3+look, fy+1, 5, 1, P.EYE);
      } else if (lidHalf) {
        // Bottom half of the open eye. The glint survives the half-lid — losing
        // it would blank the eye and put us back at the hard cut.
        rect(CX-7+look, fy+1, 5, 3, P.EYE); rect(CX+3+look, fy+1, 5, 3, P.EYE);
        px(CX-6+look, fy+1, P.WHT); px(CX+4+look, fy+1, P.WHT);
      } else if (mood === 'HAPPY') {
        [-7, 3].forEach(function(ox) {
          px(CX+ox, fy+1, P.EYE); px(CX+ox+1, fy, P.EYE);
          px(CX+ox+2, fy-1, P.EYE); px(CX+ox+3, fy, P.EYE); px(CX+ox+4, fy+1, P.EYE);
        });
      } else if (mood === 'SMUG') {
        rect(CX-7, fy, 5, 1, P.EYE);   rect(CX+3, fy, 5, 1, P.EYE);
        rect(CX-7, fy+1, 5, 2, P.EYE); rect(CX+3, fy+1, 5, 2, P.EYE);
      } else if (mood === 'BRACE') {
        // Narrowed, and hard over toward whatever he is about to work — the
        // glance is doing the pointing, this is the squint that sells intent.
        // Wide eyes here would read as SCARED; the wind-up is focus, not fear.
        var bl = Math.round(lookX * 3);
        rect(CX-7+bl, fy, 5, 3, P.EYE); rect(CX+3+bl, fy, 5, 3, P.EYE);
        px(CX-6+bl, fy+1, P.WHT); px(CX+4+bl, fy+1, P.WHT);
      } else {
        var ew = mood === 'SCARED' ? 6 : 5;
        rect(CX-7+look, fy-1, ew, ew, P.EYE); rect(CX+3+look, fy-1, ew, ew, P.EYE);
        var gx = mood === 'SCARED' ? 1 : 0;
        px(CX-6+look+gx, fy, P.WHT); px(CX+4+look+gx, fy, P.WHT);
        // BOUNCE LIGHT, lower-right — opposite the key, which is upper-left
        // (see LX/LY). One glint reads as a dot painted ON the eye; two read as
        // light wrapping a sphere. Cheapest depth in the whole face, 2 pixels.
        // P.HI not P.WHT: a second full-white would compete with the key and
        // flatten both back into dots.
        px(CX-7+look+ew-2, fy+2, P.HI); px(CX+3+look+ew-2, fy+2, P.HI);
        if (mood === 'ALERT') { px(CX-5+look, fy+1, P.CYN); px(CX+5+look, fy+1, P.CYN); }
      }

      // ── Brows ─────────────────────────────────────────────────────────────
      // Drawn AFTER the eyes so a heavy brow can overlap the eye's top row —
      // that overlap is what a scowl IS. Suppressed under the visor, which
      // already owns the whole brow line.
      var B = BROWS[mood] || BROWS.IDLE;
      if (B.on && !self.visor) {
        // fy already carries the bob (it derives from cy), so brows ride the
        // face for free — no separate offset.
        var by = fy - 4 + B.drop;
        var inner = Math.round(5 * B.tilt);   // where the left brow's inner end lands
        brow(CX-8, by, 6, B.tilt, B.th);
        // SMUG lifts ONLY the right one. A symmetric smirk is just a face; the
        // asymmetry IS the smugness, and it costs one number.
        brow(CX+3, by + inner - (mood === 'SMUG' ? 3 : 0), 6, -B.tilt, B.th);
      }

      var my = fy + 8;
      if (mood === 'HAPPY') {
        rect(CX-3, my, 7, 1, P.EYE);   rect(CX-4, my-1, 1, 1, P.EYE);
        rect(CX+4, my-1, 1, 1, P.EYE); rect(CX-2, my+1, 5, 1, P.EYE);
      } else if (mood === 'SCARED') { rect(CX-2, my-1, 5, 4, P.EYE); }
      else if (mood === 'ALERT')    { rect(CX-2, my-1, 5, 3, P.EYE); }
      else if (mood === 'SLEEP')    { rect(CX-1, my, 3, 1, P.EYE); }
      else if (mood === 'SMUG')     { rect(CX-3, my, 5, 1, P.EYE); rect(CX+2, my-1, 2, 1, P.EYE); }
      // BRACE — a small tight line. Held breath.
      else if (mood === 'BRACE')    { rect(CX-1, my, 3, 2, P.EYE); }
      else                          { rect(CX-2, my, 5, 1, P.EYE); }

      // ── FX particles ──────────────────────────────────────────────────────
      fx = fx.filter(function(f) { return f.life-- > 0; });
      fx.forEach(function(f) {
        f.y += f.vy;
        var X = Math.round(f.x), Y = Math.round(f.y);
        if (f.t === 'spark') {
          var c = f.life > 4 ? P.GRN : P.WHT;
          px(X,Y,c); px(X-1,Y,c); px(X+1,Y,c); px(X,Y-1,c); px(X,Y+1,c);
        } else if (f.t === 'sweat') { rect(X,Y,2,3,P.CYN); px(X,Y-1,P.CYN); }
        else if (f.t === 'bang')    { rect(X,Y,2,5,P.CYN); rect(X,Y+6,2,2,P.CYN); }
      });
      if (mood === 'SLEEP' && self.tick % 22 === 0) {
        fx.push({ t:'spark', x:W*0.75, y:H*0.33, life:16, vy:-0.3 });
      }

      ctx.putImageData(img, 0, 0);
      if (self.onAccent) self.onAccent(accent);
    }

    function loop() {
      self.tick++;
      if (moodUntil > 0 && self.tick > moodUntil) { self.mood = 'IDLE'; moodUntil = -1; }
      if (self.tick > nextBlink) {
        blinkUntil = self.tick + 3;    // 3 ticks = closing / shut / opening
        nextBlink = self.tick + 30 + Math.random() * 50;
      }
      draw();
    }

    // ── Public API ──────────────────────────────────────────────────────────
    var api = {
      start: function() {
        if (!self.timer) self.timer = setInterval(loop, 1000 / FPS);
        return api;
      },
      stop: function() { clearInterval(self.timer); self.timer = null; return api; },

      // Transient moods pass durTicks and decay back to IDLE.
      setMood: function(m, durTicks) {
        if (MOODS.indexOf(m) < 0) return api;
        self.mood = m;
        moodUntil = durTicks ? self.tick + durTicks : -1;
        if (m === 'HAPPY') {
          for (var i = 0; i < 7; i++) {
            fx.push({ t:'spark', x:W/2 + (Math.random()*30-15), y:H*0.42 + (Math.random()*16-8),
                      life:8 + Math.random()*7, vy:-0.35 });
          }
        }
        if (m === 'SCARED') fx.push({ t:'sweat', x:W*0.69, y:H*0.35, life:14, vy:0.5 });
        if (m === 'ALERT')  fx.push({ t:'bang',  x:W/2,     y:H*0.17, life:12, vy:-0.1 });
        return api;
      },
      setPnl:   function(pct) { self.pnl = pct; return api; },
      setVisor: function(on)  { self.visor = !!on; return api; },

      // Look at something. dx is -1 (hard left) .. +1 (hard right); durTicks
      // decays back to the P&L drift, same as a transient mood. Used to glance
      // at a tile a beat BEFORE it lands — which is what makes him read as
      // placing it rather than reacting to it.
      glance: function(dx, durTicks) {
        lookX = Math.max(-1, Math.min(1, dx));
        lookUntil = self.tick + (durTicks || 12);
        return api;
      },

      getMood:  function()    { return self.mood; },
      // His heartbeat, exposed. On a headless box "is he animating?" cannot be
      // answered by looking, and hashing the canvas cannot tell a frozen loop
      // from a loop drawing an identical frame. This can.
      getTick:  function()    { return self.tick; },
      isRunning: function()   { return !!self.timer; },
      MOODS: MOODS
    };
    return api;
  }

  global.TNDBlob = { create: create, PALETTE: P, MOODS: MOODS };

})(window);
