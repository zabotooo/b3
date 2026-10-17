const {test} = require('tap');
const VirtualMachine = require('../../src/virtual-machine');
const Sprite = require('../../src/sprites/sprite');
const RenderedTarget = require('../../src/sprites/rendered-target');

// Runs B3 hats through the real Runtime._step, the way the editor does.
const setup = ports => {
    const vm = new VirtualMachine();
    const runtime = vm.runtime;
    runtime.currentStepTime = 1000 / 60; // set by vm.start() in the editor
    const hub = runtime.b3hub;
    hub.clientId = 'me';
    hub.holder = 'me';
    hub.ports = {A: null, B: null, C: null, D: null, ...ports};
    const sent = [];
    hub.request = cmd => {
        sent.push(cmd);
        return Promise.resolve();
    };
    const errors = [];
    hub.on('blockError', e => errors.push(e));
    const target = new RenderedTarget(new Sprite(null, runtime), runtime);
    runtime.addTarget(target);
    runtime.setEditingTarget(target);
    return {vm, runtime, hub, sent, errors, target};
};

const block = (target, id, opcode, extra = {}) => target.blocks.createBlock({
    id,
    opcode,
    topLevel: !extra.parent,
    parent: null,
    next: null,
    shadow: false,
    inputs: {},
    fields: {},
    ...extra
});

// when [hat] → A start motor ↻
const hatThenStartMotor = (target, hatOpcode, hatExtra = {}) => {
    block(target, 'hat', hatOpcode, {next: 'go', ...hatExtra});
    block(target, 'go', 'flippermotor_motorStartDirection', {parent: 'hat',
        fields: {PORT: {name: 'PORT', value: 'A'}, DIRECTION: {name: 'DIRECTION', value: 'clockwise'}}});
};

const steps = (runtime, n) => {
    for (let i = 0; i < n; i++) runtime._step();
};

test('sensor hats do not fire before Run or after Stop', async t => {
    const {runtime, sent, target} = setup({A: {kind: 'motor_abs', name: 'Motor'}});
    hatThenStartMotor(target, 'flipperevents_whenTimer');
    block(target, 'val', 'math_number', {parent: 'hat', shadow: true, fields: {NUM: {name: 'NUM', value: '-1'}}});
    target.blocks.getBlock('hat').inputs.VALUE = {name: 'VALUE', block: 'val', shadow: 'val'};

    steps(runtime, 5);
    t.notOk(sent.includes('motor.start'), 'no motor command before Run');

    runtime.greenFlag();
    steps(runtime, 5);
    t.ok(sent.includes('motor.start'), 'hat fires while the program runs');

    runtime.stopAll();
    sent.length = 0;
    target.clearEdgeActivatedValues();
    steps(runtime, 5);
    t.notOk(sent.includes('motor.start'), 'no motor command after Stop');
});

test('a condition hat on a missing sensor reports once and stays quiet', async t => {
    const {runtime, sent, errors, target} = setup({A: {kind: 'motor_abs', name: 'Motor'}});
    hatThenStartMotor(target, 'flipperevents_whenCondition');
    block(target, 'cond', 'flippersensors_isColor', {parent: 'hat',
        fields: {PORT: {name: 'PORT', value: 'B'}, COLOR: {name: 'COLOR', value: 'red'}}});
    target.blocks.getBlock('hat').inputs.CONDITION = {name: 'CONDITION', block: 'cond', shadow: null};

    steps(runtime, 30);
    t.same(errors, [], 'nothing evaluated before Run');
    t.notOk(sent.includes('stop_all'));

    runtime.greenFlag();
    sent.length = 0;
    steps(runtime, 30);
    t.equal(errors.length, 1, 'one error naming the port');
    t.match(errors[0].message, /^Port B: expected Color Sensor/);
    t.equal(sent.filter(c => c === 'stop_all').length, 1, 'one stop_all');
});

test('WeDo hats also wait for Run', async t => {
    const {runtime, sent, target} = setup({
        A: {kind: 'motor_abs', name: 'Motor'},
        B: {kind: 'wedo_tilt', name: 'WeDo 2.0 Tilt Sensor', tilt: [0, 30]}
    });
    hatThenStartMotor(target, 'b3events_whenTilted', {fields: {
        PORT: {name: 'PORT', value: 'B'},
        DIRECTION: {name: 'DIRECTION', value: 'forward'}}});
    steps(runtime, 5);
    t.notOk(sent.includes('motor.start'), 'not before Run');
    runtime.greenFlag();
    steps(runtime, 5);
    t.ok(sent.includes('motor.start'), 'fires while running');
});
