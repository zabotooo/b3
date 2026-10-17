const {test} = require('tap');
const {isPcmWav, encodeWav, toPlayableWav, wavMd5} = require('../../src/extensions/b3/wav');
const {B3Hub} = require('../../src/extensions/b3/hub');
const {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers} = require('../fixtures/b3-fakes');

const view = bytes => new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

test('encodeWav writes a 16-bit PCM WAV', t => {
    const wav = encodeWav([Float32Array.of(0, 1, -1)], 8000);
    const v = view(wav);
    t.equal(wav.length, 44 + 6);
    t.equal(String.fromCharCode(...wav.subarray(0, 4)), 'RIFF');
    t.equal(String.fromCharCode(...wav.subarray(8, 16)), 'WAVEfmt ');
    t.equal(v.getUint16(20, true), 1, 'PCM');
    t.equal(v.getUint16(22, true), 1, 'channels');
    t.equal(v.getUint32(24, true), 8000, 'sample rate');
    t.equal(v.getUint16(34, true), 16, 'bits');
    t.same([v.getInt16(44, true), v.getInt16(46, true), v.getInt16(48, true)], [0, 32767, -32768]);
    t.ok(isPcmWav(wav));
    t.end();
});

test('isPcmWav rejects MP3 and ADPCM WAV', t => {
    t.notOk(isPcmWav(Uint8Array.from([0x49, 0x44, 0x33, 3, 0, 0, 0, 0, 0, 0])), 'ID3 header');
    const adpcm = encodeWav([Float32Array.of(0)], 22050);
    view(adpcm).setUint16(20, 17, true); // IMA ADPCM, as in many Scratch sounds
    t.notOk(isPcmWav(adpcm));
    t.end();
});

test('toPlayableWav keeps PCM WAV and converts the rest', async t => {
    const pcm = encodeWav([Float32Array.of(0.25)], 22050);
    t.equal(await toPlayableWav({data: pcm}, () => t.fail('no decode for PCM')), pcm);
    const mp3 = Uint8Array.from([0x49, 0x44, 0x33, 3, 0, 0, 0, 0, 0, 0]);
    const decode = buffer => {
        t.ok(buffer instanceof ArrayBuffer);
        return Promise.resolve({numberOfChannels: 2,
            sampleRate: 44100,
            getChannelData: c => Float32Array.of(c ? -0.5 : 0.5)});
    };
    const out = await toPlayableWav({data: mp3}, decode);
    t.ok(isPcmWav(out));
    t.equal(view(out).getUint16(22, true), 2);
    t.equal(view(out).getUint32(24, true), 44100);
});

test('wavMd5 is the md5 of the bytes', t => {
    t.equal(wavMd5(Uint8Array.from([0x61, 0x62, 0x63])), '900150983cd24fb0d6963f7d28e17f72');
    t.end();
});

const hubWith = statusFor => {
    const fetch = fakeFetch(statusFor);
    const hub = new B3Hub(new FakeRuntime(), {WebSocket: FakeWebSocket, fetch, base: 'http://pi', timers: fakeTimers()});
    return {hub, fetch};
};
const MD5 = '0123456789abcdef0123456789abcdef';

test('uploadSound puts a sound hatd does not have, once', async t => {
    const {hub, fetch} = hubWith({[`HEAD /api/sounds/${MD5}`]: 404});
    const bytes = Uint8Array.of(1, 2);
    await hub.uploadSound(MD5, bytes);
    t.same(fetch.calls.map(c => c.options.method), ['HEAD', 'PUT']);
    t.equal(fetch.calls[1].url, `http://pi/api/sounds/${MD5}`);
    t.equal(fetch.calls[1].options.body, bytes);
    t.equal(fetch.calls[1].options.credentials, 'same-origin');
    await hub.uploadSound(MD5, bytes);
    t.equal(fetch.calls.length, 2, 'remembered');
    hub.forgetSound(MD5);
    await hub.uploadSound(MD5, bytes);
    t.equal(fetch.calls.length, 4, 'checked again after forgetSound');
});

test('uploadSound skips the PUT when hatd already has the sound', async t => {
    const {hub, fetch} = hubWith({});
    await hub.uploadSound(MD5, Uint8Array.of(1));
    t.same(fetch.calls.map(c => c.options.method), ['HEAD']);
});

test('uploadSound reports hatd\'s refusal', async t => {
    const {hub} = hubWith({[`HEAD /api/sounds/${MD5}`]: 404, [`PUT /api/sounds/${MD5}`]: 400});
    await t.rejects(hub.uploadSound(MD5, Uint8Array.of(1)), {code: 'upload_failed', message: 'Wrong PIN'});
});
