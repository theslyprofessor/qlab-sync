# qlab-sync

[![Cross-Platform Safety & Formal Verification](https://github.com/theslyprofessor/qlab-sync/actions/workflows/verify.yml/badge.svg)](https://github.com/theslyprofessor/qlab-sync/actions/workflows/verify.yml)

**Read-only, zero-dependency, formally verified QLab 4 & 5 to live web program bridge for macOS, Windows, and Linux.**

`qlab-sync` watches an open QLab 4 or QLab 5 workspace over QLab's built-in TCP/SLIP OSC port (`53000`) and pushes confirmed "now on stage" cue transitions to any HTTPS webhook (such as a live digital concert program or backstage monitor).

---

## Why Booth Operators & Venues Can Verify It Is Safe

Theater and concert booth operators should never have to trust an opaque script next to a live show machine. `qlab-sync` is engineered so any booth tech, IT administrator, or audio engineer can audit the entire codebase in 5 minutes:

1. **Read-Only to QLab by Construction**:
   - Every outgoing OSC packet passes through `assert_read_only_osc(address)` before serialization.
   - Only **4 query/connect paths** are allowlisted:
     - `/workspaces`
     - `/workspace/{id}/connect`
     - `/workspace/{id}/runningOrPausedCues`
     - `/workspace/{id}/selectedCues`
   - Any attempt to emit `/go`, `/panic`, `/stop`, `/pause`, `/new`, `/delete`, `/save`, `/move`, `/level`, `/armed`, or `/fileTarget` raises `ReadOnlyViolationError` before a single byte touches the socket.
   - Verified automatically on every commit by a static Python AST audit (`tests/test_formal_and_safety.py`).
2. **Zero Setup on the QLab Booth Mac**:
   - Works on **QLab 4 Free, QLab 4 Pro, QLab 5 Free, and QLab 5 Pro**.
   - Requires **zero outgoing OSC cues**, zero workspace modifications, and zero plugins on the show computer.
   - Can even be paired with a **View-only** QLab workspace passcode (`ok:view`).
3. **Zero Third-Party Dependencies**:
   - Single-file Python 3 standard-library implementation ([qlab_sync.py](qlab_sync.py)). No `pip install`, no compiled binaries, no telemetry, no background daemons.
4. **Formally Verified Protocol (TLA+ & Exhaustive BFS)**:
   - Machine-checked with Leslie Lamport's **TLA+ TLC model checker** ([spec/QlabSync.tla](spec/QlabSync.tla)) and an embedded **exhaustive BFS model checker** (`python3 qlab_sync.py --verify`) in GitHub Actions CI across **Windows, macOS, and Linux**.
   - See [SAFETY_PROOFS.md](SAFETY_PROOFS.md) for all 6 proved safety and self-stabilization invariants.
5. **Safe Dry-Run Default**:
   - Running `qlab_sync.py` without `--live` never makes any outbound HTTP request; it only logs observed state transitions locally.

---

## Quick Start (macOS / Windows / Linux)

Requires Python 3.10+ (no external packages needed).

### 1. Run the Formal Verifier & Safety Audit Yourself

```bash
python3 qlab_sync.py --verify --config examples/sample-show.json
python3 -m unittest discover -s tests -v
```

### 2. Discover QLab on the Local Network (Optional)

```bash
python3 qlab_sync.py --discover
```

### 3. Dry-Run Against a Live QLab 4 or QLab 5 Instance

```bash
python3 qlab_sync.py \
  --config examples/sample-show.json \
  --host 192.168.1.50 \
  --port 53000 \
  --passcode ""
```

### 4. Live Sync to Your Webhook

```bash
export QLAB_SYNC_TOKEN="your-webhook-bearer-token"

python3 qlab_sync.py \
  --config path/to/your-show.json \
  --host 192.168.1.50 \
  --port 53000 \
  --live \
  --endpoint https://your-site.example/events/qlab-sync
```

---

## Webhook Payload Contract

Whenever a cue transition passes debounce confirmation (`--debounce 3` ticks at `--poll-ms 500` = `1.5s`), `qlab-sync` sends an authenticated JSON POST:

```http
POST /events/qlab-sync HTTP/1.1
Content-Type: application/json
Authorization: Bearer <QLAB_SYNC_TOKEN>

{
  "eventSlug": "example-concert-2026",
  "cueOrder": 4,
  "action": "start",
  "source": "running",
  "startedAt": 1795422841445
}
```

- `source`: `"running"` for confirmed Audio/Video/Group playback cues, or `"memo_advance"` for deliberate live-band/intermission Memo transitions.
- Receivers should treat duplicate `(eventSlug, cueOrder)` requests as idempotent.

---

## Show Mapping JSON Format

See [examples/sample-show.json](examples/sample-show.json):

- `playbackCueToOrder`: Maps QLab cue numbers (including Group cue children like `"4"`, `"4a"`, `"4b"`) to canonical integer program orders.
- `memoTransitions`: Optional `{ "from", "to", "order" }` transitions for 0-second Live Band or Intermission Memo cues. Only fires when playhead steps directly `from -> to` and rests on `to` for `>= debounce` ticks (immune to rapid arrow-key scrolling).
- `nonProgramCues`: Explicitly listed warning/header memos (`PRE`, `1W`, `END`, etc.); config loading fails fast if any cue overlaps `playbackCueToOrder`.

---

## License

MIT License. See [LICENSE](LICENSE).
