const {test} = require('tap');
const {B3Hub} = require('../../src/extensions/b3/hub');
const Sound = require('../../src/extensions/b3/sound');
const {encodeWav, wavMd5} = require('../../src/extensions/b3/wav');
const {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers, fakeUtil} = require('../fixtures/b3-fakes');

const flush = () => new Promise(resolve => setImmediate(resolve));
const POP = encodeWav([Float32Array.of(0, 0.5)], 22050);
const POP_MD5 = wavMd5(POP);

const setup = async (statusFor = {}) => {
    const runtime = new FakeRuntime();
    runtime.stage = {volume: 100,
        sprite: {sounds: [
            {name: 'pop', asset: {data: POP}},
            {name: 'boing', asset: {data: Uint8Array.of(0x49, 0x44, 0x33)}}
        ]}};
    runtime._primitives.sound_setvolumeto = (args, util) => {
        util.target.volume = Math.max(0, Math.min(100, Number(args.VOLUME)));
        return Promise.resolve();
    };
    const fetch = fakeFetch(statusFor);
    runtime.b3hub = new B3Hub(runtime, {WebSocket: FakeWebSocket, fetch, base: 'http://pi', timers: fakeTimers()});
    await runtime.b3hub.start();
    const ws = FakeWebSocket.last;
    ws.open('me', 'me');
    const errors = [];
    runtime.b3hub.on('blockError', e => errors.push(e.message));
    const sound = new Sound(runtime);
    sound.decode = () => Promise.resolve({numberOfChannels: 1,
        sampleRate: 8000,
        getChannelData: () => Float32Array.of(0)});
    return {sound, runtime, ws, fetch, errors};
};
const reply = (ws, ok = true, error) => ws.receive({type: 'reply', id: ws.lastRequest().id, ok, result: {}, error});

test('play sound until done uploads the WAV once and waits for hatd', async t => {
    const {sound, ws, fetch} = await setup({[`HEAD /api/sounds/${POP_MD5}`]: 404});
    const done = sound.playSoundUntilDone({SOUND: 'pop'}, fakeUtil());
    await flush();
    t.same(fetch.calls.map(c => c.options.method || 'GET'), ['GET', 'HEAD', 'PUT']); // GET = connect probe
    t.same(ws.lastRequest().cmd, 'sound.play');
    t.same(ws.lastRequest().args, {md5: POP_MD5, wait: true});
    reply(ws);
    await done;
    const again = sound.playSound({SOUND: 'pop'}, fakeUtil());
    await flush();
    t.same(ws.lastRequest().args, {md5: POP_MD5, wait: false});
    t.equal(fetch.calls.length, 3, 'no second upload');
    reply(ws);
    await again;
});

test('sounds are found by name or by number; unknown ones do nothing', async t => {
    const {sound, ws} = await setup();
    const p = sound.playSound({SOUND: 1}, fakeUtil());
    await flush();
    t.equal(ws.lastRequest().args.md5, POP_MD5);
    reply(ws);
    await p;
    const before = ws.sent.length;
    await sound.playSound({SOUND: 'nope'}, fakeUtil());
    t.equal(ws.sent.length, before);
});

test('non-PCM sounds are converted before upload', async t => {
    const {sound, ws} = await setup();
    const p = sound.playSound({SOUND: 'boing'}, fakeUtil());
    await flush();
    t.equal(ws.lastRequest().args.md5, wavMd5(encodeWav([Float32Array.of(0)], 8000)));
    reply(ws);
    await p;
});

test('a sound hatd lost is uploaded again and played', async t => {
    const {sound, ws, fetch} = await setup();
    const p = sound.playSound({SOUND: 'pop'}, fakeUtil());
    await flush();
    reply(ws, false, {code: 'not_found', message: 'Sound is not uploaded'});
    await flush();
    t.equal(fetch.calls.filter(c => c.options.method === 'HEAD').length, 2);
    t.equal(ws.sent.filter(m => m.cmd === 'sound.play').length, 2);
    reply(ws);
    await p;
});

test('upload failure names the sound and stops the program', async t => {
    const {sound, runtime, errors} = await setup({[`HEAD /api/sounds/${POP_MD5}`]: 404,
        [`PUT /api/sounds/${POP_MD5}`]: 400});
    await sound.playSound({SOUND: 'pop'}, fakeUtil());
    t.same(errors, ['Sound "pop": Wrong PIN']);
    t.equal(runtime.stopped, 1);
});

test('beeps: note and duration clamped; zero duration does nothing; start beep has no duration', async t => {
    const {sound, ws} = await setup();
    const p = sound.beepForTime({NOTE: 200, DURATION: 100}, fakeUtil());
    t.same(ws.lastRequest().args, {note: 123, duration: 60});
    reply(ws);
    await p;
    const before = ws.sent.length;
    await sound.beepForTime({NOTE: 60, DURATION: 0}, fakeUtil());
    t.equal(ws.sent.length, before);
    const q = sound.beep({NOTE: 10.4}, fakeUtil());
    t.same(ws.lastRequest(), {id: ws.lastRequest().id, cmd: 'sound.beep', args: {note: 44}});
    reply(ws);
    await q;
    const r = sound.stopSound({}, fakeUtil());
    t.equal(ws.lastRequest().cmd, 'sound.stop');
    reply(ws);
    await r;
});

test('Scratch volume blocks set the Pi volume too', async t => {
    const {runtime, ws} = await setup();
    const util = {...fakeUtil(), target: runtime.stage};
    const p = runtime._primitives.sound_setvolumeto({VOLUME: 33.6}, util);
    await flush();
    t.same(ws.lastRequest().args, {value: 34});
    t.equal(ws.lastRequest().cmd, 'sound.volume');
    reply(ws);
    await p;
});

test('program start sends the stage volume when in control', async t => {
    const {runtime, ws} = await setup();
    runtime.stage.volume = 40;
    runtime.emit('PROJECT_START');
    t.same(ws.lastRequest().args, {value: 40});
});

test('sound menu lists the stage sounds', async t => {
    const {sound, runtime} = await setup();
    t.same(sound.getSoundMenu(), ['pop', 'boing']);
    runtime.stage.sprite.sounds = [];
    t.same(sound.getSoundMenu(), ['']);
    const blocks = Object.fromEntries(sound.getInfo().blocks.filter(b => b.opcode).map(b => [b.opcode, b]));
    t.same(Object.keys(blocks), ['playSoundUntilDone', 'playSound', 'stopSound', 'beepForTime', 'beep']);
    t.equal(sound.getInfo().id, 'flippersound');
});

test('volume blocks without control keep the value and do not stop the program', async t => {
    const {runtime, ws, errors} = await setup();
    ws.receive({type: 'control', holder: 'other', you: false});
    errors.length = 0; // losing control reports itself
    const util = {...fakeUtil(), target: runtime.stage};
    await runtime._primitives.sound_setvolumeto({VOLUME: 20}, util);
    t.equal(runtime.stage.volume, 20);
    t.same(errors, []);
    t.notOk(ws.sent.find(m => m.cmd === 'sound.volume'));
});

test('sounds the VM already decoded (e.g. ADPCM WAV) are not decoded again', async t => {
    const {sound, runtime, ws} = await setup();
    const adpcm = {name: 'movie', soundId: 's1', asset: {data: Uint8Array.of(0x52, 0x49, 0x46, 0x46)}};
    runtime.stage.sprite.sounds.push(adpcm);
    runtime.stage.sprite.soundBank = {soundPlayers: {s1: {buffer: {numberOfChannels: 1,
        sampleRate: 11025,
        getChannelData: () => Float32Array.of(0.1)}}}};
    sound.decode = () => Promise.reject(new Error('Unable to decode audio data'));
    const p = sound.playSound({SOUND: 'movie'}, fakeUtil());
    await flush();
    t.equal(ws.lastRequest().args.md5, wavMd5(encodeWav([Float32Array.of(0.1)], 11025)));
    reply(ws);
    await p;
});

test('a sound still being prepared when Stop is pressed does not start afterwards', async t => {
    const {sound, runtime, ws} = await setup();
    let finishDecode;
    sound.decode = () => new Promise(resolve => {
        finishDecode = () => resolve({numberOfChannels: 1, sampleRate: 8000, getChannelData: () => Float32Array.of(0)});
    });
    const p = sound.playSoundUntilDone({SOUND: 'boing'}, fakeUtil());
    await flush();
    runtime.stopAll();
    finishDecode();
    await p;
    await flush();
    t.notOk(ws.sent.find(m => m.cmd === 'sound.play'), 'no sound.play after Stop');
});
