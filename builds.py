"""Animation builds: read a slide's click sequence, and render each build state.

A PowerPoint slide's animations live in <p:timing>. The main sequence
(cTn nodeType="mainSeq") holds one outer <p:par> per click. Inside it, each
effect is a <p:cTn presetClass="entr|exit|emph|path|..."> whose behaviours
target a shape (<p:spTgt spid="4">), optionally one or more paragraphs of it
(<p:txEl><p:pRg st="0" end="0"/></p:txEl>).

We only care about visibility: an entrance shows a target, an exit hides it.
Emphasis and motion-path effects don't change what's on screen in a still
frame, so they're ignored (their click is still a click). The result is a list
of states, state 0 being the slide before the first click, each state the set
of targets hidden at that point.

A state is rendered by editing a copy of the slide: hidden shapes are removed,
and hidden paragraphs get fully transparent text and no bullet, so they keep
their space and nothing else on the slide moves (LibreOffice honours text
alpha but not bullet alpha, hence buNone).
"""

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _p(tag):
    return f"{{{P}}}{tag}"


def _a(tag):
    return f"{{{A}}}{tag}"


class Builds:
    """states[k] = frozenset of hidden targets after k clicks. A target is
    (spid, paragraph_index), with paragraph_index None for the whole shape."""

    def __init__(self, states, ignored, auto_start):
        self.states = states
        self.ignored = ignored          # effect classes seen but not rendered, e.g. {"emph"}
        self.auto_start = auto_start    # effects that play by themselves when the slide opens

    @property
    def clicks(self):
        return len(self.states) - 1


NO_BUILDS = Builds([frozenset()], set(), 0)


def _targets(effect):
    """The (spid, paragraph) targets of one effect, in order, without repeats."""
    out = []
    for tgt in effect.iter(_p("spTgt")):
        spid = tgt.get("spid")
        prg = tgt.find(f"{_p('txEl')}/{_p('pRg')}")
        if prg is not None:
            keys = [(spid, i) for i in range(int(prg.get("st")), int(prg.get("end")) + 1)]
        else:
            # Whole shape. Also covers <p:bg/> (a shape's background animated
            # separately from its paragraphs) and character-range builds,
            # which are approximated as the whole shape.
            keys = [(spid, None)]
        for k in keys:
            if k not in out:
                out.append(k)
    return out


def parse_builds(sld):
    """Builds for one slide element (python-pptx slide._element)."""
    main = None
    timing = sld.find(_p("timing"))
    if timing is not None:
        for ctn in timing.iter(_p("cTn")):
            if ctn.get("nodeType") == "mainSeq":
                main = ctn
                break
    if main is None:
        return NO_BUILDS
    groups = main.findall(f"{_p('childTnLst')}/{_p('par')}")
    events, ignored = [], set()
    for group in groups:
        effects = [c for c in group.iter(_p("cTn")) if c.get("presetClass")]
        is_click = not effects or effects[0].get("nodeType") == "clickEffect"
        actions = []
        for eff in effects:
            cls = eff.get("presetClass")
            if cls in ("entr", "exit"):
                actions += [(t, cls == "entr") for t in _targets(eff)]
            else:
                ignored.add(cls)
        events.append((is_click, actions))
    if not events:
        return NO_BUILDS

    # Before anything plays, a target is hidden if the first thing that ever
    # happens to it is an entrance.
    first = {}
    for _, actions in events:
        for target, show in actions:
            first.setdefault(target, show)
    hidden = {t for t, show in first.items() if show}

    def apply(actions):
        for target, show in actions:
            (hidden.discard if show else hidden.add)(target)

    # Groups that start without a click ("after/with previous" as the very
    # first effect) play as the slide opens, so they're part of state 0.
    i, auto = 0, 0
    while i < len(events) and not events[i][0]:
        apply(events[i][1])
        auto += 1
        i += 1
    states = [frozenset(hidden)]
    for is_click, actions in events[i:]:
        apply(actions)
        if is_click:
            states.append(frozenset(hidden))
        else:                       # an automatic group after a click joins that click
            states[-1] = frozenset(hidden)
    return Builds(states, ignored, auto)


# ------------------------------------------------------------------ rendering a state

def _shape_by_id(sld, spid):
    tree = sld.find(f"{_p('cSld')}/{_p('spTree')}")
    for cnv in tree.iter(_p("cNvPr")):
        if cnv.get("id") == spid:
            shape = cnv.getparent().getparent()     # cNvPr -> nvXxPr -> sp/pic/grpSp/graphicFrame/cxnSp
            if shape is not tree:
                return shape
    return None


_FILLS = ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill")
_BULLETS = ("buNone", "buAutoNum", "buChar", "buBlip")
_AFTER_BULLET = ("tabLst", "defRPr", "extLst")


def _transparent(rpr):
    """Make one run's text fully transparent: no outline, glow, shadow or highlight either."""
    for child in list(rpr):
        local = child.tag.split("}")[1]
        if local in _FILLS or local in ("ln", "effectLst", "effectDag", "highlight"):
            rpr.remove(child)
    fill = rpr.makeelement(_a("solidFill"), {})
    color = fill.makeelement(_a("srgbClr"), {"val": "000000"})
    color.append(color.makeelement(_a("alpha"), {"val": "0"}))
    fill.append(color)
    rpr.insert(0, fill)


def _hide_paragraph(para):
    ppr = para.find(_a("pPr"))
    if ppr is None:
        ppr = para.makeelement(_a("pPr"), {})
        para.insert(0, ppr)
    for child in list(ppr):
        if child.tag.split("}")[1] in _BULLETS:
            ppr.remove(child)
    nobullet = ppr.makeelement(_a("buNone"), {})
    after = [c for c in ppr if c.tag.split("}")[1] in _AFTER_BULLET]
    if after:
        after[0].addprevious(nobullet)
    else:
        ppr.append(nobullet)
    for run in para:
        local = run.tag.split("}")[1]
        if local in ("r", "fld", "br"):
            rpr = run.find(_a("rPr"))
            if rpr is None:
                rpr = run.makeelement(_a("rPr"), {})
                run.insert(0, rpr)
            _transparent(rpr)
        elif local == "endParaRPr":
            _transparent(run)


def apply_state(sld, hidden):
    """Edit a slide element in place to show one build state. Returns targets
    that couldn't be found (a stale animation pointing at a deleted shape)."""
    missing = []
    for spid, para in sorted((t for t in hidden if t[1] is not None), key=lambda t: (t[0], t[1])):
        shape = _shape_by_id(sld, spid)
        body = shape.find(f".//{_p('txBody')}") if shape is not None else None
        paras = body.findall(_a("p")) if body is not None else []
        if para < len(paras):
            _hide_paragraph(paras[para])
        else:
            missing.append((spid, para))
    for spid, para in sorted(t for t in hidden if t[1] is None):
        shape = _shape_by_id(sld, spid)
        if shape is not None:
            shape.getparent().remove(shape)
        else:
            missing.append((spid, None))
    timing = sld.find(_p("timing"))
    if timing is not None:          # a still frame has no animations
        sld.remove(timing)
    return missing


def describe(sld, builds):
    """Human-readable lines for --show-builds."""
    names = {}
    tree = sld.find(f"{_p('cSld')}/{_p('spTree')}")
    for cnv in tree.iter(_p("cNvPr")):
        names[cnv.get("id")] = cnv.get("name") or f"shape {cnv.get('id')}"

    def label(t):
        spid, para = t
        name = names.get(spid, f"missing shape {spid}")
        return f"{name}" if para is None else f"{name} ¶{para + 1}"

    lines = []
    all_targets = set().union(*builds.states)
    for k, state in enumerate(builds.states):
        if k == 0:
            what = "hidden at start: " + (", ".join(sorted(label(t) for t in state)) or "nothing")
        else:
            prev = builds.states[k - 1]
            shown = sorted(label(t) for t in prev - state)
            gone = sorted(label(t) for t in state - prev)
            bits = ([f"shows {', '.join(shown)}"] if shown else []) + ([f"hides {', '.join(gone)}"] if gone else [])
            what = "; ".join(bits) or "no visible change (emphasis or motion only)"
        lines.append(f"  state {k}{' (start)' if k == 0 else f' (click {k})'}: {what}")
    if not all_targets and builds.clicks == 0:
        lines = ["  no builds"]
    return lines
