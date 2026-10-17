/**
 * WeDo 2.0 Tilt Sensor: hatd reports buildhat's mode 0 as tilt [x, y] in degrees.
 * Which sign means forward/right has not been checked on hardware yet; if the blocks
 * report the opposite direction, swap the signs here.
 */
const TILT_THRESHOLD = 10;

const TILT_MENU = {acceptReporters: false, items: ['forward', 'backward', 'left', 'right', 'any']};

const tiltDirection = tilt => {
    const [x, y] = Array.isArray(tilt) ? tilt.map(Number) : [0, 0];
    if (Math.max(Math.abs(x), Math.abs(y)) < TILT_THRESHOLD) return 'level';
    if (Math.abs(y) >= Math.abs(x)) return y > 0 ? 'forward' : 'backward';
    return x > 0 ? 'right' : 'left';
};

const isTiltedAs = (tilt, option) => {
    const direction = tiltDirection(tilt);
    return option === 'any' ? direction !== 'level' : direction === option;
};

module.exports = {TILT_THRESHOLD, TILT_MENU, tiltDirection, isTiltedAs};
