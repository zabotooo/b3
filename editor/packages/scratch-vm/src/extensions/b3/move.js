const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const Cast = require('../../util/cast');
const {getHub} = require('./hub');
const {send} = require('./run');
const {wheelSpeeds, pairRunArgs} = require('./movement');
const {COLORS, toSpeed} = require('./menus');

const DIRECTION_STEERING = {forward: [0, 1], back: [0, -1], right: [100, 1], left: [-100, 1]};
const PAIRS = ['A+B', 'A+C', 'A+D', 'B+A', 'B+C', 'B+D', 'C+A', 'C+B', 'C+D', 'D+A', 'D+B', 'D+C'];
const UNITS = ['cm', 'in', 'rotations', 'degrees', 'seconds'];

class Scratch3FlipperMove {
    constructor (runtime) {
        this.runtime = runtime;
        this.hub = getHub(runtime);
    }

    getInfo () {
        const value = {type: ArgumentType.NUMBER, defaultValue: 10};
        const unit = {type: ArgumentType.STRING, menu: 'UNIT', defaultValue: 'cm'};
        const dir = {type: ArgumentType.STRING, menu: 'DIRECTION', defaultValue: 'forward'};
        const steering = {type: ArgumentType.NUMBER, defaultValue: 30};
        return {
            id: 'flippermove',
            name: 'Movement',
            color1: COLORS.move[0],
            color2: COLORS.move[1],
            color3: COLORS.move[2],
            blocks: [
                {opcode: 'move',
                    blockType: BlockType.COMMAND,
                    text: 'move [DIRECTION] for [VALUE] [UNIT]',
                    arguments: {DIRECTION: dir, VALUE: value, UNIT: unit}},
                {opcode: 'startMove',
                    blockType: BlockType.COMMAND,
                    text: 'start moving [DIRECTION]',
                    arguments: {DIRECTION: dir}},
                {opcode: 'steer',
                    blockType: BlockType.COMMAND,
                    text: 'move [STEERING] for [VALUE] [UNIT]',
                    arguments: {STEERING: steering, VALUE: value, UNIT: unit}},
                {opcode: 'startSteer',
                    blockType: BlockType.COMMAND,
                    text: 'start moving [STEERING]',
                    arguments: {STEERING: steering}},
                {opcode: 'stopMove', blockType: BlockType.COMMAND, text: 'stop moving'},
                {opcode: 'movementSpeed',
                    blockType: BlockType.COMMAND,
                    text: 'set movement speed to [SPEED] %',
                    arguments: {SPEED: {type: ArgumentType.NUMBER, defaultValue: 50}}},
                {opcode: 'setMovementPair',
                    blockType: BlockType.COMMAND,
                    text: 'set movement motors to [PAIR]',
                    arguments: {PAIR: {type: ArgumentType.STRING, menu: 'PAIR', defaultValue: 'A+B'}}},
                {opcode: 'setDistance',
                    blockType: BlockType.COMMAND,
                    text: 'set 1 motor rotation to [DISTANCE] [UNIT]',
                    arguments: {DISTANCE: {type: ArgumentType.NUMBER, defaultValue: 17.5},
                        UNIT: {type: ArgumentType.STRING, menu: 'DISTANCE_UNIT', defaultValue: 'cm'}}}
            ],
            menus: {
                DIRECTION: {acceptReporters: false,
                    items: [
                        {text: '⬆ forward', value: 'forward'}, {text: '⬇ back', value: 'back'},
                        {text: '↻ right', value: 'right'}, {text: '↺ left', value: 'left'}]},
                UNIT: {acceptReporters: false, items: UNITS},
                PAIR: {acceptReporters: false, items: PAIRS},
                DISTANCE_UNIT: {acceptReporters: false, items: ['cm', 'in']}
            }
        };
    }

    _run (steering, sign, args, util) {
        const runArgs = pairRunArgs(this.hub.movement, steering, sign * Cast.toNumber(args.VALUE), args.UNIT);
        if (!runArgs) return;
        return send(this.hub, util, 'pair.run_for', runArgs);
    }

    _start (steering, sign, util) {
        const {left, right} = wheelSpeeds(sign * this.hub.movement.speed, steering);
        return send(this.hub, util, 'pair.start', {left: this.hub.movement.left,
            right: this.hub.movement.right,
            left_speed: left,
            right_speed: right});
    }

    move (args, util) {
        const [steering, sign] = DIRECTION_STEERING[args.DIRECTION] || DIRECTION_STEERING.forward;
        return this._run(steering, sign, args, util);
    }

    startMove (args, util) {
        const [steering, sign] = DIRECTION_STEERING[args.DIRECTION] || DIRECTION_STEERING.forward;
        return this._start(steering, sign, util);
    }

    steer (args, util) {
        return this._run(Cast.toNumber(args.STEERING), 1, args, util);
    }

    startSteer (args, util) {
        return this._start(Cast.toNumber(args.STEERING), 1, util);
    }

    stopMove (args, util) {
        return send(this.hub, util, 'pair.stop', {left: this.hub.movement.left, right: this.hub.movement.right});
    }

    movementSpeed (args) {
        this.hub.movement.speed = toSpeed(args.SPEED);
    }

    setMovementPair (args) {
        const [left, right] = String(args.PAIR).split('+');
        if (left && right && left !== right) {
            this.hub.movement.left = left;
            this.hub.movement.right = right;
        }
    }

    setDistance (args) {
        const distance = Cast.toNumber(args.DISTANCE);
        if (distance <= 0) return;
        const cm = args.UNIT === 'in' ? distance * 2.54 : distance;
        this.hub.movement.cmPerRotation = Math.round(cm * 1000) / 1000;
    }
}

module.exports = Scratch3FlipperMove;
