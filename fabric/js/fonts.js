// Font stacks read from assets/fonts/fonts.css, for the canvases.

// font stacks of assets/fonts/fonts.css (Poppins -> Helvetica; Inter Black for numbers), also used by the canvases
const cssVar = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const FONT_TEXT = cssVar('--font-text') || 'Helvetica, sans-serif', FONT_MONO = cssVar('--font-mono') || 'Helvetica, monospace';

export { cssVar, FONT_TEXT, FONT_MONO };
