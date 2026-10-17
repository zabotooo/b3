const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const Cast = require('../../util/cast');
const {getHub} = require('./hub');
const {requireDevice, send} = require('./run');
const {COLORS, PORT_MENU} = require('./menus');

/** Powered Up Light 88005: not in SPIKE, shown in the Light category. */
class B3Light {
    constructor (runtime) {
        this.runtime = runtime;
        this.hub = getHub(runtime);
    }

    getInfo () {
        const port = {type: ArgumentType.STRING, menu: 'PORT', defaultValue: 'A'};
        return {
            id: 'b3light',
            name: 'Light',
            color1: COLORS.light[0],
            color2: COLORS.light[1],
            color3: COLORS.light[2],
            blocks: [
                {opcode: 'setBrightness',
                    blockType: BlockType.COMMAND,
                    text: 'set light [PORT] brightness to [BRIGHTNESS] %',
                    arguments: {PORT: port, BRIGHTNESS: {type: ArgumentType.NUMBER, defaultValue: 100}}},
                {opcode: 'off',
                    blockType: BlockType.COMMAND,
                    text: 'turn off light [PORT]',
                    arguments: {PORT: port}}
            ],
            menus: {PORT: PORT_MENU}
        };
    }

    _set (port, brightness, util) {
        if (!requireDevice(this.hub, util, port, ['light'], 'Light')) return;
        return send(this.hub, util, 'light.set', {port, brightness});
    }

    setBrightness (args, util) {
        return this._set(args.PORT, Math.min(100, Math.max(0, Math.round(Cast.toNumber(args.BRIGHTNESS)))), util);
    }

    off (args, util) {
        return this._set(args.PORT, 0, util);
    }
}

module.exports = B3Light;
