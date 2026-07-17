// ═══════════════════════════════════════════════════════════════════════════
// STREAM BACKGROUND — an 80s arcade sidescroller he is travelling through
//
// The starfield is gone. Stars drift; they do not MEAN anything. This scrolls,
// and its horizon RISES when he wins and SINKS when he loses — so the scene is
// a readout you feel instead of read. On a losing run the whole world sinks
// under him, which is the most honest thing on the page.
//
// Fills the whole 1080x1920 stage, reserved bands included. Deliberate:
// everything here is ATMOSPHERE, never information, so losing the top and
// bottom 380 to YouTube's chrome costs nothing. The rule still holds — you
// could crop this layer to the safe box and lose zero meaning.
//
// Three decisions carry it:
//
//   HALF-RESOLUTION BUFFER. 540x960 upscaled to 1080x1920 by CSS with
//   image-rendering:pixelated. 4x cheaper to fill — this runs unattended for
//   hours beside a 10fps Blob — AND every edge lands on a chunky 2px grid,
//   which is what makes it read as a cartridge rather than a screensaver.
//   Cheaper and more correct at once.
//
//   THE CAMERA IS THE DATA. camY eases toward a target that wins push up and
//   losses push down, and everything except the sun parallaxes against it. No
//   number, no arrow, no label: the ground falling away IS the loss.
//
//   LUMPY, NOT SHARP. The hills are three sine harmonics sampled against the
//   pixel grid — the same construction as the Blob's silhouette (BLOB.md), so
//   the world he moves through is made of the same maths he is, and aliases the
//   same way. Sharp triangles would read as a stock synthwave loop; lumps read
//   as a cartoon.
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

    // ── Where things sit ────────────────────────────────────────────────────
    // Buffer coords are half of stage coords. The Blob's box is stage y600-1368
    // = buffer y300-684, and his sprite does not fill it — he is a blob with
    // transparent corners — so a sun behind him HALOS him rather than hiding.
    // The horizon sits at his waist, so the grid runs out from under his feet.
    var SUN_X = W / 2, SUN_Y = 330, SUN_R = 168;
    var HORIZON = 430;                 // camY moves this — see draw()

    // ── Palette — vaporwave proper ──────────────────────────────────────────
    // The sky is a sunset ramp, the ground is a cyan grid, and the only warm
    // colour in the frame is the sun. The pinks and purples are the dashboard's
    // own set, so the world does not look bolted on to the character.
    var SKY = [
      [0.00, [10, 2, 33]],       // near-black violet at the top
      [0.42, [45, 8, 82]],
      [0.72, [122, 16, 128]],
      [0.94, [214, 38, 148]],    // the hot band right above the horizon
      [1.00, [255, 110, 199]]
    ];
    var C_SUN_TOP  = [255, 214, 64];
    var C_SUN_BOT  = [255, 0, 150];
    var C_GRID     = [0, 229, 255];
    var C_HILL_FAR = [26, 0, 51];
    var C_HILL_MID = [16, 0, 34];
    var C_HILL_NEAR= [8, 0, 18];
    var C_RIM      = [255, 0, 204];

    // ── The camera — this is the data ───────────────────────────────────────
    // camTarget is kicked by pulse() and decays back toward level; camY chases
    // it. A win lifts the world, a loss drops it, and a RUN of either compounds,
    // because kicks stack faster than the decay bleeds them off.
    //
    // Clamped hard. Without a ceiling a losing session drives the horizon off
    // the bottom of the buffer inside a minute and the scene becomes plain sky.
    // The clamp is what keeps this a mood rather than a counter.
    var camY = 0, camTarget = 0;
    var CAM_MAX   = 130;               // buffer px of travel either way
    var CAM_DECAY = 0.994;             // per frame — a kick bleeds off over ~10s
    var CAM_EASE  = 0.055;             // how hard camY chases the target

    // ── Scroll ──────────────────────────────────────────────────────────────
    // Constant travel: he is always going somewhere. Speed is NOT tied to P&L —
    // the world's DIRECTION is the signal, and modulating both would make
    // neither legible.
    var scrollX = 0;
    var SCROLL = 0.55;
    // The floor's sweep multiplier. It is the nearest surface in the frame, so
    // it moves hardest — at the hills' rate the ground would look painted on.
    // 2.4 wraps the 46px lattice about every 1.6s: fast enough to read as travel
    // at a glance, slow enough not to strobe against the 3px scanlines.
    var GRID_SWEEP = 2.4;

    // ── The hills ───────────────────────────────────────────────────────────
    // Three sine harmonics per column, rounded to the 2px grid.
    function hillY(x, seed, amp, base) {
      return base
        - Math.sin((x + seed) * 0.011) * amp
        - Math.sin((x + seed) * 0.031) * amp * 0.42
        - Math.sin((x + seed) * 0.071) * amp * 0.17;
    }

    function drawHills(seed, amp, base, col, rim, par) {
      var off = scrollX * par;
      var y0 = base + camY * par;
      ctx.beginPath();
      ctx.moveTo(0, H);
      for (var x = 0; x <= W; x += 2) {
        ctx.lineTo(x, Math.round(hillY(x + off, seed, amp, y0) / 2) * 2);
      }
      ctx.lineTo(W, H);
      ctx.closePath();
      ctx.fillStyle = 'rgb(' + col[0] + ',' + col[1] + ',' + col[2] + ')';
      ctx.fill();

      // Neon rim along the ridge — the one thing keeping a black silhouette from
      // reading as a hole punched in the picture.
      if (!rim) return;
      ctx.beginPath();
      for (var x2 = 0; x2 <= W; x2 += 2) {
        var y2 = Math.round(hillY(x2 + off, seed, amp, y0) / 2) * 2;
        if (x2 === 0) ctx.moveTo(x2, y2); else ctx.lineTo(x2, y2);
      }
      ctx.strokeStyle = 'rgba(' + rim[0] + ',' + rim[1] + ',' + rim[2] + ',' + par + ')';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // ── Reactive layer ──────────────────────────────────────────────────────
    // Kept from the starfield: shockwaves and sparks are the only thing here
    // that fires ON the beat rather than drifting.
    var waves = [], sparks = [];

    function px(x, y, w, h, c, a) {
      ctx.fillStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')';
      ctx.fillRect(x | 0, y | 0, w, h);
    }

    function skyAt(f) {
      for (var i = 1; i < SKY.length; i++) {
        if (f > SKY[i][0]) continue;
        var a = SKY[i - 1], b = SKY[i];
        var k = (f - a[0]) / (b[0] - a[0]);
        return [Math.round(a[1][0] + (b[1][0] - a[1][0]) * k),
                Math.round(a[1][1] + (b[1][1] - a[1][1]) * k),
                Math.round(a[1][2] + (b[1][2] - a[1][2]) * k)];
      }
      return SKY[SKY.length - 1][1];
    }

    function draw() {
      t += 1 / FPS;

      camTarget *= CAM_DECAY;
      if (camTarget >  CAM_MAX) camTarget =  CAM_MAX;
      if (camTarget < -CAM_MAX) camTarget = -CAM_MAX;
      camY += (camTarget - camY) * CAM_EASE;
      scrollX += SCROLL;

      var hz = HORIZON + camY;

      // ── Sky ───────────────────────────────────────────────────────────────
      // BANDED, not smooth: 4px steps, so the ramp quantizes like a 16-colour
      // palette instead of dithering like a photograph.
      for (var y = 0; y < hz; y += 4) {
        px(0, y, W, 4, skyAt(Math.max(0, Math.min(1, y / Math.max(1, hz)))), 1);
      }

      // ── Sun ───────────────────────────────────────────────────────────────
      // Nearly fixed against the camera — it is infinitely far, and a sun that
      // bobbed with the hills would collapse the depth. The horizontal slits are
      // the single most recognisable vaporwave tell; they thicken toward the
      // bottom so the sun appears to sink into its own bands.
      var sy = SUN_Y + camY * 0.12;    // a HINT of parallax, not none
      for (var r = -SUN_R; r <= SUN_R; r += 2) {
        var half = Math.sqrt(Math.max(0, SUN_R * SUN_R - r * r));
        if (half < 1) continue;
        var f = (r + SUN_R) / (2 * SUN_R);          // 0 top .. 1 bottom
        if (f > 0.45) {
          var gap = 2 + Math.floor(((f - 0.45) * 30) / 3);
          if ((r + SUN_R) % (gap + 4) < gap) continue;
        }
        px(SUN_X - half, sy + r, half * 2, 2, [
          Math.round(C_SUN_TOP[0] + (C_SUN_BOT[0] - C_SUN_TOP[0]) * f),
          Math.round(C_SUN_TOP[1] + (C_SUN_BOT[1] - C_SUN_TOP[1]) * f),
          Math.round(C_SUN_TOP[2] + (C_SUN_BOT[2] - C_SUN_TOP[2]) * f)
        ], 1);
      }

      // ── Hills — two ranges behind the horizon, parallaxing ────────────────
      drawHills(0,   26, hz - 6,  C_HILL_FAR, C_RIM, 0.18);
      drawHills(900, 40, hz + 10, C_HILL_MID, C_RIM, 0.36);

      // ── Horizon glow ──────────────────────────────────────────────────────
      px(0, hz - 1, W, 2, [255, 140, 220], 0.75);
      px(0, hz - 4, W, 3, [255, 0, 204], 0.16);

      // ── Grid floor — a SIDESCROLLER, so it moves sideways and only sideways ──
      // The two axes have to agree about which way the world is going. The
      // horizontal rules used to roll toward the viewer, which says "flying
      // forward", while the verticals swept across, which says "travelling
      // sideways" — together they said neither, and the floor read as a shimmer.
      //
      // So: the horizontals are STATIC. They are depth markers, not motion. All
      // the travel lives in the verticals sweeping past, which is what a
      // sidescroller's ground actually does.
      // ── The grid, as a NEON TUBE ──────────────────────────────────────────
      // A vaporwave grid is not a hairline, it is a lit tube: the light BLEEDS.
      // Thin lines are the single thing that makes this look like a wireframe
      // rather than a scene.
      //
      // The bloom is a real shadowBlur, and this is the one place on the stage
      // where a genuine diffused blur is right: phosphor smear is period-correct
      // for the reference, and at half-res upscaled 2x with pixelated rendering
      // the falloff quantizes into visible bands — which is exactly how a CRT
      // actually smears a bright line. It arrives chunky, not airbrushed.
      //
      // ONE path for BOTH axes, stroked twice. That is two blurred operations
      // per frame instead of fifty, which is what makes a real blur affordable
      // on a free-tier ARM box that has to hold this for hours. The crisp cores
      // are drawn afterwards with the blur off, and they carry the depth fade.
      var depth = H - hz;

      // Build the whole lattice once — the halo pass and the core pass walk the
      // same geometry, so they cannot drift apart.
      var rules = [];        // horizontal depth markers: [y, alpha]
      for (var i = 1; i <= 22; i++) {
        var z = i / 22;
        var yy = hz + Math.pow(z, 2.4) * depth;
        if (yy < hz || yy > H) continue;
        rules.push([Math.round(yy / 2) * 2, Math.min(0.6, Math.pow(z, 0.7) * 0.65)]);
      }

      // The verticals carry the whole sidescroll. FASTEST layer in the scene by
      // far (hills run 0.18/0.36/0.62) — parallax says the nearest surface moves
      // most, and at the hills' rate the ground looks painted on.
      //
      // The fan does the perspective for free: each line runs from just off the
      // vanishing point to 3.4x out at the bottom, so its near end sweeps 3.4x
      // faster than its far end. That one ratio is what makes a flat set of
      // lines read as a plane rushing past underneath.
      var GRID_RGB = C_GRID[0] + ',' + C_GRID[1] + ',' + C_GRID[2];

      // The bloom is drawn EXPLICITLY, not with shadowBlur. shadowBlur was tried
      // and is a trap here: the shadow inherits the SOURCE's alpha, so a 10%
      // stroke casts a 10% shadow smeared over 18px, which is nothing. Measured
      // — the falloff came back 1,1,2,2,28,2,2,1,1: a hairline with a rumour of
      // a glow. Cranking the source alpha to fix it lights every rule equally
      // and destroys the depth fade, which is the one thing making this a floor
      // rather than a net.
      //
      // So: concentric bands, widest and faintest first, each pass compositing
      // over the last. It is cheaper than a blur, it is predictable, and it
      // BANDS — which upscaled 2x with pixelated rendering is exactly how a CRT
      // smears a bright line. An airbrushed gaussian would look more correct on
      // a monitor and less correct on this stage.
      //
      // Every band scales by the rule's own depth alpha, so the far rules keep
      // their haze in proportion and the horizon does not light up like the
      // foreground.
      var GLOW = [[8, 0.05], [5, 0.09], [2, 0.15]];   // [half-height, alpha]

      for (var b = 0; b < GLOW.length; b++) {
        var hw = GLOW[b][0], ga = GLOW[b][1];
        for (var r2 = 0; r2 < rules.length; r2++) {
          px(0, rules[r2][0] - hw, W, hw * 2 + 2, C_GRID, ga * rules[r2][1]);
        }
        ctx.beginPath();
        for (var g2 = -14; g2 <= 14; g2++) {
          var gx2 = W / 2 + g2 * 46 - (scrollX * GRID_SWEEP) % 46;
          ctx.moveTo(W / 2 + (gx2 - W / 2) * 0.06, hz);
          ctx.lineTo(W / 2 + (gx2 - W / 2) * 3.4, H);
        }
        ctx.strokeStyle = 'rgba(' + GRID_RGB + ',' + (ga * 0.9) + ')';
        ctx.lineWidth = hw * 2 + 2;
        ctx.stroke();
      }

      // The cores, crisp and full-strength, drawn last so no haze washes over
      // them. This is what keeps the grid a lit TUBE — a hot filament inside a
      // soft envelope — rather than a blurred smear.
      for (var r3 = 0; r3 < rules.length; r3++) {
        px(0, rules[r3][0], W, 2, C_GRID, Math.min(1, rules[r3][1] * 1.5));
      }
      ctx.beginPath();
      for (var g3 = -14; g3 <= 14; g3++) {
        var gx3 = W / 2 + g3 * 46 - (scrollX * GRID_SWEEP) % 46;
        ctx.moveTo(W / 2 + (gx3 - W / 2) * 0.06, hz);
        ctx.lineTo(W / 2 + (gx3 - W / 2) * 3.4, H);
      }
      ctx.strokeStyle = 'rgba(' + GRID_RGB + ',0.5)';
      ctx.lineWidth = 2;
      ctx.stroke();

      // ── Near ridge ────────────────────────────────────────────────────────
      // In FRONT of the grid and almost black: it gives the floor an edge to run
      // behind, which stops the bottom of the frame reading as a flat poster.
      drawHills(4200, 22, H - 40 + camY * 0.7, C_HILL_NEAR, C_RIM, 0.62);

      // ── Shockwaves ────────────────────────────────────────────────────────
      for (var w = waves.length - 1; w >= 0; w--) {
        var wv = waves[w];
        wv.r += wv.sp;
        wv.a *= 0.94;
        if (wv.a < 0.02) { waves.splice(w, 1); continue; }
        // Quantized ring: sampled points drawn as pixels, never a stroked arc —
        // a smooth circle on a pixel stage is the tell that breaks it.
        for (var k = 0; k < 40; k++) {
          var ang = (k / 40) * 6.283;
          px(wv.x + Math.cos(ang) * wv.r, wv.y + Math.sin(ang) * wv.r, 2, 2, wv.c, wv.a);
        }
      }

      // ── Sparks ────────────────────────────────────────────────────────────
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
      //
      // THE CAMERA KICK IS THE POINT. 'enter' deliberately does NOT move it:
      // buying is not yet good or bad news, and a camera lurching on every
      // acquisition would be noise rather than signal.
      pulse: function(kind, originY) {
        var c = kind === 'win' ? [0, 255, 157]
              : kind === 'loss' ? [255, 51, 102]
              : kind === 'money' ? [0, 255, 157]
              : [0, 229, 255];

        if (kind === 'win')        camTarget += 34;
        else if (kind === 'loss')  camTarget -= 34;
        else if (kind === 'money') camTarget += 70;   // a viewer paying lifts it hardest

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
      },

      // For diagnosis on a headless box: "is the world reacting?" is otherwise
      // unanswerable without eyes on the frame.
      getCam: function() { return { y: camY, target: camTarget, horizon: HORIZON + camY }; }
    };
    return api;
  }

  global.TNDBg = { create: create };

})(window);
