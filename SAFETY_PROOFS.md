# Safety Proofs & Formal Verification

This document specifies the exact safety guarantees proved for `qlab-sync` and explains how any engineer can independently reproduce every check.

---

## 1. Read-Only QLab Guarantee (By Construction)

Unlike event-driven scripts that can accidentally invoke mutating commands, `qlab-sync` enforces a strict **single-gateway allowlist** inside `osc_message()` (`qlab_sync.py`):

```python
ALLOWED_READ_ONLY_OSC_PATTERNS = (
    re.compile(r"^/workspaces$"),
    re.compile(r"^/workspace/[A-Za-z0-9-]+/connect$"),
    re.compile(r"^/workspace/[A-Za-z0-9-]+/runningOrPausedCues$"),
    re.compile(r"^/workspace/[A-Za-z0-9-]+/selectedCues$"),
)
```

- `tests/test_formal_and_safety.py::TestReadOnlyBoundary::test_static_ast_audit_zero_mutating_osc_calls_in_client` parses `qlab_sync.py` with Python's `ast` module and asserts:
  1. `QLabReadOnlyClient` contains exactly **one** `sock.sendall(...)` callsite, routed through `osc_message()`.
  2. Zero mutating OSC verbs (`/go`, `/panic`, `/stop`, `/pause`, `/new`, `/delete`, `/save`, `/move`, `/level`, `/armed`) exist anywhere in `QLabReadOnlyClient`.
- `TestMockQLabIntegration` runs a live localhost TCP/SLIP mock QLab server and verifies every single packet emitted over the wire passes `assert_read_only_osc()`.

---

## 2. State-Based Observation vs. Event-Based UDP

Fire-and-forget UDP OSC events (`"Cue X fired"`) suffer from packet loss, duplication, reordering, and cold-start blindness (starting mid-show misses earlier events).

`qlab-sync` instead uses **state-based TCP observation**: every poll tick observes the full ground-truth tuple `(connected, running_cues, playhead_cue)` and feeds it into a pure transition function:

```
step(SyncState, Observation, ShowConfig) -> (SyncState', Optional[SyncCommand])
```

This yields **Dijkstra self-stabilization**: after any transient Wi-Fi drop, QLab restart, or mid-show startup, the state machine converges automatically to the active stage cue within `debounce_ticks * poll_ms`.

---

## 3. Formally Verified Invariants

Both the TLA+ specification ([spec/QlabSync.tla](spec/QlabSync.tla), checked by official TLC in GitHub Actions) and the executable Python BFS model checker (`qlab_sync.py --verify`) verify all 6 invariants across every reachable state:

| ID | Invariant | Formal Meaning | Live-Show Protection |
|---|---|---|---|
| **I1** | **Non-Program Isolation** | `emittedLog[i] \in Orders` | Warning/header memos (`PRE`, `1W`, `6W`, `END`) never leak to the public program. |
| **I2** | **Debounce / Panic Immunity** | Emission requires `pendingTicks == DebounceTicks` | Accidental `SPACE` followed by `ESC` (Panic) within `1.5s` produces zero false updates. |
| **I3** | **Group Cue Atomicity** | `{4}`, `{4a}`, `{4b}`, `{4, 4a, 4b}` -> `{4}`; emitted `<= 1` time | Synced video + master WAV Group cues (and `1.5s` Fade & Stop Peers crossfades) emit cleanly once for the incoming act. |
| **I4** | **Idempotency** | `Cardinality({i : emittedLog[i] = o}) <= 1` | Duplicate poll ticks or reconnects never re-fire the same cue. |
| **I5** | **Strict Monotonicity** | `emittedLog[i] < emittedLog[i+1]` (unless `--allow-rewind`) | Up/down arrow browsing in QLab never rewinds the audience program; rapid scrolling across live-band memos never false-triggers. |
| **I6** | **Disconnect Safety** | `!connected => pending = None /\ cmd = None` | Network loss clears unconfirmed debounce without mutating committed progress; failed webhook POSTs preserve pending state so the next tick retries. |

---

## 4. Reproducing All Checks Locally

```bash
# 1. Exhaustive Python BFS model check
python3 qlab_sync.py --verify --config examples/sample-show.json

# 2. Full safety, AST audit, and mock-QLab TCP/SLIP test suite
python3 -m unittest discover -s tests -v

# 3. Official Lamport TLA+ TLC model checker (requires Java 17+ and tla2tools.jar)
java -cp tla2tools.jar tlc2.TLC -deadlock -config spec/QlabSync.cfg spec/QlabSync.tla
```
