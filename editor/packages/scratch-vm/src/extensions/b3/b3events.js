const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const Cast = require('../../util/cast');
const {getHub} = require('./hub');
const {deviceOfKind} = require('./run');
const {COLORS, PORT_MENU} = require('./menus');
const {TILT_MENU, isTiltedAs} = require('./wedo');

/** WeDo 2.0 hats: not in SPIKE, shown in the Events category; gated like SPIKE hats (events.js). */
class B3Events {
    constructor (runtime) {
        this.runtime = runtime;
        this.hub = getHub(runtime);
    }

    getInfo () {
        const port = {type: ArgumentType.STRING, menu: 'PORT', defaultValue: 'A'};
        return {
            id: 'b3events',
            name: 'Events',
            color1: COLORS.events[0],
            color2: COLORS.events[1],
            color3: COLORS.events[2],
            blocks: [
                {opcode: 'whenTilted',
                    blockType: BlockType.HAT,
                    text: 'when WeDo tilt [PORT] is [DIRECTION]',
                    arguments: {PORT: port,
                        DIRECTION: {type: ArgumentType.STRING, menu: 'TILT', defaultValue: 'forward'}}},
                {opcode: 'whenMotion',
                    blockType: BlockType.HAT,
                    text: 'when WeDo motion [PORT] detects something closer than [VALUE]',
                    arguments: {PORT: port, VALUE: {type: ArgumentType.NUMBER, defaultValue: 5}}}
            ],
            menus: {PORT: PORT_MENU, TILT: TILT_MENU}
        };
    }

    whenTilted (args) {
        const device = deviceOfKind(this.hub, args.PORT, ['wedo_tilt']);
        return Boolean(device) && isTiltedAs(device.tilt, args.DIRECTION);
    }

    whenMotion (args) {
        const device = deviceOfKind(this.hub, args.PORT, ['wedo_motion']);
        return Boolean(device) && device.distance < Cast.toNumber(args.VALUE);
    }
}

module.exports = B3Events;
