# Scene layer

The raw dialogue graph is not a player-facing map. It may contain debug nodes,
future branches, condition routers, and conversations that share no physical
location. Deriving navigation from that graph would expose unearned structure.

A scene is therefore a hand-curated spatial menu above the graph. Points enter
conversations; exits move between scenes. When a conversation terminates, the
engine returns to its current scene or a curated home scene for that
conversation.

`show_when` hides unearned points. `done_when` retires exhausted points. Scene
conditions use the same variable, inventory, vitality, and clock semantics as
dialogue conditions.
