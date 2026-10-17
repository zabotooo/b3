const {test} = require('tap');
const {wheelSpeeds, toDegrees, pairRunArgs} = require('../../src/extensions/b3/movement');
const {B3Hub} = require('../../src/extensions/b3/hub');
const Move = require('../../src/extensions/b3/move');
const {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers, fakeUtil} = require('../fixtures/b3-fakes');

const movement = {left: 'A', right: 'B', speed: 50, cmPerRotation: 17.5};

test('wheel speeds: straight, pivot, spin, mirrored left motor', t => {
    t.same(wheelSpeeds(50, 0), {left: -50, right: 50});
    t.same(wheelSpeeds(50, 50), {left: -50, right: 0});
    t.same(wheelSpeeds(50, 100), {left: -50, right: -50});
    t.same(wheelSpeeds(50, -100), {left: 50, right: 50});
    t.same(wheelSpeeds(50, 25), {left: -50, right: 25});
    t.same(wheelSpeeds(50, 400), wheelSpeeds(50, 100));
    t.end();
});

test('distance units to degrees', t => {
    t.equal(toDegrees(17.5, 'cm', 17.5), 360);
    t.equal(toDegrees(2, 'rotations', 17.5), 720);
    t.equal(toDegrees(90, 'degrees', 17.5), 90);
    t.equal(Math.round(toDegrees(1, 'in', 2.54)), 360);
    t.equal(toDegrees(3, 'seconds', 17.5), null);
    t.end();
});

test('pair args: faster wheel covers the distance, slower one scaled', t => {
    t.same(pairRunArgs(movement, 0, 35, 'cm'), {left: 'A',
        right: 'B',
        unit: 'degrees',
        left_value: 720,
        right_value: 720,
        left_speed: -50,
        right_speed: 50});
    t.same(pairRunArgs(movement, 25, 1, 'rotations'), {left: 'A',
        right: 'B',
        unit: 'degrees',
        left_value: 360,
        right_value: 180,
        left_speed: -50,
        right_speed: 25});
    t.same(pairRunArgs(movement, 0, 2, 'seconds'), {left: 'A',
        right: 'B',
        unit: 'seconds',
        left_value: 2,
        right_value: 2,
        left_speed: -50,
        right_speed: 50});
    t.same(pairRunArgs(movement, 0, -1, 'rotations').left_speed, 50, 'negative value drives back');
    const far = pairRunArgs(movement, 25, 50000, 'cm');
    t.same([far.left_value, far.right_value], [1000000, 500000], 'capped, steering ratio kept');
    t.equal(pairRunArgs(movement, 0, 4000, 'seconds').left_value, 3600);
    t.equal(pairRunArgs(movement, 0, Infinity, 'rotations').left_value, 1000000);
    t.equal(pairRunArgs(movement, 0, 10, 'furlongs'), null);
    t.equal(pairRunArgs(movement, 0, 0, 'cm'), null);
    t.equal(pairRunArgs({...movement, speed: 0}, 0, 10, 'cm'), null);
    t.end();
});

const setup = async () => {
    const runtime = new FakeRuntime();
    runtime.b3hub = new B3Hub(runtime, {WebSocket: FakeWebSocket,
        fetch: fakeFetch(),
        base: 'http://pi',
        timers: fakeTimers()});
    await runtime.b3hub.start();
    FakeWebSocket.last.open('me', 'me');
    return {move: new Move(runtime), hub: runtime.b3hub, ws: FakeWebSocket.last};
};
const answer = ws => ws.receive({type: 'reply', id: ws.lastRequest().id, ok: true, result: {}});

test('move blocks', async t => {
    const {move, hub, ws} = await setup();
    move.setMovementPair({PAIR: 'C+D'});
    move.movementSpeed({SPEED: 30});
    const p = move.move({DIRECTION: 'back', VALUE: 10, UNIT: 'cm'}, fakeUtil());
    const args = ws.lastRequest().args;
    t.equal(ws.lastRequest().cmd, 'pair.run_for');
    t.same([args.left, args.right, args.left_speed, args.right_speed], ['C', 'D', 30, -30]);
    answer(ws);
    await p;
    move.setDistance({DISTANCE: 10, UNIT: 'in'});
    t.equal(hub.movement.cmPerRotation, 25.4);
    const s = move.startSteer({STEERING: 100}, fakeUtil());
    t.same(ws.lastRequest(), {id: ws.lastRequest().id,
        cmd: 'pair.start',
        args: {left: 'C', right: 'D', left_speed: -30, right_speed: -30}});
    answer(ws);
    await s;
    const st = move.stopMove({}, fakeUtil());
    t.same(ws.lastRequest().args, {left: 'C', right: 'D'});
    answer(ws);
    await st;
});
