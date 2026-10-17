# B3 Build HAT Recovery (Plan 3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** hatd survives a Build HAT that stops answering and a device that drops off a port for a moment. It recovers by itself, and the editor says what happened. The Color & Distance sensor stops flashing while no program runs.

**Architecture:**
- Every blocking `buildhat` call runs on hatd's own thread pool, so aiohttp's default pool (static files, login) never starves.
- A watchdog in `BuildHatBackend` notices a read that has waited longer than `HAT_TIMEOUT`. It then fails every future `buildhat` is waiting on, which frees the stuck threads, and raises `hat_not_responding`. The telemetry loop hands that to the app, which tells the editors, exits with code 75, and lets systemd restart it.
- At start, "HAT not found" triggers a GPIO reset of the HAT and one retry.
- When a port's device changes, the waiters on that port are failed, so the old device object is freed and the new one can be opened.
- The editor tells hatd whether a program runs (`program.running`). While idle, multi-mode sensors are read in their first mode only (color).

**Tech Stack:** Python 3.11, aiohttp 3.8, buildhat 0.6.0 (gpiozero for the reset), pytest; scratch-vm (tap), scratch-gui (Jest).

**Spec:** `docs/superpowers/specs/2026-10-14-b3-design.md`, sections 3.3 ("restarted automatically on crash"), 4.2 and 6.

## Evidence (2026-10-17, Pi 4, installed service)

1. **Firmware stopped answering.** At 19:37 the HAT firmware stopped answering. `faulthandler` dumps showed seven threads in `Motor.run_for_degrees → get_position → Device.get → Future.result()`, plus the telemetry reads and `get_vin`, all waiting forever. The default thread pool was exhausted, so even `GET /` hung.
2. **No recovery on restart.** After a restart, `buildhat.Hat()` raised `BuildHATError("HAT not found")` on every start. buildhat resets the HAT only when the firmware version differs. A manual GPIO reset (`hat_reset.py`, the same sequence as `BuildHAT.resethat`) brought it back.
3. **Port A stayed dead after a blip.** At 19:46:25 the Color & Distance sensor on port A briefly re-enumerated. hatd then logged "cannot open Color & Distance Sensor on port A: Port already used" 20 times a second until a restart. The old device object was still held by a read thread stuck in `Device.get()` (buildhat frees a port only in `Device.__del__`).
4. **The sensor flashes.** The user sees the Color & Distance LED flashing. hatd cycles it through color, reflection and distance about 7 times a second.

## Global Constraints

- Rules from `CLAUDE.md` apply. On the Pi, only `~/b3-dev` work (deploy, tests, temporary hatd) needs no question. The installed service `b3`, `sudo`, GPIO resets outside tests, and moving motors outside tests each need the user's yes, given for that one action.
- Target runtime: Python 3.11.2, aiohttp 3.8.4, buildhat 0.6.0, gpiozero (Debian bookworm).
- The API version stays `"1"`. The new command `program.running` and the new server message `{"type": "error", "error": {"code": "hat_not_responding", …}}` are additive.
- UI text is English.
- User decision (2026-10-17): while no program runs, the Color & Distance sensor stays in color mode. While a program runs, it keeps cycling as now.

## Review Focus

1. **False alarms.** A long but healthy movement (`run_for_degrees` 3600° at speed 10) must not trigger the watchdog, because only reads count. Pinned by `test_long_movement_is_not_a_hang` (Task 3).
2. **Watchdog during start or close.** The watchdog must never fire while the HAT is loading firmware at start, because telemetry starts only after `start()`. The exit must not hang. Pinned by `test_unresponsive_hat_frees_threads_and_reports` (Task 3) and checked on the Pi in Task 6.
3. **Ordering of `stop_all` and `program.running true` on Run.** Run sends `stop_all` and then `program.running`. The idle switch happens in `stop_all`'s synchronous prefix, so the later `running: true` wins. Pinned by `test_stop_all_then_running_ends_active` (Task 4).
4. **A reporter block clicked while idle** (e.g. "reflected light" on a Color & Distance sensor) gets only the color mode's values. Accepted for now and listed under "Not in this plan".
5. **Restart loop.** If the HAT never comes back after a reset, hatd exits non-zero again and systemd keeps retrying every 2 s plus start time. The log names the cause each time ("Build HAT not responding" or "HAT not found after reset").

---

### Task 1: A device that re-enumerates can be opened again

**Files:**
- Modify: `hatd/b3hatd/buildhat_backend.py`
- Test: `hatd/tests/test_buildhat_backend.py`

**Interfaces:**
- Produces: `BuildHatBackend._fail_port_waiters(port: str, error: Exception) -> None`. It sets `error` on every pending future in buildhat's `portftr[i]`, `rampftr[i]` and `pulseftr[i]` for that port and empties the lists. Task 3 reuses it.

- [ ] **Step 1: Write the failing test.** In `hatd/tests/test_buildhat_backend.py`:

Extend `FakeInstance.__init__` with:

```python
        self.portftr = [[] for _ in range(4)]
        self.vinftr = []
```

Add a fake that frees its port only when garbage-collected, like `buildhat.Device`:

```python
class FakeHangingColorDistance:
    """Like buildhat: the port is free again only when the object is deleted, and a
    getter waits on a portftr future that only the firmware resolves."""
    used: set = set()
    hang = False

    def __init__(self, port):
        self.idx = "ABCD".index(port)
        if self.idx in FakeHangingColorDistance.used:
            raise RuntimeError("Port already used")
        FakeHangingColorDistance.used.add(self.idx)

    def __del__(self):
        FakeHangingColorDistance.used.discard(self.idx)

    def _value(self, value):
        if FakeHangingColorDistance.hang:
            ftr = Future()
            FakeMotor.instance.portftr[self.idx].append(ftr)
            ftr.result(timeout=10)  # real buildhat waits forever; bounded so tests end
        return value

    def get_color(self):
        return self._value("red")

    def get_reflected_light(self):
        return self._value(40)

    def get_distance(self):
        return self._value(5)
```

Then the test:

```python
async def test_device_that_dropped_off_while_reading_is_opened_again(fake_buildhat, monkeypatch):
    monkeypatch.setattr(fake_buildhat, "ColorDistanceSensor", FakeHangingColorDistance)
    monkeypatch.setattr(FakeHangingColorDistance, "used", set())
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    FakeHangingColorDistance.hang = True
    try:
        await backend.read()  # a read starts and waits for a frame that never comes
        FakeHat.types = {"A": -1, "B": -1, "C": -1, "D": -1}  # sensor drops off
        await backend.read()
        FakeHangingColorDistance.hang = False
        FakeHat.types = {"A": 37, "B": -1, "C": -1, "D": -1}  # and comes back
        for _ in range(20):
            await backend.read()
            if backend.typeids()["A"] == 37:
                break
            await asyncio.sleep(0.05)
        assert backend.typeids()["A"] == 37
        assert "A" in backend._devices
    finally:
        FakeHangingColorDistance.hang = False
        await backend.close()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd hatd && .venv/bin/python -m pytest tests/test_buildhat_backend.py -k dropped_off -v`
Expected: FAIL on `typeids()["A"] == 37`. The log shows "Port already used", because the stuck read thread still holds the old object.

- [ ] **Step 3: Implement.** In `buildhat_backend.py`, add the method in the "interruption" section:

```python
    def _fail_port_waiters(self, port: str, error: Exception) -> None:
        """Wake every thread waiting on this port's firmware replies with `error`.
        buildhat waits on these futures without a timeout; a device that dropped off
        (or a silent HAT) would hold such a thread, and the old device object, forever."""
        hat = self._buildhat.devices.Device._instance
        i = PORTS.index(port)
        for lists in (hat.portftr, hat.rampftr, hat.pulseftr):
            pending = list(lists[i])
            lists[i].clear()
            for ftr in pending:
                try:
                    ftr.set_exception(error)
                except InvalidStateError:
                    pass
```

In `_refresh`, after `self._release_waiters(p)`, add:

```python
                self._fail_port_waiters(p, RuntimeError(f"port {p}: device changed"))
                self._reading.pop(p, None)
```

The woken thread's exception keeps a traceback, and so the frame holding the old device, alive in a reference cycle. buildhat frees the port only in `Device.__del__`. So in the `except` branch that logs "cannot open … Port already used", add `gc.collect()` (with `import gc` at the top). The next refresh, 50 ms later, can then open the port.

- [ ] **Step 4: Run the backend tests**

Run: `cd hatd && .venv/bin/python -m pytest tests/test_buildhat_backend.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** `fix(hatd): a device that drops off a port while being read can be opened again`

---

### Task 2: buildhat calls run on hatd's own threads

**Files:**
- Modify: `hatd/b3hatd/buildhat_backend.py`
- Test: `hatd/tests/test_buildhat_backend.py`

**Interfaces:**
- Produces: `BuildHatBackend._run(fn, *args, **kwargs)`, which is awaitable and runs `fn` on `self._hw_pool` (`ThreadPoolExecutor(max_workers=16, thread_name_prefix="b3-hw")`). Every `asyncio.to_thread` in the module is replaced by it.

- [ ] **Step 1: Write the failing test:**

```python
class _NoDefaultPool(ThreadPoolExecutor):
    def submit(self, *args, **kwargs):
        raise AssertionError("buildhat call on the event loop's default thread pool")


async def test_buildhat_calls_leave_the_default_pool_free(hat):
    # aiohttp serves files through the default pool; stuck hardware calls must not starve it
    asyncio.get_running_loop().set_default_executor(_NoDefaultPool(max_workers=1))
    await hat.read()
    await hat.vin()
    await hat.motor_run_for_degrees("A", 90, 50)
    await hat.motor_start("A", 20)
    await hat.motor_stop("A")
    await hat.stop_all()
```

Also add `from concurrent.futures import Future, ThreadPoolExecutor` to the test imports.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd hatd && .venv/bin/python -m pytest tests/test_buildhat_backend.py -k default_pool -v`
Expected: FAIL with "buildhat call on the event loop's default thread pool".

- [ ] **Step 3: Implement.** In `__init__`:

```python
        # all blocking buildhat calls; aiohttp's default pool stays free for files and logins
        self._hw_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="b3-hw")
```

Add this method:

```python
    async def _run(self, fn, *args, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(self._hw_pool, partial(fn, *args, **kwargs))
```

Replace each `asyncio.to_thread(` in `buildhat_backend.py` with `self._run(`. There are six places:
- `start`;
- `_refresh` (twice);
- `_call`;
- `vin`.

In `close()`, after `self._read_pool.shutdown(wait=False)`, add `self._hw_pool.shutdown(wait=False)`.

- [ ] **Step 4: Run the backend tests**

Run: `cd hatd && .venv/bin/python -m pytest tests/test_buildhat_backend.py -q`
Expected: all pass.

Then run `grep -n "to_thread" hatd/b3hatd/buildhat_backend.py`.
Expected: no output.

- [ ] **Step 5: Commit** `fix(hatd): run buildhat calls on hatd's own threads so the web server never starves`

---

### Task 3: Watchdog for a Build HAT that stops answering

**Files:**
- Modify: `hatd/b3hatd/buildhat_backend.py`, `hatd/b3hatd/telemetry.py`, `hatd/b3hatd/app.py`, `hatd/b3hatd/keys.py`, `hatd/b3hatd/__main__.py`
- Test: `hatd/tests/test_buildhat_backend.py`, `hatd/tests/test_telemetry.py`, `hatd/tests/test_app_fatal.py` (new)

**Interfaces:**
- Consumes: `_fail_port_waiters` (Task 1) and `_run` (Task 2).
- Produces:
  - `HAT_TIMEOUT = 3.0` (module constant in `buildhat_backend.py`);
  - `B3Error("hat_not_responding", "Build HAT is not responding. B3 restarts it; reconnect in a moment.")`, raised by `BuildHatBackend.read()` and `vin()`;
  - `TelemetryLoop(..., on_fatal: Callable[[B3Error], Awaitable[None]] | None = None)`;
  - `app.fatal(app, error)`, which broadcasts `{"type": "error", "error": error.to_dict()}`, sets `app[EXIT_CODE] = 75` and sends SIGTERM to its own process;
  - `__main__.main` exits with `app[EXIT_CODE]` when that is set.

- [ ] **Step 1: Write the failing tests.**

In `test_buildhat_backend.py`, give `FakeHat` a hanging `get_vin`:

```python
class FakeHat:
    types = {"A": 48, "B": -1, "C": -1, "D": -1}
    vin_hangs = False
    vin_released = False

    def get(self):
        return {p: {"typeid": t} for p, t in self.types.items()}

    def get_vin(self):
        if FakeHat.vin_hangs:
            ftr = Future()
            FakeMotor.instance.vinftr.append(ftr)
            try:
                ftr.result(timeout=10)
            except Exception:
                FakeHat.vin_released = True
                raise
        return 8.0
```

In the `fake_buildhat` fixture, add `monkeypatch.setattr(FakeHat, "vin_hangs", False)` and `monkeypatch.setattr(FakeHat, "vin_released", False)`. Then add these tests:

```python
async def test_unresponsive_hat_frees_threads_and_reports(fake_buildhat, monkeypatch):
    monkeypatch.setattr("b3hatd.buildhat_backend.HAT_TIMEOUT", 0.3)
    monkeypatch.setattr(fake_buildhat, "ColorDistanceSensor", FakeHangingColorDistance)
    monkeypatch.setattr(FakeHangingColorDistance, "used", set())
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    FakeHangingColorDistance.hang = True
    FakeHat.vin_hangs = True
    try:
        with pytest.raises(B3Error) as e:
            for _ in range(40):  # telemetry steps until the stuck read is older than HAT_TIMEOUT
                await backend.read()
                await asyncio.sleep(0.05)
        assert e.value.code == "hat_not_responding"
        with pytest.raises(B3Error) as e:
            await backend.vin()
        assert e.value.code == "hat_not_responding"
        await asyncio.sleep(0.1)
        assert FakeHat.vin_released, "the thread stuck in get_vin was woken"
        assert fake_buildhat.devices.Device._instance.portftr[0] == []
    finally:
        FakeHangingColorDistance.hang = False
        await backend.close()


async def test_long_movement_is_not_a_hang(hat, monkeypatch):
    monkeypatch.setattr("b3hatd.buildhat_backend.HAT_TIMEOUT", 0.3)
    task = asyncio.create_task(hat.motor_run_for_degrees("A", 3600, 10))  # 36 s in the fake
    for _ in range(12):
        await hat.read()
        await asyncio.sleep(0.05)
    assert not task.done()
    await hat.motor_stop("A")
    with pytest.raises(B3Error):
        await task
```

In `test_telemetry.py`:

```python
async def test_hat_not_responding_is_handed_to_on_fatal():
    from b3hatd.errors import B3Error

    class Dead(SimBackend):
        async def read(self):
            raise B3Error("hat_not_responding", "Build HAT is not responding.")

    fatal = []

    async def on_fatal(error):
        fatal.append(error.code)

    sink = Sink()
    loop = TelemetryLoop(Dead(), sink, on_fatal=on_fatal)
    await loop.step()
    await loop.step()
    assert fatal == ["hat_not_responding"]  # once, not every step
    assert sink.of("telemetry") == []
```

New file `hatd/tests/test_app_fatal.py`:

```python
import signal

from b3hatd import app as app_module
from b3hatd.errors import B3Error
from b3hatd.keys import EXIT_CODE
from tests.helpers import next_of_type, open_ws


async def test_fatal_tells_editors_and_stops_with_exit_code(authed, monkeypatch):
    kills = []
    monkeypatch.setattr(app_module.os, "kill", lambda pid, sig: kills.append(sig))
    ws, _ = await open_ws(authed)
    app = authed.server.app
    await app_module.fatal(app, B3Error("hat_not_responding", "Build HAT is not responding."))
    msg = await next_of_type(ws, "error")
    assert msg["error"]["code"] == "hat_not_responding"
    assert app[EXIT_CODE] == 75
    assert kills == [signal.SIGTERM]
    await app_module.fatal(app, B3Error("hat_not_responding", "again"))
    assert kills == [signal.SIGTERM], "only once"
    await ws.close()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd hatd && .venv/bin/python -m pytest tests/test_buildhat_backend.py tests/test_telemetry.py tests/test_app_fatal.py -q -k "unresponsive or long_movement or on_fatal or fatal"`
Expected: failures and errors:
- the unresponsive test raises no `B3Error`;
- `TelemetryLoop` rejects the `on_fatal` keyword;
- `EXIT_CODE` cannot be imported.

`test_long_movement_is_not_a_hang` may already pass. It guards against a wrong watchdog.

- [ ] **Step 3: Implement.**

In `buildhat_backend.py`, add a constant near `READ_WAIT`:

```python
# A healthy read answers within ~50 ms; one older than this means the HAT went silent
HAT_TIMEOUT = 3.0
```

In `__init__`, add `self._read_started: dict[str, float] = {}`. In `read()`, store the start time of each read where it is submitted, right after `self._reading[p] = fut`:

```python
            self._read_started[p] = loop.time()
```

At the top of `read()`, right after `await self._refresh()`:

```python
        loop = asyncio.get_running_loop()
        for p, fut in list(self._reading.items()):
            if not fut.done() and loop.time() - self._read_started.get(p, loop.time()) > HAT_TIMEOUT:
                self._unresponsive()
```

The existing `loop = asyncio.get_running_loop()` line below it can stay or be removed; it is the same object.

Replace `vin()`:

```python
    async def vin(self) -> float:
        try:
            return await asyncio.wait_for(self._run(self._hat.get_vin), HAT_TIMEOUT)
        except asyncio.TimeoutError:
            self._unresponsive()
```

Add this method:

```python
    def _unresponsive(self) -> None:
        """The HAT stopped answering: wake every thread waiting on it, then give up."""
        log.error("Build HAT not responding")
        error = RuntimeError("Build HAT not responding")
        for p in PORTS:
            self._fail_port_waiters(p, error)
        hat = self._buildhat.devices.Device._instance
        pending = list(hat.vinftr)
        hat.vinftr.clear()
        for ftr in pending:
            try:
                ftr.set_exception(error)
            except InvalidStateError:
                pass
        raise B3Error("hat_not_responding", "Build HAT is not responding. B3 restarts it; reconnect in a moment.")
```

In `telemetry.py`:
- `__init__` gains `on_fatal=None`, stored as `self.on_fatal`, plus `self._fatal = False`;
- at the start of `step()`, add `if self._fatal: return`;
- in `step()`, put this `except` before the generic `except Exception`:

```python
        except B3Error as e:
            if e.code != "hat_not_responding":
                log.exception("telemetry read failed")
                return
            self._fatal = True
            if self.on_fatal is not None:
                await self.on_fatal(e)
            return
```

Add `from .errors import B3Error`.

In `keys.py`, add `EXIT_CODE = _key("exit_code")`.

In `app.py`:
- add `import os` and `import signal`;
- import `EXIT_CODE`;
- add:

```python
async def fatal(app: web.Application, error: B3Error) -> None:
    """The hardware is gone: tell the editors, then stop so systemd restarts hatd."""
    if EXIT_CODE in app:
        return
    log.error("stopping: %s", error.message)
    app[EXIT_CODE] = 75
    await app[CLIENTS].broadcast({"type": "error", "error": error.to_dict()})
    os.kill(os.getpid(), signal.SIGTERM)
```

In `_on_startup`, create the loop as follows:

```python
    telemetry = TelemetryLoop(app[BACKEND], app[CLIENTS].broadcast, interval=config.telemetry_interval,
                              on_fatal=lambda e: fatal(app, e))
```

In `__main__.py`, keep a reference to the app and exit with its code. Import `sys` and `EXIT_CODE`.

```python
    app = build(args.config, args.sim, args.sim_devices)
    web.run_app(app, host=config.http_host, port=config.http_port, shutdown_timeout=5)
    if EXIT_CODE in app:
        sys.exit(app[EXIT_CODE])
```

`aiohttp.web.Application` supports `in` with both AppKey and str keys. On aiohttp 3.8 the keys are plain strings.

If `B3Error` has no `message` attribute, use `str(error)` in the log line. Check `b3hatd/errors.py` and use what is there.

- [ ] **Step 4: Run the hatd suite**

Run: `cd hatd && .venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit** `fix(hatd): a silent Build HAT frees its waiting threads, tells the editors and restarts hatd`

---

### Task 4: GPIO reset when the HAT is not found at start

**Files:**
- Modify: `hatd/b3hatd/buildhat_backend.py`
- Test: `hatd/tests/test_buildhat_backend.py`

**Interfaces:**
- Produces:
  - `reset_hat() -> None` (module function). It does what `buildhat`'s `BuildHAT.resethat` does: BOOT0 (GPIO 22) low, RESET (GPIO 4) low for 10 ms, then high, wait 0.5 s. With BOOT0 low the HAT restarts into its bootloader, and `buildhat.Hat()` then loads the firmware.
  - `BuildHatBackend(reset=reset_hat)`.

- [ ] **Step 1: Write the failing tests:**

```python
class FakeHatNotFoundOnce(FakeHat):
    failures = 1

    def __init__(self):
        if FakeHatNotFoundOnce.failures:
            FakeHatNotFoundOnce.failures -= 1
            raise RuntimeError("HAT not found")


async def test_hat_not_found_is_reset_and_retried(fake_buildhat, monkeypatch):
    monkeypatch.setattr(fake_buildhat, "Hat", FakeHatNotFoundOnce)
    monkeypatch.setattr(FakeHatNotFoundOnce, "failures", 1)
    resets = []
    backend = BuildHatBackend(reset=lambda: resets.append(1))
    await backend.start()
    assert resets == [1]
    assert backend.typeids()["A"] == 48
    await backend.close()


async def test_other_start_errors_are_not_retried(fake_buildhat, monkeypatch):
    def broken():
        raise RuntimeError("no serial port")
    monkeypatch.setattr(fake_buildhat, "Hat", broken)
    resets = []
    backend = BuildHatBackend(reset=lambda: resets.append(1))
    with pytest.raises(RuntimeError, match="no serial port"):
        await backend.start()
    assert resets == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd hatd && .venv/bin/python -m pytest tests/test_buildhat_backend.py -k "not_found or other_start" -v`
Expected: the first test fails with `TypeError` (unexpected keyword `reset`); the second fails the same way.

- [ ] **Step 3: Implement.** Add a module function:

```python
def reset_hat() -> None:
    """Restart the HAT into its bootloader, as buildhat does before loading new firmware.
    buildhat itself only resets on a firmware version mismatch, so a HAT whose firmware
    hung answers nothing and Hat() reports "HAT not found"."""
    import time
    from gpiozero import DigitalOutputDevice  # Pi only
    reset = DigitalOutputDevice(4)
    boot0 = DigitalOutputDevice(22)
    boot0.off()
    reset.off()
    time.sleep(0.01)
    reset.on()
    time.sleep(0.01)
    boot0.close()
    reset.close()
    time.sleep(0.5)
```

`__init__` gains a `reset=reset_hat` parameter, stored as `self._reset`. In `start()`, replace the `Hat()` line with:

```python
        try:
            self._hat = await self._run(buildhat.Hat)  # loads firmware on first run
        except Exception as e:
            if "HAT not found" not in str(e):
                raise
            log.warning("Build HAT not answering; resetting it")
            await self._run(self._reset)
            self._hat = await self._run(buildhat.Hat)
```

- [ ] **Step 4: Run the hatd suite.** Expected: all pass.

- [ ] **Step 5: Commit** `fix(hatd): reset the Build HAT when it is not found at start`

---

### Task 5: Sensors stay in one mode while no program runs; editor messages

**Files:**
- Modify:
  - `hatd/b3hatd/backend.py`, `hatd/b3hatd/buildhat_backend.py`, `hatd/b3hatd/commands.py`
  - `editor/packages/scratch-vm/src/extensions/b3/hub.js`
  - `editor/packages/scratch-gui/src/components/b3-bar/describe-port.js`
- Test:
  - `hatd/tests/test_buildhat_backend.py`, `hatd/tests/test_commands.py`
  - `editor/packages/scratch-vm/test/unit/b3_hub.js`
  - `editor/packages/scratch-gui/test/unit/components/b3-describe-port.test.js`

**Interfaces:**
- Produces:
  - `HatBackend.set_program_running(running: bool) -> None`, a non-abstract no-op in the base class, so `SimBackend` inherits it;
  - in `BuildHatBackend`, `stop_all()` switches to idle in its synchronous prefix;
  - the WebSocket command `program.running {running: bool}`, actuating (controller only);
  - the hub sends `program.running {running: true}` on `PROJECT_START` when it is the controller;
  - the hub shows a hatd `error` message with code `hat_not_responding` as a block error and stops the program.

- [ ] **Step 1: Write the failing tests.**

In `test_buildhat_backend.py`, change `test_multi_mode_sensor_reads_one_value_per_step` to call `backend.set_program_running(True)` right after `await backend.start()`, and add:

```python
async def test_idle_sensor_stays_in_its_first_mode(fake_buildhat, monkeypatch):
    # the Color & Distance LED changes with the mode; cycling makes it flash
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    sensor = backend._devices["A"]
    sensor.calls.clear()
    for _ in range(4):
        values = await backend.read()
    assert set(sensor.calls) == {"color"}
    assert values["A"] == {"color": "red"}
    backend.set_program_running(True)
    for _ in range(3):
        values = await backend.read()
    assert sorted(set(sensor.calls)) == ["color", "distance", "reflection"]
    assert values["A"] == {"color": "red", "reflection": 40, "distance": 5}
    await backend.close()


async def test_stop_all_then_running_ends_active(fake_buildhat, monkeypatch):
    # Run sends stop_all and then program.running; hatd handles them as concurrent tasks
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    backend.set_program_running(True)
    stop = asyncio.ensure_future(backend.stop_all())
    await asyncio.sleep(0)
    backend.set_program_running(True)
    await stop
    assert backend._active
    await backend.close()
```

In `test_commands.py`, follow its existing helper style (use `call(ws, cmd, args)` from `tests/helpers.py` and the existing fixtures that give control):

```python
async def test_program_running_sets_backend_mode(authed, backend):
    ws, _ = await open_ws(authed)
    await call(ws, "control.claim", {})
    reply = await call(ws, "program.running", {"running": True})
    assert reply["ok"]
    assert backend.program_running is True
    reply = await call(ws, "program.running", {"running": "yes"})
    assert reply["error"]["code"] == "bad_args"
    await ws.close()
```

If `call`'s signature differs, adapt the test to the existing helpers and ledger a ruling. `SimBackend` gets `program_running` through Step 3.

Append to `b3_hub.js`:

```js
test('program start tells hatd a program runs, only when in control', async t => {
    const {runtime} = await connected('me');
    runtime.emit('PROJECT_START');
    t.same(FakeWebSocket.last.lastRequest(), {id: FakeWebSocket.last.lastRequest().id, cmd: 'program.running',
        args: {running: true}});
    const other = await connected('someone');
    other.runtime.emit('PROJECT_START');
    t.notOk(FakeWebSocket.last.sent.some(m => m.cmd === 'program.running'));
});

test('hatd reporting a silent Build HAT stops the program and says so', async t => {
    const {hub, runtime} = await connected('me');
    const errors = [];
    hub.on('blockError', e => errors.push(e.message));
    FakeWebSocket.last.receive({type: 'error', error: {code: 'hat_not_responding', message: 'Build HAT is not responding.'}});
    t.equal(runtime.stopped, 1);
    t.same(errors, ['Build HAT is not responding.']);
});
```

Add to `b3-describe-port.test.js`, in `test('sensors', …)`:

```js
        expect(describePort('A', {kind: 'color_distance', name: 'Color & Distance Sensor', color: 'red'}))
            .toEqual({title: 'A · Color & Distance Sensor', value: 'red'});
```

- [ ] **Step 2: Run them to verify they fail**

Run:
- `cd hatd && .venv/bin/python -m pytest tests/test_buildhat_backend.py tests/test_commands.py -q -k "idle or running"`;
- `cd editor/packages/scratch-vm && ../../../.superpowers/tools/n npx tap test/unit/b3_hub.js 2>&1 | grep -E "^# \{|not ok"`;
- `cd editor/packages/scratch-gui && ../../../.superpowers/tools/n npx jest test/unit/components/b3-describe-port.test.js`.

Expected: the new tests fail. The causes are a missing `set_program_running` and an unknown command `program.running`; no request sent and no blockError; and `'red · undefined% · undefined'`.

- [ ] **Step 3: Implement.**

In `backend.py` (`HatBackend`), add this non-abstract method:

```python
    def set_program_running(self, running: bool) -> None:
        """Whether an editor program runs; backends may read sensors less while idle."""
        self.program_running = running

    program_running = False
```

In `buildhat_backend.py`:
- in `__init__`, add `self._active = False`;
- override the method:

```python
    def set_program_running(self, running: bool) -> None:
        self._active = running
        self.program_running = running
```

In `read()`, replace `readers = _READERS[self._kinds[p]]` with:

```python
            readers = _READERS[self._kinds[p]]
            if not self._active:
                readers = readers[:1]  # idle: one mode only, so a sensor's LED does not flash
```

In the `_refresh` open path, replace `_read_all(dev, dev_info.kind)` with a reader list that respects idle:

```python
                    readers = _READERS[dev_info.kind] if self._active else _READERS[dev_info.kind][:1]
                    self._values[p] = await self._run(lambda: {k: v for r in readers for k, v in r(dev).items()})
```

Then delete `_read_all` if nothing else uses it. In `set_program_running(False)`, drop the values of the other modes so the port bar does not show stale ones:

```python
    def set_program_running(self, running: bool) -> None:
        if not running and self._active:
            for p, kind in self._kinds.items():
                if len(_READERS[kind]) > 1:
                    self._values[p] = {}
        self._active = running
        self.program_running = running
```

In `stop_all()`, as the first line (before the interrupt loop, synchronous), add `self.set_program_running(False)`.

In `commands.py`, add this next to the other commands:

```python
@command("program.running")
async def _program_running(ctx: Context, args: dict):
    running = args.get("running")
    if not isinstance(running, bool):
        raise B3Error("bad_args", "running must be true or false")
    ctx.backend.set_program_running(running)
```

In `hub.js`, extend the `PROJECT_START` handler:

```js
        runtime.on('PROJECT_START', () => {
            this.running = true;
            this.resetProgramState();
            if (this.isController) this.request('program.running', {running: true}).catch(() => {});
        });
```

Add this case to `_onMessage`:

```js
        case 'error':
            if (msg.error && msg.error.code === 'hat_not_responding') {
                this.runtime.stopAll();
                this.emit('blockError', {message: msg.error.message, port: null, blockId: null});
            }
            break;
```

In `describe-port.js`, show only the values that are present:

```js
const joined = (...parts) => parts.filter(p => p !== null).join(' · ');
const pct = v => (typeof v === 'number' ? `${v}%` : null);
const colorName = c => {
    if (typeof c !== 'string') return null;
    return c === 'none' ? 'no color' : c;
};
```

and:

```js
    case 'color': return joined(colorName(device.color), pct(device.reflection));
    case 'color_distance':
        return joined(colorName(device.color), pct(device.reflection),
            typeof device.distance === 'number' ? `${device.distance}` : null);
```

- [ ] **Step 4: Run all suites**
- hatd: `cd hatd && .venv/bin/python -m pytest -q`. Expected: all pass.
- VM: `cd editor/packages/scratch-vm && ../../../.superpowers/tools/n npx tap test/unit/b3_*.js 2>&1 | grep -E "^# \{|not ok"; ../../../.superpowers/tools/n npx eslint src/extensions/b3 test/unit/b3_hub.js`. Expected: all pass, no lint errors.
- GUI: `cd editor/packages/scratch-gui && ../../../.superpowers/tools/n npx jest test/unit 2>&1 | grep -E "^Tests:"; ../../../.superpowers/tools/n npx eslint src/components/b3-bar`. Expected: all pass, no lint errors.
- e2e: from `editor/`, `NODE_ENV=production ../.superpowers/tools/n npm run build --workspace=packages/scratch-vm`, then in `scratch-gui` `npm run build:b3`, then from the root `PYTHON=hatd/.venv/bin/python .superpowers/tools/n ci/e2e.sh`. Expected: 5 passed, 1 skipped.

- [ ] **Step 5: Commit** `feat: sensors stay in one mode while no program runs; the editor shows a silent Build HAT`

---

### Task 6: Verify on the Pi 4 (with the user)

Each of these steps needs the user's yes:
- an update of the installed service with a local archive (`install.sh`, `sudo`);
- a GPIO reset of the HAT while the service runs;
- a motor program.

The user also unplugs and replugs the sensor on port A once.

- [ ] **Step 1:** Run the hardware suite in `~/b3-dev` first (no consent needed for the tests themselves). The service holds the HAT, so ask the user for `sudo systemctl stop b3` before the run and `sudo systemctl start b3` after it. Command: `ssh … 'cd ~/b3-dev/hatd && B3_HW_MOTOR=B B3_HW_ANGULAR=C B3_HW_CDS=A python3 -m pytest -m hardware -q'`. Expected: `12 passed, 1 skipped`.
- [ ] **Step 2:** Build the release archive (`install/make-release.sh`), copy it to `~/b3-dev`, and update the service: `sudo env B3_ARCHIVE=$HOME/b3-dev/b3.tar.gz bash ~/b3-dev/install.sh`.
- [ ] **Step 3: Idle LED.** With the editor open and no program running, the sensor LED on port A stays steady (color mode). The port bar shows the color only. Run a program and the LED cycles; press Stop and it is steady again.
- [ ] **Step 4: Port blip.** The user unplugs the sensor on port A for 2 s and plugs it back. Expected: the port bar shows "empty" and then the sensor again within a few seconds. The journal shows no repeating "Port already used".
- [ ] **Step 5: Silent HAT.** With the editor open, run `python3 ~/b3-dev/hat_reset.py`, which resets the HAT into its bootloader so its firmware stops answering. Expected:
  - within about 3–4 s the editor shows "Build HAT is not responding…" and the program stops;
  - the journal shows "Build HAT not responding" and an exit with status 75;
  - systemd restarts hatd and `buildhat` loads the firmware;
  - within about 30 s the editor reconnects. It asks for the PIN again, because sessions live in memory.

  Measure the time to recovery.
- [ ] **Step 6:** Record the results in `hatd/docs/hardware-notes.md` ("Build HAT recovery (2026-10-…)"), including the evidence list at the top of this plan. Commit.

## Not in this plan

- **The editor asks for the PIN again after every hatd restart**, because sessions are in memory. Keeping sessions in `/var/lib/b3` would avoid that.
- **A reporter block clicked while no program runs** reads only the idle mode's values (e.g. no reflection on a Color & Distance sensor).
- **The cause of the firmware hang itself.** Suspects are concurrent mode switches and reads on one port, or the forced kills during the install test. If it happens again, the hardware notes and the watchdog log will show when.
