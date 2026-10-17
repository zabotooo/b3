const EventEmitter = require('events');

class FakeWebSocket {
    constructor (url) {
        this.url = url;
        this.readyState = 0;
        this.sent = [];
        FakeWebSocket.last = this;
    }
    send (data) {
        this.sent.push(JSON.parse(data));
    }
    close () {
        this.readyState = 3;
    }
    // test helpers
    open (clientId = 'me', holder = null) {
        this.readyState = 1;
        this.receive({type: 'hello', api_version: '1', client_id: clientId, control: {holder}});
    }
    receive (msg) {
        this.onmessage({data: JSON.stringify(msg)});
    }
    drop () {
        this.readyState = 3;
        this.onclose({});
    }
    lastRequest () {
        return [...this.sent].reverse().find(m => m.cmd);
    }
}

const fakeFetch = (statusFor = {}) => {
    const calls = [];
    const fn = (url, options = {}) => {
        calls.push({url, options});
        const path = url.replace(/^https?:\/\/[^/]+/, '');
        const method = options.method || 'GET';
        const status = statusFor[`${method} ${path}`] || statusFor[path] || 200;
        return Promise.resolve({
            status,
            ok: status < 400,
            json: () => Promise.resolve(status < 400 ? {} : {error: {message: 'Wrong PIN'}})
        });
    };
    fn.calls = calls;
    return fn;
};

class FakeRuntime extends EventEmitter {
    constructor () {
        super();
        this.stopped = 0;
        this.started = [];
        this.stage = null; // set by tests: {volume, sprite: {sounds: [...]}}
        this._primitives = {}; // core block implementations, as in the real Runtime
    }
    getTargetForStage () {
        return this.stage;
    }
    stopAll () {
        this.stopped++;
        this.emit('PROJECT_STOP_ALL');
    }
    startHats (opcode, fields) {
        this.started.push({opcode, fields});
        return [];
    }
}

const fakeTimers = () => {
    const t = {intervals: [], timeouts: []};
    t.setInterval = (fn, ms) => t.intervals.push({fn, ms}) - 1;
    t.clearInterval = id => {
        t.intervals[id] = null;
    };
    t.setTimeout = (fn, ms) => t.timeouts.push({fn, ms}) - 1;
    t.clearTimeout = id => {
        t.timeouts[id] = null;
    };
    return t;
};

const fakeUtil = (topBlock = 'stack1', current = topBlock) => ({thread: {topBlock, peekStack: () => current}});

module.exports = {FakeWebSocket, fakeFetch, FakeRuntime, fakeTimers, fakeUtil};
