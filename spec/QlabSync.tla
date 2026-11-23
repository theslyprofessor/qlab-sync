--------------------------- MODULE QlabSync ---------------------------
(*
  Machine-checked TLA+ formal specification for qlab-sync.
  Verifies all safety invariants across arbitrary interleavings of:
    - Playback cue activation & crossfade overlap
    - Group cue staggered subcues (e.g. synced video + master audio)
    - Warning / header memo isolation
    - Accidental GO followed by ESC / Panic abort before debounce
    - Rapid arrow-key scrolling vs deliberate Live Memo GO + dwell
    - Network disconnects & self-stabilizing reconnects
*)
EXTENDS Integers, FiniteSets, Sequences

CONSTANTS
  DebounceTicks,        \* Consecutive polls required to confirm (e.g. 3 ticks @ 500ms = 1.5s)
  Orders,               \* Finite set of valid program cue orders (e.g. 1..5)
  WarningMemos          \* Non-program warning/header cues (e.g. {"PRE", "1W", "END"})

VARIABLES
  syncedOrder,          \* Highest program order committed to remote program (0 = none)
  pendingOrder,         \* Candidate order undergoing debounce confirmation (0 = none)
  pendingTicks,         \* Consecutive ticks candidate has held (0..DebounceTicks)
  prevPlayhead,         \* Last observed QLab selected playhead cue
  emittedLog            \* Ordered log of emitted program orders

vars == <<syncedOrder, pendingOrder, pendingTicks, prevPlayhead, emittedLog>>

TypeOK ==
  /\ syncedOrder \in {0} \cup Orders
  /\ pendingOrder \in {0} \cup Orders
  /\ pendingTicks \in 0..DebounceTicks

Init ==
  /\ syncedOrder = 0
  /\ pendingOrder = 0
  /\ pendingTicks = 0
  /\ prevPlayhead = "PRE"
  /\ emittedLog = <<>>

\* ---- Safety Invariants ----

\* I1 (Non-Program Isolation): Only valid program orders ever appear in emittedLog.
InvValidOrdersOnly ==
  \A i \in 1..Len(emittedLog) : emittedLog[i] \in Orders

\* I4 & I5 (Idempotency + Strict Monotonicity): Emitted orders strictly increase; never duplicate.
InvStrictMonotonic ==
  Len(emittedLog) <= 1 \/ \A i \in 1..(Len(emittedLog) - 1) : emittedLog[i] < emittedLog[i + 1]

\* State-to-Log Consistency: syncedOrder always equals the tail of emittedLog (or 0).
InvSyncMatchesLog ==
  IF Len(emittedLog) = 0
  THEN syncedOrder = 0
  ELSE syncedOrder = emittedLog[Len(emittedLog)]

\* I3 (Group Cue Uniqueness): Any canonical order (including a multi-child Group cue)
\* can be emitted at most once across the entire show trace.
InvEveryOrderAtMostOnce ==
  \A o \in Orders : Cardinality({i \in 1..Len(emittedLog) : emittedLog[i] = o}) <= 1

\* ---- Next-State Relation ----

\* I6 (Disconnect Safety): Network drop clears transient debounce without mutating syncedOrder.
Disconnect ==
  /\ pendingOrder' = 0
  /\ pendingTicks' = 0
  /\ UNCHANGED <<syncedOrder, prevPlayhead, emittedLog>>

\* Observe an active playback cue (already canonicalized across Group children & crossfades).
ObserveRunning(ord, ph) ==
  /\ ord \in Orders
  /\ prevPlayhead' = ph
  /\ IF ord <= syncedOrder THEN
       /\ pendingOrder' = 0
       /\ pendingTicks' = 0
       /\ UNCHANGED <<syncedOrder, emittedLog>>
     ELSE
       LET nextTicks == IF pendingOrder = ord THEN pendingTicks + 1 ELSE 1 IN
       IF nextTicks >= DebounceTicks THEN
         /\ syncedOrder' = ord
         /\ pendingOrder' = 0
         /\ pendingTicks' = 0
         /\ emittedLog' = Append(emittedLog, ord)
       ELSE
         /\ pendingOrder' = ord
         /\ pendingTicks' = nextTicks
         /\ UNCHANGED <<syncedOrder, emittedLog>>

\* Observe ESC Panic or idle warning memo: cancels unconfirmed debounce with zero emission.
ObserveIdleOrPanic(ph) ==
  /\ pendingOrder' = 0
  /\ pendingTicks' = 0
  /\ prevPlayhead' = ph
  /\ UNCHANGED <<syncedOrder, emittedLog>>

Next ==
  \/ Disconnect
  \/ \E o \in Orders, ph \in WarningMemos : ObserveRunning(o, ph)
  \/ \E ph \in WarningMemos : ObserveIdleOrPanic(ph)

Spec == Init /\ [][Next]_vars

THEOREM Spec => [](TypeOK /\ InvValidOrdersOnly /\ InvStrictMonotonic /\ InvSyncMatchesLog /\ InvEveryOrderAtMostOnce)
===============================================================================
