const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const Cast = require('../../util/cast');
const {getHub} = require('./hub');
const {fail, requireDevice, send} = require('./run');
const {COLORS, PORT_MENU} = require('./menus');
const M = require('./matrix');

const clamp100 = value => Math.min(100, Math.max(0, Math.round(Cast.toNumber(value))));

const PATTERNS = [
    {text: 'all white', value: 'wwwwwwwww'},
    {text: 'all red', value: 'rrrrrrrrr'},
    {text: 'all green', value: 'ggggggggg'},
    {text: 'all blue', value: 'bbbbbbbbb'},
    {text: 'all yellow', value: 'yyyyyyyyy'},
    {text: 'cross', value: 'rkrkrkrkr'},
    {text: 'frame', value: 'bbbbkbbbb'}
];

class Scratch3FlipperLight {
    constructor (runtime) {
        this.runtime = runtime;
        this.hub = getHub(runtime);
        this.matrices = {};
        runtime.on('PROJECT_START', () => {
            this.matrices = {};
        });
    }

    getInfo () {
        const port = {type: ArgumentType.STRING, menu: 'PORT', defaultValue: 'A'};
        const pattern = {type: ArgumentType.STRING, menu: 'PATTERN', defaultValue: 'wwwwwwwww'};
        return {
            id: 'flipperlight',
            name: 'Light',
            color1: COLORS.light[0],
            color2: COLORS.light[1],
            color3: COLORS.light[2],
            blocks: [
                {opcode: 'ultrasonicLightUp',
                    blockType: BlockType.COMMAND,
                    text: 'light up [PORT] with [VALUE]',
                    arguments: {PORT: port, VALUE: {type: ArgumentType.STRING, defaultValue: '100 100 100 100'}}},
                '---',
                {opcode: 'lightColorMatrixImageOn',
                    blockType: BlockType.COMMAND,
                    text: 'turn on [PORT] [PATTERN]',
                    arguments: {PORT: port, PATTERN: pattern}},
                {opcode: 'lightColorMatrixImageOnForTime',
                    blockType: BlockType.COMMAND,
                    text: 'turn on [PORT] [PATTERN] for [DURATION] seconds',
                    arguments: {PORT: port, PATTERN: pattern, DURATION: {type: ArgumentType.NUMBER, defaultValue: 2}}},
                {opcode: 'lightColorMatrixOff',
                    blockType: BlockType.COMMAND,
                    text: 'turn off [PORT]',
                    arguments: {PORT: port}},
                {opcode: 'lightColorMatrixSetPixel',
                    blockType: BlockType.COMMAND,
                    text: 'set [PORT] pixel [X] , [Y] to [COLOR] [BRIGHTNESS] %',
                    arguments: {PORT: port,
                        X: {type: ArgumentType.NUMBER, defaultValue: 1},
                        Y: {type: ArgumentType.NUMBER, defaultValue: 1},
                        COLOR: {type: ArgumentType.STRING, menu: 'MATRIX_COLOR', defaultValue: 'red'},
                        BRIGHTNESS: {type: ArgumentType.NUMBER, defaultValue: 100}}},
                {opcode: 'lightColorMatrixSetBrightness',
                    blockType: BlockType.COMMAND,
                    text: 'set [PORT] brightness to [BRIGHTNESS] %',
                    arguments: {PORT: port, BRIGHTNESS: {type: ArgumentType.NUMBER, defaultValue: 100}}},
                {opcode: 'lightColorMatrixRotate',
                    blockType: BlockType.COMMAND,
                    text: 'rotate [PORT] [DIRECTION]',
                    arguments: {PORT: port,
                        DIRECTION: {type: ArgumentType.STRING, menu: 'ROTATE', defaultValue: 'clockwise'}}},
                {opcode: 'lightColorMatrixSetOrientation',
                    blockType: BlockType.COMMAND,
                    text: 'set [PORT] orientation to [ORIENTATION]',
                    arguments: {PORT: port,
                        ORIENTATION: {type: ArgumentType.STRING, menu: 'ORIENTATION', defaultValue: 'upright'}}}
            ],
            menus: {
                PORT: PORT_MENU,
                PATTERN: {acceptReporters: true, items: PATTERNS},
                MATRIX_COLOR: {acceptReporters: true,
                    items: M.MATRIX_COLORS.map(c => (c === 'black' ? {text: 'off', value: 'black'} : c))},
                ROTATE: {acceptReporters: false,
                    items: [{text: '↻ clockwise', value: 'clockwise'},
                        {text: '↺ counterclockwise', value: 'counterclockwise'}]},
                ORIENTATION: {acceptReporters: false,
                    items: [{text: 'upright', value: 'upright'}, {text: 'left', value: 'left'},
                        {text: 'right', value: 'right'}, {text: 'upside down', value: 'upsidedown'}]}
            }
        };
    }

    ultrasonicLightUp (args, util) {
        if (!requireDevice(this.hub, util, args.PORT, ['distance'], 'Distance Sensor')) return;
        const values = String(args.VALUE).trim()
            .split(/[\s,]+/)
            .slice(0, 4)
            .map(clamp100);
        while (values.length < 4) values.push(0);
        return send(this.hub, util, 'sensor.lights', {port: args.PORT, values});
    }

    _matrix (port, util) {
        if (!requireDevice(this.hub, util, port, ['matrix'], '3x3 Color Light Matrix')) return null;
        if (!this.matrices[port]) this.matrices[port] = M.newMatrix();
        return this.matrices[port];
    }

    _show (port, util) {
        return send(this.hub, util, 'matrix.set', {port, pixels: M.render(this.matrices[port])});
    }

    _pattern (args, util) {
        const colors = M.parsePattern(args.PATTERN);
        if (!colors) {
            fail(this.hub, util,
                `Port ${args.PORT}: pattern "${args.PATTERN}" must be 9 colour letters (k p l b c t g y o r w)`,
                args.PORT);
        }
        return colors;
    }

    lightColorMatrixImageOn (args, util) {
        const matrix = this._matrix(args.PORT, util);
        const colors = matrix && this._pattern(args, util);
        if (!colors) return;
        M.showPattern(matrix, colors);
        return this._show(args.PORT, util);
    }

    // Waits on the thread's stack timer like Scratch's "wait": Stop kills the thread, so
    // the "off" frame never runs after Stop.
    lightColorMatrixImageOnForTime (args, util) {
        if (util.stackTimerNeedsInit()) {
            const matrix = this._matrix(args.PORT, util);
            const colors = matrix && this._pattern(args, util);
            if (!colors) return;
            M.showPattern(matrix, colors);
            this._show(args.PORT, util); // not awaited: the block waits on its timer
            util.startStackTimer(Math.max(0, Cast.toNumber(args.DURATION)) * 1000);
            util.yield();
        } else if (util.stackTimerFinished()) {
            M.clear(this.matrices[args.PORT]);
            return this._show(args.PORT, util);
        } else {
            util.yield();
        }
    }

    lightColorMatrixOff (args, util) {
        const matrix = this._matrix(args.PORT, util);
        if (!matrix) return;
        M.clear(matrix);
        return this._show(args.PORT, util);
    }

    lightColorMatrixSetPixel (args, util) {
        const matrix = this._matrix(args.PORT, util);
        if (!matrix) return;
        const color = String(args.COLOR).toLowerCase();
        if (!M.setPixel(matrix, Cast.toNumber(args.X), Cast.toNumber(args.Y), color, Cast.toNumber(args.BRIGHTNESS))) {
            return;
        }
        return this._show(args.PORT, util);
    }

    lightColorMatrixSetBrightness (args, util) {
        const matrix = this._matrix(args.PORT, util);
        if (!matrix) return;
        matrix.brightness = clamp100(args.BRIGHTNESS);
        return this._show(args.PORT, util);
    }

    lightColorMatrixRotate (args, util) {
        const matrix = this._matrix(args.PORT, util);
        if (!matrix) return;
        M.rotate(matrix, args.DIRECTION);
        return this._show(args.PORT, util);
    }

    lightColorMatrixSetOrientation (args, util) {
        const matrix = this._matrix(args.PORT, util);
        if (!matrix || !M.ORIENTATIONS.includes(args.ORIENTATION)) return;
        matrix.orientation = args.ORIENTATION;
        return this._show(args.PORT, util);
    }
}

module.exports = Scratch3FlipperLight;
