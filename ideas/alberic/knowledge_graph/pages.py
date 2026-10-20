"""The two HTML pages: /gaps/board (the demo screen) and /gaps/{id}/talk (answer by voice or text)."""

import json
from html import escape

STYLE = """
:root{--navy-950:#000d3a;--navy-800:#001c52;--blue-600:#006dd8;--sky-300:#9ed2ff;--amber:#e8a877;--magenta:#b8688f;
--coral:#da3300;--text:#f4f8ff;--muted:#9fb0cc;--glass:rgba(255,255,255,.045);--glass-line:rgba(255,255,255,.11);
--human:linear-gradient(135deg,var(--amber),var(--magenta));--display:"Bricolage Grotesque","Avenir Next",sans-serif;
--sans:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;color:var(--text);font:16px/1.55 var(--sans);background:
radial-gradient(60rem 40rem at 85% -10%,rgba(0,109,216,.28),transparent 60%),
radial-gradient(45rem 35rem at -10% 110%,rgba(184,104,143,.14),transparent 60%),
linear-gradient(160deg,var(--navy-950),var(--navy-800) 70%);background-attachment:fixed}
main{max-width:1100px;margin:0 auto;padding:40px 16px 80px}
h1,h2,h3{font-family:var(--display);font-weight:800;line-height:1.08;margin:0}
h1{font-size:clamp(2rem,4vw,3rem);margin:8px 0 10px}h2{font-size:1.4rem;margin:36px 0 14px}
a{color:var(--sky-300)}.muted{color:var(--muted)}
.kicker{font:600 .8rem/1.2 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--amber)}
.grad-human{background:var(--human);-webkit-background-clip:text;background-clip:text;color:transparent}
.glass{background:var(--glass);border:1px solid var(--glass-line);border-radius:18px;padding:18px 20px;margin:0 0 12px}
.btn{display:inline-block;padding:10px 18px;border-radius:999px;font-weight:600;text-decoration:none;border:0;cursor:pointer;
color:var(--navy-950);background:var(--human);font-size:15px}
.btn.ghost{background:none;color:var(--text);border:1px solid var(--glass-line)}
.row{display:flex;gap:16px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.tag{display:inline-block;font-size:12px;padding:2px 10px;border-radius:999px;border:1px solid var(--glass-line);color:var(--muted)}
.tag.risk{border-color:var(--coral);color:#ffb59c}
.ai{color:var(--sky-300)}.human{color:var(--amber)}
.draft{border-left:3px solid var(--blue-600);padding-left:12px;margin:10px 0 0}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px}
.pair>div{border-radius:12px;padding:12px 14px}
.pair .claude{border:1px solid rgba(0,109,216,.5)}.pair .final{border:1px solid rgba(232,168,119,.6)}
@media(max-width:640px){.pair{grid-template-columns:1fr}}
textarea,input{width:100%;font:inherit;color:var(--text);background:rgba(255,255,255,.06);border:1px solid var(--glass-line);
border-radius:12px;padding:10px 12px}
textarea{min-height:110px}label{display:block;margin:14px 0 6px;color:var(--muted);font-size:14px}
"""

RESULT_LABEL = {"confirmed": "just confirmed (counts half)", "edited": "edited Claude's draft", "rewritten": "said it in their own words"}


def _page(title: str, body: str, script: str = "") -> str:
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)}</title><link rel=preconnect href=https://fonts.googleapis.com>"
            "<link href='https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@800&family=Inter:wght@400;600&display=swap' rel=stylesheet>"
            f"<style>{STYLE}</style></head><body><main>{body}</main>{script}</body></html>")


def _who(gap: dict) -> str:
    return escape((gap.get("owner") or "nobody").capitalize())


def _open_card(gap: dict, phone: bool) -> str:
    risk = gap.get("risk", "")
    tag = f"<span class='tag risk'>{escape(risk.replace('_', ' '))}</span>" if risk in ("dark", "single_point") else f"<span class=tag>{escape(risk)}</span>"
    kind = "no why given" if gap["kind"] == "missing_why" else "no session behind it"
    link = f" · <a href='{escape(gap['link'])}'>commit</a>" if gap.get("link") else ""
    source = "Claude's guess" if gap.get("draft_source") == "claude" else "template, no Claude key"
    action = (f"<button class=btn data-call='{escape(gap['id'])}'>Call {_who(gap)}</button>" if phone and gap.get("owner")
              else f"<a class=btn href='/gaps/{escape(gap['id'])}/talk'>Call {_who(gap)}</a>") if gap.get("owner") else ""
    calling = " <span class=tag>calling…</span>" if gap["status"] == "calling" else ""
    return (f"<div class=glass><div class=row><div><b>{escape(gap['subject'])}</b><br>"
            f"<span class=muted>{escape(gap['topic'])} · {kind} · owner <span class=human>{_who(gap)}</span>{link}</span> {tag}{calling}</div>"
            f"<div>{action}</div></div>"
            f"<p class='draft ai'>{escape(gap['draft'])}<br><span class=muted>{source}</span></p></div>")


def _answered_card(gap: dict) -> str:
    return (f"<div class=glass><b>{escape(gap['subject'])}</b> <span class=muted>· {escape(gap['topic'])}</span>"
            f"<div class=pair><div class=claude><div class=kicker style='color:var(--sky-300)'>Claude guessed</div>{escape(gap['draft'])}</div>"
            f"<div class=final><div class=kicker>{_who(gap)} fixed it</div>&ldquo;{escape(gap['answer'] or '')}&rdquo;"
            f"<br><span class=muted>{escape(RESULT_LABEL.get(gap.get('draft_result'), ''))}</span></div></div></div>")


BOARD_JS = """<script>
let seen=null;
async function poll(){try{const r=await fetch('/gaps?status=answered');const n=(await r.json()).length;
if(seen!==null&&n!==seen)location.reload();seen=n}catch(e){}}
poll();setInterval(poll,4000);
document.querySelectorAll('[data-call]').forEach(b=>b.onclick=async()=>{
let t=localStorage.getItem('kgAdmin');if(!t){t=prompt('Admin token to start a phone call');if(!t)return;localStorage.setItem('kgAdmin',t)}
b.textContent='Calling…';const r=await fetch('/gaps/'+b.dataset.call+'/call',{method:'POST',headers:{Authorization:'Bearer '+t}});
if(r.status===403){localStorage.removeItem('kgAdmin')}
if(!r.ok){location.href='/gaps/'+b.dataset.call+'/talk'}});
</script>"""


def board(open_gaps: list[dict], answered: list[dict], phone: bool, claude: bool, limit: int = 12) -> str:
    shown = "".join(_open_card(g, phone) for g in open_gaps[:limit])
    more = f"<p class=muted>and {len(open_gaps) - limit} more</p>" if len(open_gaps) > limit else ""
    done = "".join(_answered_card(g) for g in answered) or "<p class=muted>Nothing answered yet. Call someone.</p>"
    state = ("Claude drafts on" if claude else "Template drafts (no Claude key)") + " · " + (
        "phone calls on" if phone else "browser call (no phone number set)")
    body = (f"<div class=kicker>Backtracking</div><h1>Claude guessed. <span class=grad-human>The human fixed it.</span></h1>"
            f"<p class=muted>Work nobody explained, riskiest first. A guess stays a guess until its owner says it in their own words. {escape(state)}</p>"
            f"<h2>Now knowledge</h2>{done}<h2>Waiting for the why <span class=muted>({len(open_gaps)})</span></h2>{shown}{more}")
    return _page("Backtracking board", body, BOARD_JS)


TALK_JS = """<script>
const id=%s;const tok=document.getElementById('tok');tok.value=localStorage.getItem('kgMember')||'';
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const m=document.getElementById('msg');
localStorage.setItem('kgMember',tok.value.trim());
const r=await fetch('/gaps/'+id+'/answer',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+tok.value.trim()},
body:JSON.stringify({answer:document.getElementById('a').value})});
if(r.ok){location.href='/gaps/board'}else{m.textContent=(await r.json()).detail||'Not saved'}};
</script>"""


def talk(gap: dict, widget: str) -> str:
    done = "<p class=human>Already answered. <a href='/gaps/board'>Back to the board</a></p>" if gap["status"] == "answered" else ""
    body = (f"<div class=kicker>One minute, {_who(gap)}</div><h1>{escape(gap['subject'])}</h1>"
            f"<p class='draft ai'>Claude's guess: {escape(gap['draft'])}<br><span class=muted>{escape(gap.get('check_question') or '')}</span></p>{done}"
            f"{widget}"
            "<h2>Or type it</h2><form id=f class=glass><label for=a>Is that right, or how would you put it? (max 200 characters)</label>"
            f"<textarea id=a maxlength=200>{escape(gap['draft'][:200])}</textarea>"
            "<label for=tok>Your member token (kept in this browser)</label><input id=tok type=password autocomplete=off>"
            "<p><button class=btn>Save in my words</button> <a class='btn ghost' href='/gaps/board'>Back</a> <span id=msg class=human></span></p></form>")
    return _page("Answer a gap", body, TALK_JS % json.dumps(gap["id"]))
