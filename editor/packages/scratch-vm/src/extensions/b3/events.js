const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const Cast = require('../../util/cast');
const {getHub} = require('./hub');
const {deviceOfKind} = require('./run');
const {COLORS, PORT_MENU} = require('./menus');
const {
    COLOR_KINDS, DISTANCE_KINDS, FORCE_KINDS, COLOR_MENU, DISTANCE_UNIT_MENU, PRESS_MENU,
    distanceIn, isPressedAs, timerSeconds
} = require('./sensors');

class Scratch3FlipperEvents {
    constructor (runtime) {
        this.runtime = runtime;
        this.hub = getHub(runtime);
        runtime.on('PROJECT_START', () => runtime.startHats('flipperevents_whenProgramStarts'));
        // Like SPIKE, sensor/timer/condition hats (SPIKE's and B3's WeDo hats) only fire
        // while a program runs.
        const gated = ['flipperevents_', 'b3events_'];
        runtime.edgeHatGate = opcode => !gated.some(prefix => opcode.startsWith(prefix)) || this.hub.running;
    }

    getInfo () {
        const port = {type: ArgumentType.STRING, menu: 'PORT', defaultValue: 'A'};
        return {
            id: 'flipperevents',
            name: 'Events',
            color1: COLORS.events[0],
            color2: COLORS.events[1],
            color3: COLORS.events[2],
            blocks: [
                {opcode: 'whenProgramStarts',
                    blockType: BlockType.HAT,
                    text: 'when program starts',
                    isEdgeActivated: false},
                {opcode: 'whenColor',
                    blockType: BlockType.HAT,
                    text: 'when [PORT] color is [COLOR]',
                    arguments: {PORT: port, COLOR: {type: ArgumentType.STRING, menu: 'COLOR', defaultValue: 'red'}}},
                {opcode: 'whenPressed',
                    blockType: BlockType.HAT,
                    text: 'when [PORT] is [OPTION]',
                    arguments: {PORT: port,
                        OPTION: {type: ArgumentType.STRING, menu: 'PRESS', defaultValue: 'pressed'}}},
                {opcode: 'whenDistance',
                    blockType: BlockType.HAT,
                    text: 'when [PORT] is [COMPARATOR] [VALUE] [UNIT]',
                    arguments: {PORT: port,
                        COMPARATOR: {type: ArgumentType.STRING, menu: 'DISTANCE_COMPARATOR', defaultValue: 'closer'},
                        VALUE: {type: ArgumentType.NUMBER, defaultValue: 15},
                        UNIT: {type: ArgumentType.STRING, menu: 'DISTANCE_UNIT', defaultValue: 'cm'}}},
                {opcode: 'whenTimer',
                    blockType: BlockType.HAT,
                    text: 'when timer > [VALUE]',
                    arguments: {VALUE: {type: ArgumentType.NUMBER, defaultValue: 5}}},
                {opcode: 'whenCondition',
                    blockType: BlockType.HAT,
                    text: 'when [CONDITION]',
                    arguments: {CONDITION: {type: ArgumentType.BOOLEAN}}}
            ],
            menus: {
                PORT: PORT_MENU,
                COLOR: COLOR_MENU,
                PRESS: PRESS_MENU,
                DISTANCE_UNIT: DISTANCE_UNIT_MENU,
                DISTANCE_COMPARATOR: {acceptReporters: false,
                    items: [
                        {text: 'closer than', value: 'closer'}, {text: 'farther than', value: 'farther'}]}
            }
        };
    }

    whenProgramStarts () {
        return true;
    }

    whenColor (args) {
        const device = deviceOfKind(this.hub, args.PORT, COLOR_KINDS);
        return Boolean(device) && device.color === args.COLOR;
    }

    whenPressed (args) {
        const device = deviceOfKind(this.hub, args.PORT, FORCE_KINDS);
        return Boolean(device) && isPressedAs(device, args.OPTION);
    }

    whenDistance (args) {
        const device = deviceOfKind(this.hub, args.PORT, DISTANCE_KINDS);
        if (!device) return false;
        const value = distanceIn(device, args.UNIT);
        const limit = Cast.toNumber(args.VALUE);
        return args.COMPARATOR === 'farther' ? value > limit : value < limit;
    }

    whenTimer (args) {
        return timerSeconds(this.hub) > Cast.toNumber(args.VALUE);
    }

    whenCondition (args) {
        return Cast.toBoolean(args.CONDITION);
    }
}

module.exports = Scratch3FlipperEvents;
