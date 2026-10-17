const {test} = require('tap');
const {B3Hub} = require('../../src/extensions/b3/hub');
const {send, requireDevice} = require('../../src/extensions/b3/run');
const {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers, fakeUtil} = require('../fixtures/b3-fakes');

const flush = () => new Promise(resolve => setImmediate(resolve));

const makeHub = (statusFor = {}) => {
    const runtime = new FakeRuntime();
    const timers = fakeTimers();
    const fetch = fakeFetch(statusFor);
    const hub = new B3Hub(runtime, {WebSocket: FakeWebSocket, fetch, base: 'http://pi:8080', timers});
    return {hub, runtime, timers, fetch};
};

const connected = async (holder = null) => {
    const env = makeHub();
    await env.hub.start();
    FakeWebSocket.last.open('me', holder);
    return env;
};

test('default timers are called as plain functions, like browsers require', async t => {
    // window.setTimeout throws "Illegal invocation" when called as a method of another object
    const names = ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'];
    const saved = names.map(n => globalThis[n]);
    names.forEach((n, i) => {
        globalThis[n] = function (...args) {
            if (this !== undefined && this !== globalThis) throw new TypeError('Illegal invocation');
            return saved[i](...args);
        };
    });
    t.teardown(() => names.forEach((n, i) => {
        globalThis[n] = saved[i];
    }));
    const hub = new B3Hub(new FakeRuntime(), {WebSocket: FakeWebSocket, fetch: fakeFetch(), base: 'http://pi'});
    await hub.start();
    FakeWebSocket.last.open('me', 'me');
    t.equal(hub.state, 'connected');
    FakeWebSocket.last.drop();
    t.equal(hub.state, 'disconnected');
    hub._timers.clearTimeout(hub._timers.setTimeout(() => {}, 0));
});

test('asks for the PIN when the API answers 401', async t => {
    const {hub} = makeHub({'/api/projects': 401});
    await hub.start();
    t.equal(hub.state, 'need-pin');
});

test('connects, says hello and tracks control', async t => {
    const {hub} = await connected('someone');
    const ws = FakeWebSocket.last;
    t.equal(ws.url, 'ws://pi:8080/api/ws');
    t.same(ws.sent[0], {type: 'hello', api_version: '1'});
    t.equal(hub.state, 'connected');
    t.equal(hub.holder, 'someone');
    t.notOk(hub.isController);
});

test('login posts the PIN and reports a wrong one', async t => {
    const {hub, fetch} = makeHub({'/api/login': 401});
    await t.rejects(hub.login('0000'), {message: 'Wrong PIN'});
    t.same(JSON.parse(fetch.calls[0].options.body), {pin: '0000'});
});

test('request resolves on reply and rejects with code and port', async t => {
    const {hub} = await connected();
    const ws = FakeWebSocket.last;
    const ok = hub.request('motor.stop', {port: 'A'});
    ws.receive({type: 'reply', id: ws.lastRequest().id, ok: true, result: {done: 1}});
    t.same(await ok, {done: 1});
    const bad = hub.request('motor.stop', {port: 'B'});
    ws.receive({type: 'reply',
        id: ws.lastRequest().id,
        ok: false,
        error: {code: 'no_device', message: 'Port B: no device', port: 'B'}});
    await t.rejects(bad, {code: 'no_device', port: 'B'});
});

test('controller pings every second, stops pinging when control is lost', async t => {
    const {hub, timers} = await connected();
    const ws = FakeWebSocket.last;
    ws.receive({type: 'control', holder: 'me', you: true});
    t.ok(hub.isController);
    const ping = timers.intervals.find(i => i && i.ms === 1000);
    t.ok(ping);
    ping.fn();
    t.equal(ws.lastRequest().cmd, 'ping');
    ws.receive({type: 'control', holder: 'other', you: false});
    t.notOk(timers.intervals.find(i => i && i.ms === 1000));
});

test('telemetry is cached per port', async t => {
    const {hub} = await connected();
    FakeWebSocket.last.receive({type: 'telemetry',
        vin: 7.8,
        ports: {A: {typeid: 48, kind: 'motor_abs', position: 10}, B: null, C: null, D: null}});
    t.equal(hub.device('A').position, 10);
    t.equal(hub.device('B'), null);
    t.equal(hub.vin, 7.8);
});

test('dropped connection ends pending blocks, stops the program and retries', async t => {
    const {hub, runtime, timers} = await connected();
    const pending = hub.request('motor.run_for', {port: 'A'});
    FakeWebSocket.last.drop();
    await t.rejects(pending, {code: 'disconnected'});
    t.equal(hub.state, 'disconnected');
    t.equal(runtime.stopped, 1);
    t.ok(timers.timeouts.find(x => x && x.ms === 2000));
});

test('losing control stops the program and says so', async t => {
    const {hub, runtime} = await connected('me');
    const errors = [];
    hub.on('blockError', e => errors.push(e));
    FakeWebSocket.last.receive({type: 'control', holder: 'other', you: false});
    t.equal(runtime.stopped, 1);
    t.equal(errors.length, 1);
    t.match(errors[0].message, /no longer control the robot/);
    FakeWebSocket.last.receive({type: 'control', holder: null, you: false});
    t.equal(runtime.stopped, 1, 'only when this editor had control');
});

test('three seconds without any message from hatd counts as a lost connection', async t => {
    const {hub, runtime, timers} = await connected();
    const ws = FakeWebSocket.last;
    const pending = hub.request('motor.run_for', {port: 'A'});
    const live = () => timers.timeouts.filter(x => x && x.ms === 3000);
    ws.receive({type: 'telemetry', vin: 8, ports: {A: null, B: null, C: null, D: null}});
    t.equal(live().length, 1, 'one watchdog, re-armed by each message');
    live()[0].fn();
    await t.rejects(pending, {code: 'disconnected'});
    t.equal(hub.state, 'disconnected');
    t.equal(ws.readyState, 3, 'socket closed');
    t.equal(runtime.stopped, 1);
});

test('request while disconnected rejects at once', async t => {
    const {hub} = makeHub();
    await t.rejects(hub.request('motor.stop', {port: 'A'}), {code: 'disconnected'});
});

test('program start resets speeds, movement and timer', async t => {
    const {hub, runtime} = await connected();
    hub.speeds.A = 10;
    hub.movement.left = 'C';
    hub.timerStart = 0;
    runtime.emit('PROJECT_START');
    t.equal(hub.speeds.A, 75);
    t.equal(hub.movement.left, 'A');
    t.ok(hub.timerStart > 0);
});

test('stop sends one stop_all, only when in control', async t => {
    const {runtime} = await connected();
    const ws = FakeWebSocket.last;
    runtime.emit('PROJECT_STOP_ALL');
    t.notOk(ws.sent.find(m => m.cmd === 'stop_all'));
    ws.receive({type: 'control', holder: 'me', you: true});
    runtime.emit('PROJECT_STOP_ALL');
    t.equal(ws.sent.filter(m => m.cmd === 'stop_all').length, 1);
});

test('send reports errors with the port and stops the program', async t => {
    const {hub, runtime} = await connected('other'); // another device holds control
    const errors = [];
    hub.on('blockError', e => errors.push(e));
    const done = send(hub, fakeUtil('stack9'), 'motor.stop', {port: 'C'});
    const ws = FakeWebSocket.last;
    ws.receive({type: 'reply',
        id: ws.lastRequest().id,
        ok: false,
        error: {code: 'not_controller', message: 'Another device controls the robot. Take control first.'}});
    await done;
    t.same(errors, [{message: 'Another device controls the robot. Take control first.',
        port: null,
        blockId: 'stack9'}]);
    t.equal(runtime.stopped, 1);
});

test('send is silent for interrupted', async t => {
    const {hub, runtime} = await connected();
    const errors = [];
    hub.on('blockError', e => errors.push(e));
    const done = send(hub, fakeUtil(), 'motor.run_for', {port: 'A'});
    const ws = FakeWebSocket.last;
    ws.receive({type: 'reply',
        id: ws.lastRequest().id,
        ok: false,
        error: {code: 'interrupted', message: 'Port A: stopped', port: 'A'}});
    await done;
    t.same(errors, []);
    t.equal(runtime.stopped, 0);
});

test('requireDevice names port, expectation and what was found', async t => {
    const {hub} = await connected();
    const errors = [];
    hub.on('blockError', e => errors.push(e));
    FakeWebSocket.last.receive({type: 'telemetry',
        vin: 8,
        ports: {
            A: {typeid: 47, name: 'Technic XL Motor', kind: 'motor_rel'}, B: null, C: null, D: null}});
    t.equal(requireDevice(hub, fakeUtil(), 'A', ['color', 'color_distance'], 'Color Sensor'), null);
    t.equal(requireDevice(hub, fakeUtil(), 'B', ['color'], 'Color Sensor'), null);
    t.same(errors.map(e => e.message), [
        'Port A: expected Color Sensor, found Technic XL Motor',
        'Port B: expected Color Sensor, found nothing'
    ]);
    t.ok(requireDevice(hub, fakeUtil(), 'A', ['motor_rel'], 'motor'));
    await flush();
});

test('the error points at the failing block, not the hat', async t => {
    const {hub} = await connected('me');
    const errors = [];
    hub.on('blockError', e => errors.push(e));
    const p = send(hub, fakeUtil('hat1', 'block7'), 'motor.start', {port: 'A', speed: 50});
    FakeWebSocket.last.receive({type: 'reply',
        id: FakeWebSocket.last.lastRequest().id,
        ok: false,
        error: {code: 'no_device', message: 'Port A: expected motor, found nothing', port: 'A'}});
    await p;
    t.equal(errors[0].blockId, 'block7');
});

test('not_controller while nobody has control asks to take control', async t => {
    const {hub} = await connected(null);
    const errors = [];
    hub.on('blockError', e => errors.push(e.message));
    const p = send(hub, fakeUtil(), 'motor.start', {port: 'A', speed: 50});
    FakeWebSocket.last.receive({type: 'reply',
        id: FakeWebSocket.last.lastRequest().id,
        ok: false,
        error: {code: 'not_controller', message: 'Another device controls the robot. Take control first.'}});
    await p;
    t.same(errors, ['Take control of the robot first.']);
});

test('connecting gives up after 5 s and retries', async t => {
    const runtime = new FakeRuntime();
    const timers = fakeTimers();
    const hub = new B3Hub(runtime, {WebSocket: FakeWebSocket, fetch: () => new Promise(() => {}), base: 'http://pi', timers});
    const started = hub.start();
    t.equal(hub.state, 'connecting');
    timers.timeouts.find(x => x && x.ms === 5000).fn();
    await started;
    t.equal(hub.state, 'disconnected');
    t.ok(timers.timeouts.find(x => x && x.ms === 2000), 'reconnect scheduled');
});

test('hello with another major API version stops and does not reconnect', async t => {
    const {hub, timers} = makeHub();
    await hub.start();
    const ws = FakeWebSocket.last;
    ws.readyState = 1;
    ws.receive({type: 'hello', api_version: '2', version: '0.9.0', client_id: 'me', control: {holder: null}});
    t.equal(hub.state, 'incompatible');
    t.equal(hub.serverApiVersion, '2');
    t.equal(hub.serverVersion, '0.9.0');
    t.equal(ws.readyState, 3, 'socket closed');
    t.same(ws.sent, [], 'no hello sent back');
    ws.onclose({});
    t.equal(hub.state, 'incompatible', 'close of the rejected socket is ignored');
    t.notOk(timers.timeouts.some(x => x && x.ms === 2000), 'no reconnect scheduled');
    await t.rejects(hub.request('ping'), {code: 'disconnected'});
});

test('hello with the same major API version and a minor suffix connects', async t => {
    const {hub} = makeHub();
    await hub.start();
    FakeWebSocket.last.readyState = 1;
    FakeWebSocket.last.receive({type: 'hello', api_version: '1.3', client_id: 'me', control: {holder: null}});
    t.equal(hub.state, 'connected');
    t.equal(hub.serverVersion, null);
});

test('program start tells hatd a program runs, only when in control', async t => {
    const {runtime} = await connected('me');
    runtime.emit('PROJECT_START');
    const sent = FakeWebSocket.last.lastRequest();
    t.equal(sent.cmd, 'program.running');
    t.same(sent.args, {running: true});
    const other = await connected('someone');
    other.runtime.emit('PROJECT_START');
    t.notOk(FakeWebSocket.last.sent.some(m => m.cmd === 'program.running'));
});

test('hatd reporting a silent Build HAT stops the program and says so', async t => {
    const {hub, runtime} = await connected('me');
    const errors = [];
    hub.on('blockError', e => errors.push(e.message));
    FakeWebSocket.last.receive({
        type: 'error',
        error: {code: 'hat_not_responding', message: 'Build HAT is not responding.'}
    });
    t.equal(runtime.stopped, 1);
    t.same(errors, ['Build HAT is not responding.']);
});

const runningSent = ws => ws.sent.filter(m => m.cmd === 'program.running').map(m => m.args.running);

test('a clicked script counts as a running program while its threads run', async t => {
    const {runtime} = await connected('me');
    runtime.emit('PROJECT_RUN_START');
    runtime.emit('PROJECT_RUN_STOP');
    t.same(runningSent(FakeWebSocket.last), [true, false]);
});

test('threads ending inside a Run keep the program running until Stop', async t => {
    const {runtime} = await connected('me');
    runtime.emit('PROJECT_START');
    runtime.emit('PROJECT_RUN_START');
    runtime.emit('PROJECT_RUN_STOP');
    t.same(runningSent(FakeWebSocket.last), [true], 'hats stay armed until Stop');
});

test('taking control while a program runs tells hatd it runs', async t => {
    const {hub, runtime} = await connected('someone');
    runtime.emit('PROJECT_START');
    t.same(runningSent(FakeWebSocket.last), [], 'not in control yet');
    FakeWebSocket.last.receive({type: 'control', holder: 'me', you: true});
    t.ok(hub.isController);
    t.same(runningSent(FakeWebSocket.last), [true]);
});
