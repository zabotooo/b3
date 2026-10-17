const BlockType = require('../../extension-support/block-type');
const {COLORS} = require('./menus');

class Scratch3FlipperControl {
    constructor (runtime) {
        this.runtime = runtime;
    }

    getInfo () {
        return {
            id: 'flippercontrol',
            name: 'Control',
            color1: COLORS.control[0],
            color2: COLORS.control[1],
            color3: COLORS.control[2],
            blocks: [
                {opcode: 'stopOtherStacks', blockType: BlockType.COMMAND, text: 'stop other stacks'}
            ]
        };
    }

    stopOtherStacks (args, util) {
        util.stopOtherTargetThreads();
    }
}

module.exports = Scratch3FlipperControl;
