const md5 = require('js-md5');

const text = (bytes, start, end) => String.fromCharCode(...bytes.subarray(start, end));

/**
 * hatd plays sounds with aplay and accepts only RIFF/WAVE files; this checks for the
 * 16-bit PCM kind aplay always plays (Scratch also uses ADPCM WAV and MP3).
 * @param {Uint8Array} bytes - file contents
 * @returns {boolean} true for a 16-bit PCM WAV whose first chunk is "fmt "
 */
const isPcmWav = bytes => bytes.length >= 44 &&
    text(bytes, 0, 4) === 'RIFF' && text(bytes, 8, 16) === 'WAVEfmt ' &&
    bytes[20] === 1 && bytes[21] === 0 && bytes[34] === 16 && bytes[35] === 0;

/**
 * @param {Float32Array[]} channels - samples -1..1, one array per channel, equal lengths
 * @param {number} sampleRate - samples per second
 * @returns {Uint8Array} a 16-bit PCM WAV file
 */
const encodeWav = (channels, sampleRate) => {
    const count = channels.length;
    const frames = channels[0].length;
    const dataSize = frames * count * 2;
    const bytes = new Uint8Array(44 + dataSize);
    const view = new DataView(bytes.buffer);
    const writeText = (offset, s) => {
        for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
    };
    writeText(0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true);
    writeText(8, 'WAVEfmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, count, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * count * 2, true);
    view.setUint16(32, count * 2, true);
    view.setUint16(34, 16, true);
    writeText(36, 'data');
    view.setUint32(40, dataSize, true);
    let offset = 44;
    for (let frame = 0; frame < frames; frame++) {
        for (let c = 0; c < count; c++) {
            const s = Math.max(-1, Math.min(1, channels[c][frame]));
            view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
            offset += 2;
        }
    }
    return bytes;
};

/**
 * The sound as a WAV hatd can play: PCM WAV as is, anything else decoded and re-encoded.
 * @param {{data: Uint8Array}} asset - the sound's storage asset
 * @param {function(ArrayBuffer): Promise<object>} decode - e.g. AudioContext#decodeAudioData
 * @returns {Promise<Uint8Array>} 16-bit PCM WAV bytes
 */
const toPlayableWav = async (asset, decode) => {
    if (isPcmWav(asset.data)) return asset.data;
    const audio = await decode(asset.data.slice().buffer); // decodeAudioData detaches its input
    const channels = [];
    for (let c = 0; c < audio.numberOfChannels; c++) channels.push(audio.getChannelData(c));
    return encodeWav(channels, audio.sampleRate);
};

const wavMd5 = bytes => md5(bytes);

module.exports = {isPcmWav, encodeWav, toPlayableWav, wavMd5};
