const {test} = require('tap');
const {B3Hub} = require('../../src/extensions/b3/hub');
const Light = require('../../src/extensions/b3/light');
const B3Light = require('../../src/extensions/b3/b3light');
const {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers, fakeUtil} = require('../fixtures/b3-fakes');

const PORTS = {
    A: {typeid: 62, name: 'Distance Sensor', kind: 'distance', distance_mm: -1},
    B: {typeid: 64, name: '3x3 Color Light Matrix', kind: 'matrix'},
    C: {typeid: 8, name: 'Light', kind: 'light', brightness: 0},
    D: {typeid: 48, name: 'Medium Angular Motor (Cyan)', kind: 'motor_abs'}
};

const setup = async () => {
    const runtime = new FakeRuntime();
    runtime.b3hub = new B3Hub(runtime, {WebSocket: FakeWebSocket, fetch: fakeFetch(), base: 'http://pi', timers: fakeTimers()});
    await runtime.b3hub.start();
    const ws = FakeWebSocket.last;
    ws.open('me', 'me');
    ws.receive({type: 'telemetry', vin: 8, ports: PORTS});
    const errors = [];
    runtime.b3hub.on('blockError', e => errors.push(e.message));
    return {light: new Light(runtime), b3light: new B3Light(runtime), runtime, ws, errors};
};
const last = ws => ws.lastRequest();
const timerUtil = () => {
    const util = {...fakeUtil(), timer: null, yielded: 0};
    util.stackTimerNeedsInit = () => util.timer === null;
    util.startStackTimer = ms => {
        util.timer = {ms, finished: false};
    };
    util.stackTimerFinished = () => util.timer.finished;
    util.yield = () => {
        util.yielded++;
    };
    return util;
};

test('distance sensor lights: four values 0..100 in order, missing ones off', async t => {
    const {light, ws} = await setup();
    light.ultrasonicLightUp({PORT: 'A', VALUE: '100 50 0 25'}, fakeUtil());
    t.same(last(ws).args, {port: 'A', values: [100, 50, 0, 25]});
    light.ultrasonicLightUp({PORT: 'A', VALUE: '300,x'}, fakeUtil());
    t.same(last(ws).args.values, [100, 0, 0, 0]);
});

test('light blocks name the port and device when the device is wrong', async t => {
    const {light, b3light, ws, errors} = await setup();
    const lightCommands = () => ws.sent.filter(m => m.cmd && m.cmd !== 'stop_all').length; // fail() sends stop_all
    const before = lightCommands();
    light.ultrasonicLightUp({PORT: 'D', VALUE: '1 1 1 1'}, fakeUtil());
    light.lightColorMatrixOff({PORT: 'C'}, fakeUtil());
    b3light.setBrightness({PORT: 'B', BRIGHTNESS: 50}, fakeUtil());
    t.equal(lightCommands(), before);
    t.same(errors, [
        'Port D: expected Distance Sensor, found Medium Angular Motor (Cyan)',
        'Port C: expected 3x3 Color Light Matrix, found Light',
        'Port B: expected Light, found 3x3 Color Light Matrix'
    ]);
});

test('matrix: pattern, pixel, brightness, rotate, orientation', async t => {
    const {light, ws, errors} = await setup();
    light.lightColorMatrixImageOn({PORT: 'B', PATTERN: 'rrrrrrrrr'}, fakeUtil());
    t.equal(last(ws).cmd, 'matrix.set');
    t.same(last(ws).args, {port: 'B', pixels: Array(9).fill(['red', 10])});
    light.lightColorMatrixSetBrightness({PORT: 'B', BRIGHTNESS: 150}, fakeUtil());
    t.same(last(ws).args.pixels[0], ['red', 10], 'brightness clamped to 100');
    light.lightColorMatrixSetBrightness({PORT: 'B', BRIGHTNESS: 30}, fakeUtil());
    t.same(last(ws).args.pixels[0], ['red', 3]);
    light.lightColorMatrixSetPixel({PORT: 'B', X: 2, Y: 2, COLOR: 'Blue', BRIGHTNESS: 100}, fakeUtil());
    t.same(last(ws).args.pixels[4], ['blue', 3]);
    const before = ws.sent.length;
    light.lightColorMatrixSetPixel({PORT: 'B', X: 4, Y: 1, COLOR: 'blue', BRIGHTNESS: 100}, fakeUtil());
    light.lightColorMatrixSetOrientation({PORT: 'B', ORIENTATION: 'sideways'}, fakeUtil());
    t.equal(ws.sent.length, before, 'out of range: nothing sent');
    light.lightColorMatrixRotate({PORT: 'B', DIRECTION: 'clockwise'}, fakeUtil());
    light.lightColorMatrixSetOrientation({PORT: 'B', ORIENTATION: 'upsidedown'}, fakeUtil());
    t.equal(last(ws).cmd, 'matrix.set');
    light.lightColorMatrixImageOn({PORT: 'B', PATTERN: 'rrr'}, fakeUtil());
    t.match(errors[0], /^Port B: pattern "rrr" must be 9 colour letters/);
});

test('turn on for time: on, wait on the stack timer, then off', async t => {
    const {light, ws} = await setup();
    const util = timerUtil();
    light.lightColorMatrixImageOnForTime({PORT: 'B', PATTERN: 'ggggggggg', DURATION: 2}, util);
    t.same(last(ws).args.pixels[0], ['green', 10]);
    t.equal(util.timer.ms, 2000);
    const sent = ws.sent.length;
    light.lightColorMatrixImageOnForTime({PORT: 'B', PATTERN: 'ggggggggg', DURATION: 2}, util);
    t.equal(ws.sent.length, sent, 'nothing sent while waiting');
    t.equal(util.yielded, 2);
    util.timer.finished = true;
    light.lightColorMatrixImageOnForTime({PORT: 'B', PATTERN: 'ggggggggg', DURATION: 2}, util);
    t.same(last(ws).args.pixels, Array(9).fill(['black', 0]));
});

test('Light 88005: brightness 0..100 and off', async t => {
    const {b3light, ws} = await setup();
    b3light.setBrightness({PORT: 'C', BRIGHTNESS: 150}, fakeUtil());
    t.same(last(ws), {id: last(ws).id, cmd: 'light.set', args: {port: 'C', brightness: 100}});
    b3light.off({PORT: 'C'}, fakeUtil());
    t.same(last(ws).args, {port: 'C', brightness: 0});
});

test('opcodes match SPIKE and the spec', async t => {
    const {light, b3light} = await setup();
    const ops = ext => ext.getInfo().blocks.filter(b => b.opcode).map(b => b.opcode);
    t.same(ops(light), ['ultrasonicLightUp', 'lightColorMatrixImageOn', 'lightColorMatrixImageOnForTime',
        'lightColorMatrixOff', 'lightColorMatrixSetPixel', 'lightColorMatrixSetBrightness',
        'lightColorMatrixRotate', 'lightColorMatrixSetOrientation']);
    t.same(ops(b3light), ['setBrightness', 'off']);
    t.equal(light.getInfo().id, 'flipperlight');
    t.equal(b3light.getInfo().id, 'b3light');
});
