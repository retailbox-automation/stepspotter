"""Form A — the chat master. One page, inline CSS and JS, no build step, no CDN.

What it is: a message feed, like the one the owner of this product already uses to get
things explained to him. He writes what he wants to do and shows a photo; one step
comes back drawn on that photo; he sends a photo of the result; the answer is "done",
"not done, because…" or "stop". Questions go into the same feed and are answered there.

Three rules this file follows and the screen-stack version could not:
  1. ONE action button at a time, at the bottom, labelled with what happens next. The
     composer never shows a choice the person did not ask for.
  2. Nothing is ever removed from the feed. A refusal stays on screen above the retry,
     so "it said no and then I fixed it" is readable afterwards — by him and by a judge.
  3. The page holds no state. Every action is: call the API, re-read /feed, append the
     new messages. The server's trace is the transcript (see web/feed.py).

Colours are the reference card's colours: green = do this, red = do not touch,
orange = stop and get a person. Light theme, 17px base, thumb-sized targets.
"""

CHAT_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>StepSpotter</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%231a8a4f'/%3E%3Ctext x='16' y='23' font-size='20' text-anchor='middle' fill='%23fff' font-family='sans-serif'%3E1%3C/text%3E%3C/svg%3E">
<style>
  :root{
    --bg:#eef0f4; --panel:#ffffff; --ink:#15181e; --dim:#5d6572; --line:#dfe3ea;
    --act:#12804a; --actbg:#e8f6ee; --avoid:#c62a30; --avoidbg:#fdecec;
    --stop:#b45309; --stopbg:#fdf3e3; --accent:#1f5fd6; --mine:#dbe7fb;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:17px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
       -webkit-text-size-adjust:100%;overscroll-behavior-y:none}
  .app{display:flex;flex-direction:column;height:100dvh;max-width:520px;margin:0 auto;
       background:var(--bg)}

  /* ---- header: who is talking, where we are, and the way to the receipts ---- */
  header{flex:0 0 auto;background:var(--panel);border-bottom:1px solid var(--line);
         padding:10px 14px;display:flex;align-items:center;gap:10px}
  .dot{width:34px;height:34px;border-radius:11px;background:var(--act);color:#fff;
       display:grid;place-items:center;font-weight:700;flex:0 0 auto}
  .who{min-width:0}
  .who b{display:block;font-size:16px;line-height:1.2}
  .who span{display:block;color:var(--dim);font-size:13px;white-space:nowrap;
            overflow:hidden;text-overflow:ellipsis}
  .why{margin-left:auto;flex:0 0 auto;background:none;border:1px solid var(--line);
       color:var(--dim);font:inherit;font-size:14px;padding:7px 12px;border-radius:999px}

  /* ---- the feed ---- */
  .feed{flex:1 1 auto;overflow-y:auto;padding:14px 12px 6px;-webkit-overflow-scrolling:touch}
  .msg{margin:0 0 12px;max-width:92%;animation:in .18s ease-out}
  @keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  .msg.you{margin-left:auto}
  .bubble{background:var(--panel);border:1px solid var(--line);border-radius:16px;
          padding:12px 14px;border-bottom-left-radius:5px}
  .you .bubble{background:var(--mine);border-color:#c9daf7;border-bottom-left-radius:16px;
               border-bottom-right-radius:5px}
  .you .bubble img{border-radius:11px;display:block;width:100%}
  .cap{color:var(--dim);font-size:13px;margin-top:6px}

  /* ---- the step card: the reference sheet, in a bubble ---- */
  .step{background:var(--panel);border:1px solid var(--line);border-radius:16px;
        border-bottom-left-radius:5px;overflow:hidden}
  .step .head{padding:12px 14px 10px}
  .chip{display:inline-block;background:var(--actbg);color:var(--act);font-weight:700;
        font-size:13px;letter-spacing:.3px;padding:4px 10px;border-radius:999px}
  .step h2{font-size:19px;margin:8px 0 0;line-height:1.25}
  .step img{width:100%;display:block;background:#e9ecf1}
  .shotnote{color:var(--dim);font-size:13px;padding:7px 14px 0}
  /* The legend under the photo. The badge numbers and colours are the ones drawn
     into the JPEG by marker.py; the words are HTML, so they stay selectable and
     resize with the phone's text setting instead of being baked into a picture. */
  .leg{list-style:none;margin:8px 0 0;padding:0 14px}
  .leg li{display:flex;gap:8px;align-items:flex-start;padding:3px 0;font-size:15px}
  .leg .n{flex:0 0 21px;height:21px;border-radius:50%;color:#fff;font-size:12px;font-weight:800;
          display:grid;place-items:center;margin-top:2px}
  .leg .act{background:var(--act)} .leg .avoid{background:var(--avoid)} .leg .stop{background:var(--stop)}
  .do{font-size:19px;line-height:1.45;padding:12px 14px 4px;font-weight:500}
  .rows{padding:4px 14px 14px}
  .r{display:flex;gap:10px;padding:9px 0;border-top:1px solid var(--line)}
  .r .k{flex:0 0 22px;height:22px;border-radius:6px;display:grid;place-items:center;
        font-size:13px;font-weight:800;color:#fff;margin-top:1px}
  .r .t{min-width:0}
  .r .t b{display:block;font-size:12px;letter-spacing:.6px;text-transform:uppercase;
          color:var(--dim);margin-bottom:1px}
  .r.avoid .k{background:var(--avoid)} .r.stop .k{background:var(--stop)}
  .r.act .k{background:var(--act)}
  .r.avoid .t b{color:var(--avoid)} .r.stop .t b{color:var(--stop)} .r.act .t b{color:var(--act)}
  .src{padding:0 14px 12px;color:var(--dim);font-size:13px}
  /* In-message links. Deliberately NOT composer buttons: the composer holds one
     action, and these two are the ways out of the happy path — trying to move on
     without proof, and stopping the job for a person. */
  .link{display:inline-block;margin-top:9px;background:none;border:0;padding:0;font:inherit;
        font-size:15px;color:inherit;opacity:.75;text-decoration:underline}
  .r .link{margin-top:6px;color:var(--stop);opacity:1;font-weight:600}

  /* ---- verdicts, refusals, notes ---- */
  .verdict{border-radius:16px;border-bottom-left-radius:5px;padding:12px 14px;border:1px solid}
  .verdict h3{margin:0 0 4px;font-size:17px}
  .v-pass{background:var(--actbg);border-color:#b9e2cc;color:#0d5f37}
  .v-fail{background:var(--avoidbg);border-color:#f3c6c8;color:#8f1f24}
  .v-halt{background:var(--stopbg);border-color:#f0d9ac;color:#8a3f06}
  .note{background:#eef2fb;border:1px solid #d6e0f5;border-radius:14px;padding:10px 12px;
        color:#274b8f;font-size:15px}
  .note a{color:#274b8f}

  /* ---- composer: one action, and a place to ask ---- */
  .composer{flex:0 0 auto;background:var(--panel);border-top:1px solid var(--line);
            padding:10px 12px calc(10px + env(safe-area-inset-bottom))}
  textarea{width:100%;border:1px solid var(--line);border-radius:14px;padding:12px;
           font:inherit;resize:none;min-height:76px;background:#fff;color:var(--ink)}
  .shot{display:flex;align-items:center;gap:10px;width:100%;margin-top:8px;
        border:1px dashed var(--line);border-radius:14px;padding:12px;color:var(--dim);
        background:#fafbfd;font-size:15px}
  .shot.has{border-style:solid;color:var(--ink);background:var(--actbg);border-color:#b9e2cc}
  /* Scoped to the element: a bare .act also matches the green "do this" row in a
     step card and the legend badges, and the button's blue then painted over them. */
  button.act{display:block;width:100%;margin-top:9px;border:0;border-radius:14px;padding:16px;
       background:var(--accent);color:#fff;font:inherit;font-weight:700;font-size:17px}
  button.act.danger{background:var(--stop)}
  button.act:disabled{opacity:.45}
  .askrow{display:flex;gap:8px;margin-top:9px;align-items:center}
  .askrow input{flex:1 1 auto;min-width:0;border:1px solid var(--line);border-radius:999px;
                padding:11px 14px;font:inherit;font-size:15px;background:#fff;color:var(--ink)}
  .askrow button{flex:0 0 auto;border:1px solid var(--line);background:#fff;color:var(--dim);
                 border-radius:999px;padding:11px 14px;font:inherit;font-size:15px}
  .hint{color:var(--dim);font-size:13px;margin:8px 2px 0;text-align:center}
  .err{color:var(--avoid);font-size:14px;margin:8px 2px 0}

  /* ---- typing + trace sheet ---- */
  .typing{display:flex;gap:4px;padding:14px}
  .typing i{width:7px;height:7px;border-radius:50%;background:#b7bec9;animation:b 1s infinite}
  .typing i:nth-child(2){animation-delay:.15s} .typing i:nth-child(3){animation-delay:.3s}
  @keyframes b{0%,60%,100%{opacity:.3}30%{opacity:1}}
  .sheet{position:fixed;inset:0;background:#0a0c1088;display:none;z-index:20}
  .sheet.on{display:block}
  .sheet .inner{position:absolute;left:0;right:0;bottom:0;top:8%;background:var(--panel);
        border-radius:18px 18px 0 0;display:flex;flex-direction:column;max-width:520px;margin:0 auto}
  .sheet h3{margin:0;padding:16px 16px 10px;font-size:18px}
  .sheet p.s{margin:0;padding:0 16px 10px;color:var(--dim);font-size:14px}
  .sheet ol{flex:1 1 auto;overflow-y:auto;list-style:none;margin:0;padding:0 16px 16px;
        font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
  .sheet li{border-top:1px solid var(--line);padding:9px 0;color:var(--dim);word-break:break-word}
  .sheet li b{color:var(--ink)}
  .sheet .close{margin:0 16px 16px;border:1px solid var(--line);background:#fff;color:var(--ink);
        border-radius:14px;padding:14px;font:inherit;font-weight:600}
  .hide{display:none !important}
</style>
</head>
<body>
<div class="app">

<header>
  <div class="dot">1</div>
  <div class="who"><b>StepSpotter</b><span id="sub">one step at a time, on your photo</span></div>
  <button class="why" id="whyBtn">why</button>
</header>

<div class="feed" id="feed"></div>

<div class="composer">
  <!-- start mode: what are we doing, and a photo of it -->
  <div id="startBox">
    <textarea id="task" placeholder="What do you want to do? Write it how you would say it."></textarea>
    <label class="shot" id="shotLabel" for="startPhoto">
      <span>&#128247;</span><span id="shotText">Take a photo of the thing</span>
    </label>
    <input id="startPhoto" type="file" accept="image/*" capture="environment" class="hide">
  </div>

  <!-- running mode: exactly one action, named after what happens -->
  <button class="act" id="actBtn">Plan my steps</button>
  <input id="stepPhoto" type="file" accept="image/*" capture="environment" class="hide">

  <div class="askrow hide" id="askRow">
    <input id="ask" placeholder="Ask a question about this step">
    <button id="askBtn">Ask</button>
  </div>
  <p class="hint" id="hint"></p>
  <p class="err hide" id="err"></p>
</div>
</div>

<div class="sheet" id="sheet"><div class="inner">
  <h3>Everything it did</h3>
  <p class="s">Plans, cards, photo verdicts and every refusal, in the order they happened.
     This is the record the answers above come from.</p>
  <ol id="traceList"></ol>
  <button class="close" id="closeSheet">Close</button>
</div></div>

<script>
const $ = (id) => document.getElementById(id);
let JOB = null, SHOWN = 0, MODE = "start", BUSY = false;

const esc = (s) => (s==null?"":String(s)).replace(/[&<>"]/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

async function api(url, opts){
  const r = await fetch(url, opts||{});
  let body = null;
  try { body = await r.json(); } catch(e) {}
  if(!r.ok) throw new Error((body && (body.detail||body.message)) || ("Something went wrong ("+r.status+")"));
  return body;
}
function fail(msg){ const e = $("err"); e.textContent = msg; e.classList.remove("hide"); }
function clearFail(){ $("err").classList.add("hide"); }
function atBottom(){ const f = $("feed"); return f.scrollHeight - f.scrollTop - f.clientHeight < 120; }
function toBottom(){ const f = $("feed"); f.scrollTop = f.scrollHeight; }

function typing(on){
  const old = $("typing"); if(old) old.remove();
  if(!on) return;
  const d = document.createElement("div");
  d.id = "typing"; d.className = "msg"; d.innerHTML =
    '<div class="bubble typing"><i></i><i></i><i></i></div>';
  $("feed").appendChild(d); toBottom();
}

function legend(items){
  if(!items || !items.length) return "";
  return '<ul class="leg">' + items.map(it =>
    '<li><span class="n ' + esc(it.kind) + '">' + it.n + '</span><span>' + esc(it.label)
    + (it.kind === "avoid" ? " — leave alone" : (it.kind === "stop" ? " — watch this" : ""))
    + '</span></li>').join("") + '</ul>';
}

// ---- one message -> one node ------------------------------------------------
function node(m){
  const wrap = document.createElement("div");
  wrap.className = "msg " + (m.from === "you" ? "you" : "");
  const stick = atBottom();

  if(m.kind === "step"){
    let rows = "";
    if(m.do_not_touch && m.do_not_touch.length)
      rows += '<div class="r avoid"><div class="k">&#10005;</div><div class="t">'
           +  '<b>Do not touch</b>' + esc(m.do_not_touch.join(" · ")) + '</div></div>';
    // The stop row is ALWAYS drawn, even when the planner wrote no stop condition for
    // this step: the way out is the one control that must never depend on the model
    // having remembered to offer it.
    const stopText = m.stop_condition
      || "anything is hot, smells burnt, is wet or sparking, or you are not sure what "
       + "you are looking at";
    rows += '<div class="r stop"><div class="k">!</div><div class="t">'
         +  '<b>Stop and get a person if</b>' + esc(stopText)
         +  '<br><button class="link" data-act="escalate">That is happening — stop now</button>'
         +  '</div></div>';
    rows += '<div class="r act"><div class="k">&#9679;</div><div class="t">'
         +  '<b>Your next photo must show</b>' + esc(m.evidence_required) + '</div></div>';
    wrap.innerHTML = '<div class="step">'
      + '<div class="head"><span class="chip">Step ' + m.step_number + ' of ' + m.total + '</span>'
      + '<h2>' + esc(m.title) + '</h2></div>'
      + '<img alt="your photo, with this step marked on it" src="' + m.card_url + '">'
      + legend(m.legend)
      + '<p class="shotnote">Boxes show roughly where to look, not exactly.</p>'
      + '<div class="do">' + esc(m.action) + '</div>'
      + '<div class="rows">' + rows + '</div>'
      + (m.source ? '<div class="src">Source: ' + esc(m.source) + '</div>' : '')
      + '</div>';
    const img = wrap.querySelector("img");
    img.onerror = () => { img.remove();
      const n = wrap.querySelector(".shotnote");
      if(n) n.textContent = "The marked photo could not be drawn; the words below still apply."; };
  }
  else if(m.kind === "photo"){
    wrap.innerHTML = '<div class="bubble"><img alt="' + esc(m.caption) + '" src="' + m.url + '">'
      + '<div class="cap">' + esc(m.caption) + '</div></div>';
    const img = wrap.querySelector("img");
    img.onerror = () => { img.remove(); };
  }
  else if(m.kind === "verdict"){
    const cls  = m.stop ? "v-halt" : (m.passed ? "v-pass" : "v-fail");
    const head = m.stop ? "Stop — that is not safe"
                        : (m.passed ? "That is done" : "Not done yet");
    // Offering the skip is the point. If this button were hidden until a photo
    // passed, the browser would be the gate, and the refusal below it — the one
    // thing this product is — would never be seen by the person holding the phone.
    const skip = (!m.passed && !m.stop)
      ? '<button class="link" data-act="advance">It is fine — move on anyway</button>' : '';
    wrap.innerHTML = '<div class="verdict ' + cls + '"><h3>' + head + '</h3><p>'
      + esc(m.reason) + '</p>' + skip + '</div>';
  }
  else if(m.kind === "block"){
    wrap.innerHTML = '<div class="verdict ' + (m.hazard ? "v-halt" : "v-fail") + '">'
      + '<h3>' + (m.hazard ? "Stopped for a person" : "I am not opening the next step") + '</h3>'
      + '<p>' + esc(m.reason) + '</p></div>';
  }
  else if(m.kind === "vendor"){
    wrap.innerHTML = '<div class="verdict v-halt"><h3>Please do not do this one yourself</h3>'
      + '<p>' + esc(m.reason) + '</p>'
      + '<p>I have not written any steps for it, on purpose.</p></div>';
  }
  else if(m.kind === "stopped"){
    wrap.innerHTML = '<div class="verdict v-halt"><h3>A person has this now</h3><p>'
      + esc(m.reason) + '</p><p>Nothing else happens on this job until they answer.</p></div>';
  }
  else if(m.kind === "done"){
    wrap.innerHTML = '<div class="verdict v-pass"><h3>All ' + m.total + ' steps are done</h3><p>'
      + esc(m.text) + '</p></div>';
  }
  else if(m.kind === "plan"){
    const tools = (m.tools_needed && m.tools_needed.length)
      ? '<div class="cap">You will need: ' + esc(m.tools_needed.join(", ")) + '</div>' : '';
    wrap.innerHTML = '<div class="bubble">' + esc(m.text) + tools + '</div>';
  }
  else if(m.kind === "note"){
    const link = m.url ? ' <a href="' + esc(m.url) + '" target="_blank" rel="noopener">open it</a>' : '';
    wrap.innerHTML = '<div class="note">' + esc(m.text) + link + '</div>';
  }
  else { // task, text
    wrap.innerHTML = '<div class="bubble">' + esc(m.text) + '</div>';
  }

  $("feed").appendChild(wrap);
  if(stick) toBottom();
  return wrap;
}

// ---- the feed is append-only, so only the tail is ever drawn ----------------
function draw(payload){
  JOB = payload.job;
  const msgs = payload.messages || [];
  typing(false);
  // What the person should be looking at when the dust settles: the newest step card
  // if one arrived (that is the thing to act on), otherwise the first new message.
  let anchor = null;
  const LANDS_ON = ["step", "done", "stopped", "vendor"];
  for(let i = SHOWN; i < msgs.length; i++){
    const el = node(msgs[i]);
    if(!anchor || LANDS_ON.includes(msgs[i].kind)) anchor = el;
  }
  SHOWN = msgs.length;
  composer(payload.composer || {});
  $("sub").textContent = JOB.job_title
    ? (JOB.step_number ? JOB.job_title + " · step " + JOB.step_number + " of " + JOB.total
                       : JOB.job_title)
    : "one step at a time, on your photo";
  // Land on the TOP of the first new message, not the bottom of the feed: a step card
  // is taller than a phone, and bottom-anchoring it hides the photo it is built around.
  if(anchor) anchor.scrollIntoView({block:"start"}); else toBottom();
}

function composer(c){
  MODE = c.action || "start";
  $("startBox").classList.add("hide");
  $("askRow").classList.toggle("hide", !c.can_ask);
  const btn = $("actBtn");
  btn.textContent = c.label || "Next";
  btn.classList.toggle("danger", MODE === "escalate");
  btn.disabled = false;
  $("hint").textContent = MODE === "photo"
    ? "The photo decides. I cannot open the next step without one."
    : (MODE === "advance" ? "" : "");
}

function startMode(){
  MODE = "start"; SHOWN = 0; JOB = null;
  $("feed").innerHTML = "";
  node({from:"agent", kind:"text",
        text:"Tell me what you want to do, and show me a photo of it. I will give you "
           + "one step at a time, drawn on your own photo."});
  $("startBox").classList.remove("hide");
  $("askRow").classList.add("hide");
  $("actBtn").textContent = "Plan my steps";
  $("actBtn").classList.remove("danger");
  $("hint").textContent = "One step at a time. Nothing is marked done without a photo.";
}

async function refresh(){ draw(await api("/api/jobs/" + JOB.job_id + "/feed")); }

// ---- actions ---------------------------------------------------------------
$("startPhoto").addEventListener("change", e => {
  const f = e.target.files[0];
  $("shotText").textContent = f ? "Photo ready" : "Take a photo of the thing";
  $("shotLabel").classList.toggle("has", !!f);
});

async function doStart(){
  const task = $("task").value.trim(), file = $("startPhoto").files[0];
  if(!task) return fail("Write what you want to do first.");
  if(!file) return fail("Add a photo of the thing you are fixing.");
  clearFail();
  // Echo what they said straight away, then let the server's feed replace the lot:
  // the wait for a plan is half a minute and a silent screen reads as a hang.
  node({from:"you", kind:"text", text:task});
  const fd = new FormData(); fd.append("task", task); fd.append("photo", file);
  $("hint").textContent = "Looking at your photo. This takes about half a minute.";
  typing(true);
  const created = await api("/api/jobs", {method:"POST", body:fd});
  history.replaceState(null, "", "?job=" + created.job_id);
  JOB = created; SHOWN = 0; $("feed").innerHTML = "";
  $("hint").textContent = "";
  await refresh();
}

async function doPhoto(file){
  const fd = new FormData(); fd.append("photo", file);
  typing(true);
  await api("/api/jobs/" + JOB.job_id + "/photo", {method:"POST", body:fd});
  await refresh();
}

async function doAdvance(){
  typing(true);
  await api("/api/jobs/" + JOB.job_id + "/advance", {method:"POST"});
  await refresh();     // a refusal is a trace row, so it arrives as a message like any other
}

async function doEscalate(){
  const fd = new FormData();
  fd.append("reason", "The person pressed Stop on their phone.");
  typing(true);
  await api("/api/jobs/" + JOB.job_id + "/escalate", {method:"POST", body:fd});
  await refresh();
}

$("actBtn").addEventListener("click", async () => {
  if(BUSY) return;
  if(MODE === "restart"){ history.replaceState(null, "", location.pathname); return startMode(); }
  if(MODE === "photo"){ return $("stepPhoto").click(); }
  BUSY = true; $("actBtn").disabled = true; clearFail();
  try {
    if(MODE === "start")         await doStart();
    else if(MODE === "advance")  await doAdvance();
    else if(MODE === "escalate") await doEscalate();
  } catch(err){ typing(false); fail(err.message); $("actBtn").disabled = false; }
  finally { BUSY = false; }
});

$("stepPhoto").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if(!f) return;
  BUSY = true; $("actBtn").disabled = true; clearFail();
  try { await doPhoto(f); }
  catch(err){ typing(false); fail(err.message); $("actBtn").disabled = false; }
  finally { BUSY = false; e.target.value = ""; }
});

async function doAsk(){
  const q = $("ask").value.trim(); if(!q || !JOB) return;
  $("ask").value = ""; clearFail();
  typing(true);
  try { await api("/api/jobs/" + JOB.job_id + "/ask",
                  {method:"POST", body:new URLSearchParams({question:q})});
        await refresh(); }
  catch(err){ typing(false); fail(err.message); }
}
// One handler for every in-message link, so a message drawn from the feed needs no
// wiring of its own.
$("feed").addEventListener("click", async (e) => {
  const btn = e.target.closest("button.link"); if(!btn || BUSY || !JOB) return;
  const act = btn.dataset.act;
  BUSY = true; btn.disabled = true; clearFail();
  try { if(act === "advance") await doAdvance(); else if(act === "escalate") await doEscalate(); }
  catch(err){ typing(false); fail(err.message); }
  finally { BUSY = false; }
});

$("askBtn").addEventListener("click", doAsk);
$("ask").addEventListener("keydown", e => { if(e.key === "Enter") doAsk(); });

// ---- the receipts ----------------------------------------------------------
$("whyBtn").addEventListener("click", async () => {
  if(!JOB) return fail("Nothing has happened yet.");
  try {
    const res = await api("/api/jobs/" + JOB.job_id + "/trace");
    // Absolute paths from the server are noise on a phone and say more about the
    // machine than about the job. Keep the last two segments, drop the rest.
    const short = (v) => JSON.stringify(v).replace(
      /"[^"]*\/([^"\/]+\/[^"\/]+)"/g, '"…/$1"');
    $("traceList").innerHTML = res.rows.map(r => {
      const rest = Object.keys(r).filter(k => !["at","job_id","event"].includes(k))
        .map(k => k + "=" + short(r[k])).join("  ");
      return "<li><b>" + esc(r.event) + "</b> " + esc(r.at) + "<br>" + esc(rest) + "</li>";
    }).join("");
    $("sheet").classList.add("on");
  } catch(err){ fail(err.message); }
});
$("closeSheet").addEventListener("click", () => $("sheet").classList.remove("on"));

// A phone locks, the tab dies, someone comes back later. ?job=<id> restores the whole
// conversation, because the conversation lives on the server, not in this page.
(async function resume(){
  const id = new URLSearchParams(location.search).get("job");
  if(!id) return startMode();
  try { const f = await api("/api/jobs/" + id + "/feed"); SHOWN = 0; draw(f); }
  catch(err){ startMode(); fail(err.message); }
})();
</script>
</body>
</html>
"""
