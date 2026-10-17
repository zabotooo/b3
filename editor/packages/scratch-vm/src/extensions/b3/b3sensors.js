const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const {getHub} = require('./hub');
const {requireDevice} = require('./run');
const {COLORS, PORT_MENU} = require('./menus');
const {TILT_MENU, tiltDirection, isTiltedAs} = require('./wedo');

/** WeDo 2.0 sensors: not in SPIKE, shown in the Sensors category. */
class B3Sensors {
    constructor (runtime) {
        this.runtime = runtime;
        this.hub = getHub(runtime);
    }

    getInfo () {
        const port = {type: ArgumentType.STRING, menu: 'PORT', defaultValue: 'A'};
        return {
            id: 'b3sensors',
            name: 'Sensors',
            color1: COLORS.sensors[0],
            color2: COLORS.sensors[1],
            color3: COLORS.sensors[2],
            blocks: [
                {opcode: 'tiltDirection',
                    blockType: BlockType.REPORTER,
                    text: 'WeDo tilt [PORT] direction',
                    arguments: {PORT: port}},
                {opcode: 'isTilted',
                    blockType: BlockType.BOOLEAN,
                    text: 'WeDo tilt [PORT] is [DIRECTION] ?',
                    arguments: {PORT: port,
                        DIRECTION: {type: ArgumentType.STRING, menu: 'TILT', defaultValue: 'forward'}}},
                {opcode: 'motionDistance',
                    blockType: BlockType.REPORTER,
                    text: 'WeDo motion [PORT] distance',
                    arguments: {PORT: port}}
            ],
            menus: {PORT: PORT_MENU, TILT: TILT_MENU}
        };
    }

    _tilt (port, util) {
        const device = requireDevice(this.hub, util, port, ['wedo_tilt'], 'WeDo 2.0 Tilt Sensor');
        return device ? device.tilt : null;
    }

    tiltDirection (args, util) {
        const tilt = this._tilt(args.PORT, util);
        return tilt ? tiltDirection(tilt) : '';
    }

    isTilted (args, util) {
        const tilt = this._tilt(args.PORT, util);
        return Boolean(tilt) && isTiltedAs(tilt, args.DIRECTION);
    }

    motionDistance (args, util) {
        const device = requireDevice(this.hub, util, args.PORT, ['wedo_motion'], 'WeDo 2.0 Motion Sensor');
        return device ? device.distance : 0;
    }
}

module.exports = B3Sensors;
