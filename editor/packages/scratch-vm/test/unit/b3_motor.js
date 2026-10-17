const {test} = require('tap');
const {B3Hub} = require('../../src/extensions/b3/hub');
const Motor = require('../../src/extensions/b3/motor');
const {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers, fakeUtil} = require('../fixtures/b3-fakes');

const setup = async (ports = {}) => {
    const runtime = new FakeRuntime();
    runtime.b3hub = new B3Hub(runtime, {WebSocket: FakeWebSocket,
        fetch: fakeFetch(),
        base: 'http://pi',
        timers: fakeTimers()});
    await runtime.b3hub.start();
    const ws = FakeWebSocket.last;
    ws.open('me', 'me');
    ws.receive({type: 'telemetry', vin: 8, ports: {A: null, B: null, C: null, D: null, ...ports}});
    const errors = [];
    runtime.b3hub.on('blockError', e => errors.push(e.message));
    return {motor: new Motor(runtime), hub: runtime.b3hub, ws, errors};
};

// Resolve the block's pending request like hatd would.
const answer = (ws, ok = true) => ws.receive({type: 'reply', id: ws.lastRequest().id, ok, result: {}});

test('run for rotations uses the port speed and direction', async t => {
    const {motor, hub, ws} = await setup();
    hub.speeds.A = 50;
    const p = motor.motorTurnForDirection({PORT: 'A', DIRECTION: 'counterclockwise', VALUE: 2, UNIT: 'rotations'},
        fakeUtil());
    t.same(ws.lastRequest(), {id: ws.lastRequest().id,
        cmd: 'motor.run_for',
        args: {port: 'A', unit: 'degrees', value: 720, speed: -50}});
    answer(ws);
    await p;
});

test('negative value turns the other way; zero does nothing', async t => {
    const {motor, ws} = await setup();
    const p = motor.motorTurnForDirection({PORT: 'B', DIRECTION: 'clockwise', VALUE: -3, UNIT: 'seconds'},
        fakeUtil());
    t.same(ws.lastRequest().args, {port: 'B', unit: 'seconds', value: 3, speed: -75});
    answer(ws);
    await p;
    const before = ws.sent.length;
    await motor.motorTurnForDirection({PORT: 'B', DIRECTION: 'clockwise', VALUE: 0, UNIT: 'degrees'}, fakeUtil());
    await motor.motorTurnForDirection({PORT: 'B', DIRECTION: 'clockwise', VALUE: 'abc', UNIT: 'degrees'},
        fakeUtil());
    t.equal(ws.sent.length, before);
});

test('huge or infinite amounts are capped at what hatd accepts', async t => {
    const {motor, ws} = await setup();
    const run = (VALUE, UNIT) => {
        const p = motor.motorTurnForDirection({PORT: 'A', DIRECTION: 'clockwise', VALUE, UNIT}, fakeUtil());
        const {value} = ws.lastRequest().args;
        answer(ws);
        return p.then(() => value);
    };
    t.equal(await run(5000, 'rotations'), 1000000);
    t.equal(await run(4000, 'seconds'), 3600);
    t.equal(await run(Infinity, 'degrees'), 1000000);
    t.equal(await run(-Infinity, 'degrees'), 1000000);
});

test('speed is clamped and rounded', async t => {
    const {motor, hub} = await setup();
    motor.motorSetSpeed({PORT: 'C', SPEED: 250});
    t.equal(hub.speeds.C, 100);
    motor.motorSetSpeed({PORT: 'C', SPEED: -33.6});
    t.equal(hub.speeds.C, -34);
});

test('go to position wraps the position and maps direction', async t => {
    const {motor, ws} = await setup();
    const p = motor.motorGoDirectionToPosition({PORT: 'A', DIRECTION: 'counterclockwise', POSITION: 720 + 45},
        fakeUtil());
    t.same(ws.lastRequest().args, {port: 'A', position: 45, direction: 'ccw', speed: 75});
    answer(ws);
    await p;
});

test('start and stop', async t => {
    const {motor, ws} = await setup();
    const p1 = motor.motorStartDirection({PORT: 'D', DIRECTION: 'counterclockwise'}, fakeUtil());
    t.same(ws.lastRequest().args, {port: 'D', speed: -75});
    answer(ws);
    await p1;
    const p2 = motor.motorStop({PORT: 'D'}, fakeUtil());
    t.equal(ws.lastRequest().cmd, 'motor.stop');
    answer(ws);
    await p2;
});

test('position and speed reporters', async t => {
    const {motor, errors} = await setup({
        A: {typeid: 48,
            name: 'Medium Angular Motor (Cyan)',
            kind: 'motor_abs',
            aposition: -90,
            position: 5000,
            speed: 12},
        B: {typeid: 47, name: 'Technic XL Motor', kind: 'motor_rel', position: 370, speed: -3},
        C: {typeid: 2, name: 'Train Motor', kind: 'motor_passive', power: 40},
        D: {typeid: 61, name: 'Color Sensor', kind: 'color', color: 'red', reflection: 1}
    });
    t.equal(motor.absolutePosition({PORT: 'A'}, fakeUtil()), 270);
    t.equal(motor.absolutePosition({PORT: 'B'}, fakeUtil()), 10);
    t.equal(motor.speed({PORT: 'A'}, fakeUtil()), 12);
    t.equal(motor.speed({PORT: 'C'}, fakeUtil()), 40);
    t.equal(motor.speed({PORT: 'D'}, fakeUtil()), 0);
    t.same(errors, ['Port D: expected motor, found Color Sensor']);
});

test('getInfo declares SPIKE opcodes', async t => {
    const {motor} = await setup();
    const info = motor.getInfo();
    t.equal(info.id, 'flippermotor');
    t.same(info.blocks.map(b => b.opcode), ['motorTurnForDirection', 'motorGoDirectionToPosition',
        'motorStartDirection', 'motorStop', 'motorSetSpeed', 'absolutePosition', 'speed']);
});
