const {test} = require('tap');
const {B3Hub} = require('../../src/extensions/b3/hub');
const Sensors = require('../../src/extensions/b3/sensors');
const Operator = require('../../src/extensions/b3/operator');
const {distanceIn, forceIn} = require('../../src/extensions/b3/sensors');
const {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers, fakeUtil} = require('../fixtures/b3-fakes');

const PORTS = {
    A: {typeid: 37,
        name: 'Color & Distance Sensor',
        kind: 'color_distance',
        color: 'red',
        reflection: 40,
        distance: 5},
    B: {typeid: 62, name: 'Distance Sensor', kind: 'distance', distance_mm: 123},
    C: {typeid: 63, name: 'Force Sensor', kind: 'force', force_n: 9.1, pressed: true},
    D: {typeid: 48, name: 'Medium Angular Motor (Cyan)', kind: 'motor_abs', aposition: 0}
};

const setup = async () => {
    const runtime = new FakeRuntime();
    runtime.b3hub = new B3Hub(runtime, {WebSocket: FakeWebSocket,
        fetch: fakeFetch(),
        base: 'http://pi',
        timers: fakeTimers()});
    await runtime.b3hub.start();
    FakeWebSocket.last.open('me', 'me');
    FakeWebSocket.last.receive({type: 'telemetry', vin: 8, ports: PORTS});
    const errors = [];
    runtime.b3hub.on('blockError', e => errors.push(e.message));
    return {s: new Sensors(runtime), hub: runtime.b3hub, errors, runtime};
};

test('colour and reflection', async t => {
    const {s} = await setup();
    t.equal(s.color({PORT: 'A'}, fakeUtil()), 'red');
    t.equal(s.isColor({PORT: 'A', COLOR: 'red'}, fakeUtil()), true);
    t.equal(s.isColor({PORT: 'A', COLOR: 'blue'}, fakeUtil()), false);
    t.equal(s.reflectivity({PORT: 'A'}, fakeUtil()), 40);
    t.equal(s.isReflectivity({PORT: 'A', COMPARATOR: '<', VALUE: 50}, fakeUtil()), true);
});

test('distance in units', async t => {
    const {s} = await setup();
    t.equal(s.distance({PORT: 'B', UNIT: 'cm'}, fakeUtil()), 12.3);
    t.equal(Math.round(s.distance({PORT: 'B', UNIT: 'in'}, fakeUtil()) * 100) / 100, 4.84);
    t.equal(s.distance({PORT: 'B', UNIT: '%'}, fakeUtil()), 6.15);
    t.equal(s.isDistance({PORT: 'A', COMPARATOR: '<', VALUE: 20, UNIT: 'cm'}, fakeUtil()), true);
    t.equal(distanceIn({kind: 'distance', distance_mm: -1}, 'cm'), Infinity);
});

// BOOST Color & Distance raw distance against a white sheet, measured 2026-10-17
// (hatd/docs/hardware-notes.md "C&D distance calibration"): [raw, cm].
const MEASURED = [[0, 1], [1, 4], [2, 7], [3, 10], [5, 15], [7, 20]];

test('BOOST Color & Distance raw distance is converted to cm', async t => {
    for (const [raw, cm] of MEASURED) {
        const got = distanceIn({kind: 'color_distance', distance: raw}, 'cm');
        t.ok(Math.abs(got - cm) <= 2, `raw ${raw}: ${got} cm, measured ${cm} cm`);
    }
    t.equal(distanceIn({kind: 'color_distance', distance: 10}, 'cm'), Infinity, 'raw 10 means nothing in range');
    t.equal(distanceIn({kind: 'color_distance', distance: 10}, '%'), 100);
    const {s} = await setup();
    t.equal(s.distance({PORT: 'A', UNIT: 'cm'}, fakeUtil()), 16);
});

test('force', async t => {
    const {s} = await setup();
    t.equal(s.force({PORT: 'C', UNIT: 'N'}, fakeUtil()), 9.1);
    t.equal(s.force({PORT: 'C', UNIT: '%'}, fakeUtil()), 91);
    t.equal(s.isPressed({PORT: 'C', OPTION: 'pressed'}, fakeUtil()), true);
    t.equal(s.isPressed({PORT: 'C', OPTION: 'hardpressed'}, fakeUtil()), true);
    t.equal(s.isPressed({PORT: 'C', OPTION: 'released'}, fakeUtil()), false);
    t.equal(forceIn({force_n: 2}, '%'), 20);
});

test('wrong device names port and expectation, program stops', async t => {
    const {s, errors, runtime} = await setup();
    t.equal(s.color({PORT: 'D'}, fakeUtil()), '');
    t.equal(s.distance({PORT: 'C', UNIT: 'cm'}, fakeUtil()), 0);
    t.same(errors, [
        'Port D: expected Color Sensor, found Medium Angular Motor (Cyan)',
        'Port C: expected Distance Sensor, found Force Sensor'
    ]);
    t.equal(runtime.stopped, 2);
});

test('timer', async t => {
    const {s, hub} = await setup();
    hub.timerStart = Date.now() - 2500;
    t.equal(Math.round(s.timer()), 3);
    s.resetTimer();
    t.ok(s.timer() < 0.1);
});

test('is between', t => {
    const op = new Operator(new FakeRuntime());
    t.equal(op.isInBetween({VALUE: 5, LOW: 1, HIGH: 10}), true);
    t.equal(op.isInBetween({VALUE: 5, LOW: 10, HIGH: 1}), true);
    t.equal(op.isInBetween({VALUE: 11, LOW: 1, HIGH: 10}), false);
    t.equal(op.getInfo().id, 'flipperoperator');
    t.end();
});
