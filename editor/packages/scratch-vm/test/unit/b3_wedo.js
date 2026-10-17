const {test} = require('tap');
const {B3Hub} = require('../../src/extensions/b3/hub');
const {tiltDirection, isTiltedAs} = require('../../src/extensions/b3/wedo');
const B3Sensors = require('../../src/extensions/b3/b3sensors');
const B3Events = require('../../src/extensions/b3/b3events');
const {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers, fakeUtil} = require('../fixtures/b3-fakes');

test('tilt direction from [x, y] degrees', t => {
    t.equal(tiltDirection([0, 0]), 'level');
    t.equal(tiltDirection([9, -9]), 'level');
    t.equal(tiltDirection([0, 30]), 'forward');
    t.equal(tiltDirection([5, -20]), 'backward');
    t.equal(tiltDirection([25, 10]), 'right');
    t.equal(tiltDirection([-25, 10]), 'left');
    t.equal(tiltDirection(undefined), 'level');
    t.ok(isTiltedAs([0, 30], 'any'));
    t.notOk(isTiltedAs([0, 0], 'any'));
    t.ok(isTiltedAs([0, 30], 'forward'));
    t.end();
});

const setup = async ports => {
    const runtime = new FakeRuntime();
    runtime.b3hub = new B3Hub(runtime, {WebSocket: FakeWebSocket, fetch: fakeFetch(), base: 'http://pi', timers: fakeTimers()});
    await runtime.b3hub.start();
    FakeWebSocket.last.open('me', 'me');
    FakeWebSocket.last.receive({type: 'telemetry', vin: 8, ports: {A: null, B: null, C: null, D: null, ...ports}});
    const errors = [];
    runtime.b3hub.on('blockError', e => errors.push(e.message));
    return {s: new B3Sensors(runtime), ev: new B3Events(runtime), errors, runtime};
};

test('WeDo reporters and the wrong-device message', async t => {
    const {s, errors} = await setup({
        A: {kind: 'wedo_tilt', name: 'WeDo 2.0 Tilt Sensor', tilt: [0, -30]},
        B: {kind: 'wedo_motion', name: 'WeDo 2.0 Motion Sensor', distance: 4}
    });
    t.equal(s.tiltDirection({PORT: 'A'}, fakeUtil()), 'backward');
    t.equal(s.isTilted({PORT: 'A', DIRECTION: 'backward'}, fakeUtil()), true);
    t.equal(s.isTilted({PORT: 'A', DIRECTION: 'left'}, fakeUtil()), false);
    t.equal(s.motionDistance({PORT: 'B'}, fakeUtil()), 4);
    t.same(errors, []);
    t.equal(s.motionDistance({PORT: 'A'}, fakeUtil()), 0);
    t.same(errors, ['Port A: expected WeDo 2.0 Motion Sensor, found WeDo 2.0 Tilt Sensor']);
});

test('WeDo hats are silent predicates', async t => {
    const {ev, errors, runtime} = await setup({
        A: {kind: 'wedo_tilt', name: 'WeDo 2.0 Tilt Sensor', tilt: [30, 0]},
        B: {kind: 'wedo_motion', name: 'WeDo 2.0 Motion Sensor', distance: 3}
    });
    t.equal(ev.whenTilted({PORT: 'A', DIRECTION: 'right'}), true);
    t.equal(ev.whenTilted({PORT: 'A', DIRECTION: 'any'}), true);
    t.equal(ev.whenTilted({PORT: 'A', DIRECTION: 'forward'}), false);
    t.equal(ev.whenMotion({PORT: 'B', VALUE: 5}), true);
    t.equal(ev.whenMotion({PORT: 'B', VALUE: 2}), false);
    t.equal(ev.whenTilted({PORT: 'C', DIRECTION: 'any'}), false);
    t.same(errors, []);
    t.equal(runtime.stopped, 0);
});

test('WeDo opcodes and ids', async t => {
    const {s, ev} = await setup({});
    t.equal(s.getInfo().id, 'b3sensors');
    t.equal(ev.getInfo().id, 'b3events');
    t.same(s.getInfo().blocks.map(b => b.opcode), ['tiltDirection', 'isTilted', 'motionDistance']);
    t.same(ev.getInfo().blocks.map(b => b.opcode), ['whenTilted', 'whenMotion']);
});
