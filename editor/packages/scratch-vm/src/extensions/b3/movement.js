const {MAX_AMOUNT, clamp} = require('./menus');

const CM_PER_INCH = 2.54;

/**
 * Wheel speeds for a driving base. The left motor is mounted mirrored, so driving
 * forward turns it counterclockwise (negative). Steering -100..100: the inner wheel
 * slows down by 1 - |steering|/50 (0 at 50 = pivot, reversed at 100 = spin).
 * @param speed
 * @param steering
 */
const wheelSpeeds = (speed, steering) => {
    const s = clamp(steering, -100, 100);
    const factor = 1 - (Math.abs(s) / 50);
    let left = speed;
    let right = speed;
    if (s > 0) right = speed * factor;
    if (s < 0) left = speed * factor;
    return {left: -Math.round(left) || 0, right: Math.round(right) || 0};
};

const toDegrees = (value, unit, cmPerRotation) => {
    switch (unit) {
    case 'cm': return value / cmPerRotation * 360;
    case 'in': return value * CM_PER_INCH / cmPerRotation * 360;
    case 'rotations': return value * 360;
    case 'degrees': return value;
    default: return null;
    }
};

const pairRunArgs = (movement, steering, value, unit) => {
    if (Number.isNaN(value) || value === 0 || movement.speed === 0) return null;
    const speed = value < 0 ? -movement.speed : movement.speed;
    const amount = Math.abs(value);
    const {left, right} = wheelSpeeds(speed, steering);
    const base = {left: movement.left, right: movement.right, left_speed: left, right_speed: right};
    if (unit === 'seconds') {
        const seconds = Math.min(amount, MAX_AMOUNT.seconds);
        return {...base, unit: 'seconds', left_value: seconds, right_value: seconds};
    }
    const raw = toDegrees(amount, unit, movement.cmPerRotation);
    const fastest = Math.max(Math.abs(left), Math.abs(right));
    if (raw === null || fastest === 0) return null;
    const degrees = Math.min(raw, MAX_AMOUNT.degrees);
    return {
        left: movement.left,
        right: movement.right,
        unit: 'degrees',
        left_value: degrees * Math.abs(left) / fastest,
        right_value: degrees * Math.abs(right) / fastest,
        left_speed: left,
        right_speed: right
    };
};

module.exports = {wheelSpeeds, toDegrees, pairRunArgs};
