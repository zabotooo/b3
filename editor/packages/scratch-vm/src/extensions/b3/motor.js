const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const Cast = require('../../util/cast');
const {getHub} = require('./hub');
const {send, requireDevice} = require('./run');
const {
    COLORS, PORT_MENU, DIRECTION_MENU, MOTOR_KINDS, ENCODER_KINDS, MAX_AMOUNT, toSpeed, wrap360
} = require('./menus');

const port = {type: ArgumentType.STRING, menu: 'PORT', defaultValue: 'A'};
const direction = {type: ArgumentType.STRING, menu: 'DIRECTION', defaultValue: 'clockwise'};
const GO_TO_DIRECTIONS = {shortest: 'shortest', clockwise: 'cw', counterclockwise: 'ccw'};

class Scratch3FlipperMotor {
    constructor (runtime) {
        this.runtime = runtime;
        this.hub = getHub(runtime);
    }

    getInfo () {
        return {
            id: 'flippermotor',
            name: 'Motors',
            color1: COLORS.motor[0],
            color2: COLORS.motor[1],
            color3: COLORS.motor[2],
            blocks: [
                {opcode: 'motorTurnForDirection',
                    blockType: BlockType.COMMAND,
                    text: '[PORT] run [DIRECTION] for [VALUE] [UNIT]',
                    arguments: {PORT: port,
                        DIRECTION: direction,
                        VALUE: {type: ArgumentType.NUMBER, defaultValue: 1},
                        UNIT: {type: ArgumentType.STRING, menu: 'UNIT', defaultValue: 'rotations'}}},
                {opcode: 'motorGoDirectionToPosition',
                    blockType: BlockType.COMMAND,
                    text: '[PORT] go [DIRECTION] to position [POSITION]',
                    arguments: {PORT: port,
                        DIRECTION: {type: ArgumentType.STRING, menu: 'GO_TO_DIRECTION', defaultValue: 'shortest'},
                        POSITION: {type: ArgumentType.NUMBER, defaultValue: 0}}},
                {opcode: 'motorStartDirection',
                    blockType: BlockType.COMMAND,
                    text: '[PORT] start motor [DIRECTION]',
                    arguments: {PORT: port, DIRECTION: direction}},
                {opcode: 'motorStop',
                    blockType: BlockType.COMMAND,
                    text: '[PORT] stop motor',
                    arguments: {PORT: port}},
                {opcode: 'motorSetSpeed',
                    blockType: BlockType.COMMAND,
                    text: '[PORT] set speed to [SPEED] %',
                    arguments: {PORT: port, SPEED: {type: ArgumentType.NUMBER, defaultValue: 75}}},
                {opcode: 'absolutePosition',
                    blockType: BlockType.REPORTER,
                    text: '[PORT] position',
                    arguments: {PORT: port}},
                {opcode: 'speed',
                    blockType: BlockType.REPORTER,
                    text: '[PORT] speed',
                    arguments: {PORT: port}}
            ],
            menus: {
                PORT: PORT_MENU,
                DIRECTION: DIRECTION_MENU,
                UNIT: {acceptReporters: false, items: ['rotations', 'degrees', 'seconds']},
                GO_TO_DIRECTION: {acceptReporters: false,
                    items: [
                        {text: 'shortest path', value: 'shortest'},
                        {text: '↻ clockwise', value: 'clockwise'},
                        {text: '↺ counterclockwise', value: 'counterclockwise'}
                    ]}
            }
        };
    }

    _signedSpeed (portName, dir) {
        const speed = this.hub.speeds[portName];
        return dir === 'counterclockwise' ? -speed : speed;
    }

    motorTurnForDirection (args, util) {
        let value = Cast.toNumber(args.VALUE);
        let speed = this._signedSpeed(args.PORT, args.DIRECTION);
        if (value < 0) {
            value = -value;
            speed = -speed;
        }
        if (value === 0 || speed === 0) return;
        const unit = args.UNIT === 'seconds' ? 'seconds' : 'degrees';
        if (args.UNIT === 'rotations') value *= 360;
        value = Math.min(value, MAX_AMOUNT[unit]);
        return send(this.hub, util, 'motor.run_for', {port: args.PORT, unit, value, speed});
    }

    motorGoDirectionToPosition (args, util) {
        const speed = Math.abs(this.hub.speeds[args.PORT]);
        if (speed === 0) return;
        return send(this.hub, util, 'motor.go_to', {
            port: args.PORT,
            position: wrap360(Cast.toNumber(args.POSITION)),
            direction: GO_TO_DIRECTIONS[args.DIRECTION] || 'shortest',
            speed
        });
    }

    motorStartDirection (args, util) {
        return send(this.hub, util, 'motor.start',
            {port: args.PORT, speed: this._signedSpeed(args.PORT, args.DIRECTION)});
    }

    motorStop (args, util) {
        return send(this.hub, util, 'motor.stop', {port: args.PORT});
    }

    motorSetSpeed (args) {
        this.hub.speeds[args.PORT] = toSpeed(args.SPEED);
    }

    absolutePosition (args, util) {
        const device = requireDevice(this.hub, util, args.PORT, ENCODER_KINDS, 'motor with encoder');
        if (!device) return 0;
        return wrap360(device.kind === 'motor_abs' ? device.aposition : device.position);
    }

    speed (args, util) {
        const device = requireDevice(this.hub, util, args.PORT, MOTOR_KINDS, 'motor');
        if (!device) return 0;
        return device.kind === 'motor_passive' ? device.power : device.speed;
    }
}

module.exports = Scratch3FlipperMotor;
