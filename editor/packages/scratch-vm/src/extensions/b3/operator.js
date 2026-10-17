const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const Cast = require('../../util/cast');
const {COLORS} = require('./menus');

class Scratch3FlipperOperator {
    constructor (runtime) {
        this.runtime = runtime;
    }

    getInfo () {
        return {
            id: 'flipperoperator',
            name: 'Operators',
            color1: COLORS.operator[0],
            color2: COLORS.operator[1],
            color3: COLORS.operator[2],
            blocks: [
                {opcode: 'isInBetween',
                    blockType: BlockType.BOOLEAN,
                    text: '[VALUE] is between [LOW] and [HIGH]',
                    arguments: {VALUE: {type: ArgumentType.NUMBER, defaultValue: 0},
                        LOW: {type: ArgumentType.NUMBER, defaultValue: -10},
                        HIGH: {type: ArgumentType.NUMBER, defaultValue: 10}}}
            ]
        };
    }

    isInBetween (args) {
        const value = Cast.toNumber(args.VALUE);
        const a = Cast.toNumber(args.LOW);
        const b = Cast.toNumber(args.HIGH);
        return value >= Math.min(a, b) && value <= Math.max(a, b);
    }
}

module.exports = Scratch3FlipperOperator;
