# Hardware notes (measured)

Pi: Raspberry Pi 4 Model B Rev 1.5, Debian 12, Python 3.11.2, buildhat 0.6.0, date 2026-10-14.
Devices connected: Technic XL Motor 88014 on port B only.

| Item | Result |
|---|---|
| read() time, one motor | 0.4–20 ms (varies between runs) |
| Telemetry rate | loop sleeps 50 ms after each read, so real rate is ~14–20 Hz |
| run_for_degrees 90 @ 20 % overshoot (Technic XL 88014) | +109…+112° (≈ 20° overshoot), measured manually before hatd |
| stop_all during run_for: reply time | < 1 s (hardware test); motor stop not observed visually |
| Interrupted runs leaking threads | fixed — 10 interrupts in a row keep the thread count stable, each interrupt 0.3 s |
| hatd on real hardware | login, WebSocket hello, telemetry OK (vin 7.76 V) |
| Positive speed direction (seen from motor face) | not observed yet |
| Color names from get_color() | not measured (no sensor connected) |
| Raw ranges: C&D distance | 0–10, see "C&D distance calibration" |
| Raw ranges: WeDo tilt, WeDo motion | not measured (no device connected) |

## C&D distance calibration

Date 2026-10-17. BOOST Color & Distance 88007 on port A, a white sheet of paper held square
in front of the sensor, 20 samples of `ColorDistanceSensor.get_distance()` per distance.
All 20 samples were identical at every distance.

| Distance (cm) | 1 | 2 | 4 | 6 | 8 | 10 | 15 | 20 | 30 / nothing |
|---|---|---|---|---|---|---|---|---|---|
| Raw | 0 | 0 | 1 | 2 | 2 | 3 | 5 | 7 | 10 |

The editor converts with `cm = 3 × raw + 1` (`distanceCm` in `sensors.js`). Raw 10 is
also what the sensor reports with nothing in front, so the editor treats it as out of
range (`Infinity`, 100 %), like the Distance Sensor's −1.

## buildhat quirk: interrupted movements never complete

`Motor.run_for_degrees/run_for_seconds/run_to_position(blocking=True)` wait on a
future that is resolved by the firmware's "ramp done"/"pulse done" message. If the
movement is cut short by `stop()` (coast), that message never comes and the calling
thread blocks forever. hatd resolves those futures itself on interruption
(`BuildHatBackend._release_waiters`) and lets the released thread finish its trailing
`coast()` before the next command on the same port (`_settle`). Without this, after
~7 interrupted movements the thread pool is exhausted and `stop` takes 10 s.

## Pi Zero 2 W (simulator mode, no Build HAT)

Date 2026-10-14, Raspberry Pi Zero 2 W Rev 1.0, Debian 12, Python 3.11.2, aiohttp 3.8.4.
Load: 3 WebSocket clients from the PC for 60 s, one holding control and pinging every second.

| Item | Result | Limit |
|---|---|---|
| hatd RSS with 3 clients (peak) | 30.4 MB | < 100 MB |
| hatd average CPU (one core) | 2 % | < 25 % |
| Telemetry rate per client | 19.4 msg/s | ≥ 18 |

## Read timing with four devices (2026-10-14)

Devices: A BOOST Color & Distance 88007, B Technic XL 88014, C Large Angular (Grey) 88017, D Technic Large 88013.

| Read | Time |
|---|---|
| hatd `read()` today (each value read separately, ports one after another) | 144–170 ms → telemetry ≈ 5 Hz |
| one buildhat getter (waits for the next data frame) | ≈ 10 ms |
| C&D `get_color` / `get_reflected_light` / `get_distance` (each switches mode) | 30 / 40 / 10 ms, ≈ 110 ms for all three |
| one `Motor.get()` → `[speed, position, aposition]` | 10 ms |
| three motors, one `get()` each | 10 ms in total |
| C&D combi mode `[(0,0),(1,0),(3,0)]` → `[color index, proximity, reflected]` | 1.4 ms, but returned `[-1, 0, 0]` while single modes gave distance 3 / reflected 2 — semantics to be checked |
| C&D mode 8 | hangs — do not use |

Hardware suite with these devices: 11 passed, 1 skipped (no empty port), 1 failed (read time).
go_to 270 on Large Angular → aposition −95 (≈ 265°).

After the fix (motors one `get()`, sensors one value per step in per-port reader
threads, read() waits ≤ 30 ms): read() 10–17 ms with all four devices; hardware
suite 13/13 passed in 8 of 9 runs. One run (the 3rd of three back-to-back runs)
hung before its 6th test and was killed by `timeout`; not reproduced in the next
6 runs. Open issue — watch for it.

## Editor end-to-end on Pi 4 (2026-10-16)

hatd and the built editor deployed to `~/b3-dev`, hatd started from there; the
Playwright test (`test/b3-e2e`, Chromium headless on the PC, `B3_MOTOR=B`) passed
in 10.9 s: wrong PIN rejected, right PIN accepted, take control, a "when program
starts → B run clockwise for 1 rotations" script turned the Technic XL motor one
rotation, and a color block on port B showed "Port B: expected Color Sensor".
The port bar showed the real devices (A Color & Distance with color, reflected
light and distance, B Technic XL, C Large Angular Grey, D Technic Large). hatd
came up within ~10 s of start; its log had no warnings or errors.

## buildhat reader thread and stop_all (2026-10-16)

Checking the editor review's stop_all race on the Pi (stop_all, then at once a
C+D pair move) showed two hatd bugs:

- stop_all halted the new move, and the firmware's late `ramp done` for it made
  buildhat's reader thread (`serinterface.py` loop, `self.rampftr[portid].pop()`)
  raise `IndexError: pop from empty list` and die. From then on no port answered,
  and hatd did not exit on SIGTERM. This is the likely cause of the one hung
  hardware run noted above.
- Fix: buildhat's waiter lists are wrapped so an empty pop returns a spare
  future, and every motor command takes its own generation so stop_all leaves a
  port alone when a newer command has started on it.

After the fix, on the Pi: hardware suite 13/13 (B3_HW_MOTOR=B, B3_HW_ANGULAR=C,
B3_HW_CDS=A); 5× "stop_all + pair move" → all moves completed; 5× "stop_all
during a long pair move, then a 90° move" → interrupted / ok / ok; editor e2e
passed; a healthy hatd exits within 1 s of SIGTERM. Log clean throughout.

## Editor part B on Pi 4 (2026-10-16)

- Local suites: hatd 142, scratch-vm 4149, scratch-gui 342 (1 skipped) — all pass.
- Hardware suite on the Pi (B3_HW_MOTOR=B, B3_HW_ANGULAR=C, B3_HW_CDS=A): first runs were
  flaky. Cause: buildhat's `callbackloop` thread died with `TypeError: 'NoneType' object is
  not callable` when a device object was freed between the WeakMethod `_alive` check and the
  call; after that no sensor reported values until hatd restarted. Fixed by handing that
  thread only live callbacks (`_live_callbacks` in `buildhat_backend.py`). The test fixture
  now also waits for every configured port ("Port already used" while the previous test's
  device object is still alive). After both: 8 of 8 runs "12 passed, 1 skipped" (all four
  ports are occupied, so the empty-port test skips; "13 passed" meant a port was missing).
- Editor e2e against the Pi (B3_MOTOR=B): 3 passed, 1 skipped (light test needs simulated
  light devices). Motor B turned one rotation; the default "pop" sound (already PCM WAV, so
  uploaded unchanged: its md5 equals the asset id) went to `~/b3-dev/data/sounds` and played
  with aplay on the 3.5 mm jack (no listener present to confirm it was audible). hatd log clean.
- Light 88005, 3×3 matrix, Distance Sensor lights and WeDo tilt/motion checked only against
  the simulator; tilt direction signs (`wedo.js`) and the Distance Sensor light order are
  unverified on hardware.

## Installed service on Pi 4 (2026-10-17)

`install.sh` with a local release archive (`B3_ARCHIVE`), B3 0.1.0, on pipina2 (desktop session with PipeWire running):

| Check | Result |
|---|---|
| Install | apt had everything already; UART already set (no raspi-config change, no reboot hint); user `b3` created; service enabled and active on port 80 |
| Process | runs as `b3`, RSS 36 MB right after start |
| Files | `/opt/b3` root:root; `/var/lib/b3` owned by `b3`; `config.toml` mode 600 |
| Audio | installer chose `plughw:CARD=Headphones,DEV=0`; `start sound` played on the 3.5 mm jack while PipeWire was running |
| Editor at `http://pipina2.local` | login with the generated PIN, all four devices in the port bar, motor B turned 1 rotation |
| HTTP | `200`, `Cache-Control: no-cache` |
| `systemctl restart b3` with 2–4 editor connections open | 0.24 s |
| `systemctl kill -s KILL b3` | systemd restarted it (NRestarts=1) |
| Update (installer run again) | same PIN printed, both saved projects kept, no `/opt/b3.old` left |

## Build HAT recovery (2026-10-17)

What happened on the installed service (evidence for plan 3b):

1. **Firmware stopped answering.** At 19:37 the HAT firmware stopped answering while a program ran. A
   `faulthandler` dump (via gdb) showed seven threads in
   `Motor.run_for_degrees → get_position → Device.get → Future.result()`, plus telemetry reads and
   `get_vin`, all waiting forever. buildhat waits on these futures with no timeout. The default thread
   pool was exhausted, so even `GET /` hung.
2. **No recovery on restart.** Every restart failed with `BuildHATError("HAT not found")`, because buildhat
   resets the HAT only on a firmware version mismatch. A GPIO reset (`hat_reset.py`: BOOT0 low, RESET
   pulse) brought it back.
3. **A sensor blip killed its port until restart.** The Color & Distance sensor re-enumerated once, and
   port A then stayed "Port already used" until a restart. A read thread stuck in `Device.get()` held the
   old device object, and buildhat frees a port only in `Device.__del__`.
4. **The sensor LED flashed.** hatd cycled the Color & Distance sensor through color, reflection and
   distance about 7 times a second, so its LED flashed.

After plan 3b, with B3 0.1.0 and the service updated through `install.sh`:

| Check | Result |
|---|---|
| Hardware suite (`B3_HW_MOTOR=B B3_HW_ANGULAR=C B3_HW_CDS=A`) | 12 passed, 1 skipped (`test_color_distance_sensor_values` sets program running first) |
| Idle sensor | Color & Distance LED steady while no program runs; cycles during a program; steady again after Stop |
| Sensor unplugged for 2 s on port A | port shown empty, then the sensor again within seconds; motors unaffected |
| HAT reset into its bootloader while the service runs | watchdog after 4.4 s ("Build HAT not responding"), editors told, exit 75; systemd restart at 6.2 s; firmware loaded and editor reachable at 22.7 s; all four devices back, vin 7.79 V |

Note: port C (Large Angular) once was not detected until its cable was reseated; this was a loose plug,
not software.

## Motor stopping accuracy (2026-10-17)

buildhat's positional moves (`run_to_position`, `run_for_degrees`) plan a fast ramp, wait 0.2 s after
it and then release (coast) the motor; a fast move then rolls on. The user saw "go to position 0" end
past 0 on the other side each time.

Measured on a Large Angular motor (port C), error after 1 s:

| Move | buildhat default | hold until on target and not moving, then release |
|---|---|---|
| go to 0 from 6 positions, speed 40 / 75 / 100 % | up to 13° / 31° | at most 4° (all speeds) |
| run for 90/360/-180/720°, speed 40 / 75 % | up to 19° / 148° | at most 4° / 3° |
| holding forever (Pybricks-style `Stop.HOLD`) | | at most 2°, but the motor stays powered |

hatd now holds the motor (`release = False`) after these moves until it is within 3° of the target
and not moving for 3 reads (at most 1.5 s), then coasts it, so it can be turned by hand. A block takes
about 0.6 s longer. A stop while holding releases the motor at once.

Hardware suite after the change (3 runs): `run_for_degrees 90` moved 86-90°, `go_to 270` ended at
-87…-88 (target -90). `test_start_right_after_stop_keeps_running` was flaky before (a Technic XL at
30 % reports a speed of 3-12 0.6 s after start); it and `test_new_command_replaces_running_move` now
check the angle turned in 0.5 s.
