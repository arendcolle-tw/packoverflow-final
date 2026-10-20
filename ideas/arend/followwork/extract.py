"""Turn captured window events into steps and procedures.

All rules are deterministic. An optional Claude call can polish names
(see polish.py); it only ever sees the rule-based names, never raw text.
"""
import hashlib
import re
from datetime import datetime, timezone

GAP_SECONDS = 300  # idle this long and a new procedure starts
BROWSERS = {"google chrome", "safari", "firefox", "microsoft edge", "arc"}
SPREADSHEETS = {"microsoft excel": "Excel", "numbers": "Numbers"}
MAIL = {"microsoft outlook": "Outlook", "mail": "Mail"}
PORTALS = ["mysdworx", "protime", "insights"]


def _key(e):
    return (e["app"], e["title"])


def group_steps(events):
    """Group consecutive events of the same app and window title.

    A single-frame glance at another window between two frames of the same
    window is treated as noise and dropped.
    """
    runs = []
    for e in events:
        if runs and _key(runs[-1][-1]) == _key(e):
            runs[-1].append(e)
        else:
            runs.append([e])
    out = []
    i = 0
    while i < len(runs):
        run = runs[i]
        if (out and len(run) == 1 and i + 1 < len(runs)
                and _key(runs[i + 1][0]) == _key(out[-1][0])):
            out[-1].extend(runs[i + 1])
            i += 2
            continue
        if out and _key(out[-1][0]) == _key(run[0]):
            out[-1].extend(run)
        else:
            out.append(list(run))
        i += 1
    return out


def split_procedures(events, gap=GAP_SECONDS):
    procs = []
    for e in sorted(events, key=lambda e: e["ts"]):
        if procs and e["ts"] - procs[-1][-1]["ts"] <= gap:
            procs[-1].append(e)
        else:
            procs.append([e])
    return procs


def app_label(e):
    app = e["app"].lower()
    if app in SPREADSHEETS:
        return SPREADSHEETS[app]
    if app in MAIL:
        return MAIL[app]
    if app in BROWSERS:
        t = e["title"].lower()
        for p in PORTALS:
            if p in t:
                return p
        return e["app"]
    return e["app"]


def _page(title):
    # "mysdworx - Client portfolio - Google Chrome" -> "Client portfolio"
    parts = [p.strip() for p in re.split(r"\s[-|–]\s", title) if p.strip()]
    parts = [p for p in parts if p.lower() not in PORTALS and p.lower() not in BROWSERS]
    return parts[0] if parts else title


def _lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


FILE_RE = re.compile(r"([\w\-. ]+?\.(?:xlsx|xls|csv|numbers))", re.I)
PC_FILTER = re.compile(r"(?i)filter\w*\b.*?(?:joint committee|paritair comit[eé]|\bpc)\s*[=:]?\s*(\d{3})")
GEN_FILTER = re.compile(r"(?i)filter\w*\s*(?:on)?\s*:?\s*([A-Za-z][A-Za-z ]{1,30}?)\s*[=:]\s*([\w .]{1,30})")
SUM_RE = re.compile(r"(?i)=SUM\(|\btotal\b")
SAVE_RE = re.compile(r"(?i)\b(saved|submitted|confirmed|scheduled|sent)\b")
DOWNLOAD_RE = re.compile(r"(?i)download(?:ed| complete[d]?)?\b\W*([\w\-.]+\.(?:zip|pdf|csv|xlsx))")
SUBJECT_RE = re.compile(r"(?i)^subject:\s*(.+)$", re.M)


def name_run(run, clip_before, seen_titles):
    """Return (named steps, clipboard after this run) for one window run."""
    first, last = run[0], run[-1]
    label = app_label(first)
    app = first["app"].lower()
    before = set(_lines(first["text"]))
    new = [ln for e in run[1:] for ln in _lines(e["text"]) if ln not in before]
    new_text = "\n".join(dict.fromkeys(new))
    all_text = "\n".join(e["text"] for e in run)
    steps = []

    # Opening the window.
    if _key(first) not in seen_titles:
        if app in MAIL:
            m = SUBJECT_RE.search(all_text)
            subject = m.group(1).strip() if m else _page(first["title"])
            steps.append(f'Read "{subject}" in {label}')
        elif app in SPREADSHEETS:
            m = FILE_RE.search(first["title"])
            steps.append(f"Open {m.group(1).strip() if m else _page(first['title'])} in {label}")
        else:
            steps.append(f"Open {_page(first['title'])} in {label}")
    seen_titles.add(_key(first))

    # What changed inside the window.
    m = PC_FILTER.search(new_text)
    if m:
        steps.append(f"Filter on joint committee PC {m.group(1)}")
    else:
        m = GEN_FILTER.search(new_text)
        if m:
            steps.append(f"Filter {m.group(1).strip()} = {m.group(2).strip()}")
    if app in SPREADSHEETS and SUM_RE.search(new_text):
        m = re.search(r"(?i)total\s+([a-z][a-z ]*?)(?:\s+\d|$)", new_text, re.M)
        steps.append(f"Sum {m.group(1).strip()}" if m else "Sum the column")

    clip = clip_before
    for e in run:
        c = e.get("clipboard")
        if c and c != clip:
            if not any(s.startswith("Copy") for s in steps):
                steps.append("Copy the total" if SUM_RE.search(all_text) else "Copy a value")
            clip = c
    if clip_before and clip_before in new_text and app not in SPREADSHEETS:
        steps.append(f"Paste it into {_page(first['title'])} in {label}")

    m = DOWNLOAD_RE.search(new_text)
    if m:
        steps.append(f"Download {m.group(1)}")
    if app not in SPREADSHEETS and SAVE_RE.search(new_text):
        steps.append(f"Save {_page(first['title'])} in {label}")
    return steps, clip


TOPICS = [
    (re.compile(r"(?i)\bindexation\b|\bindexering\b"), "indexation"),
    (re.compile(r"(?i)pay transparency"), "pay transparency"),
    (re.compile(r"(?i)\bpayslips?\b"), "payslips"),
    (re.compile(r"(?i)\bsalary export\b|salary_export"), "salary export"),
]
PC_RE = re.compile(r"(?i)(?:joint committee|paritair comit[eé]|\bPC)\s*[=:]?\s*(\d{3})")


def topic_of(events):
    text = "\n".join(e["title"] + "\n" + e["text"] for e in events)
    tags = [t for pat, t in TOPICS if pat.search(text)]
    pcs = sorted(set(PC_RE.findall(text)))
    tags += [f"PC {p}" for p in pcs[:2]]
    return ", ".join(tags) if tags else "general"


def title_of(topic, apps):
    path = " to ".join(apps) if len(apps) > 1 else apps[0]
    if "indexation" in topic:
        pc = re.search(r"PC \d{3}", topic)
        return f"Apply the {pc.group(0) + ' ' if pc else ''}indexation: {path}"
    if "payslips" in topic:
        return f"Get the payslips out of {path}"
    return f"Move data: {path}"


def extract(events):
    """Return procedures: {id, topic, title, steps, apps, captured_at, ...}."""
    out = []
    for proc in split_procedures(events):
        runs = group_steps(proc)
        steps, apps, clip, seen = [], [], None, set()
        for run in runs:
            named, clip = name_run(run, clip, seen)
            steps.extend(s for s in named if not steps or s != steps[-1])
            label = app_label(run[0])
            if label not in apps:
                apps.append(label)
        if len(steps) < 2:
            continue
        topic = topic_of(proc)
        title = title_of(topic, apps)
        pid = "proc-" + hashlib.sha1(f"{topic}|{title}".encode()).hexdigest()[:10]
        day = datetime.fromtimestamp(proc[0]["ts"], timezone.utc).date().isoformat()
        out.append({
            "id": pid, "topic": topic, "title": title, "steps": steps, "apps": apps,
            "captured_at": day,
            # Local-only fields for the review screen; never written to the output.
            "_span": [proc[0]["ts"], proc[-1]["ts"]],
            "_events": len(proc),
            "_redacted": sum(len(re.findall(r"\[[A-Z_]+\]", e["text"] + e["title"])) for e in proc),
        })
    return out
