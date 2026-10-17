/**
 * Shared helpers for B3 blocks: sending commands to hatd and reporting problems
 * the way the spec asks (message naming the port, failing stack, program stops).
 */

const fail = (hub, util, message, port = null) => {
    const thread = util && util.thread;
    const blockId = thread ? ((thread.peekStack && thread.peekStack()) || thread.topBlock) : null;
    hub.emit('blockError', {message, port, blockId});
    hub.runtime.stopAll();
};

const report = (hub, util, error) => {
    if (error.code === 'interrupted') return; // Stop pressed or a newer block took over the port
    const message = error.code === 'not_controller' && hub.holder === null ?
        'Take control of the robot first.' : error.message;
    fail(hub, util, message, error.port || null);
};

const send = (hub, util, cmd, args) => hub.request(cmd, args).catch(error => report(hub, util, error));

const deviceOfKind = (hub, port, kinds) => {
    const device = hub.device(port);
    return device && kinds.includes(device.kind) ? device : null;
};

const requireDevice = (hub, util, port, kinds, expected) => {
    const device = deviceOfKind(hub, port, kinds);
    if (device) return device;
    const found = hub.device(port);
    fail(hub, util, `Port ${port}: expected ${expected}, found ${found ? found.name : 'nothing'}`, port);
    return null;
};

module.exports = {fail, report, send, deviceOfKind, requireDevice};
