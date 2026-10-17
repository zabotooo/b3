const EventEmitter = require('events');

const API_VERSION = '1';
const PORTS = ['A', 'B', 'C', 'D'];
const DEFAULT_SPEED = 75;
const RECONNECT_MS = 2000;
const PING_MS = 1000;
const CONNECT_TIMEOUT_MS = 5000;
const SILENCE_MS = 3000; // hatd sends telemetry 20 times a second

const withTimeout = (promise, timers, ms) => new Promise((resolve, reject) => {
    const id = timers.setTimeout(() => reject(new Error('Connection timed out')), ms);
    promise.then(value => {
        timers.clearTimeout(id);
        resolve(value);
    }, error => {
        timers.clearTimeout(id);
        reject(error);
    });
});

class B3CommandError extends Error {
    constructor (error) {
        super(error.message);
        this.code = error.code;
        this.port = error.port || null;
    }
}

/**
 * Connection to hatd on the Raspberry Pi plus the state B3 blocks share:
 * telemetry per port, per-port motor speed, movement settings and the timer.
 */
class B3Hub extends EventEmitter {
    constructor (runtime, options = {}) {
        super();
        this.runtime = runtime;
        this._WebSocket = options.WebSocket || (typeof WebSocket === 'undefined' ? null : WebSocket);
        this._fetch = options.fetch || (typeof fetch === 'undefined' ? null : fetch.bind(globalThis));
        this._base = options.base || (typeof location === 'undefined' ? '' : location.origin);
        // Wrapped: browsers reject window.setTimeout & co. called as methods of another object.
        this._timers = options.timers || {
            setInterval: (fn, ms) => setInterval(fn, ms),
            clearInterval: id => clearInterval(id),
            setTimeout: (fn, ms) => setTimeout(fn, ms),
            clearTimeout: id => clearTimeout(id)
        };
        this.state = 'idle';
        this.clientId = null;
        this.holder = null;
        this.ports = {A: null, B: null, C: null, D: null};
        this.vin = null;
        this.serverApiVersion = null;
        this.serverVersion = null;
        this._ws = null;
        this._nextId = 1;
        this._pending = new Map();
        this._sounds = new Set(); // md5s hatd is known to have
        this._ping = null;
        this._silence = null;
        this.running = false; // between Run and Stop; B3 sensor hats only fire then
        this.resetProgramState();
        runtime.on('PROJECT_START', () => {
            this.running = true;
            this.resetProgramState();
            this.emit('running', true);
            // hatd reads every sensor mode only while a program runs (idle: no flashing LED)
            if (this.isController) this.request('program.running', {running: true}).catch(() => {});
        });
        runtime.on('PROJECT_STOP_ALL', () => {
            this.running = false;
            this.emit('running', false);
            if (this.isController) this.request('stop_all').catch(() => {});
        });
    }

    get isController () {
        return this.clientId !== null && this.holder === this.clientId;
    }

    resetProgramState () {
        this.speeds = {A: DEFAULT_SPEED, B: DEFAULT_SPEED, C: DEFAULT_SPEED, D: DEFAULT_SPEED};
        this.movement = {left: 'A', right: 'B', speed: 50, cmPerRotation: 17.5};
        this.timerStart = Date.now();
    }

    _setState (state) {
        if (this.state !== state) {
            this.state = state;
            this.emit('state', state);
        }
    }

    async start () {
        if (this.state === 'connecting' || this.state === 'connected') return;
        this._setState('connecting');
        let resp;
        try {
            const probe = this._fetch(`${this._base}/api/projects`, {credentials: 'same-origin'});
            resp = await withTimeout(probe, this._timers, CONNECT_TIMEOUT_MS);
        } catch (e) {
            this._scheduleReconnect();
            return;
        }
        if (resp.status === 401) {
            this._setState('need-pin');
            return;
        }
        this._open();
    }

    async login (pin) {
        const resp = await this._fetch(`${this._base}/api/login`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({pin})
        });
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.error ? body.error.message : 'Login failed');
        }
        this._setState('idle');
        await this.start();
    }

    _open () {
        const ws = new this._WebSocket(`${this._base.replace(/^http/, 'ws')}/api/ws`);
        this._ws = ws;
        ws.onmessage = event => {
            this._watchSilence(ws);
            this._onMessage(JSON.parse(event.data));
        };
        ws.onclose = () => this._onClose(ws);
    }

    // A dead Wi-Fi link can leave the socket open for minutes; treat silence as a drop.
    _watchSilence (ws) {
        if (this._silence !== null) this._timers.clearTimeout(this._silence);
        this._silence = this._timers.setTimeout(() => {
            this._silence = null;
            if (ws !== this._ws) return;
            ws.close();
            this._onClose(ws);
        }, SILENCE_MS);
    }

    _onMessage (msg) {
        switch (msg.type) {
        case 'hello':
            this.serverApiVersion = String(msg.api_version);
            this.serverVersion = msg.version || null;
            if (this.serverApiVersion.split('.')[0] !== API_VERSION) {
                this._incompatible();
                break;
            }
            this.clientId = msg.client_id;
            this.holder = msg.control.holder;
            this._send({type: 'hello', api_version: API_VERSION});
            this._setState('connected');
            this._updatePing();
            this.emit('control', this.holder);
            break;
        case 'reply': {
            const pending = this._pending.get(msg.id);
            if (!pending) return;
            this._pending.delete(msg.id);
            if (msg.ok) pending.resolve(msg.result);
            else pending.reject(new B3CommandError(msg.error));
            break;
        }
        case 'telemetry':
            this.ports = msg.ports;
            this.vin = msg.vin;
            this.emit('telemetry', msg);
            break;
        case 'device':
            this.emit('device', msg);
            break;
        case 'error':
            if (msg.error && msg.error.code === 'hat_not_responding') {
                this.runtime.stopAll();
                this.emit('blockError', {message: msg.error.message, port: null, blockId: null});
            }
            break;
        case 'control': {
            const hadControl = this.isController;
            this.holder = msg.holder;
            this._updatePing();
            this.emit('control', msg.holder);
            if (hadControl && !this.isController) {
                this.runtime.stopAll();
                this.emit('blockError', {
                    message: 'You no longer control the robot, so it stopped. Take control to continue.',
                    port: null,
                    blockId: null
                });
            }
            break;
        }
        }
    }

    _onClose (ws) {
        if (ws !== this._ws) return;
        this._ws = null;
        this.holder = null;
        if (this._silence !== null) {
            this._timers.clearTimeout(this._silence);
            this._silence = null;
        }
        this._updatePing();
        for (const pending of this._pending.values()) {
            pending.reject(new B3CommandError({code: 'disconnected', message: 'Connection to the robot lost'}));
        }
        this._pending.clear();
        this._setState('disconnected');
        this.runtime.stopAll();
        this._scheduleReconnect();
    }

    // hatd speaks another API: retrying cannot help, the page itself is out of date
    _incompatible () {
        const ws = this._ws;
        this._ws = null; // _onClose ignores this socket, so no reconnect
        if (this._silence !== null) {
            this._timers.clearTimeout(this._silence);
            this._silence = null;
        }
        ws.close();
        this._setState('incompatible');
    }

    _scheduleReconnect () {
        this._setState('disconnected');
        this._timers.setTimeout(() => {
            if (this.state !== 'disconnected') return;
            this._setState('idle');
            this.start();
        }, RECONNECT_MS);
    }

    _send (msg) {
        if (this._ws && this._ws.readyState === 1) this._ws.send(JSON.stringify(msg));
    }

    request (cmd, args = {}) {
        if (!this._ws || this.state !== 'connected') {
            return Promise.reject(new B3CommandError({code: 'disconnected', message: 'Not connected to the robot'}));
        }
        const id = this._nextId++;
        return new Promise((resolve, reject) => {
            this._pending.set(id, {resolve, reject});
            this._send({id, cmd, args});
        });
    }

    async claimControl () {
        await this.request('control.claim');
    }

    /**
     * Make sure hatd's sound cache has this sound: HEAD first, PUT only when missing.
     * @param {string} md5 - md5 of the WAV bytes
     * @param {Uint8Array} bytes - 16-bit PCM WAV
     */
    async uploadSound (md5, bytes) {
        if (this._sounds.has(md5)) return;
        const url = `${this._base}/api/sounds/${md5}`;
        const head = await this._fetch(url, {method: 'HEAD', credentials: 'same-origin'});
        if (!head.ok) {
            const put = await this._fetch(url, {method: 'PUT', credentials: 'same-origin', body: bytes});
            if (!put.ok) {
                const body = await put.json().catch(() => ({}));
                throw new B3CommandError({
                    code: 'upload_failed',
                    message: (body.error && body.error.message) || `Sound upload failed (${put.status})`
                });
            }
        }
        this._sounds.add(md5);
    }

    forgetSound (md5) {
        this._sounds.delete(md5);
    }

    _updatePing () {
        if (this.isController && this._ping === null) {
            this._ping = this._timers.setInterval(() => this.request('ping').catch(() => {}), PING_MS);
        } else if (!this.isController && this._ping !== null) {
            this._timers.clearInterval(this._ping);
            this._ping = null;
        }
    }

    device (port) {
        return (this.ports && this.ports[port]) || null;
    }
}

const getHub = runtime => {
    if (!runtime.b3hub) runtime.b3hub = new B3Hub(runtime);
    return runtime.b3hub;
};

module.exports = {API_VERSION, PORTS, B3CommandError, B3Hub, getHub};
