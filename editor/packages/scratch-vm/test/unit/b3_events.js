const {test} = require('tap');
const {B3Hub} = require('../../src/extensions/b3/hub');
const Events = require('../../src/extensions/b3/events');
const Control = require('../../src/extensions/b3/control');
const {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers} = require('../fixtures/b3-fakes');

const setup = async ports => {
    const runtime = new FakeRuntime();
    runtime.b3hub = new B3Hub(runtime, {WebSocket: FakeWebSocket,
        fetch: fakeFetch(),
        base: 'http://pi',
        timers: fakeTimers()});
    await runtime.b3hub.start();
    FakeWebSocket.last.open('me', 'me');
    FakeWebSocket.last.receive({type: 'telemetry', vin: 8, ports: {A: null, B: null, C: null, D: null, ...ports}});
    const errors = [];
    runtime.b3hub.on('blockError', e => errors.push(e));
    return {ev: new Events(runtime), runtime, hub: runtime.b3hub, errors};
};

test('program start fires the hat', async t => {
    const {runtime} = await setup({});
    runtime.emit('PROJECT_START');
    t.same(runtime.started.map(s => s.opcode), ['flipperevents_whenProgramStarts']);
});

test('sensor hats are predicates', async t => {
    const {ev} = await setup({
        A: {kind: 'color_distance', color: 'red', reflection: 1, distance: 3},
        B: {kind: 'force', force_n: 1, pressed: true}
    });
    t.equal(ev.whenColor({PORT: 'A', COLOR: 'red'}), true);
    t.equal(ev.whenColor({PORT: 'A', COLOR: 'blue'}), false);
    t.equal(ev.whenDistance({PORT: 'A', COMPARATOR: 'closer', VALUE: 15, UNIT: 'cm'}), true);
    t.equal(ev.whenDistance({PORT: 'A', COMPARATOR: 'farther', VALUE: 15, UNIT: 'cm'}), false);
    t.equal(ev.whenPressed({PORT: 'B', OPTION: 'pressed'}), true);
    t.equal(ev.whenPressed({PORT: 'B', OPTION: 'released'}), false);
});

test('hats on missing or wrong devices stay silent and false', async t => {
    const {ev, errors, runtime} = await setup({C: {kind: 'motor_abs', name: 'Motor'}});
    t.equal(ev.whenColor({PORT: 'C', COLOR: 'red'}), false);
    t.equal(ev.whenPressed({PORT: 'D', OPTION: 'pressed'}), false);
    t.same(errors, []);
    t.equal(runtime.stopped, 0);
});

test('timer and condition hats', async t => {
    const {ev, hub} = await setup({});
    hub.timerStart = Date.now() - 3000;
    t.equal(ev.whenTimer({VALUE: 2}), true);
    t.equal(ev.whenTimer({VALUE: 5}), false);
    t.equal(ev.whenCondition({CONDITION: true}), true);
    t.equal(ev.whenCondition({CONDITION: 'false'}), false);
});

test('hat declarations', async t => {
    const {ev} = await setup({});
    const blocks = Object.fromEntries(ev.getInfo().blocks.map(b => [b.opcode, b]));
    t.equal(blocks.whenProgramStarts.isEdgeActivated, false);
    t.notOk(blocks.whenColor.isEdgeActivated === false);
    t.equal(ev.getInfo().id, 'flipperevents');
});

test('stop other stacks', t => {
    const control = new Control(new FakeRuntime());
    let called = 0;
    control.stopOtherStacks({}, {stopOtherTargetThreads: () => called++});
    t.equal(called, 1);
    t.equal(control.getInfo().id, 'flippercontrol');
    t.end();
});
