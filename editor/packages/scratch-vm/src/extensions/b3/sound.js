const ArgumentType = require('../../extension-support/argument-type');
const BlockType = require('../../extension-support/block-type');
const Cast = require('../../util/cast');
const {getHub} = require('./hub');
const {fail, report, send} = require('./run');
const {COLORS} = require('./menus');
const {toPlayableWav, wavMd5} = require('./wav');

const clampNote = value => Math.min(123, Math.max(44, Math.round(Cast.toNumber(value))));

class Scratch3FlipperSound {
    constructor (runtime) {
        this.runtime = runtime;
        this.hub = getHub(runtime);
        this._wavs = new WeakMap(); // sound asset -> Promise<{bytes, md5}>
        this.decode = buffer => runtime.audioEngine.audioContext.decodeAudioData(buffer);
        this._stops = 0; // Stop presses; a sound prepared across one must not start
        runtime.on('PROJECT_STOP_ALL', () => {
            this._stops++;
        });
        this._redirectVolume();
        runtime.on('PROJECT_START', () => {
            const stage = runtime.getTargetForStage();
            if (stage && this.hub.isController) {
                this.hub.request('sound.volume', {value: Math.round(stage.volume)}).catch(() => {});
            }
        });
    }

    // Scratch's volume blocks keep their own value (the "volume" reporter) and set the Pi's too.
    // Without control the value is only kept (Scratch projects run without a robot too); the
    // next program start sends it.
    _redirectVolume () {
        const primitives = this.runtime._primitives;
        for (const opcode of ['sound_setvolumeto', 'sound_changevolumeby']) {
            const scratch = primitives[opcode];
            if (!scratch) continue;
            primitives[opcode] = (args, util) => Promise.resolve(scratch(args, util))
                .then(() => this.hub.isController &&
                    send(this.hub, util, 'sound.volume', {value: Math.round(util.target.volume)}));
        }
    }

    getInfo () {
        const soundArg = {type: ArgumentType.STRING, menu: 'SOUND', defaultValue: 'pop'};
        return {
            id: 'flippersound',
            name: 'Sound',
            color1: COLORS.sound[0],
            color2: COLORS.sound[1],
            color3: COLORS.sound[2],
            blocks: [
                {opcode: 'playSoundUntilDone',
                    blockType: BlockType.COMMAND,
                    text: 'play sound [SOUND] until done',
                    arguments: {SOUND: soundArg}},
                {opcode: 'playSound',
                    blockType: BlockType.COMMAND,
                    text: 'start sound [SOUND]',
                    arguments: {SOUND: soundArg}},
                {opcode: 'stopSound', blockType: BlockType.COMMAND, text: 'stop all sounds'},
                '---',
                {opcode: 'beepForTime',
                    blockType: BlockType.COMMAND,
                    text: 'play beep [NOTE] for [DURATION] seconds',
                    arguments: {NOTE: {type: ArgumentType.NUMBER, defaultValue: 60},
                        DURATION: {type: ArgumentType.NUMBER, defaultValue: 0.2}}},
                {opcode: 'beep',
                    blockType: BlockType.COMMAND,
                    text: 'start playing beep [NOTE]',
                    arguments: {NOTE: {type: ArgumentType.NUMBER, defaultValue: 60}}}
            ],
            menus: {
                SOUND: {acceptReporters: true, items: 'getSoundMenu'}
            }
        };
    }

    _sounds () {
        const stage = this.runtime.getTargetForStage();
        return (stage && stage.sprite.sounds) || [];
    }

    getSoundMenu () {
        const names = this._sounds().map(sound => sound.name);
        return names.length ? names : [''];
    }

    // By name first, then as a 1-based number, like Scratch's sound blocks.
    _findSound (value) {
        const sounds = this._sounds();
        const byName = sounds.find(sound => sound.name === String(value));
        if (byName) return byName;
        const index = Math.round(Cast.toNumber(value));
        return Number.isInteger(index) && index >= 1 && index <= sounds.length ? sounds[index - 1] : null;
    }

    // The VM has usually decoded the sound already (scratch-audio also decodes ADPCM WAV,
    // which browsers' decodeAudioData cannot); decodeAudioData is only the fallback.
    _decoder (sound) {
        const stage = this.runtime.getTargetForStage();
        const bank = stage && stage.sprite.soundBank;
        const player = bank && bank.soundPlayers && bank.soundPlayers[sound.soundId];
        return player && player.buffer ? () => Promise.resolve(player.buffer) : this.decode;
    }

    _prepare (sound) {
        let ready = this._wavs.get(sound.asset);
        if (!ready) {
            ready = toPlayableWav(sound.asset, this._decoder(sound)).then(bytes => ({bytes, md5: wavMd5(bytes)}));
            this._wavs.set(sound.asset, ready);
        }
        return ready;
    }

    async _play (args, util, wait) {
        const sound = this._findSound(args.SOUND);
        if (!sound || !sound.asset) return;
        const stops = this._stops;
        let wav;
        try {
            wav = await this._prepare(sound);
            await this.hub.uploadSound(wav.md5, wav.bytes);
        } catch (error) {
            if (this._stops !== stops) return; // stopped meanwhile: the error no longer matters
            fail(this.hub, util, `Sound "${sound.name}": ${error.message}`);
            return;
        }
        // Decoding and uploading can take seconds; Stop meanwhile cancels the sound.
        const play = () => (this._stops === stops ?
            this.hub.request('sound.play', {md5: wav.md5, wait}) : Promise.resolve());
        return play()
            .catch(error => {
                if (error.code !== 'not_found') throw error;
                this.hub.forgetSound(wav.md5); // hatd's cache was cleared since the upload
                return this.hub.uploadSound(wav.md5, wav.bytes).then(play);
            })
            .catch(error => report(this.hub, util, error));
    }

    playSoundUntilDone (args, util) {
        return this._play(args, util, true);
    }

    playSound (args, util) {
        return this._play(args, util, false);
    }

    stopSound (args, util) {
        return send(this.hub, util, 'sound.stop');
    }

    beepForTime (args, util) {
        const duration = Math.min(60, Cast.toNumber(args.DURATION));
        if (!(duration > 0)) return;
        return send(this.hub, util, 'sound.beep', {note: clampNote(args.NOTE), duration: Math.max(0.01, duration)});
    }

    beep (args, util) {
        return send(this.hub, util, 'sound.beep', {note: clampNote(args.NOTE)});
    }
}

module.exports = Scratch3FlipperSound;
