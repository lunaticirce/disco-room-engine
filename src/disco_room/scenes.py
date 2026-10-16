"""Scene layer — the spatial layer above the conversation graph.

A *scene* is a named location with a hand-curated list of interaction points
and exits. It is the text analog of a game's spatial room: when a conversation
terminates, the detective returns to the current scene's menu — never to the
dialogue graph (DOM). See docs/scene-layer.md.

Curation is hand-written, grown as the detective notices things; the menu
is NEVER derived from the graph — that would leak unearned branches, the very
thing the engine exists to hide. Each interaction point maps to a conversation
(conv id) under the hood; on a terminal the engine comes back here.

Scene files live in ../scenes/<id>.json:
  { id, name, blurb?,
    home_convs?: [conv_id, ...],
    points: [ {label, conv, node?, done_when?, show_when?, gain_item?, set_vars?, advance?} ],
    exits:  [ {label, to, show_when?, set_vars?} ],
    ending?: {show_when, title?, text?, continue_to?: [{label, to}, ...]} }

This module imports `room` (room imports THIS lazily, inside functions, to avoid
a load-time cycle). It owns no save schema of its own beyond a single-row
`scene(key=1, id)` table that records which scene the detective is standing in.
"""
import json, os
from . import room


def scenes_dir():
    return os.path.join(room.PROJ, "scenes")


def load_scene(scene_id):
    path = os.path.join(scenes_dir(), f"{scene_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


_SCENES_CACHE = None   # per-process: scene files are tiny and don't change mid-invocation

def _all_scenes():
    """Every scene file, loaded once (cached). Hand-curated and small."""
    global _SCENES_CACHE
    if _SCENES_CACHE is None:
        _SCENES_CACHE = {}
        directory = scenes_dir()
        if os.path.isdir(directory):
            for fn in sorted(os.listdir(directory)):
                if fn.endswith(".json"):
                    s = load_scene(fn[:-5])
                    if s:
                        _SCENES_CACHE[s["id"]] = s
    return _SCENES_CACHE

def _scene_lists_conv(scene, conv):
    if conv in scene.get("home_convs", []):
        return True
    return any(p.get("conv") == conv for p in scene.get("points", []))

def home_scene_for(conv, preferred=None):
    """The scene whose interaction points include this conversation, if any — a
    conversation's 'home' (where a [Leave.] terminal should return you to).
    When a conversation is intentionally reused in several scenes, preserve the
    caller's current scene; otherwise use deterministic scene-id order.
    None when the conv isn't a point in any built scene (e.g. the dream, or a
    location not yet drawn). Used by room.cmd_start so entering a conversation
    also places you in its scene, closing the maroon-on-leave gap."""
    if preferred:
        scene = _all_scenes().get(preferred)
        if scene and _scene_lists_conv(scene, conv):
            return preferred
    for sid, s in _all_scenes().items():
        if _scene_lists_conv(s, conv):
            return sid
    return None


def scenes_listing_conv(conv):
    """Where (if anywhere) a conversation is curated across all built scenes — a
    coverage check for the curation tool. Returns a list of (scene_id, kind, label,
    gate): kind is 'point' (player-facing menu item) or 'home' (terminal-return only,
    via home_convs — not shown in the menu); label/gate come from the point's own
    curation metadata (ours, not DE prose). Empty list = no built scene reaches it."""
    out = []
    for sid, s in _all_scenes().items():
        if conv in s.get("home_convs", []):
            out.append((sid, "home", None, None))
        for p in s.get("points", []):
            if p.get("conv") == conv:
                out.append((sid, "point", p.get("label"), p.get("show_when")))
    return out


def _ensure_scene_table(c):
    c.execute("CREATE TABLE IF NOT EXISTS scene(key INTEGER PRIMARY KEY, id TEXT)")


def current_scene_id():
    if not os.path.exists(room.SAVE):
        return None
    c = room.save(); _ensure_scene_table(c)
    r = c.execute("SELECT id FROM scene WHERE key=1").fetchone(); c.close()
    return r["id"] if r else None


def set_scene(scene_id):
    if not os.path.exists(room.SAVE):
        print(f"房间是空的。先: disco-room --profile {room.PROFILE_NAME} start <conv>")
        return
    c = room.save(); _ensure_scene_table(c)
    c.execute("INSERT INTO scene(key,id) VALUES(1,?) ON CONFLICT(key) DO UPDATE SET id=excluded.id", (scene_id,))
    c.commit(); c.close()


def _cond(cond, vars, inv, clock=None):
    """A missing condition = always; otherwise defer to the engine's DSL.
    `clock` threads the world-clock through scene gating (docs/clock.md:
    time-gated scene points/exits must see the same clock dialogue does)."""
    return True if cond is None else room.eval_condition(cond, vars, inv, clock=clock)


def menu_items(scene, vars, inv, clock=None):
    """The numbered menu: filtered interaction points, then exits.
    A point whose `done_when` holds is hidden (one-shot exhausted); a point whose
    `show_when` fails is hidden (unnoticed / unearned). Exits gate on their own
    `show_when` if present. An active ending seals both lists and exposes only
    its explicit `continue_to` exits. Order is stable so `look N` resolves the
    same list."""
    items = []
    # Ending state (case closed): the scene's ordinary points/exits are sealed;
    # only the ending's `continue_to` exits remain — the postgame roam entrypoints.
    ending = ending_for(scene, vars, inv, clock)
    if ending:
        for ct in ending.get("continue_to", []):
            items.append({"kind": "exit", "label": ct["label"], "to": ct["to"], "set_vars": {}})
        return items
    for p in scene.get("points", []):
        if "done_when" in p and _cond(p.get("done_when"), vars, inv, clock):
            continue
        if "show_when" in p and not _cond(p.get("show_when"), vars, inv, clock):
            continue
        items.append({
            "kind": "point",
            "label": p["label"],
            "conv": p["conv"],
            "node": p.get("node"),
            "gain_item": p.get("gain_item"),
            "set_vars": p.get("set_vars", {}),
            "advance": p.get("advance"),
            "heal": p.get("heal"),
            "repeat_heal": p.get("repeat_heal"),
        })
    for e in scene.get("exits", []):
        if "show_when" in e and not _cond(e.get("show_when"), vars, inv, clock):
            continue
        items.append({
            "kind": "exit",
            "label": e["label"],
            "to": e["to"],
            "set_vars": e.get("set_vars", {}),
        })
    return items


def ending_for(scene, vars, inv, clock=None):
    ending = scene.get("ending")
    if not ending:
        return None
    if "show_when" in ending and not _cond(ending.get("show_when"), vars, inv, clock):
        return None
    return ending


def _dialogue_option_count():
    """Read-only hint for command UX: is the current dialogue showing choices?"""
    conv, node = room.position()
    if conv is None:
        return 0
    rc = room.rom()
    sc = room.save()
    vars = room.load_vars(sc)
    fired = room.load_fired(sc)
    inv = room.load_inventory(sc)
    vit = room.load_vitality(sc)
    clock = room.load_clock(sc)
    sc.close()
    _, opts, _ = room.beat_options_with_origin(rc, conv, node, vars, inv, fired=fired, vit=vit, clock=clock)
    rc.close()
    return len(opts)


def _state():
    c = room.save()
    vars = room.load_vars(c); inv = room.load_inventory(c); clock = room.load_clock(c); c.close()
    return vars, inv, clock


def cmd_scene(scene_id=None):
    if scene_id:
        if not load_scene(scene_id):
            print(f"（场景 {scene_id} 没找到；当前位置未改变。）")
            return
        set_scene(scene_id)
    sid = current_scene_id()
    if not sid:
        print("（还没进任何场景。先用 `scene <id>` 进入，或 start 一个对话。）")
        return
    scene = load_scene(sid)
    if not scene:
        print(f"（场景 {sid} 没找到——scenes/{sid}.json 不存在。）")
        return
    vars, inv, clock = _state()
    ending = ending_for(scene, vars, inv, clock)
    if ending:
        print(f"〔{ending.get('title', scene['name'])}〕")
        if ending.get("text"):
            print(ending["text"])
        elif scene.get("blurb"):
            print(scene["blurb"])
        items = menu_items(scene, vars, inv, clock)   # ending state → continue_to exits only
        if items:
            print("—— 还能去（look N）——")
            for i, it in enumerate(items, 1):
                print(f"  {i}) {it['label']}    [look {i}]")
        else:
            print("（本案已结。这个存档停在结尾之后。）")
        return
    items = menu_items(scene, vars, inv, clock)
    print(f"〔{scene['name']}〕")
    if scene.get("blurb"):
        print(scene["blurb"])
    if not items:
        print("（这里没有可互动的了。）")
        return
    print("—— 可以 · 场景（look N）——")
    for i, it in enumerate(items, 1):
        print(f"  {i}) {it['label']}    [look {i}]")


def apply_repeat_heal(c, conv, node, spec):
    """Apply a scene-level repeatable rest-heal — but ONLY on a repeat visit, i.e.
    when (conv, node) is already in `fired`. The first visit is left to the conv's own
    ROM HealEndurance/HealVolition (which the engine fires exactly once, per make_fire).
    This key therefore heals every visit AFTER the first, where fire-once semantics
    would otherwise swallow the conversation's own heal verb after its node was
    durably fired.

    spec: {"health": n} and/or {"morale": n}, each a positive int (amount, capped at max).
    Requires `node` — (conv, node) is the fired key, so a repeat_heal point must pin its
    entry node. Returns the applied delta {pool: +/-n} ({} on first visit or empty spec).

    Why fired-gated, not unconditional: applying on the first visit too would double-heal
    (point-key +1 AND the conv's first-fire HealEndurance +1). Gating on `fired` makes
    first and repeat visits both heal exactly once.
    """
    if node is None:
        raise ValueError(f"repeat_heal on conv {conv} must specify `node` (the fired key)")
    if not isinstance(spec, dict):
        # repeat_heal is dict-only (unlike heal, which also accepts "full"). A
        # non-dict spec (e.g. "full") would otherwise iterate `pool in spec` over
        # the string chars, find nothing, and silently no-op. Fail loudly instead.
        raise ValueError(f"repeat_heal spec must be a dict of pool->positive-int, got {spec!r}")
    if (conv, node) not in room.load_fired(c):
        return {}
    amounts = {}
    for pool in ("health", "morale"):
        if pool in spec:
            amt = spec[pool]
            if not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
                raise ValueError(f"repeat_heal {pool} must be a positive int, got {amt!r}")
            amounts[pool] = amt
    if not amounts:
        return {}
    vit = room.load_vitality(c)
    vit0 = dict(vit)
    if "health" in amounts:
        vit["health_cur"] = min(vit["health_max"], vit["health_cur"] + amounts["health"])
    if "morale" in amounts:
        vit["morale_cur"] = min(vit["morale_max"], vit["morale_cur"] + amounts["morale"])
    room.save_vitality(c, vit)
    room.surface_vitality(vit0, vit)
    return {pool: vit[f"{pool}_cur"] - vit0[f"{pool}_cur"] for pool in amounts}


def apply_rest_heal(c, spec):
    """Apply a rest-heal tied to a sleep/bench point — UNCONDITIONAL: every rest
    heals, every time. Unlike repeat_heal (fired-gated, to avoid double-healing a
    conv's own first-fire ROM heal), rest points carry no ROM heal of their own,
    so there is no double-heal to avoid. This is the systematic morale/health
    restore that sleep otherwise lacks (DE's daychange heal is opaque C# we don't run).

    spec: "full" (both pools to max) or {"morale": n, "health": n} (positive ints,
    capped at max). Returns the applied delta {pool: +n} ({} if already at max).
    """
    vit = room.load_vitality(c)
    vit0 = dict(vit)
    if spec == "full":
        pools = ("morale", "health")
        vit["morale_cur"] = vit["morale_max"]
        vit["health_cur"] = vit["health_max"]
    elif isinstance(spec, dict):
        pools = tuple(pool for pool in ("morale", "health") if pool in spec)
        for pool in pools:
            amt = spec[pool]
            if not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
                raise ValueError(f"rest heal {pool} must be a positive int, got {amt!r}")
            vit[f"{pool}_cur"] = min(vit[f"{pool}_max"], vit[f"{pool}_cur"] + amt)
    else:
        raise ValueError(f"rest heal spec must be 'full' or a dict, got {spec!r}")
    room.save_vitality(c, vit)
    room.surface_vitality(vit0, vit)
    return {pool: vit[f"{pool}_cur"] - vit0[f"{pool}_cur"] for pool in pools}


def cmd_look(n, force=False):
    sid = current_scene_id()
    if not sid:
        print("（还没进任何场景，没东西可看。）")
        return
    # Soft-block: don't let `look` jump scenes / enter points while mid-conversation.
    # Faithful to DE (the world is greyed out during dialogue); the in-fiction exit
    # is a `[Leave.]` dialogue option. Escape valves: `leave`, or `look N!` to force
    # straight to item N.
    in_dialog = room.in_dialogue()
    if in_dialog and not force:
        print("（你在对话中——这会儿看场景会中断谈话。）")
        print("  离开对话：`beat` 看选项，挑 [Leave.] 那类 `choose N` 结束，会自然回到场景。")
        print("  实在出不来（没有 [Leave.]）：`leave` 强制结束对话，或 `look N!` 直接去第 N 项。")
        return
    if in_dialog and force:
        # Forced escape: abandon the current conversation cleanly first, so the next
        # `beat` shows the scene rather than the convo we just walked away from.
        room.abandon_conversation()
    scene = load_scene(sid)
    if not scene:
        return
    vars, inv, clock = _state()
    items = menu_items(scene, vars, inv, clock)
    if n < 1 or n > len(items):
        dialogue_count = _dialogue_option_count()
        if dialogue_count:
            print(f"无效场景选项 (look 只能用 1..{len(items)}；对话选项请用 choose 1..{dialogue_count})")
            if 1 <= n <= dialogue_count:
                print(f"如果你想选刚才对话里的第 {n} 项，请输入: choose {n}")
            return
        print(f"无效选项 (1..{len(items)})")
        return
    it = items[n - 1]
    if it["kind"] == "point":
        print(f"（{it['label']}）")
        if it.get("gain_item") or it.get("set_vars") or it.get("advance") or it.get("heal") or it.get("repeat_heal"):
            c = room.save()
            vars = room.load_vars(c)
            inv = room.load_inventory(c)
            if it.get("gain_item"):
                inv[it["gain_item"]] = False
            for key, value in it.get("set_vars", {}).items():
                vars[key] = value
            if it.get("advance"):   # "morning", "night", or +N minutes. See docs/clock.md.
                clock = room.load_clock(c)
                spec = it.get("advance")
                if spec == "morning":
                    # next 08:00 — if before 08:00 (e.g. slept at 01:00) keep the same day; else roll to tomorrow.
                    # (The bed is night-gated 21:00–04:59, so an early-morning sleep must not skip the day.)
                    if clock["minute"] < 8 * 60:
                        clock["minute"] = 8 * 60; clock["second"] = 0
                    else:
                        clock["day"] += 1; clock["minute"] = 8 * 60; clock["second"] = 0
                elif spec == "night":
                    night = 21 * 60
                    if clock["minute"] < night:
                        clock["minute"] = night; clock["second"] = 0
                    else:
                        clock["day"] += 1; clock["minute"] = night; clock["second"] = 0
                else:
                    clock["minute"] += int(spec)
                room.save_clock(c, clock)
            if it.get("heal"):   # rest-heal tied to a sleep/bench point — unconditional, every rest. See apply_rest_heal.
                apply_rest_heal(c, it["heal"])
            if it.get("repeat_heal"):   # scene-level repeatable rest-heal, fired-gated — see apply_repeat_heal. Only heals on repeat visits; first visit is the conv's own ROM HealEndurance(1).
                apply_repeat_heal(c, it["conv"], it.get("node"), it["repeat_heal"])
            room.save_vars(c, vars)
            room.save_inventory(c, inv)
            c.commit(); c.close()
        room.cmd_start(it["conv"], announce=False, node=it.get("node"))   # enter the conversation; scene unchanged
    else:  # exit → another scene
        if not load_scene(it["to"]):
            print(f"（{it['label']}——这块场景还没建。出去之前先得把它画好。见 docs/scene-layer.md。）")
            return
        if it.get("set_vars"):
            c = room.save()
            vars = room.load_vars(c)
            for key, value in it["set_vars"].items():
                vars[key] = value
            room.save_vars(c, vars)
            c.commit(); c.close()
        set_scene(it["to"])
        print(f"（{it['label']}）")
        cmd_scene()


def maybe_show_scene(conv=None):
    """On a conversation terminal: return to the current scene if one is set.
    If the current save has no scene but the terminal conversation has a known
    home scene, recover that scene first. Returns True if a scene menu was shown;
    with no scene available, prints a compass hint and returns False."""
    sid = current_scene_id()
    if not sid and conv is not None:
        home = home_scene_for(conv)
        if home:
            set_scene(home)
            sid = home
    if not sid:
        print("（这段到头了，此刻没有可回的场景。用 where 看你在哪儿，或 scene <id> / start <conv> 继续。）")
        return False
    scene = load_scene(sid)
    if scene:
        vars, inv, clock = _state()
        if ending_for(scene, vars, inv, clock):
            cmd_scene()
            return True
    print("（这条路到头了。回到房间。）")
    cmd_scene()
    return True


def maybe_show_ending():
    sid = current_scene_id()
    if not sid:
        return False
    scene = load_scene(sid)
    if not scene:
        return False
    vars, inv, clock = _state()
    if not ending_for(scene, vars, inv, clock):
        return False
    cmd_scene()
    return True
