const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const Cast = require('../../util/cast');
const {getHub} = require('./hub');
const {requireDevice} = require('./run');
const {COLORS, PORT_MENU} = require('./menus');

const COLOR_KINDS = ['color', 'color_distance'];
const DISTANCE_KINDS = ['distance', 'color_distance'];
const FORCE_KINDS = ['force'];
const HARD_PRESS_N = 8;
const CD_DISTANCE_NONE = 10;

const COLOR_MENU = {acceptReporters: true,
    items: [
        'black', 'violet', 'blue', 'cyan', 'green', 'yellow', 'red', 'white', {text: 'no color', value: 'none'}]};
const COMPARATOR_MENU = {acceptReporters: false, items: ['<', '>', '=']};
const DISTANCE_UNIT_MENU = {acceptReporters: false, items: ['cm', 'in', '%']};
const PRESS_MENU = {acceptReporters: false,
    items: [
        {text: 'pressed', value: 'pressed'}, {text: 'hard pressed', value: 'hardpressed'},
        {text: 'released', value: 'released'}]};

const distanceCm = device => {
    if (device.kind === 'distance') {
        return device.distance_mm < 0 ? Infinity : device.distance_mm / 10;
    }
    // BOOST Color & Distance reports 0..10; 10 also means nothing in front of it.
    // Linear fit of hatd/docs/hardware-notes.md "C&D distance calibration".
    if (device.distance >= CD_DISTANCE_NONE) return Infinity;
    return (device.distance * 3) + 1;
};

const distanceIn = (device, unit) => {
    const cm = distanceCm(device);
    if (unit === 'in') return cm / 2.54;
    if (unit === '%') return Math.min(100, cm / 2);
    return cm;
};

const forceIn = (device, unit) => (unit === '%' ? device.force_n * 10 : device.force_n);

const isPressedAs = (device, option) => {
    if (option === 'released') return !device.pressed;
    if (option === 'hardpressed') return device.force_n >= HARD_PRESS_N;
    return Boolean(device.pressed);
};

const compare = (a, op, b) => {
    if (op === '<') return a < b;
    if (op === '>') return a > b;
    return Math.abs(a - b) < 0.5;
};

const timerSeconds = hub => (Date.now() - hub.timerStart) / 1000;

class Scratch3FlipperSensors {
    constructor (runtime) {
        this.runtime = runtime;
        this.hub = getHub(runtime);
    }

    getInfo () {
        const port = {type: ArgumentType.STRING, menu: 'PORT', defaultValue: 'A'};
        const comparator = {type: ArgumentType.STRING, menu: 'COMPARATOR', defaultValue: '<'};
        return {
            id: 'flippersensors',
            name: 'Sensors',
            color1: COLORS.sensors[0],
            color2: COLORS.sensors[1],
            color3: COLORS.sensors[2],
            blocks: [
                {opcode: 'isColor',
                    blockType: BlockType.BOOLEAN,
                    text: '[PORT] is color [COLOR] ?',
                    arguments: {PORT: port, COLOR: {type: ArgumentType.STRING, menu: 'COLOR', defaultValue: 'red'}}},
                {opcode: 'color', blockType: BlockType.REPORTER, text: '[PORT] color', arguments: {PORT: port}},
                {opcode: 'isReflectivity',
                    blockType: BlockType.BOOLEAN,
                    text: '[PORT] reflected light [COMPARATOR] [VALUE] % ?',
                    arguments: {PORT: port,
                        COMPARATOR: comparator,
                        VALUE: {type: ArgumentType.NUMBER, defaultValue: 50}}},
                {opcode: 'reflectivity',
                    blockType: BlockType.REPORTER,
                    text: '[PORT] reflected light',
                    arguments: {PORT: port}},
                '---',
                {opcode: 'isDistance',
                    blockType: BlockType.BOOLEAN,
                    text: '[PORT] is distance [COMPARATOR] [VALUE] [UNIT] ?',
                    arguments: {PORT: port,
                        COMPARATOR: comparator,
                        VALUE: {type: ArgumentType.NUMBER, defaultValue: 15},
                        UNIT: {type: ArgumentType.STRING, menu: 'DISTANCE_UNIT', defaultValue: 'cm'}}},
                {opcode: 'distance',
                    blockType: BlockType.REPORTER,
                    text: '[PORT] distance in [UNIT]',
                    arguments: {PORT: port,
                        UNIT: {type: ArgumentType.STRING, menu: 'DISTANCE_UNIT', defaultValue: 'cm'}}},
                '---',
                {opcode: 'isPressed',
                    blockType: BlockType.BOOLEAN,
                    text: '[PORT] is [OPTION] ?',
                    arguments: {PORT: port,
                        OPTION: {type: ArgumentType.STRING, menu: 'PRESS', defaultValue: 'pressed'}}},
                {opcode: 'force',
                    blockType: BlockType.REPORTER,
                    text: '[PORT] pressure in [UNIT]',
                    arguments: {PORT: port,
                        UNIT: {type: ArgumentType.STRING, menu: 'FORCE_UNIT', defaultValue: '%'}}},
                '---',
                {opcode: 'timer', blockType: BlockType.REPORTER, text: 'timer'},
                {opcode: 'resetTimer', blockType: BlockType.COMMAND, text: 'reset timer'}
            ],
            menus: {
                PORT: PORT_MENU,
                COLOR: COLOR_MENU,
                COMPARATOR: COMPARATOR_MENU,
                DISTANCE_UNIT: DISTANCE_UNIT_MENU,
                PRESS: PRESS_MENU,
                FORCE_UNIT: {acceptReporters: false, items: ['%', 'N']}
            }
        };
    }

    _color (port, util) {
        return requireDevice(this.hub, util, port, COLOR_KINDS, 'Color Sensor');
    }

    isColor (args, util) {
        const device = this._color(args.PORT, util);
        return Boolean(device) && device.color === args.COLOR;
    }

    color (args, util) {
        const device = this._color(args.PORT, util);
        return device ? device.color : '';
    }

    isReflectivity (args, util) {
        const device = this._color(args.PORT, util);
        return Boolean(device) && compare(device.reflection, args.COMPARATOR, Cast.toNumber(args.VALUE));
    }

    reflectivity (args, util) {
        const device = this._color(args.PORT, util);
        return device ? device.reflection : 0;
    }

    isDistance (args, util) {
        const device = requireDevice(this.hub, util, args.PORT, DISTANCE_KINDS, 'Distance Sensor');
        return Boolean(device) &&
            compare(distanceIn(device, args.UNIT), args.COMPARATOR, Cast.toNumber(args.VALUE));
    }

    distance (args, util) {
        const device = requireDevice(this.hub, util, args.PORT, DISTANCE_KINDS, 'Distance Sensor');
        if (!device) return 0;
        const value = distanceIn(device, args.UNIT);
        return Number.isFinite(value) ? Math.round(value * 100) / 100 : -1;
    }

    isPressed (args, util) {
        const device = requireDevice(this.hub, util, args.PORT, FORCE_KINDS, 'Force Sensor');
        return Boolean(device) && isPressedAs(device, args.OPTION);
    }

    force (args, util) {
        const device = requireDevice(this.hub, util, args.PORT, FORCE_KINDS, 'Force Sensor');
        return device ? forceIn(device, args.UNIT) : 0;
    }

    timer () {
        return timerSeconds(this.hub);
    }

    resetTimer () {
        this.hub.timerStart = Date.now();
    }
}

module.exports = Scratch3FlipperSensors;
Object.assign(module.exports, {
    COLOR_KINDS,
    DISTANCE_KINDS,
    FORCE_KINDS,
    COLOR_MENU,
    COMPARATOR_MENU,
    DISTANCE_UNIT_MENU,
    PRESS_MENU,
    distanceIn,
    forceIn,
    isPressedAs,
    compare,
    timerSeconds
});
