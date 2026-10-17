const Cast = require('../../util/cast');

/** Category colours [primary, secondary, tertiary], close to SPIKE's for familiarity. */
const COLORS = {
    motor: ['#0090F5', '#0081DC', '#0072C4'],
    move: ['#FF4CCD', '#E544B8', '#CC3DA4'],
    events: ['#FFBF00', '#E6AC00', '#CC9900'],
    control: ['#FFAB19', '#EC9C13', '#CF8B17'],
    sensors: ['#4CBFE6', '#44ABCF', '#3D99B8'],
    operator: ['#59C059', '#46B946', '#389438'],
    light: ['#9966FF', '#855CD6', '#774DCB'],
    sound: ['#CF63CF', '#C94FC9', '#BD42BD']
};

const PORT_MENU = {acceptReporters: false, items: ['A', 'B', 'C', 'D']};
const DIRECTION_MENU = {acceptReporters: false,
    items: [
        {text: '↻ clockwise', value: 'clockwise'},
        {text: '↺ counterclockwise', value: 'counterclockwise'}
    ]};

const MOTOR_KINDS = ['motor_abs', 'motor_rel', 'motor_passive'];
const ENCODER_KINDS = ['motor_abs', 'motor_rel'];

/** Largest amounts hatd accepts for motor.run_for / pair.run_for. */
const MAX_AMOUNT = {degrees: 1000000, seconds: 3600};

const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
const toSpeed = value => clamp(Math.round(Cast.toNumber(value)), -100, 100);
const wrap360 = n => ((Math.round(n) % 360) + 360) % 360;

module.exports = {COLORS, PORT_MENU, DIRECTION_MENU, MOTOR_KINDS, ENCODER_KINDS, MAX_AMOUNT, clamp, toSpeed, wrap360};
