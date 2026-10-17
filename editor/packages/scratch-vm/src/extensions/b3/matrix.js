/**
 * State of a SPIKE 3×3 Color Light Matrix. hatd's matrix.set needs all nine pixels every
 * time, so the editor keeps the image, the brightness and the orientation per port.
 * Pixels are row-major, top row first, as hatd expects.
 */

const MATRIX_COLORS = ['black', 'pink', 'lilac', 'blue', 'cyan', 'turquoise',
    'green', 'yellow', 'orange', 'red', 'white'];
// One letter per colour for patterns typed as text; k (black) is off.
const LETTERS = Object.fromEntries([
    ['k', 'black'], ['p', 'pink'], ['l', 'lilac'], ['b', 'blue'], ['c', 'cyan'], ['t', 'turquoise'],
    ['g', 'green'], ['y', 'yellow'], ['o', 'orange'], ['r', 'red'], ['w', 'white']
]);
const ORIENTATIONS = ['upright', 'right', 'upsidedown', 'left']; // quarter turns clockwise

const blank = () => Array.from({length: 9}, () => ({color: 'black', level: 0}));
const newMatrix = () => ({pixels: blank(), brightness: 100, orientation: 'upright'});

const parsePattern = text => {
    const letters = [...String(text).toLowerCase()
        .replace(/[\s,]/g, '')];
    if (letters.length !== 9 || letters.some(ch => !LETTERS[ch])) return null;
    return letters.map(ch => LETTERS[ch]);
};

const showPattern = (matrix, colors) => {
    matrix.pixels = colors.map(color => ({color, level: color === 'black' ? 0 : 100}));
};

const clear = matrix => {
    matrix.pixels = blank();
};

const setPixel = (matrix, x, y, color, level) => {
    const column = Math.round(x);
    const row = Math.round(y);
    if (!(column >= 1 && column <= 3 && row >= 1 && row <= 3) || !MATRIX_COLORS.includes(color)) return false;
    matrix.pixels[((row - 1) * 3) + (column - 1)] = {color, level: Math.min(100, Math.max(0, Math.round(level)))};
    return true;
};

// new[row][col] = old[2 - col][row]
const turnClockwise = pixels => [6, 3, 0, 7, 4, 1, 8, 5, 2].map(i => pixels[i]);

const rotate = (matrix, direction) => {
    const turns = direction === 'counterclockwise' ? 3 : 1;
    for (let i = 0; i < turns; i++) matrix.pixels = turnClockwise(matrix.pixels);
};

const render = matrix => {
    let shown = matrix.pixels;
    for (let i = 0; i < ORIENTATIONS.indexOf(matrix.orientation); i++) shown = turnClockwise(shown);
    return shown.map(({color, level}) => [color, Math.round(level * matrix.brightness / 1000)]);
};

module.exports = {MATRIX_COLORS, ORIENTATIONS, newMatrix, parsePattern, showPattern, clear, setPixel, rotate, render};
