#!/usr/bin/env python3
"""Disco Room Engine — a local, data-driven runtime for condition-heavy dialogue
graphs. Content (the dialogue database, profiles, scenes, saves) lives in a
separate content project pointed to by --project; this package ships none of it.

A "beat" is the NPC line(s) currently being heard plus the player's options.
Visibility is condition-driven: a branch is shown only when the current
profile's world-state has earned it. Run `disco-room help` for the command list.
"""
import ast, sqlite3, os, sys, re, random, json

PROJ = os.path.abspath(os.environ.get("DISCO_ROOM_PROJECT", os.getcwd()))
ROM = os.path.abspath(os.environ.get("DISCO_ROOM_ROM", os.path.join(PROJ, "data", "disco-rom.db")))
PROFILES = os.path.abspath(os.environ.get("DISCO_ROOM_PROFILES", os.path.join(PROJ, "profiles")))
DEFAULT_PROFILE = os.environ.get("DISCO_ROOM_DEFAULT_PROFILE", "default")
COMPAT = {}
SAVE = None

NODES = "temp_table"   # the full graph (dentries is an incomplete subset)

SKILL_BY_ATTR = {
    "Intellect": ["Logic", "Rhetoric", "Encyclopedia", "Drama", "Conceptualization", "Visual Calculus"],
    "Psyche":    ["Volition", "Inland Empire", "Empathy", "Authority", "Esprit de Corps", "Suggestion"],
    "Physique":  ["Endurance", "Pain Threshold", "Physical Instrument", "Electrochemistry", "Shivers", "Half Light"],
    "Motorics":  ["Hand/Eye Coordination", "Perception", "Reaction Speed", "Savoir Faire", "Interfacing", "Composure"],
}
DEFAULT_ATTRS = {"Intellect": 4, "Psyche": 4, "Physique": 2, "Motorics": 2}
ALL_SKILLS = [skill for skills in SKILL_BY_ATTR.values() for skill in skills]
CHECK_SKILL_ALIASES = {
    "Perception (Hearing)": "Perception",
    "Perception (Sight)": "Perception",
}
XP_BOOL_VERBS = (
    "XPPicoSetBool", "XPTinySetBool", "XPMinorSetBool",
    "XPStandardSetBool", "XPMajorSetBool",
)
REPUTATION_ALIASES = {
    "lawbringer": "the_law",
    "narcomania": "nacromania",
}
POLITICAL_REPUTATIONS = (
    "communist", "revacholian_nationhood", "ultraliberal", "moralist",
)
COPOTYPE_REPUTATIONS = (
    "superstar_cop", "apocalypse_cop", "sorry_cop", "boring_cop",
    "art_cop", "lawbringer",
)
PROFILE_NAME = DEFAULT_PROFILE
PROFILE = {}
BUILD = {"attrs": DEFAULT_ATTRS, "skill_by_attr": SKILL_BY_ATTR}

def scene_module():
    from . import scenes
    return scenes

def _content_path(value, default):
    path = value or default
    return path if os.path.isabs(path) else os.path.join(PROJ, path)

def configure_project(path=None, rom_path=None, profiles_path=None):
    """Point the engine at a content project without coupling it to this package.

    A content project owns its ROM, profiles, scenes, and saves. The public
    engine owns none of those files. Explicit arguments override environment
    variables; relative ROM/profile paths are resolved under the project root.
    """
    global PROJ, ROM, PROFILES, COMPAT
    PROJ = os.path.abspath(path or os.environ.get("DISCO_ROOM_PROJECT", os.getcwd()))
    ROM = os.path.abspath(_content_path(
        rom_path or os.environ.get("DISCO_ROOM_ROM"),
        os.path.join(PROJ, "data", "disco-rom.db"),
    ))
    PROFILES = os.path.abspath(_content_path(
        profiles_path or os.environ.get("DISCO_ROOM_PROFILES"),
        os.path.join(PROJ, "profiles"),
    ))
    compat_path = os.path.join(PROJ, "compatibility.json")
    if os.path.isfile(compat_path):
        with open(compat_path, "r", encoding="utf-8") as f:
            COMPAT = json.load(f)
    else:
        COMPAT = {}
    scenes = sys.modules.get("disco_room.scenes")
    if scenes is not None:
        scenes._SCENES_CACHE = None

def _project_path(path):
    return path if os.path.isabs(path) else os.path.join(PROJ, path)

def load_profile(name):
    path = os.path.join(PROFILES, f"{name}.json")
    if not os.path.exists(path):
        raise SystemExit(f"找不到档案: {name}（看 profiles/ 目录，或运行 disco-room profiles）")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    attrs = raw.get("attrs", DEFAULT_ATTRS)
    missing = [attr for attr in SKILL_BY_ATTR if attr not in attrs]
    if missing:
        raise SystemExit(f"profile {name} 缺少属性: {', '.join(missing)}")
    signature_skill = raw.get("signature_skill")
    if signature_skill and signature_skill not in ALL_SKILLS:
        raise SystemExit(f"profile {name} 的 signature_skill 不存在: {signature_skill}")
    return {
        "id": raw.get("id", name),
        "name": raw.get("name", name),
        "save": _project_path(raw.get("save", f"data/{name}-save.db")),
        "wall": raw.get("wall"),
        "attrs": attrs,
        "signature_skill": signature_skill,
        "notes": raw.get("notes", []),
    }

def configure_profile(name):
    global PROFILE_NAME, PROFILE, SAVE, BUILD
    PROFILE_NAME = name
    PROFILE = load_profile(name)
    SAVE = PROFILE["save"]
    BUILD = {
        "attrs": PROFILE["attrs"],
        "skill_by_attr": SKILL_BY_ATTR,
        "signature_skill": PROFILE.get("signature_skill"),
    }

def parse_cli(argv):
    project = os.environ.get("DISCO_ROOM_PROJECT", os.getcwd())
    profile = os.environ.get("DISCO_PROFILE", DEFAULT_PROFILE)
    args = list(argv[1:])
    while args:
        if args[0] in ("--project", "-C"):
            if len(args) < 2:
                raise SystemExit("--project 需要内容项目路径")
            project = args[1]
            args = args[2:]
        elif args[0].startswith("--project="):
            project = args[0].split("=", 1)[1]
            args = args[1:]
        elif args[0] in ("--profile", "-p"):
            if len(args) < 2:
                raise SystemExit("--profile 需要一个名字，比如 --profile lien")
            profile = args[1]
            args = args[2:]
        elif args[0].startswith("--profile="):
            profile = args[0].split("=", 1)[1]
            args = args[1:]
        else:
            break
    configure_project(project)
    return profile, args

def profile_label():
    return f"{PROFILE.get('name', PROFILE_NAME)} [{PROFILE_NAME}]"

# ---------- ROM (read-only) ----------
def rom():
    if not os.path.isfile(ROM):
        raise FileNotFoundError(
            f"ROM not found: {ROM}. Set --project or DISCO_ROOM_PROJECT to a content project."
        )
    c = sqlite3.connect(f"file:{ROM}?mode=ro", uri=True); c.row_factory = sqlite3.Row; return c

def actor_name(c, aid):
    r = c.execute("SELECT name FROM actors WHERE id=?", (aid,)).fetchone()
    return r["name"] if r else f"actor#{aid}"

def get_node(c, conv, nid):
    return c.execute(f"SELECT * FROM {NODES} WHERE conversationid=? AND id=?", (conv, nid)).fetchone()

def raw_outs(c, conv, nid):
    return [(r["dc"], r["dd"]) for r in c.execute(
        """SELECT destinationconversationid dc, destinationdialogueid dd
           FROM dlinks
           WHERE originconversationid=? AND origindialogueid=?
           ORDER BY priority""",
        (conv, nid))]

def is_text(n):
    if n is None:
        return False
    t = (n["dialoguetext"] or "").strip()
    return t != "" and t != "0"   # '0' is the extraction marker for "no line"

def entry_node(c, conv):
    """Max-reach node = de-facto START (the graph has cycles, so 'no incoming' fails)."""
    from collections import defaultdict, deque
    adj = defaultdict(list); nodes = set()
    for o, d in c.execute("SELECT origindialogueid,destinationdialogueid FROM dlinks WHERE originconversationid=? AND destinationconversationid=?", (conv, conv)):
        adj[o].append(d); nodes.add(o); nodes.add(d)
    for (nid,) in c.execute(f"SELECT id FROM {NODES} WHERE conversationid=?", (conv,)):
        nodes.add(nid)
    if not nodes:
        return None
    mem = {}
    def reach(s):
        if s in mem: return mem[s]
        seen = {s}; dq = deque([s])
        while dq:
            u = dq.popleft()
            for v in adj.get(u, []):
                if v not in seen: seen.add(v); dq.append(v)
        mem[s] = len(seen); return mem[s]
    return max(nodes, key=lambda n: (reach(n), -n))

# ---------- condition DSL ----------
# DE conditions are near-Python: lowercase `and`/`or`/`not`, ==, !=, parens.
# `Variable["x"]` reads the current profile's world-vars; predicates are stubbed to the honest
# opening state (no companions, thoughts, or inventory; day one, morning).
HOUR = 10   # the detective wakes mid-morning of day one; refine when DE's clock matters

class VarProxy:
    def __init__(self, vars): self.vars = vars
    def __getitem__(self, name): return self.vars.get(name, False)   # undefined var → False

def _day_count():
    """Frozen default day (1). Overridden when _cond_namespace is given a live `clock`."""
    return 1

def _clock_parts(clock=None):
    """Return a normalized (day, minute, hour) tuple without mutating the clock."""
    day = clock["day"] if clock else _day_count()
    minute = clock["minute"] if clock else (HOUR * 60)
    day += minute // 1440
    minute %= 1440
    return day, minute, minute // 60

def _cond_namespace(vars, inv, vit=None, clock=None):
    def equipped_any(prefix):
        return any(eq and item.startswith(prefix) for item, eq in inv.items())
    def has_item_group(group):
        return any(group in item for item in inv)
    def equipped_group(group):
        return any(eq and group in item for item, eq in inv.items())
    def kim_present():
        key = COMPAT.get("party_variables", {}).get("kim", "party.kim")
        return bool(vars.get(key, False))
    def cuno_present():
        key = COMPAT.get("party_variables", {}).get("cuno", "party.cuno")
        return bool(vars.get(key, False))
    def task_active(task):
        return (bool(vars.get(task, False)) and
                not bool(vars.get(f"{task}_done", False)) and
                not bool(vars.get(f"{task}_cancelled", False)) and
                not bool(vars.get(f"{task}_canceled", False)))
    def task_completed(task):
        return bool(vars.get(f"{task}_done", False))
    # Thought Cabinet: state lives in vars (no new table, no signature churn).
    # THP.<id> means the story has granted the thought; THF.<id> means the
    # detective chose to internalize it. ROM character.*_thought_done vars are
    # dialogue bookkeeping and can also be set when a thought is declined.
    def thc_present(tid):
        return bool(vars.get(f"THP.{tid}")) or bool(vars.get(f"THF.{tid}"))
    def thc_fixed(tid):
        return bool(vars.get(f"THF.{tid}"))
    def thc_cooking(tid):
        return thc_present(tid) and not thc_fixed(tid)
    # Clock — threaded from beat/choose/scene entry points (docs/clock.md). None ⇒
    # frozen Day1/10:00 (the pre-clock stub behaviour). Time predicates read these,
    # not the module globals; HOUR/_day_count survive only as the frozen default.
    # Normalize locally (read-only — don't mutate the caller's clock during eval). A PassTime
    # mid-traversal can leave minute>=1440 before save_clock rolls it over.
    cday, cminute, chour = _clock_parts(clock)
    def is_hour_between(a, b):
        if a <= b: return a <= chour <= b
        return chour >= a or chour <= b   # wraps past midnight (night spans like 21,4)
    return {
        "__builtins__": {},
        "Variable": VarProxy(vars),
        "true": True, "false": False,
        "IsKimHere": kim_present,
        "IsCunoInParty": cuno_present,
        "IsTHCPresent": thc_present,
        "IsTHCFixed": thc_fixed,
        "IsExterior": lambda: False, "IsOutside": lambda: False,
        "IsHourBetween": is_hour_between,
        "DayCount": lambda: cday,
        "IsDayFrom": lambda d: cday >= d,
        "IsDayUntil": lambda d: cday <= d,
        "IsMorning": lambda: 6 <= chour < 12,
        "IsNoon": lambda: 12 <= chour < 14,
        "IsAfternoon": lambda: 12 <= chour < 18,
        "IsDusk": lambda: 17 <= chour < 20,
        "IsEvening": lambda: 18 <= chour < 22,
        "IsNight": lambda: chour >= 22 or chour < 6,
        "IsDaytime": lambda: 6 <= chour < 22,
        "IsNighttime": lambda: chour >= 22 or chour < 6,
        "HourCount": lambda: chour,
        "TotalHourCount": lambda: (cday - 1) * 24 + chour,
        "IsTaskActive": task_active,
        "IsTaskCompleted": task_completed,
        # inventory-driven (these stubs retire now that items exist)
        "CheckItem":          lambda iid: iid in inv,
        "CheckItemGroup":     has_item_group,
        "CheckEquipped":      lambda iid: bool(inv.get(iid, False)),
        "CheckEquippedGroup": equipped_group,
        "CheckHeldRightGroup": equipped_group,
        "HasJacket":          lambda: equipped_any("jacket_"),
        "HasShirt":           lambda: equipped_any("shirt_"),
        "HasPants":           lambda: equipped_any("pants_"),
        "HasShoes":           lambda: equipped_any("shoes_"),
        "HasHat":             lambda: equipped_any("hat_"),
        "HasNecktie":         lambda: equipped_any("neck_"),
        "HasPawnablesInInventory": lambda: False,
        "IsTHCCookingOrFixed": thc_present,
        "IsTHCCooking": thc_cooking,
        "IsKimInParty": kim_present,
        "IsHighestPolitical": lambda name: _is_highest_reputation(vars, name, POLITICAL_REPUTATIONS),
        "IsHighestCopotype":  lambda name: _is_highest_reputation(vars, name, COPOTYPE_REPUTATIONS),
        "SubstanceUsedOnce":  lambda *a: False,
        "SubstanceUsedMore":  lambda *a: False,
        "WeirdClothing":      lambda: False,
        "MoneyAmount":        lambda: 0,
        # Wound predicates read the vitality pools (cur < max ⇒ damaged). vit is
        # threaded from the beat/choose entry points; callers that don't pass it
        # (e.g. scenes.py show_when/done_when, which never gate on wound state)
        # get vit=None ⇒ "not wounded", matching the old stub behaviour.
        "HasVolitionDamage":  lambda: vit is not None and vit["morale_cur"] < vit["morale_max"],
        "HasEnduranceDamage": lambda: vit is not None and vit["health_cur"] < vit["health_max"],
        "XPStandardSetBool":  lambda name: bool(vars.get(name, False)),
        "FinishTask":         lambda name: bool(vars.get(name, False)),
    }

_ALLOWED_CONDITION_NODES = (
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Call, ast.Name, ast.Load, ast.Constant, ast.Subscript,
)

def _validated_condition(expr, namespace):
    """Compile the condition subset without exposing general Python execution."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_CONDITION_NODES):
            raise ValueError(f"condition syntax is not allowed: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in namespace:
            raise ValueError(f"condition name is not allowed: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("condition calls must target a named predicate")
            target = namespace.get(node.func.id)
            if not callable(target) or node.keywords:
                raise ValueError(f"condition call is not allowed: {node.func.id}")
        if isinstance(node, ast.Subscript):
            if not isinstance(node.value, ast.Name) or node.value.id != "Variable":
                raise ValueError("only Variable[...] subscripts are allowed")
            if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
                raise ValueError("Variable keys must be string literals")
    return compile(tree, "<condition>", "eval")

def eval_condition(expr, vars, inv, vit=None, clock=None):
    """Evaluate a DE condition string against profile vars + inventory. Fail-open (True) + warn.
    `vit` (vitality pools) lets HasVolitionDamage/HasEnduranceDamage reflect current wounds.
    `clock` ({day,minute}) lets the time/day predicates reflect the live world-clock.
    The expression is AST-validated before evaluation; content cannot access
    Python attributes, imports, comprehensions, lambdas, or dynamic call targets."""
    expr = (expr or "").strip()
    expr = re.sub(r"--\[\[.*?\]\]", "", expr, flags=re.S).strip()   # strip Lua long comments
    expr = normalize_condition_expr(expr)
    if not expr:
        return True
    try:
        namespace = _cond_namespace(vars, inv, vit, clock)
        code = _validated_condition(expr, namespace)
        return bool(eval(code, namespace))
    except Exception as e:
        sys.stderr.write(f"[cond fail-open] {expr!r}: {e}\n")
        return True

def cond_true(c, conv, nid, vars, inv, vit=None, clock=None):
    n = get_node(c, conv, nid)
    if n is None:
        return False
    return eval_condition(n["conditionstring"], vars, inv, vit, clock)

def outs_passing(c, conv, nid, vars, inv, vit=None, clock=None):
    """Children of nid whose own condition passes, in priority order."""
    return [(dc, dd) for dc, dd in raw_outs(c, conv, nid) if cond_true(c, dc, dd, vars, inv, vit, clock)]

# ---------- beat resolution (condition-aware) ----------
def flow_to_player(c, conv, nid, vars, inv, vit=None, clock=None):
    """From nid, walk the condition-allowed path to the first 'You' (player) text line."""
    seen = set(); cur = (conv, nid)
    while cur is not None and cur not in seen:
        seen.add(cur)
        cur_conv, cur_node = cur
        n = get_node(c, cur_conv, cur_node)
        if n is None:
            return None
        if is_text(n) and actor_name(c, n["actor"]) == "You":
            return cur
        ps = outs_passing(c, cur_conv, cur_node, vars, inv, vit, clock)
        if not ps:
            return None
        cur = ps[0]
    return None

def option_available(c, conv, node, vars, fired=None):
    """Hide resolved (succeeded) and one-shot (red) checks; leave ordinary repeatable
    options and retryable white checks visible after a failure."""
    hidden = {tuple(pair) for pair in COMPAT.get("hidden_player_lines", [])}
    if (conv, node) in hidden:
        return False
    n = get_node(c, conv, node)
    if n is None or not n["hascheck"]:
        return True
    cr = check_row(c, conv, node)
    if not cr:
        return True
    if vars.get(cr["flagname"]) is True:
        return False    # succeeded -> resolved, hide
    # Red checks are one-shot: lock after one attempt. White checks are retryable
    # after a failure (faithful to DE's common white-check behaviour -- failing a
    # white check doesn't permanently lose the option). The rarer "locked until the
    # skill increases" white-check subset is future work (skill-change reopen model).
    if cr["isred"] and fired and (conv, node) in fired:
        return False
    return True

def beat_options_with_origin(c, conv, start, vars, inv, fired=None, fire=None, vit=None, clock=None):
    """From an NPC text node, walk forward collecting NPC lines until player option(s).
    Returns (npc_lines, options, origin) where options is a list of (conv, node)
    player lines and origin is the graph node whose passing outs produced them.
    Condition-failed branches are hidden — the detective only sees what he's earned.
    `fire(conv, nid)` is called on each node traversed; its userscript fires once
    by convention of the caller's fire-once guard."""
    npc = []; seen = set(); cur = (conv, start)
    while cur is not None and cur not in seen:
        seen.add(cur)
        cur_conv, cur_node = cur
        n = get_node(c, cur_conv, cur_node)
        if n is None:
            return npc, [], cur
        if fire:
            fire(cur_conv, cur_node)
        if is_text(n):
            sp = actor_name(c, n["actor"])
            if sp == "You":           # current position is an already-chosen player line
                if not outs_passing(c, cur_conv, cur_node, vars, inv, vit, clock):
                    return npc, [], cur
                return npc, [cur], cur
            npc.append((sp, n["dialoguetext"]))
        ps = outs_passing(c, cur_conv, cur_node, vars, inv, vit, clock)
        if not ps:
            return npc, [], cur       # terminal
        if len(ps) == 1:
            cur = ps[0]; continue
        # fork: resolve each passing child to its player line
        opts = []; seen_opts = set()
        for child_conv, child_node in ps:
            pl = flow_to_player(c, child_conv, child_node, vars, inv, vit, clock)
            if pl is not None and pl not in seen_opts and option_available(c, pl[0], pl[1], vars, fired):
                seen_opts.add(pl)
                opts.append(pl)
        return npc, opts, cur
    return npc, [], cur

def beat_options(c, conv, start, vars, inv, fired=None, fire=None, vit=None, clock=None):
    npc, opts, _ = beat_options_with_origin(c, conv, start, vars, inv, fired=fired, fire=fire, vit=vit, clock=clock)
    return npc, opts

def walk_to_npc(c, conv, player_node, vars, inv, fire=None, vit=None, clock=None):
    """After the player speaks, flow to the next NPC text node.
    Fires the userscript of every node traversed (world mutates as the detective moves),
    including the player's own line and the destination node."""
    seen = set(); cur = (conv, player_node)
    if fire:
        fire(*cur)                         # the player's own line
    while cur is not None and cur not in seen:
        seen.add(cur)
        cur_conv, cur_node = cur
        ps = outs_passing(c, cur_conv, cur_node, vars, inv, vit, clock)
        if not ps:
            return None
        cur = ps[0]
        if fire:
            fire(*cur)                     # each node stepped onto, destination included
        cur_conv, cur_node = cur
        n = get_node(c, cur_conv, cur_node)
        if n is not None and is_text(n) and actor_name(c, n["actor"]) != "You":
            return cur
    return None

# ---------- userscripts (world mutation) ----------
def parse_lua_value(raw):
    raw = raw.strip()
    if raw == "true":  return True
    if raw == "false": return False
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        return raw

def _split_lua_args(raw):
    args = []; start = 0; depth = 0; in_string = False; escape = False
    for i, ch in enumerate(raw):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(raw[start:i].strip())
            start = i + 1
    args.append(raw[start:].strip())
    return args

def iter_lua_calls(script, name):
    needle = f"{name}("
    pos = 0
    while True:
        start = script.find(needle, pos)
        if start == -1:
            return
        i = start + len(needle)
        depth = 1; in_string = False; escape = False
        while i < len(script):
            ch = script[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    yield _split_lua_args(script[start + len(needle):i])
                    pos = i + 1
                    break
            i += 1
        else:
            return

def _as_number(value):
    if value is True:
        return 1
    if value is False or value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

def _finished_task_key(name, vars):
    """ROM FinishTask usually receives a *_done flag, but 26 calls pass the task base."""
    if not isinstance(name, str) or name.endswith("_done"):
        return name
    done = f"{name}_done"
    return done if done in vars else name

def _reputation_key(name):
    return f"reputation.{REPUTATION_ALIASES.get(name, name)}"

def _is_highest_reputation(vars, name, group):
    target = _as_number(vars.get(_reputation_key(name), 0))
    values = [_as_number(vars.get(_reputation_key(candidate), 0)) for candidate in group]
    return target > 0 and target == max(values)

def _xp_flag_key(name, known):
    """Prefer the exact XP flag; repair the one ROM call missing its XP. prefix."""
    if name in known:
        return name
    prefixed = f"XP.{name}"
    return prefixed if prefixed in known else name

def iter_reputation_changes(script):
    """Yield canonical (variable, delta) pairs from the ROM reputation verbs."""
    for args in iter_lua_calls(script or "", "ReputationGrows"):
        if args:
            yield _reputation_key(parse_lua_value(args[0])), 1
    for args in iter_lua_calls(script or "", "ReputationLowers"):
        if args:
            yield _reputation_key(parse_lua_value(args[0])), -1
    for args in iter_lua_calls(script or "", "Reputation"):
        if len(args) >= 2:
            yield _reputation_key(parse_lua_value(args[0])), _as_number(parse_lua_value(args[1]))

def _split_top_level(raw, delimiter):
    """Split a one-character Lua operator outside strings and nested calls."""
    parts = []; start = 0; depth = 0; in_string = False; escape = False
    for i, ch in enumerate(raw):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == delimiter and depth == 0:
            parts.append(raw[start:i].strip())
            start = i + 1
    parts.append(raw[start:].strip())
    return parts

def eval_lua_value(raw, vars, inv=None, vit=None, clock=None):
    """Evaluate the small value-expression subset emitted by SetVariableValue.

    This is deliberately not a general Lua evaluator. Every supported form is
    present in the shipped ROM and has an unambiguous value in the room state.
    """
    raw = raw.strip()
    parts = _split_top_level(raw, "+")
    if len(parts) > 1:
        return sum(_as_number(eval_lua_value(part, vars, inv, vit, clock)) for part in parts)
    m = re.fullmatch(r'Variable\["([^"]+)"\]', raw)
    if m:
        return vars.get(m.group(1), 0)
    m = re.fullmatch(r'not\(\s*Variable\["([^"]+)"\]\s*\)', raw)
    if m:
        return not bool(vars.get(m.group(1), False))
    m = re.fullmatch(r'once\(([-]?\d+)\)', raw)
    if m:
        return int(m.group(1))
    cday, cminute, chour = _clock_parts(clock)
    if raw == "TotalHourCount()":
        return (cday - 1) * 24 + chour
    if raw == "DayCount()":
        return cday
    if raw == "NextMorningTime()":
        next_day = cday if cminute < 8 * 60 else cday + 1
        return (next_day - 1) * 24 + 8
    m = re.fullmatch(r'IsHighest(Political|Copotype)\("([^"]+)"\)', raw)
    if m:
        group = POLITICAL_REPUTATIONS if m.group(1) == "Political" else COPOTYPE_REPUTATIONS
        return _is_highest_reputation(vars, m.group(2), group)
    # One ROM expression assigns `true and CancelTask(...)`; CancelTask is
    # handled independently by apply_userscript, so the assigned value is true.
    if re.fullmatch(r'true\s+and\s+[A-Za-z_]\w*\(.*\)', raw):
        return True
    return parse_lua_value(raw)

def normalize_condition_expr(expr):
    """Repair harmless extractor glitches before Python eval.

    Seen in ROM: the same Variable[...] token duplicated with only whitespace
    between the copies, which is invalid Python but semantically just the one
    gate. Keep this deliberately narrow so real malformed conditions still
    surface as fail-open warnings.
    """
    expr = expr.replace("\xa0", " ")
    expr = re.sub(r'\bIsKimere\b', "IsKimHere", expr)
    expr = re.sub(r'\bIsTHCPresenT\b', "IsTHCPresent", expr)
    expr = re.sub(
        r'SetVariableValue\(\s*"([^"]+)"\s*,\s*(true|false)\s*\)',
        r'Variable["\1"] == \2',
        expr)
    expr = re.sub(
        r'FinishTask\(\s*"([^"]+)"\s*\)',
        r'Variable["\1"]',
        expr)
    expr = re.sub(
        r'XP(?:Pico|Tiny|Minor|Standard|Major)SetBool\(\s*"([^"]+)"\s*\)',
        r'Variable["\1"]',
        expr)
    expr = re.sub(
        r'IsHourBetween\(\s*0+(\d+)\s*,\s*0*(\d+)\s*\)',
        r'IsHourBetween(\1,\2)',
        expr)
    for source, replacement in COMPAT.get("condition_replacements", {}).items():
        expr = re.sub(rf'\b{re.escape(source)}\b', replacement, expr)
    prev = None
    while prev != expr:
        prev = expr
        expr = re.sub(r'(Variable\["[^"]+"\])\s+\1', r'\1', expr)
    return expr

def apply_userscript(script, vars, inv, vit=None, clock=None):
    """Execute world-mutation calls into vars + inv (+ vitality / clock when given). Visual/game-feel ignored.
    Handled: SetVariableValue, GainTask/FinishTask/CancelTask, GainItem, LoseItem, GainThought,
    the Health/Morale verbs (Damage/Heal Volition|Endurance, HealAllVolition) when `vit` is passed
    — see docs/vitality.md; and the time verbs (PassTime/LetterSleep) when `clock` is passed
    — see docs/clock.md. XP reward flags and Reputation are handled, while XP
    totals/level-ups and TequilaWakeUp flavor remain pending."""
    if not script:
        return
    for args in iter_lua_calls(script, "SetVariableValue"):
        if len(args) >= 2:
            name = parse_lua_value(args[0])
            vars[name] = eval_lua_value(args[1], vars, inv, vit, clock)
    for args in iter_lua_calls(script, "GainTask"):
        if args:
            name = parse_lua_value(args[0])
            vars[name] = True
            cancel_keys = [
                key for key in (f"{name}_cancelled", f"{name}_canceled")
                if key in vars
            ]
            for key in cancel_keys or [f"{name}_cancelled"]:
                vars[key] = False
    for args in iter_lua_calls(script, "FinishTask"):
        if args:
            vars[_finished_task_key(parse_lua_value(args[0]), vars)] = True
    for args in iter_lua_calls(script, "CancelTask"):
        if args:
            vars[parse_lua_value(args[0])] = True
    # XP reward functions also persist a named story flag. XP totals/level-ups
    # remain deferred, but dropping the bool strands downstream ROM conditions.
    for verb in XP_BOOL_VERBS:
        for args in iter_lua_calls(script, verb):
            if args:
                name = _xp_flag_key(parse_lua_value(args[0]), vars)
                vars[name] = True
    for name, delta in iter_reputation_changes(script):
        vars[name] = _as_number(vars.get(name, 0)) + delta
    for m in re.finditer(r'GainItem\(\s*"([^"]+)"\s*\)', script):
        item_id = m.group(1)
        auto_equipped = item_id in set(COMPAT.get("auto_equip_items", []))
        inv.setdefault(item_id, auto_equipped)
    for m in re.finditer(r'LoseItem\(\s*"([^"]+)"\s*\)', script):
        inv.pop(m.group(1), None)
    # GainThought("id") — the thought enters the cabinet as cooking/present.
    # Internalize is the detective's deliberate act (cmd_internalize), not this.
    for args in iter_lua_calls(script, "GainThought"):
        if args:
            vars[f"THP.{parse_lua_value(args[0])}"] = True
    # Health & Morale — vit = {morale_cur, morale_max, health_cur, health_max}.
    # DE names the verbs by governing skill: Volition↔Morale, Endurance↔Health.
    if vit is not None:
        for args in iter_lua_calls(script, "DamageVolition"):
            vit["morale_cur"] = max(0, vit["morale_cur"] - _as_number(eval_lua_value(args[0], vars, inv, vit, clock) if args else 1))
        for args in iter_lua_calls(script, "HealVolition"):
            vit["morale_cur"] = min(vit["morale_max"], vit["morale_cur"] + _as_number(eval_lua_value(args[0], vars, inv, vit, clock) if args else 1))
        for _args in iter_lua_calls(script, "HealAllVolition"):
            vit["morale_cur"] = vit["morale_max"]
        for args in iter_lua_calls(script, "DamageEndurance"):
            vit["health_cur"] = max(0, vit["health_cur"] - _as_number(eval_lua_value(args[0], vars, inv, vit, clock) if args else 1))
        for args in iter_lua_calls(script, "HealEndurance"):
            vit["health_cur"] = min(vit["health_max"], vit["health_cur"] + _as_number(eval_lua_value(args[0], vars, inv, vit, clock) if args else 1))
        for args in iter_lua_calls(script, "DamageEnduranceWithNewspaper"):   # flavor variant of DamageEndurance
            vit["health_cur"] = max(0, vit["health_cur"] - _as_number(eval_lua_value(args[0], vars, inv, vit, clock) if args else 1))
    # Clock — see docs/clock.md. Each PassTime call advances 15 minutes.
    # LetterSleep advances to next morning (08:00). Day-rollover normalization at save_clock.
    if clock is not None:
        for _args in iter_lua_calls(script, "PassTime"):
            clock["minute"] += 15
        for _args in iter_lua_calls(script, "LetterSleep"):
            clock["day"] += 1; clock["minute"] = 8 * 60
        normalize_clock(clock)   # roll minute overflow into day mid-traversal

def apply_repeatable_userscript(script, clock=None):
    """Replay verbs that represent a deliberate repeatable action.

    A durable `fired` row protects the room from applying a node twice when
    `choose` immediately redraws the destination with `beat`. When the player
    deliberately chooses a path through an old node again, PassTime must still
    happen. Other effects keep the established
    fire-once semantics until their subsystem defines repetition explicitly.
    """
    if not script or clock is None:
        return
    for _args in iter_lua_calls(script, "PassTime"):
        clock["minute"] += 15
    normalize_clock(clock)

# ---------- checks (dice) ----------
def check_row(c, conv, nid):
    return c.execute("SELECT * FROM checks WHERE conversationid=? AND dialogueid=?", (conv, nid)).fetchone()

def check_skill_level(skills, skill_type):
    """Resolve ROM display subtypes to the detective's canonical skill row."""
    return skills.get(CHECK_SKILL_ALIASES.get(skill_type, skill_type), 0)

def effective_skill(c, conv, nid, skill, vars, inv, vit=None, clock=None):
    """Base skill with active ROM difficulty modifiers converted for 2d6 + skill >= DC."""
    base = skill
    for r in c.execute("SELECT variable, modifier FROM modifiers WHERE conversationid=? AND dialogueid=?", (conv, nid)):
        # The extractor also stores four tooltip-only section headers here with
        # modifier=''. They are labels, not unconditional arithmetic modifiers.
        if not isinstance(r["modifier"], int):
            continue
        if eval_condition(r["variable"], vars, inv, vit, clock):
            base -= r["modifier"]
    return base

def check_odds(skill, dc):
    """P(success): 2d6 + skill >= DC, with snake-eyes auto-fail and boxcars auto-success."""
    succ = 0
    for d1 in range(1, 7):
        for d2 in range(1, 7):
            s = d1 + d2
            if s == 12:
                succ += 1              # boxcars — always succeed
            elif s == 2:
                pass                   # snake eyes — always fail
            elif s + skill >= dc:
                succ += 1
    return succ / 36.0

# ---------- SAVE (read-write, mine) ----------
def save():
    if SAVE is None:
        raise RuntimeError("profile not configured")
    c = sqlite3.connect(SAVE); c.row_factory = sqlite3.Row; return c

def parse_val(v):
    if v == "True":  return True
    if v == "False": return False
    try:
        return int(v)
    except (ValueError, TypeError):
        return v

def val_str(v):
    if v is True:  return "True"
    if v is False: return "False"
    return str(v)

def init_save(conv, node=None):
    fresh = not os.path.exists(SAVE)
    if fresh:
        parent = os.path.dirname(SAVE)
        if parent:
            os.makedirs(parent, exist_ok=True)
    c = save()
    if fresh:
        c.executescript("""
          CREATE TABLE position(key INTEGER PRIMARY KEY, conv INTEGER, node INTEGER);
          CREATE TABLE attrs(attr TEXT PRIMARY KEY, value INTEGER);
          CREATE TABLE skills(skill TEXT PRIMARY KEY, level INTEGER);
          CREATE TABLE vars(name TEXT PRIMARY KEY, value TEXT);
          CREATE TABLE fired(conv INTEGER, node INTEGER, PRIMARY KEY(conv, node));
          CREATE TABLE inventory(item_id TEXT PRIMARY KEY, equipped INTEGER);
          CREATE TABLE path(seq INTEGER PRIMARY KEY AUTOINCREMENT, conv INTEGER, node INTEGER, chose INTEGER, line TEXT);
        """)
        for k, v in BUILD["attrs"].items():
            c.execute("INSERT INTO attrs VALUES(?,?)", (k, v))
        for attr, skills in BUILD["skill_by_attr"].items():
            for sk in skills:
                level = BUILD["attrs"][attr]
                if sk == BUILD.get("signature_skill"):
                    level += 1
                c.execute("INSERT INTO skills VALUES(?,?)", (sk, level))
    # migrations for saves made by older engine versions
    c.execute("CREATE TABLE IF NOT EXISTS fired(conv INTEGER, node INTEGER, PRIMARY KEY(conv, node))")
    c.execute("CREATE TABLE IF NOT EXISTS inventory(item_id TEXT PRIMARY KEY, equipped INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS scene(key INTEGER PRIMARY KEY, id TEXT)")   # scene layer: which scene the detective is in
    c.execute("CREATE TABLE IF NOT EXISTS vitality(key INTEGER PRIMARY KEY, morale_cur INTEGER, morale_max INTEGER, health_cur INTEGER, health_max INTEGER)")   # health & morale
    # seed world-vars from ROM initial values (idempotent — only adds missing)
    rc = rom()
    for name, init in rc.execute("SELECT name, initialvalue FROM variables"):
        c.execute("INSERT OR IGNORE INTO vars VALUES(?,?)", (name, val_str(parse_val(init))))
    rc.close()
    rc = rom()
    start = entry_node(rc, conv) if node is None else node
    rc.close()
    c.execute("INSERT INTO position VALUES(1,?,?) ON CONFLICT(key) DO UPDATE SET conv=excluded.conv,node=excluded.node", (conv, start))
    c.execute("INSERT INTO path(conv,node,chose,line) VALUES(?,?,?,?)", (conv, start, 0, "(进入)"))
    c.commit(); c.close()
    return conv, start

def position():
    if not os.path.exists(SAVE):
        return (None, None)
    c = save(); r = c.execute("SELECT conv,node FROM position WHERE key=1").fetchone(); c.close()
    return (r["conv"], r["node"]) if r else (None, None)

def move(conv, node, chose, line):
    c = save()
    c.execute("UPDATE position SET conv=?, node=? WHERE key=1", (conv, node))
    c.execute("INSERT INTO path(conv,node,chose,line) VALUES(?,?,?,?)", (conv, node, chose, line))
    c.commit(); c.close()

def set_position(c, conv, node):
    c.execute("UPDATE position SET conv=?, node=? WHERE key=1", (conv, node))

_FINISH_TASK_MIGRATION = "finish-task-base-name-v1"
_XP_BOOL_MIGRATION = "xp-set-bool-v1"
_REPUTATION_MIGRATION = "reputation-verbs-v1"

def _migrate_finished_tasks(c, vars):
    """Backfill old saves whose fired scripts used FinishTask("TASK.x").

    Before the task-name normalization fix those 26 ROM calls wrote the active
    task flag back to true instead of its existing *_done flag. Fired nodes are
    durable evidence that the side effect happened, so the repair is exact.
    """
    c.execute("CREATE TABLE IF NOT EXISTS migrations(name TEXT PRIMARY KEY)")
    if c.execute("SELECT 1 FROM migrations WHERE name=?", (_FINISH_TASK_MIGRATION,)).fetchone():
        return
    c.execute("CREATE TABLE IF NOT EXISTS fired(conv INTEGER, node INTEGER, PRIMARY KEY(conv, node))")
    fired = {(r[0], r[1]) for r in c.execute("SELECT conv,node FROM fired")}
    changed = {}
    if fired:
        rc = rom()
        try:
            rows = rc.execute(
                f"SELECT conversationid,id,userscript FROM {NODES} "
                "WHERE userscript LIKE '%FinishTask(%'")
            for row in rows:
                if (row["conversationid"], row["id"]) not in fired:
                    continue
                for args in iter_lua_calls(row["userscript"] or "", "FinishTask"):
                    if not args:
                        continue
                    raw_name = parse_lua_value(args[0])
                    done = _finished_task_key(raw_name, vars)
                    if done != raw_name and vars.get(done) is not True:
                        vars[done] = True
                        changed[done] = True
        finally:
            rc.close()
    for name, value in changed.items():
        c.execute(
            "INSERT INTO vars(name,value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (name, val_str(value)))
    c.execute("INSERT INTO migrations(name) VALUES(?)", (_FINISH_TASK_MIGRATION,))
    c.commit()

def _migrate_xp_flags(c, vars):
    """Backfill XP story flags for effects fired before XP*SetBool was handled."""
    c.execute("CREATE TABLE IF NOT EXISTS migrations(name TEXT PRIMARY KEY)")
    if c.execute("SELECT 1 FROM migrations WHERE name=?", (_XP_BOOL_MIGRATION,)).fetchone():
        return
    c.execute("CREATE TABLE IF NOT EXISTS fired(conv INTEGER, node INTEGER, PRIMARY KEY(conv, node))")
    fired = {(r[0], r[1]) for r in c.execute("SELECT conv,node FROM fired")}
    changed = set()
    if fired:
        rc = rom()
        try:
            rows = rc.execute(
                f"SELECT conversationid,id,userscript FROM {NODES} "
                "WHERE userscript LIKE '%SetBool(%'")
            for row in rows:
                if (row["conversationid"], row["id"]) not in fired:
                    continue
                for verb in XP_BOOL_VERBS:
                    for args in iter_lua_calls(row["userscript"] or "", verb):
                        if args:
                            name = _xp_flag_key(parse_lua_value(args[0]), vars)
                            if vars.get(name) is not True:
                                vars[name] = True
                                changed.add(name)
        finally:
            rc.close()
    for name in changed:
        c.execute(
            "INSERT INTO vars(name,value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (name, val_str(True)))
    c.execute("INSERT INTO migrations(name) VALUES(?)", (_XP_BOOL_MIGRATION,))
    c.commit()

def _migrate_reputation(c, vars):
    """Reconstruct dropped reputation writes from old saves' fired nodes."""
    c.execute("CREATE TABLE IF NOT EXISTS migrations(name TEXT PRIMARY KEY)")
    if c.execute("SELECT 1 FROM migrations WHERE name=?", (_REPUTATION_MIGRATION,)).fetchone():
        return
    c.execute("CREATE TABLE IF NOT EXISTS fired(conv INTEGER, node INTEGER, PRIMARY KEY(conv, node))")
    fired = {(r[0], r[1]) for r in c.execute("SELECT conv,node FROM fired")}
    deltas = {}
    if fired:
        rc = rom()
        try:
            rows = rc.execute(
                f"SELECT conversationid,id,userscript FROM {NODES} "
                "WHERE userscript LIKE '%Reputation%'"
            )
            for row in rows:
                if (row["conversationid"], row["id"]) not in fired:
                    continue
                for name, delta in iter_reputation_changes(row["userscript"] or ""):
                    deltas[name] = deltas.get(name, 0) + delta
        finally:
            rc.close()
    for name, delta in deltas.items():
        vars[name] = _as_number(vars.get(name, 0)) + delta
        c.execute(
            "INSERT INTO vars(name,value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (name, val_str(vars[name])))
    c.execute("INSERT INTO migrations(name) VALUES(?)", (_REPUTATION_MIGRATION,))
    c.commit()

def load_vars(c):
    vars = {r[0]: parse_val(r[1]) for r in c.execute("SELECT name,value FROM vars")}
    _migrate_finished_tasks(c, vars)
    _migrate_xp_flags(c, vars)
    _migrate_reputation(c, vars)
    for repair in COMPAT.get("state_repairs", []):
        when = repair.get("when", {})
        unless = repair.get("unless", {})
        if all(vars.get(key) == value for key, value in when.items()):
            if unless and all(vars.get(key) == value for key, value in unless.items()):
                continue
            vars.update(repair.get("set", {}))
    return vars

def save_vars(c, vars):
    for k, v in vars.items():
        c.execute("INSERT INTO vars(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (k, val_str(v)))

def load_skills(c):
    return {r[0]: r[1] for r in c.execute("SELECT skill,level FROM skills")}

def load_fired(c):
    return {(r[0], r[1]) for r in c.execute("SELECT conv,node FROM fired")}

def save_fired(c, fired):
    for (conv, node) in fired:
        c.execute("INSERT OR IGNORE INTO fired VALUES(?,?)", (conv, node))

def load_inventory(c):
    c.execute("CREATE TABLE IF NOT EXISTS inventory(item_id TEXT PRIMARY KEY, equipped INTEGER)")
    return {r[0]: bool(r[1]) for r in c.execute("SELECT item_id, equipped FROM inventory")}

def save_inventory(c, inv):
    c.execute("DELETE FROM inventory")
    for item, eq in inv.items():
        c.execute("INSERT INTO inventory(item_id,equipped) VALUES(?,?)", (item, 1 if eq else 0))

_VITALITY_TBL = "CREATE TABLE IF NOT EXISTS vitality(key INTEGER PRIMARY KEY, morale_cur INTEGER, morale_max INTEGER, health_cur INTEGER, health_max INTEGER)"

def load_vitality(c):
    """Self-healing: ensure the table + a seeded row exist (full, from Volition/Endurance), then return the pools."""
    c.execute(_VITALITY_TBL)
    r = c.execute("SELECT morale_cur,morale_max,health_cur,health_max FROM vitality WHERE key=1").fetchone()
    if r:
        return {"morale_cur": r[0], "morale_max": r[1], "health_cur": r[2], "health_max": r[3]}
    skills = load_skills(c)
    vol = max(1, skills.get("Volition", 1)); end = max(1, skills.get("Endurance", 1))
    c.execute("INSERT INTO vitality VALUES(1,?,?,?,?)", (vol, vol, end, end)); c.commit()
    return {"morale_cur": vol, "morale_max": vol, "health_cur": end, "health_max": end}

def save_vitality(c, vit):
    c.execute(_VITALITY_TBL)
    c.execute("INSERT INTO vitality VALUES(1,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
              "morale_cur=excluded.morale_cur,morale_max=excluded.morale_max,health_cur=excluded.health_cur,health_max=excluded.health_max",
              (vit["morale_cur"], vit["morale_max"], vit["health_cur"], vit["health_max"]))

_CLOCK_TBL = "CREATE TABLE IF NOT EXISTS clock(key INTEGER PRIMARY KEY, day INTEGER NOT NULL, minute INTEGER NOT NULL)"

def load_clock(c):
    """Self-healing: ensure the clock table + seeded row exist (Day 1, 10:00), then return it.
    Stores minute-of-day (0..1439) — PassTime is 15-min granularity. See docs/clock.md."""
    c.execute(_CLOCK_TBL)
    r = c.execute("SELECT day, minute FROM clock WHERE key=1").fetchone()
    if r:
        return {"day": r[0], "minute": r[1]}
    c.execute("INSERT INTO clock VALUES(1,?,?)", (1, 10 * 60)); c.commit()   # Day 1, 10:00
    return {"day": 1, "minute": 10 * 60}

def normalize_clock(clock):
    """Normalize minute overflow into the day, in-place. Day floored at 1; negative minutes
    defensive only. Used after time-verb mutation (apply_userscript/cmd_time) so mid-traversal
    reads see a clean clock, and by save_clock. See docs/clock.md."""
    day = clock["day"]; minute = clock["minute"]
    day += minute // 1440; minute %= 1440
    if minute < 0:
        minute += 1440; day -= 1
    if day < 1:
        day = 1
    clock["day"] = day; clock["minute"] = minute
    return clock

def save_clock(c, clock):
    """Persist. normalize_clock first (minute >= 1440 rolls day forward; day floored at 1) —
    in-place, so the caller's dict reflects the normalized value too."""
    c.execute(_CLOCK_TBL)
    normalize_clock(clock)
    c.execute("INSERT INTO clock VALUES(1,?,?) ON CONFLICT(key) DO UPDATE SET day=excluded.day,minute=excluded.minute",
              (clock["day"], clock["minute"]))

def surface_vitality(before, after):
    """Print inline damage/heal changes (like the check-roll line). Beats otherwise stay clean."""
    for cur, maxk, label, icon in (("morale_cur","morale_max","士气","🧠"), ("health_cur","health_max","生命","❤️")):
        d = after[cur] - before[cur]
        if d:
            print(f"   {icon} {label} {'+' if d > 0 else ''}{d} → {after[cur]}/{after[maxk]}")

def restore_if_zero(vit):
    """The roller-coaster: if a pool hit 0, restore it (to max) and return which broke. Caller narrates."""
    broke = []
    if vit["morale_cur"] <= 0:
        vit["morale_cur"] = vit["morale_max"]; broke.append("morale")
    if vit["health_cur"] <= 0:
        vit["health_cur"] = vit["health_max"]; broke.append("health")
    return broke

def print_breakdown(broke):
    """Play the edge: a breakdown line per depleted pool. Visit it, then come back — never bricked."""
    for b in broke:
        if b == "morale":
            print("   🧠 士气归零——虚无短暂接管了方向盘。然后意志把你拽回来。")
        else:
            print("   ❤️ 生命归零——躯壳撑不住、你倒下。然后又被拉了起来。")

def make_fire(c, vars, inv, fired, vit=None, clock=None, repeat_existing=False):
    """Return a node-arrival callback.

    New nodes apply their full userscript once. During an explicit player choice,
    old nodes may replay only the verbs with defined repeat semantics.
    """
    def fire(conv, nid):
        if (conv, nid) in fired:
            if repeat_existing:
                n = get_node(c, conv, nid)
                if n:
                    apply_repeatable_userscript(n["userscript"], clock)
            return
        fired.add((conv, nid))
        n = get_node(c, conv, nid)
        if n:
            apply_userscript(n["userscript"], vars, inv, vit, clock)
        vars.update(COMPAT.get("node_set_vars", {}).get(f"{conv}:{nid}", {}))
    return fire

# ---------- coverage (dev curation candidates) ----------
# A developer-side tool, NOT player navigation and NOT an auto-scene generator.
# It reads the ROM structurally (userscripts + conditions, never prose) and emits a
# candidate list of "uncovered forward steps" to stdout (the curator channel), so a
# human decides whether/where to curate — the engine does not write scenes.
# See docs/coverage.md. V1: active-task -> advancing-conv reverse index.

def active_progress_signals(vars):
    """What the save says is 'in progress'. V1: active tasks (mirrors IsTaskActive).
    Shaped to extend to non-task progress (vars / items / white checks / thoughts /
    damage / character state) without changing callers — see docs/coverage.md."""
    signals = []
    for name in sorted(vars):
        if name.endswith(("_done", "_cancelled", "_canceled")):
            continue
        if name.startswith("TASK.") and vars[name] is True:
            if (vars.get(f"{name}_done") is True or
                    vars.get(f"{name}_cancelled") is True or
                    vars.get(f"{name}_canceled") is True):
                continue
            signals.append(("task", name))
    return signals

def build_task_advancing_index(c):
    """{task: {conv_id: [(node_id, verb, conditionstring)]}} from ROM userscripts.
    A conv 'advances' a task if any of its nodes' userscripts call GainTask/FinishTask/
    CancelTask on it. Structural only (no prose). Candidate-grade: 'advances the task'
    does NOT imply 'should appear from the current room' — the conv may belong to another
    location, or sit behind an in-NPC dialogue chain (see docs/coverage.md guardrails)."""
    idx = {}
    for r in c.execute(
            f"SELECT conversationid, id, userscript, conditionstring FROM {NODES} "
            "WHERE userscript IS NOT NULL AND userscript != ''"):
        script = r["userscript"] or ""
        touched = [(verb, parse_lua_value(args[0]))
                   for verb in ("GainTask", "FinishTask", "CancelTask")
                   for args in iter_lua_calls(script, verb) if args]
        if not touched:
            continue
        for verb, task in touched:
            idx.setdefault(task, {}).setdefault(r["conversationid"], []).append(
                (r["id"], verb, (r["conditionstring"] or "").strip()))
    return idx

def task_lifecycle_keys(task):
    return [task, f"{task}_done", f"{task}_cancelled", f"{task}_canceled"]

def task_advances_for_signal(idx, task):
    out = {}
    for key in task_lifecycle_keys(task):
        for conv, entries in idx.get(key, {}).items():
            out.setdefault(conv, []).extend(entries)
    return out

# ---------- coverage V2: blocked-but-covered ----------
# V1 asked "does a scene reach the advancing conv?" V2 asks the next layer: "once
# inside that conv, can the current save actually walk to the FinishTask node — or is
# it gated by a condition (a missing item, an unset flag)?" Covered != reachable.
# Same guardrails as V1 (structural, no prose, candidate-grade, stdout-only); the extra
# boundaries are in docs/coverage.md (condition-blocks not turn-structure; same-conv;
# provider one level; fail-open flagged; simple-gate auto-resolve).

def build_provider_indices(c):
    """Two reverse indices for resolving a blocker to 'where the missing piece is got':
    item_providers {item: {conv: [node,...]}} from GainItem("x"); var_providers
    {var: {conv: [node,...]}} from SetVariableValue("x", true). Structural only;
    candidate-grade — a provider existing != currently reachable."""
    items = {}; vrs = {}
    variable_names = {row[0] for row in c.execute("SELECT name FROM variables")}
    for r in c.execute(
            f"SELECT conversationid, id, userscript FROM {NODES} "
            "WHERE userscript IS NOT NULL AND userscript != ''"):
        script = r["userscript"] or ""
        for args in iter_lua_calls(script, "GainItem"):
            if args:
                items.setdefault(parse_lua_value(args[0]), {}).setdefault(r["conversationid"], []).append(r["id"])
        for args in iter_lua_calls(script, "SetVariableValue"):
            if len(args) >= 2 and eval_lua_value(args[1], {}) is True:
                vrs.setdefault(parse_lua_value(args[0]), {}).setdefault(r["conversationid"], []).append(r["id"])
        for verb in XP_BOOL_VERBS:
            for args in iter_lua_calls(script, verb):
                if args:
                    name = _xp_flag_key(parse_lua_value(args[0]), variable_names)
                    vrs.setdefault(name, {}).setdefault(r["conversationid"], []).append(r["id"])
    return items, vrs

def _cond_passes(expr, vars, inv, clock=None):
    """Eval a node condition; return (passes, fail_open). Mirrors eval_condition but flags
    fail-open (boundary 4): an unparsable gate fail-opens to True, and we do not pretend
    that is a clean pass — it is tracked as 'uncertain', not 'reachable'."""
    expr = re.sub(r"--\[\[.*?\]\]", "", expr or "", flags=re.S).strip()
    expr = normalize_condition_expr(expr)
    if not expr:
        return (True, False)
    try:
        return (bool(eval(expr, _cond_namespace(vars, inv, None, clock))), False)
    except Exception:
        return (True, True)

def _structural_ancestors(c, conv, targets):
    """Nodes that can reach any target via same-conv edges IGNORING conditions (structural
    connectivity). Filters frontier blockers to those actually on a path toward the target,
    rather than every dead-end branch off the reachable region."""
    rev = {}
    for o, d in c.execute(
            "SELECT origindialogueid, destinationdialogueid FROM dlinks "
            "WHERE originconversationid=? AND destinationconversationid=?", (conv, conv)):
        rev.setdefault(d, set()).add(o)
    connected = set(); stack = list(targets)
    while stack:
        n = stack.pop()
        if n in connected:
            continue
        connected.add(n)
        stack.extend(rev.get(n, ()))
    return connected

def conv_reachability(c, conv, target_nodes, vars, inv, clock=None):
    """Same-conv, condition-gated reachability from the conv entry to any target node (the
    FinishTask/lifecycle node). Returns {state, blockers, uncertain}:
      state: 'reachable' (clean), 'uncertain' (only via a fail-open edge), or 'blocked'.
      blockers: [(node, conditionstring)] — gates between the reachable region and the
                target, filtered to those structurally on a path toward it.
      uncertain: count of reachable nodes reached via >=1 fail-open edge.
    Boundaries: raw-graph condition-gated, NOT play turn-structure (1); same-conv (2);
    fail-open edges flagged, not trusted (4)."""
    start = entry_node(c, conv)
    targets = set(target_nodes)
    if start is None or not targets:
        return {"state": "blocked", "blockers": [], "uncertain": 0}
    status = {start: 1}          # node -> 1 clean | 2 uncertain (reached via a fail-open edge)
    frontier = {}                # child_node -> condstring, for edges that failed the gate
    stack = [start]
    while stack:
        u = stack.pop()
        su = status[u]
        for (dc, dd) in raw_outs(c, conv, u):
            if dc != conv:
                continue
            n = get_node(c, conv, dd)
            cond = (n["conditionstring"] or "").strip() if n else ""
            passes, fo = _cond_passes(cond, vars, inv, clock) if n else (True, False)
            if not passes:
                frontier.setdefault(dd, cond)
                continue
            sv = max(su, 2 if fo else 1)
            if sv > status.get(dd, 0):
                status[dd] = sv
                stack.append(dd)
    if any(status.get(t) == 1 for t in targets):
        state = "reachable"
    elif any(t in status for t in targets):
        state = "uncertain"
    else:
        state = "blocked"
    connected = _structural_ancestors(c, conv, targets)
    blockers, seen = [], set()
    for dd, cond in frontier.items():
        if dd in connected and cond and cond not in seen:
            seen.add(cond)
            blockers.append((dd, cond))
    return {"state": state, "blockers": blockers,
            "uncertain": sum(1 for s in status.values() if s == 2)}

def _blocker_providers(cond, item_providers, var_providers):
    """Resolve a blocker condition to provider convs, structurally. Simple gates:
    CheckItem("x") -> item providers; Variable["x"] -> var providers. Compound/negated
    conditions get best-effort sub-term matches (still no prose). Returns [(kind,key,conv)]."""
    out = []
    for m in re.finditer(r'CheckItem\(\s*"([^"]+)"\s*\)', cond or ""):
        for pconv in sorted(item_providers.get(m.group(1), {})):
            out.append(("item", m.group(1), pconv))
    for m in re.finditer(r'Variable\["([^"]+)"\]', cond or ""):
        for pconv in sorted(var_providers.get(m.group(1), {})):
            out.append(("var", m.group(1), pconv))
    return out

def _player_point_listings(listings):
    return [listing for listing in listings if listing[1] == "point"]

def cmd_coverage():
    """Print a developer curation candidate list. V1: active task -> advancing conv and
    whether a scene reaches it. V2 (blocked-but-covered): if a scene DOES reach it, check
    same-conv reachability from the entry to the FinishTask node under current save
    conditions — covered != reachable. Structural only (no prose), stdout only."""
    if not os.path.exists(SAVE):
        print(f"房间是空的。先: disco-room --profile {PROFILE_NAME} start <conv>"); return
    sc = save(); vars = load_vars(sc); inv = load_inventory(sc); clock = load_clock(sc); sc.close()
    scenes = scene_module()
    sid = scenes.current_scene_id()
    rc = rom()
    idx = build_task_advancing_index(rc)
    item_providers, var_providers = build_provider_indices(rc)
    print(f"〔coverage · {profile_label()} · 开发者策展候选〕")
    print("结构候选，非必修——某 conv 推进任务 ≠ 它该从当前房间出现（可能属别处 / 需先过 NPC 对话链）。")
    print(f"当前场景: {sid or '(无)'}    覆盖态: uncovered / covered-reachable / covered-blocked")
    print()
    signals = active_progress_signals(vars)
    if not signals:
        print("没有活跃任务。"); rc.close(); return
    for kind, task in signals:
        adv = task_advances_for_signal(idx, task) if kind == "task" else idx.get(task)
        if not adv:
            continue
        print(f"〔{kind} {task} · 活跃〕 推进它的 conv:")
        for conv in sorted(adv):
            entries = adv[conv]
            gain_nodes = sorted({n for n, v, _ in entries if v == "GainTask"})
            complete_nodes = sorted({n for n, v, _ in entries if v in ("FinishTask", "CancelTask")})
            cverbs = "/".join(sorted({v for _, v, _ in entries if v in ("FinishTask", "CancelTask")}))
            listings = scenes.scenes_listing_conv(conv)
            point_listings = _player_point_listings(listings)
            if not point_listings:
                verbs = "/".join(sorted({v for _, v, _ in entries}))
                print(f"  conv {conv}  [{verbs} @ node {','.join(map(str, sorted({n for n, _, _ in entries})))}]")
                for g in sorted({g for _, _, g in entries if g}):
                    print(f"    节点条件: {g}")
                if listings:
                    homes = "; ".join(f"{s}·{k}" for s, k, _, _ in listings)
                    print(f"    场景覆盖: {homes}（仅 terminal-return home，不是玩家菜单入口） ← 候选策展")
                else:
                    print("    场景覆盖: 任何已建场景都未列出  ← 候选策展")
                continue
            cover = "; ".join(f"{s}·{k}「{lab or ''}」" for s, k, lab, _ in point_listings)
            origin_note = f"  亦 GainTask 来源 @ node {','.join(map(str, gain_nodes))}" if gain_nodes else ""
            if not complete_nodes:
                # GainTask origin only — the task is already active, so it started here in
                # the past; this is not a forward-completion target. Skip blocked analysis
                # so the FinishTask signal isn't drowned (reviewer note, pre-merge denoise).
                print(f"  conv {conv}  [GainTask @ node {','.join(map(str, gain_nodes))}]  覆盖: {cover}  · origin（任务在此激活，非完成路径）")
                continue
            reach = conv_reachability(rc, conv, complete_nodes, vars, inv, clock)
            if reach["state"] == "reachable":
                print(f"  conv {conv}  [{cverbs}]  覆盖: {cover}  · 可达 ✓{origin_note}")
            elif reach["state"] == "uncertain":
                print(f"  conv {conv}  [{cverbs}]  覆盖: {cover}  · 可达?（途经 {reach['uncertain']} 处 fail-open）{origin_note}")
            else:
                print(f"  conv {conv}  [{cverbs} @ node {','.join(map(str, complete_nodes))}]  覆盖: {cover}{origin_note}")
                print("    ⛔ covered-but-blocked（门有，当前条件走不到完成节点）:")
                if reach["blockers"]:
                    for _nd, cond in reach["blockers"]:
                        print(f"       阻塞条件: {cond}")
                        provs = _blocker_providers(cond, item_providers, var_providers)
                        for pkind, pkey, pconv in provs:
                            tag = "已覆盖" if _player_point_listings(scenes.scenes_listing_conv(pconv)) else "未覆盖 ← 候选策展"
                            print(f"         candidate provider: {pkind}「{pkey}」 in conv {pconv}  [{tag}]")
                        if not provs:
                            print("         （无结构 provider——复合条件或非 item/flag 门）")
                else:
                    print("       (找不到具体阻塞条件——可能是回合结构问题，见 docs/coverage.md)")
        print()
    rc.close()

# ---------- commands ----------
def in_dialogue():
    """True if the current position is mid-conversation (has choosable dialogue
    options); False at a scene-terminal or in an empty room. The scene layer uses
    this to soft-block `look` and to label the mode, making the conversation/scene
    boundary explicit. Side-effect-free (fire=None)."""
    conv, node = position()
    if conv is None:
        return False
    rc = rom(); sc = save()
    try:
        vars = load_vars(sc); fired = load_fired(sc); inv = load_inventory(sc)
        vit = load_vitality(sc); clock = load_clock(sc)
        _, opts = beat_options(rc, conv, node, vars, inv, fired=fired, fire=None, vit=vit, clock=clock)
        return len(opts) > 0
    finally:
        sc.close(); rc.close()


def abandon_conversation():
    """Clear the conversation position so the player is 'at the scene menu' with no
    active conversation (position conv/node -> NULL). The escape valve behind forced
    `look N!` and the `leave` command — for when a conversation has no [Leave.] exit."""
    sc = save()
    sc.execute("UPDATE position SET conv=NULL, node=NULL WHERE key=1")
    sc.commit(); sc.close()


def cmd_leave():
    """Player-facing escape: abandon the current conversation and show the current
    scene menu. The clean fallback when a conversation has no [Leave.] exit."""
    if not in_dialogue():
        scene_module().cmd_scene()      # nothing to leave; just (re)show the scene
        return
    abandon_conversation()
    scene_module().cmd_scene()


def cmd_beat():
    conv, node = position()
    if conv is None:
        # No active conversation. If a scene is set, the player is "at the scene
        # menu" (after `leave` / forced look / a cleared convo) — show it; else empty.
        scenes = scene_module()
        if scenes.current_scene_id():
            scenes.cmd_scene(); return
        print(f"房间是空的。先: disco-room --profile {PROFILE_NAME} start <conv>"); return
    scenes = scene_module()
    if scenes.maybe_show_ending():
        return
    rc = rom(); sc = save()
    vars = load_vars(sc); skills = load_skills(sc); fired = load_fired(sc); inv = load_inventory(sc)
    vit = load_vitality(sc); vit0 = dict(vit); clock = load_clock(sc)
    fire = make_fire(rc, vars, inv, fired, vit, clock)
    npc, opts, origin = beat_options_with_origin(rc, conv, node, vars, inv, fired=fired, fire=fire, vit=vit, clock=clock)
    if opts and origin != (conv, node):
        set_position(sc, origin[0], origin[1])
    # No conv/node header here: those are graph coordinates, and the scene layer's
    # principle is "never show conv ids / node structure to the player." Position
    # is an explicit-compass concern — `where`/`status` print it on demand.
    for sp, line in npc:
        print(f"{sp}: {line}")
    surface_vitality(vit0, vit)                       # damage/heal from this beat's userscripts
    print_breakdown(restore_if_zero(vit))             # 0 → the edge, then restore (never bricked)
    if not opts:
        # Scene menus read state through a fresh save connection; flush beat
        # side effects first so newly earned/finished points update immediately.
        save_vars(sc, vars); save_fired(sc, fired); save_inventory(sc, inv); save_vitality(sc, vit); save_clock(sc, clock); sc.commit()
        scenes.maybe_show_scene(conv)
    else:
        print("—— 我可以 · 对话中（choose N）——")
        for i, (opt_conv, opt_node) in enumerate(opts, 1):
            n = get_node(rc, opt_conv, opt_node)
            tail = ""
            if n and n["hascheck"]:
                cr = check_row(rc, opt_conv, opt_node)
                if cr:
                    sk = effective_skill(rc, opt_conv, opt_node, check_skill_level(skills, cr["skilltype"]), vars, inv, vit=vit, clock=clock)
                    dc = cr["difficulty"]
                    pct = check_odds(sk, dc) * 100
                    kind = "红" if cr["isred"] else "白"
                    tail = f"   ⟦检定·{kind} {cr['skilltype']} 难度{dc} · 技能{sk} · {pct:.0f}%⟧"
            print(f"  {i}) {n['dialoguetext']}{tail}")
    save_vars(sc, vars); save_fired(sc, fired); save_inventory(sc, inv); save_vitality(sc, vit); save_clock(sc, clock); sc.commit(); sc.close(); rc.close()

def cmd_choose(n):
    conv, node = position()
    if conv is None:
        # No active conversation — at scene menu (or empty). `choose` is for dialogue.
        scenes = scene_module()
        if scenes.current_scene_id():
            print("（你在场景菜单，不在对话里——`choose` 是对话选项。）看场景用 `look N`，或 `scene` 看当前场景。")
            return
        print(f"房间是空的。先: disco-room --profile {PROFILE_NAME} start <conv>")
        return
    rc = rom(); sc = save()
    vars = load_vars(sc); skills = load_skills(sc); fired = load_fired(sc); inv = load_inventory(sc)
    vit = load_vitality(sc); vit0 = dict(vit); clock = load_clock(sc)
    read_fire = make_fire(rc, vars, inv, fired, vit, clock)
    _, opts = beat_options(rc, conv, node, vars, inv, fired=fired, fire=read_fire, vit=vit, clock=clock)
    if not opts:
        # At a scene-terminal (no dialogue). `choose` is for dialogue options —
        # guide the player to `look` so the conversation/scene boundary stays clear.
        print("（你在场景菜单，不在对话里——`choose` 是对话选项。）")
        print("看场景里的东西用 `look N`，或 `scene` 看当前场景。")
        sc.close(); rc.close(); return
    if n < 1 or n > len(opts):
        print(f"无效选项 (1..{len(opts)})"); sc.close(); rc.close(); return
    pick_conv, pick_node = opts[n - 1]
    picked = get_node(rc, pick_conv, pick_node)
    picked_line = picked["dialoguetext"]

    check_summary = None; flagname = None
    if picked["hascheck"]:
        cr = check_row(rc, pick_conv, pick_node)
        if cr:
            flagname = cr["flagname"]
            sk = effective_skill(rc, pick_conv, pick_node, check_skill_level(skills, cr["skilltype"]), vars, inv, vit=vit, clock=clock)
            dc = cr["difficulty"]
            d1, d2 = random.randint(1, 6), random.randint(1, 6)
            s = d1 + d2
            if s == 12:
                success = True; how = "双六！必成"
            elif s == 2:
                success = False; how = "蛇眼…必败"
            else:
                success = (s + sk) >= dc
                how = f"{d1}+{d2}={s}，+{sk}={s+sk} {'≥' if success else '<'} {dc}"
            vars[flagname] = success
            kind = "红检" if cr["isred"] else "白检"
            check_summary = (cr["skilltype"], dc, sk, d1, d2, s, success, how, kind)

    # advance; fire userscripts of traversed nodes (player's line + path + destination)
    walk_fire = make_fire(rc, vars, inv, fired, vit, clock, repeat_existing=True)
    nxt = walk_to_npc(rc, pick_conv, pick_node, vars, inv, fire=walk_fire, vit=vit, clock=clock)
    vit_after_walk = dict(vit)          # damage from the chosen path, pre-breakdown
    broke = restore_if_zero(vit)        # 0 → restore (the edge, then come back)
    save_vars(sc, vars); save_fired(sc, fired); save_inventory(sc, inv); save_vitality(sc, vit); save_clock(sc, clock); sc.commit()
    sc.close(); rc.close()

    if check_summary:
        sk_name, dc, sk, d1, d2, s, success, how, kind = check_summary
        mark = "✓ 成功" if success else "✗ 失败"
        print(f"⟦{kind}⟧ {sk_name} · 难度{dc} · 技能{sk}")
        print(f"   掷骰 {how}  →  {mark}")
        if flagname:
            print(f"   ({flagname} = {success})")
    print(f"\n我说: {picked_line}\n")
    surface_vitality(vit0, vit_after_walk)
    print_breakdown(broke)
    if nxt is None:
        move(pick_conv, pick_node, n, picked_line)
        scenes = scene_module()
        scenes.maybe_show_scene(pick_conv)
        return
    next_conv, next_node = nxt
    move(next_conv, next_node, n, picked_line)
    cmd_beat()

def cmd_start(conv, announce=True, node=None):
    requested_node = node
    rc = rom()
    try:
        start = entry_node(rc, conv) if node is None else node
        if start is None or get_node(rc, conv, start) is None:
            target = f"conv {conv}" if node is None else f"conv {conv} · node {node}"
            print(f"找不到 {target}；当前位置未改变。")
            return
    finally:
        rc.close()
    init_save(conv, node=start)
    # Entering a conversation also places the detective in that conversation's
    # scene (its 'home'), so a later [Leave.] terminal returns to the scene menu
    # instead of a dead end. No-op when the conv has no home scene (the
    # dream, unbuilt areas) or the scene is already correct (e.g. entered via look).
    scenes = scene_module()
    current_scene = scenes.current_scene_id()
    home = scenes.home_scene_for(conv, preferred=current_scene)
    if home and scenes.current_scene_id() != home:
        scenes.set_scene(home)
    if announce:
        where = f"conv {conv}" if requested_node is None else f"conv {conv} · node {requested_node}"
        print(f"{profile_label()} 推门进入 {where}。\n")
    cmd_beat()

def cmd_where():
    conv, node = position()
    print(f"档案: {profile_label()}")
    print(f"存档: {os.path.relpath(SAVE, PROJ)}")
    print(f"位置: conv {conv} · node {node}")
    if os.path.exists(SAVE):
        c = save()
        rows = c.execute("SELECT seq,conv,node,line FROM path ORDER BY seq DESC LIMIT 6").fetchall()
        for r in reversed(rows):
            print(f"  #{r['seq']} ({r['conv']}/{r['node']}) {r['line']}")
        c.close()

def cmd_status():
    conv, node = position()
    print(f"档案: {profile_label()}")
    print(f"存档: {os.path.relpath(SAVE, PROJ)}")
    print(f"位置: conv {conv} · node {node}")
    if os.path.exists(SAVE):
        c = save()
        attrs = dict(c.execute("SELECT attr,value FROM attrs").fetchall())
        print("属性: " + " / ".join(f"{k} {v}" for k, v in attrs.items()))
        vit = load_vitality(c)
        clock = load_clock(c)
        print(f"血量: 🧠 士气 {vit['morale_cur']}/{vit['morale_max']} · ❤️ 生命 {vit['health_cur']}/{vit['health_max']}")
        print(f"时间: 🕐 第 {clock['day']} 天 · {clock['minute']//60:02d}:{clock['minute']%60:02d}")
        # world-state summary. vars is ~10k (seeded from ROM) — summarise, never dump.
        n_total = c.execute("SELECT COUNT(*) FROM vars").fetchone()[0]
        true_vars = [r[0] for r in c.execute("SELECT name FROM vars WHERE value='True' ORDER BY name")]
        n_fired = c.execute("SELECT COUNT(*) FROM fired").fetchone()[0]
        print(f"世界: {len(true_vars)} 个 flag 亮着（{n_total} 中）· {n_fired} 处副作用已触发")
        if true_vars:
            shown = ", ".join(true_vars) if len(true_vars) <= 12 else f"{len(true_vars)} 个（略）"
            print(f"  亮着: {shown}")
        c.close()

def cmd_time(args):
    """Developer clock command. See docs/clock.md.
    Usage: time | time set <day> <hour> | time advance <hours> | time next-day."""
    if not os.path.exists(SAVE):
        print("房间是空的。"); return
    sub = args[0] if args else "show"
    c = save()
    try:
        clock = load_clock(c)
        def fmt(cl): return f"第 {cl['day']} 天 · {cl['minute']//60:02d}:{cl['minute']%60:02d}"
        if sub in ("show", "status"):
            print(f"🕐 {fmt(clock)}")
        elif sub == "set":
            if len(args) < 3:
                print("用法: time set <day> <hour>"); return
            try:
                day = int(args[1]); hour = int(args[2])
            except ValueError:
                print("用法: time set <day> <hour>"); return
            if day < 1: day = 1
            if not (0 <= hour <= 23): print("小时须在 0..23"); return
            clock = {"day": day, "minute": hour * 60}
            save_clock(c, clock); c.commit()
            print(f"🕐 设为 {fmt(clock)}")
        elif sub == "advance":
            if len(args) < 2:
                print("用法: time advance <hours>"); return
            try:
                hours = float(args[1])
            except ValueError:
                print("用法: time advance <hours>"); return
            clock["minute"] += int(round(hours * 60))
            save_clock(c, clock); c.commit()
            print(f"🕐 +{hours}h → {fmt(clock)}")
        elif sub == "next-day":
            clock["day"] += 1; clock["minute"] = 8 * 60
            save_clock(c, clock); c.commit()
            print(f"🕐 次日清晨 → {fmt(clock)}")
        else:
            print("用法: time [show|set <day> <hour>|advance <hours>|next-day]")
    finally:
        c.close()

def cmd_profile():
    print(f"档案: {profile_label()}")
    print(f"存档: {os.path.relpath(SAVE, PROJ)}")
    if PROFILE.get("wall"):
        print(f"记录墙: {PROFILE['wall']}")
    attrs = PROFILE["attrs"]
    print("属性: " + " / ".join(f"{k} {v}" for k, v in attrs.items()))
    if PROFILE.get("signature_skill"):
        print(f"招牌技能: {PROFILE['signature_skill']} (+1)")
    for note in PROFILE.get("notes", []):
        print(f"- {note}")

def cmd_card():
    print(f"侦探卡: {profile_label()}")
    attrs = PROFILE["attrs"]
    total = sum(attrs.values())
    print("属性: " + " / ".join(f"{k} {v}" for k, v in attrs.items()) + f"（总计 {total}）")
    signature = PROFILE.get("signature_skill")
    print(f"招牌技能: {signature or '(未选择)'}")
    print("技能:")
    for attr, skills in SKILL_BY_ATTR.items():
        parts = []
        for skill in skills:
            level = attrs[attr] + (1 if skill == signature else 0)
            parts.append(f"{skill} {level}")
        print(f"  {attr}: " + " / ".join(parts))

def cmd_profiles():
    names = []
    if os.path.isdir(PROFILES):
        for fn in sorted(os.listdir(PROFILES)):
            if fn.endswith(".json"):
                names.append(fn[:-5])
    if not names:
        print("没有档案。")
        return
    print("可用档案：")
    for name in names:
        marker = "*" if name == PROFILE_NAME else " "
        try:
            p = load_profile(name)
            label = p["name"]
            save_path = os.path.relpath(p["save"], PROJ)
            wall = p.get("wall") or "(no wall)"
            sig = p.get("signature_skill") or "no signature"
        except Exception as e:
            label = f"(坏掉: {e})"
            save_path = "?"
            wall = "?"
            sig = "?"
        print(f"{marker} {name}: {label} -> {save_path} · {wall} · {sig}")

def cmd_inventory():
    if not os.path.exists(SAVE):
        print("（口袋空空——还什么都没有。）"); return
    c = save()
    inv = load_inventory(c); c.close()
    if not inv:
        print("（口袋空空——还什么都没有。）"); return
    print("—— 身上 ——")
    for item, eq in inv.items():
        print(f"  {'[装备]' if eq else '      '} {item}")

def cmd_equip(item_id):
    if not os.path.exists(SAVE):
        print(f"房间是空的。先: disco-room --profile {PROFILE_NAME} start <conv>")
        return
    c = save()
    inv = load_inventory(c)
    if item_id not in inv:
        print(f"没有 {item_id} 这件东西。"); c.close(); return
    inv[item_id] = True
    save_inventory(c, inv); c.commit(); c.close()
    print(f"装备: {item_id}")

def cmd_unequip(item_id):
    if not os.path.exists(SAVE):
        print(f"房间是空的。先: disco-room --profile {PROFILE_NAME} start <conv>")
        return
    c = save()
    inv = load_inventory(c)
    if item_id not in inv:
        print(f"没有 {item_id} 这件东西。"); c.close(); return
    inv[item_id] = False
    save_inventory(c, inv); c.commit(); c.close()
    print(f"卸下: {item_id}")

def _cabinet_view(c):
    """Reconstruct the cabinet from vars: (fixed_ids, cooking_ids, slots)."""
    vars = load_vars(c)
    attrs = dict(c.execute("SELECT attr,value FROM attrs").fetchall())
    slots = attrs.get("Intellect", 4) + 3   # simplified — ROM's slot rule is richer
    fixed = sorted(k[len("THF."):]
                   for k, v in vars.items()
                   if k.startswith("THF.") and v)
    present = {k[len("THP."):] for k, v in vars.items() if k.startswith("THP.") and v}
    cooking = sorted(present - set(fixed))
    return fixed, cooking, slots

def cmd_cabinet():
    if not os.path.exists(SAVE):
        print("（内阁空空——还没有任何念头找上你。）"); return
    c = save()
    fixed, cooking, slots = _cabinet_view(c); c.close()
    print(f"思维内阁（{len(fixed)}/{slots} 槽位）")
    if fixed:
        print("内化：")
        for tid in fixed:
            print(f"  ◆ {tid}")
    if cooking:
        print("酝酿：")
        for tid in cooking:
            print(f"  ◇ {tid}   (internalize {tid})")
    if not fixed and not cooking:
        print("  （空——还没有念头成形。）")

def cmd_internalize(thought_id):
    if not os.path.exists(SAVE):
        print(f"房间是空的。先: disco-room --profile {PROFILE_NAME} start <conv>"); return
    c = save()
    vars = load_vars(c)
    fixed, _, slots = _cabinet_view(c)
    present_key = f"THP.{thought_id}"
    fixed_key = f"THF.{thought_id}"
    if not bool(vars.get(present_key)):
        print(f"内阁里没有「{thought_id}」——先得在剧情里遇见它。"); c.close(); return
    if vars.get(fixed_key):
        print(f"「{thought_id}」已经内化了。"); c.close(); return
    if len(fixed) >= slots:
        print(f"内阁满了（{len(fixed)}/{slots}）。先遗忘一个：forget <id>"); c.close(); return
    vars[fixed_key] = True
    save_vars(c, vars); c.commit(); c.close()
    print(f"内化：{thought_id}（{len(fixed) + 1}/{slots}）")

def cmd_forget(thought_id):
    if not os.path.exists(SAVE):
        print(f"房间是空的。先: disco-room --profile {PROFILE_NAME} start <conv>"); return
    c = save()
    vars = load_vars(c)
    present_key = f"THP.{thought_id}"
    fixed_key = f"THF.{thought_id}"
    if not (bool(vars.get(fixed_key)) or bool(vars.get(present_key))):
        print(f"内阁里没有「{thought_id}」。"); c.close(); return
    vars.pop(present_key, None)   # release the slot; the thought can return if the story offers it again
    vars.pop(fixed_key, None)
    save_vars(c, vars)
    c.execute("DELETE FROM vars WHERE name=?", (present_key,))   # save_vars only upserts — explicitly drop the presence flag
    c.execute("DELETE FROM vars WHERE name=?", (fixed_key,))
    c.commit(); c.close()
    print(f"遗忘：{thought_id}（槽位释放）")

_HELP_TEXT = """迪斯科房间引擎 · 命令一览

用法：
  disco-room --project <内容项目> --profile <档案> <命令> [参数]

对话与场景：
  start <conv> [node]   推门进入一段对话
  beat                  看这一拍：NPC 台词 + 我的选项
  choose <N>            选择第 N 个对话选项
  leave                 结束当前对话，回到场景菜单
  scene [id]            查看当前场景，或进入指定场景
  look <N>              在场景里查看 / 进入第 N 项（look <N>! 强制离开对话）

状态查询：
  where                 当前位置与最近几步
  status                档案、存档、血量、时间、世界状态
  time [子命令]         世界时钟：show · set <天> <时> · advance <时> · next-day

档案与随身：
  profile / card        当前档案 / 侦探卡（属性与技能）
  profiles              列出所有可用档案
  inv (inventory)       随身物品
  equip / unequip <id>  装备 / 卸下物品
  cabinet (thoughts)    思维内阁
  internalize <id>      内化一个念头
  forget <id>           遗忘一个念头

开发者与维护：
  coverage              场景策展候选（开发者工具，不是自动导航）
  reset                 清空当前档案的存档

也可用环境变量指定：DISCO_ROOM_PROJECT · DISCO_ROOM_ROM · DISCO_ROOM_PROFILES ·
DISCO_ROOM_DEFAULT_PROFILE · DISCO_PROFILE。详见 README.md 与 docs/。
"""


def cmd_help():
    print(_HELP_TEXT)


def main():
    profile_name, args = parse_cli(sys.argv)
    cmd = args[0] if args else "where"
    if cmd in ("help", "-h", "--help"):
        cmd_help()
        return
    configure_profile(profile_name)
    required = {
        "start": "start <conv> [node]",
        "choose": "choose <N>",
        "equip": "equip <item_id>",
        "unequip": "unequip <item_id>",
        "internalize": "internalize <thought_id>",
        "forget": "forget <thought_id>",
    }
    if cmd in required and len(args) < 2:
        print(f"用法: {required[cmd]}")
        return
    if cmd == "start":
        try:
            conv = int(args[1]); node = int(args[2]) if len(args) > 2 else None
        except ValueError:
            print("用法: start <conv> [node]")
            return
        cmd_start(conv, node=node)
    elif cmd == "beat":  cmd_beat()
    elif cmd == "leave": cmd_leave()
    elif cmd == "choose":
        try:
            choice = int(args[1])
        except ValueError:
            print("用法: choose <N>")
            return
        cmd_choose(choice)
    elif cmd == "scene":
        scene_module().cmd_scene(args[1] if len(args) > 1 else None)
    elif cmd == "look":
        raw = args[1] if len(args) > 1 else "0"
        force = raw.endswith("!")        # `look N!` = force past the mid-conversation soft-block
        if force:
            raw = raw[:-1]
        try:
            choice = int(raw)
        except ValueError:
            print("用法: look <N> 或 look <N>!")
            return
        scene_module().cmd_look(choice, force=force)
    elif cmd == "where": cmd_where()
    elif cmd == "status":cmd_status()
    elif cmd == "time": cmd_time(args[1:])
    elif cmd == "coverage": cmd_coverage()
    elif cmd == "profile": cmd_profile()
    elif cmd == "card":  cmd_card()
    elif cmd == "profiles": cmd_profiles()
    elif cmd == "inv" or cmd == "inventory": cmd_inventory()
    elif cmd == "equip":   cmd_equip(args[1])
    elif cmd == "unequip": cmd_unequip(args[1])
    elif cmd == "cabinet" or cmd == "thoughts": cmd_cabinet()
    elif cmd == "internalize": cmd_internalize(args[1])
    elif cmd == "forget":   cmd_forget(args[1])
    elif cmd == "reset": os.path.exists(SAVE) and os.remove(SAVE); print("房间已清空")
    else:
        print(f"未知命令：{cmd}")
        print()
        cmd_help()

if __name__ == "__main__":
    main()
