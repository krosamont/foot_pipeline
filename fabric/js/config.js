// Match data, tunable parameters (P), small math helpers and the cloth grid size.

const M = window.MATCH, CAM = window.CAMERA;
// ?layout=portrait: a 9:16 stage for phones (pitch along the height, scoreboard on top, momentum bar at the bottom);
// without it the stage is the 1257 x 835 of the reference video
const PORTRAIT = /layout=portrait/.test(location.search);
const W = PORTRAIT ? 720 : 1257, H = PORTRAIT ? 1280 : 835;
if (PORTRAIT) {
  document.documentElement.classList.add('portrait');
  for (const id of ['sky', 'pulse', 'fx']) { const c = document.getElementById(id); if (c) { c.width = W; c.height = H; } }
}
const RENDER_MODE = /render=1/.test(location.search);
// ?theme=light: the light version of data-workers.com (beige paper, ink); see .light in index.html
const LIGHT_THEME = /theme=light/.test(location.search);
if (LIGHT_THEME) document.documentElement.classList.add('light');

// ------------------------------------------------------------------ tunables
const P = {
  BASE_DWELL: 0.50, SHOT_DWELL: 0.12, SHOT_DWELL_XG: 0.7, GOAL_PAUSE: 3.5, PEN_PAUSE: 8.0, END_HOLD: 3.0,
  
  SEAM_K: 84, SEAM_DAMP: 1.117, FLOOD_K: 400, FLOOD_AT: 1.14, UNFLOOD_AT: 2.2, 
  MOM_DOM: 0.35, RESTART_TAU: 195, CENTER_K: 16, FOUL_HOLD: 35, FOUL_SNAP: 12, FOLLOW_TAU: 0.5, B_MARGIN: 3, B_SIG: 16, B_MIN: 0.5, B_DIFF: 0.25, B_DIFF_DT: 0.7, FRONT_V: 45, FRONT_SLOW_MAX: 4, V_MAX: 70, LAG_REF: 90, GOAL_HOLD: 30, FOUL_HOLD_FRONT: 8, GOAL_SLOW: 1.7, FOUL_SLOW: 0.7, HALF_SLOW: 4.5, HALF_FLAT: 1.8, FOUL_RESET: 1.4, HALF_RESET: 1.6, RESET_V: 18, PERC_MARGIN: 3, PERC_SIG: 7, PERC_SIG_C: 4, PERC_V: 30, PERC_RISE_MIN: 0.6, PERC_RISE_MAX: 2.0, PERC_HOLD: 0.35, PERC_HOLD_FOUL: 0.6, PERC_DECAY: 1.3, PERC_LEAD: 0.25, FOUL_MARGIN: 2, PERC_MIN_MOVE: 0.3, GOAL_CALM: 1.7, SWING_V: 45, SWING_MAX: 2.5, FOUL_LINE_HOLD: 0.6, CARD_SLOW: 1.6, CARD_FX: 2.6, DIR_HOLD: 0.5, V_LANE: 110, DIR_MAX_WAIT: 0.6, TOP_LIFT: 0.3, TINT_LIFE: 1.2, TINT_NEAR: 8, GOAL_BUILD: 5, SKY_DOM_FULL: 0.3, RELIEF_CAP: 14, COUNTER_WAVE: 18, SHOT_WAVE: 14, TACKLE_H: 7, TACKLE_R: 18, PENMISS_PAUSE: 4.2, KICK_PAUSE: 1.5, SHOT_SLOW: 0.9, SHOT_SLOW_T: 8, CW_W: 9, CW_D: 7, CW_S: 6, CW_EDGE: 6, GAIN_WAVE: 14, MAP_SHIFT_Y: 30, PULSE_Y: 710, SHOT_PEAK: 16, SHOT_PEAK_TAU: 1.2, GAIN_TAU: 1.2, GAIN_REF: 15, TIP_LIFE: 40, HILL_OUT: 2, HILL_FADE: 2.5, SET_H_CORNER: 8, SET_H_FK: 7, SET_R: 30, SET_TAU: 1.1, SHOT_BASE: 4, SHOT_BASE_R: 24, RESTART_HOLD: 25, RESTART_RAMP: 120, CALM_DOWN: 0.45, CALM_UP: 1.2, G_BASE: 0.05, FOUL_FLAT: 150, FLASH_DUR: 1.1, OVERLAP: 2.5,
  XG_BASE: 9, XG_SCALE: 0, HILL_W0: 7, HILL_WXG: 55, ADV_H: 8, ADV_XT_REF: 0.03, ADV_R: 13, ADV_RX: 22, ADV_TAU: 0.7, PERC_H: 6, PERC_XG: 0, PERC_WXG: 30, HILL_TAU_A: 260, HILL_TAU_S: 150, HILL_S1: 16, TIP_XG: 0,
  GOAL_H: 48.6, GOAL_R: 20.7, PEN_WAVE: 11,
  TOP_H: 20, BASE: 2.0, EDGE_X: 0.35, EDGE_Y: 0.45, RISE_A: 28, PEAK_D: 16, PEAK_S: 22, BACK_LV: 0.7, FRONT_F: 0.15, FRONT_W: 14, LIP_H: 10, LIP_D: 5, LIP_W: 3.5, RAMP_H: 3, RAMP_W: 22, LOW_H: 2,
  STR_FLOOR: 0.55, STR_GAIN: 3, DOM_TAU: 0.4, DOM_HYST: 0.03, PIN_Y: 14, H_TAU: 0.2, THICK: 1.6,
  LIGHT: [-0.45, 0.8, 0.35],
};
if (PORTRAIT) P.PULSE_Y = H - 140;   // momentum bar near the bottom of the tall stage
Object.assign(P, window.PARAMS || {});

const lp = (cur, target, tau, dt) => cur + (target - cur) * (1 - Math.exp(-dt / Math.max(1e-4, tau)));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const sm = (x) => { x = clamp(x, 0, 1); return x * x * (3 - 2 * x); };
const NX = 211, NY = 137, DX = 0.5, NL = 35;

export { M, CAM, W, H, PORTRAIT, RENDER_MODE, LIGHT_THEME, P, lp, clamp, sm, NX, NY, DX, NL };
