# World clock

Each save stores `day` and `minute`, where minute is normalized to `0..1439`.
Dialogue and scene conditions receive the same clock.

- `PassTime()` advances 15 minutes per call.
- `LetterSleep()` advances to 08:00 on the next day.
- A scene point may use `advance: "morning"`, `advance: "night"`, or a numeric
  minute delta.

Repeated traversal only replays userscript verbs with explicit repeat
semantics. This lets a player deliberately wait again without replaying every
story mutation on that node.
