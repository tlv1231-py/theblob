// ═══════════════════════════════════════════════════════════════════════════
// STREAM BACKGROUND — retro command center
//
// Fills the whole 1080x1920 stage, including the bands YouTube will paint over.
// That is deliberate: everything in here is ATMOSPHERE, never information, so
// losing the top and bottom 380px to chrome costs nothing. The rule is that you
// could crop this layer to the safe box and lose zero meaning.
//
// Two decisions carry the whole thing:
//
//   HALF-RESOLUTION BUFFER. The canvas backing store is 540x960, upscaled to
//   1080x1920 by CSS with image-rendering:pixelated. That is 4x cheaper to
//   fill — this runs unattended for hours next to a 10fps Blob — AND every
//   star lands on a chunky 2px grid, which is what makes it read 8-bit instead
//   of like a screensaver. Cheaper and more correct at once.
//
//   SQUARES, NOT CIRCLES. home_nav.js draws its stars with ctx.arc. Here they
//   are fillRect. A round star on a pixel-art stage is the tell that breaks it.
//
// Everything reacts. pulse() is called on real trades and on stream events, so
// the scene is never merely decorative — the drift is idle, the flashes mean
// something happened.
// ═══════════════════════════════════════════════════════════════════════════

(function(global) {

  function create(canvas, opts) {
    opts = opts || {};
    var FPS = opts.fps || 24;          // enough to feel alive, cheap enough to leave running
    var W = 540, H = 960;              // half of 1080x1920 — see header
    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    var t = 0, timer = null;

    // ── Stars — three depth layers, ported from home_nav.js but quantized ────
    // Palette is the dashboard's: purple near, cyan mid, blue-white far.
    var LAYERS = [
      { count: 90, speed: 0.06, size: 1, a: 0.30, c: [200, 200, 255] },  // far
      { count: 34, speed: 0.16, size: 1, a: 0.42, c: [0, 229, 255] },    // mid
      { count: 16, speed: 0.34, size: 2, a: 0.55, c: [180, 0, 255] },    // near
    ];
    var stars = [];
    LAYERS.forEach(function(l) {
      for (var i = 0; i < l.count; i++) {
        stars.push({
          x: Math.random() * W, y: Math.random() * H,
          sp: l.speed * (0.7 + Math.random() * 0.6),
          size: l.size, a: l.a * (0.6 + Math.random() * 0.4), c: l.c,
          tw: Math.random() * 6.28          // twinkle phase
        });
      }
    });

    // ── Nebula — slow drifting colour fields ────────────────────────────────
    var nebula = [
      { x: 0.18, y: 0.22, r: 0.42, c: [148, 0, 255], a: 0.10, sx: 0.00009, sy: 0.00006 },
      { x: 0.80, y: 0.70, r: 0.38, c: [255, 0, 204], a: 0.07, sx: -0.00007, sy: 0.00005 },
      { x: 0.50, y: 0.92, r: 0.45, c: [0, 229, 255], a: 0.05, sx: 0.00005, sy: -0.00008 },
    ];

    // ── Drones — little pixel craft on patrol ───────────────────────────────
    // They cross the stage, blink, and occasionally drop a scan line. Kept few
    // and small: they should be noticed on the second viewing, not the first.
    var drones = [];
    for (var d = 0; d < 3; d++) {
      drones.push({
        x: Math.random() * W, y: 60 + Math.random() * (H - 120),
        vx: (Math.random() < 0.5 ? -1 : 1) * (0.10 + Math.random() * 0.14),
        bob: Math.random() * 6.28, blink: Math.random() * 6.28,
        c: [[0, 229, 255], [255, 0, 204], [148, 0, 255]][d % 3]
      });
    }

    // ── Data columns — scrolling code, deep background ──────────────────────
    var GLYPH = '01<>[]{}/\\|=+*#$%&';
    var cols = [];
    for (var c2 = 0; c2 < 14; c2++) {
      cols.push({
        x: Math.floor(Math.random() * W),
        y: Math.random() * H,
        sp: 0.25 + Math.random() * 0.5,
        len: 6 + Math.floor(Math.random() * 10),
        chars: [],
        a: 0.05 + Math.random() * 0.07
      });
      for (var g = 0; g < 20; g++) {
        cols[c2].chars.push(GLYPH[Math.floor(Math.random() * GLYPH.length)]);
      }
    }

    // ── LEDs — a rack of status lights down both margins ────────────────────
    // These live in the side reserved strips on purpose: pure decoration, and
    // the first thing YouTube's action rail will cover.
    var leds = [];
    for (var i2 = 0; i2 < 22; i2++) {
      leds.push({
        x: i2 % 2 === 0 ? 6 : W - 8,
        y: 40 + (i2 >> 1) * 82 + Math.random() * 20,
        ph: Math.random() * 6.28,
        rate: 0.4 + Math.random() * 2.2,
        c: [[0, 255, 157], [0, 229, 255], [255, 0, 204], [255, 153, 0]][i2 % 4]
      });
    }

    // ── Reactive layer ──────────────────────────────────────────────────────
    // Shockwaves and sparks spawned by real events. This is the difference
    // between a wallpaper and a scene that is watching the same trades you are.
    var waves = [], sparks = [];

    function px(x, y, w, h, c, a) {
      ctx.fillStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')';
      ctx.fillRect(x | 0, y | 0, w, h);
    }

    function draw() {
      t += 1 / FPS;
      ctx.clearRect(0, 0, W, H);

      // Nebula — the only smooth thing here; it reads as depth, not as a sprite.
      nebula.forEach(function(n) {
        n.x += n.sx; n.y += n.sy;
        if (n.x < -0.2 || n.x > 1.2) n.sx *= -1;
        if (n.y < -0.2 || n.y > 1.2) n.sy *= -1;
        var g = ctx.createRadialGradient(n.x * W, n.y * H, 0, n.x * W, n.y * H, n.r * W);
        g.addColorStop(0, 'rgba(' + n.c[0] + ',' + n.c[1] + ',' + n.c[2] + ',' + n.a + ')');
        g.addColorStop(1, 'rgba(' + n.c[0] + ',' + n.c[1] + ',' + n.c[2] + ',0)');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      });

      // Data columns — behind the stars so they read as distant.
      ctx.font = '7px monospace';
      cols.forEach(function(col) {
        col.y += col.sp;
        if (col.y - col.len * 8 > H) { col.y = -10; col.x = Math.floor(Math.random() * W); }
        for (var i = 0; i < col.len; i++) {
          var yy = col.y - i * 8;
          if (yy < -8 || yy > H) continue;
          var fade = col.a * (1 - i / col.len);
          ctx.fillStyle = 'rgba(148,0,255,' + fade + ')';
          ctx.fillText(col.chars[(i + (t * 4 | 0)) % col.chars.length], col.x, yy);
        }
      });

      // Stars — squares, drifting, twinkling.
      stars.forEach(function(s) {
        s.x -= s.sp;
        if (s.x < -2) { s.x = W + 2; s.y = Math.random() * H; }
        var tw = 0.75 + 0.25 * Math.sin(t * 2 + s.tw);
        px(s.x, s.y, s.size, s.size, s.c, s.a * tw);
      });

      // Drones.
      drones.forEach(function(dr) {
        dr.x += dr.vx;
        if (dr.x < -14) dr.x = W + 14;
        if (dr.x > W + 14) dr.x = -14;
        var y = dr.y + Math.sin(t * 0.8 + dr.bob) * 4;
        // hull
        px(dr.x - 3, y - 1, 6, 3, [40, 0, 60], 0.9);
        px(dr.x - 4, y, 8, 1, dr.c, 0.5);
        // beacon
        var b = 0.35 + 0.65 * Math.abs(Math.sin(t * 3 + dr.blink));
        px(dr.x - 1, y - 2, 2, 1, dr.c, b);
        // thruster trail
        var dir = dr.vx > 0 ? -1 : 1;
        px(dr.x + dir * 5, y, 3, 1, dr.c, 0.16 * b);
      });

      // LEDs.
      leds.forEach(function(l) {
        var on = 0.2 + 0.8 * (0.5 + 0.5 * Math.sin(t * l.rate + l.ph));
        px(l.x, l.y, 2, 2, l.c, 0.5 * on);
      });

      // Shockwaves — a ring from the middle of the stage on a real event.
      for (var w = waves.length - 1; w >= 0; w--) {
        var wv = waves[w];
        wv.r += wv.sp;
        wv.a *= 0.94;
        if (wv.a < 0.02) { waves.splice(w, 1); continue; }
        // Quantized ring: 40 sampled points drawn as pixels, not a stroked arc.
        for (var k = 0; k < 40; k++) {
          var ang = (k / 40) * 6.283;
          px(wv.x + Math.cos(ang) * wv.r, wv.y + Math.sin(ang) * wv.r, 2, 2, wv.c, wv.a);
        }
      }

      // Sparks.
      for (var s2 = sparks.length - 1; s2 >= 0; s2--) {
        var sp = sparks[s2];
        sp.x += sp.vx; sp.y += sp.vy; sp.vy += 0.02; sp.life--;
        if (sp.life <= 0) { sparks.splice(s2, 1); continue; }
        px(sp.x, sp.y, 2, 2, sp.c, Math.min(1, sp.life / 20));
      }
    }

    var api = {
      start: function() { if (!timer) timer = setInterval(draw, 1000 / FPS); return api; },
      stop: function() { clearInterval(timer); timer = null; return api; },

      // Called on real trades and stream events. kind: 'win' | 'loss' | 'enter'
      // | 'money'. The scene answers the same feed the Blob does.
      pulse: function(kind, originY) {
        var c = kind === 'win' ? [0, 255, 157]
              : kind === 'loss' ? [255, 51, 102]
              : kind === 'money' ? [0, 255, 157]
              : [0, 229, 255];
        var y = originY != null ? originY * H : H * 0.42;
        waves.push({ x: W / 2, y: y, r: 4, sp: kind === 'money' ? 5 : 3,
                     a: kind === 'money' ? 0.55 : 0.3, c: c });
        var n = kind === 'money' ? 18 : 7;
        for (var i = 0; i < n; i++) {
          var ang = Math.random() * 6.283, spd = 0.6 + Math.random() * 2.2;
          sparks.push({ x: W / 2, y: y, vx: Math.cos(ang) * spd, vy: Math.sin(ang) * spd,
                        life: 18 + Math.random() * 26, c: c });
        }
        return api;
      }
    };
    return api;
  }

  global.TNDBg = { create: create };

})(window);
