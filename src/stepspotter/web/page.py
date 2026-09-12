"""The single page. Inline CSS and JS on purpose: no build step, no CDN, no fonts to
fetch — it has to open on a phone on a bad connection while someone is standing in
front of an open panel.

The colours match the rendered card exactly (green = do this here, red = do not
touch, orange = stop and get a human), so the picture and the words agree.

Two audiences open this page, and the first screen has to serve both: the person
standing in front of the panel, and someone reviewing the project with no panel and
ten minutes. The second one gets three lines saying what this is, a link to the code,
and a demo that needs no camera.
"""

#: Shown on the first screen. The repository is public; the video link is filled in
#: when there is a video to link to, and the line simply does not render while it is
#: empty — a dead "watch the video" link is worse than no link.
REPO_URL = "https://github.com/retailbox-automation/stepspotter"
VIDEO_URL = ""


def render_page(repo_url: str = REPO_URL, video_url: str = VIDEO_URL) -> str:
    """Build the page HTML. Substitution is done by replace, not format: the inline
    CSS is full of braces and would have to be doubled for every rule."""
    video = (
        f'<a href="{video_url}" target="_blank" rel="noopener">Watch the 3-minute demo</a>'
        if video_url
        else ""
    )
    return (
        _PAGE_TEMPLATE.replace("__REPO_URL__", repo_url)
        .replace("__VIDEO_LINK__", video)
    )


_PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>StepSpotter</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%232fbf71'/%3E%3Ctext x='16' y='23' font-size='20' text-anchor='middle' fill='%23fff' font-family='sans-serif'%3E1%3C/text%3E%3C/svg%3E">
<style>
  :root{
    --bg:#12141a; --card:#1b1e26; --line:#2c3140; --ink:#f2f4f8; --dim:#a3adc2;
    --act:#2fbf71; --avoid:#e5484d; --stop:#f0932b; --accent:#4f8cff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
       -webkit-text-size-adjust:100%}
  header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);
         padding:12px 16px calc(12px);display:flex;align-items:center;gap:10px}
  header b{font-size:17px;letter-spacing:.2px}
  header small{color:var(--dim);margin-left:auto;font-size:13px}
  main{padding:16px;max-width:720px;margin:0 auto;padding-bottom:48px}
  h1{font-size:20px;margin:0 0 4px}
  p.sub{color:var(--dim);margin:0 0 18px}
  label{display:block;font-weight:600;margin:14px 0 6px}
  textarea,input[type=text]{width:100%;background:var(--card);color:var(--ink);
       border:1px solid var(--line);border-radius:12px;padding:12px;font:inherit}
  textarea{min-height:92px;resize:vertical}
  .filebtn{display:block;width:100%;text-align:center;background:var(--card);
       border:1px dashed var(--line);border-radius:12px;padding:18px;color:var(--dim)}
  .filebtn.has{border-style:solid;color:var(--ink)}
  button{font:inherit;font-weight:650;border:0;border-radius:12px;padding:15px 16px;width:100%;
         background:var(--accent);color:#fff;margin-top:12px}
  button.ghost{background:transparent;color:var(--dim);border:1px solid var(--line)}
  button.stop{background:transparent;color:var(--stop);border:1px solid var(--stop)}
  button:disabled{opacity:.5}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:12px 0}
  .card img{width:100%;border-radius:10px;display:block}
  .stepno{color:var(--dim);font-size:13px;text-transform:uppercase;letter-spacing:.8px}
  .title{font-size:19px;font-weight:700;margin:2px 0 8px}
  .action{font-size:17px}
  .tag{display:block;border-left:3px solid;padding:8px 10px;margin-top:10px;border-radius:0 8px 8px 0;
       background:#00000030;font-size:15px}
  .tag.avoid{border-color:var(--avoid)} .tag.stop{border-color:var(--stop)}
  .tag.act{border-color:var(--act)}
  .tag b{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.7px;color:var(--dim)}
  .verdict{border-radius:14px;padding:14px;margin:12px 0;border:1px solid}
  .verdict.pass{border-color:var(--act);background:#2fbf7118}
  .verdict.fail{border-color:var(--avoid);background:#e5484d18}
  .verdict.halt{border-color:var(--stop);background:#f0932b18}
  .verdict h3{margin:0 0 6px;font-size:17px}
  .verdict img{width:96px;height:96px;object-fit:cover;border-radius:10px;float:right;margin-left:12px}
  .muted{color:var(--dim);font-size:14px}
  .banner{border:1px solid var(--avoid);background:#e5484d18;border-radius:12px;padding:12px;margin:12px 0}
  .banner.stopc{border-color:var(--stop);background:#f0932b18}
  ol.trace{list-style:none;padding:0;margin:0}
  ol.trace li{border-bottom:1px solid var(--line);padding:10px 0;color:var(--dim);
       overflow-wrap:anywhere}
  ol.trace li b{color:var(--ink)}
  ol.trace.raw{font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
  .tr-head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
  .tr-actor{color:var(--ink);font-weight:700;font-size:15px}
  .tr-at{color:var(--dim);font-size:12px;font-variant-numeric:tabular-nums;margin-left:auto}
  .tr-what{color:var(--ink);font-size:15px}
  .tr-result{font-size:15px;margin-top:2px}
  .tr-why{font-size:14px;color:var(--dim);margin-top:2px}
  .tr-result.ok{color:var(--act)} .tr-result.bad{color:var(--avoid)}
  .tr-result.stop{color:var(--stop)}
  .viewswitch{display:flex;gap:10px;align-items:baseline;margin:0 0 10px}
  .viewswitch a{font-size:14px;cursor:pointer}
  .row{display:flex;gap:10px} .row button{margin-top:12px}
  .hide{display:none}
  .spin{display:inline-block;width:14px;height:14px;border:2px solid #ffffff60;border-top-color:#fff;
        border-radius:50%;animation:s .8s linear infinite;vertical-align:-2px;margin-right:8px}
  @keyframes s{to{transform:rotate(360deg)}}
  /* A manual URL is one long unbreakable token; on a 390px phone it pushed the whole
     page sideways. Break it anywhere and never let it set the page's width. */
  a{color:var(--accent);overflow-wrap:anywhere;word-break:break-word}
  #manualLine a{display:inline-block;max-width:100%;vertical-align:top}
  p,li,.tag,.verdict p{overflow-wrap:anywhere}

  /* --- first screen: what this is, and a way in without a camera --- */
  .intro{background:var(--card);border:1px solid var(--line);border-radius:14px;
         padding:14px;margin:0 0 16px}
  .intro p{margin:0 0 8px;font-size:15px}
  .intro p:last-of-type{margin-bottom:0}
  .intro .lock{color:var(--act);font-weight:650}
  .links{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;font-size:14px}
  .demo{border:1px solid var(--accent);border-radius:14px;padding:14px;margin:0 0 18px;
        background:#4f8cff12}
  .demo h2{font-size:16px;margin:0 0 6px}
  .demo p{margin:0;font-size:14px;color:var(--dim)}
  .demo button{margin-top:10px}
  .or{color:var(--dim);font-size:13px;text-transform:uppercase;letter-spacing:.8px;
      text-align:center;margin:0 0 10px}
  .wait{margin:12px 0 0;font-size:15px;color:var(--ink);min-height:22px}
  .wait .secs{color:var(--dim);font-variant-numeric:tabular-nums}
  .wait .muted{display:block;margin-top:2px}
  .demobar{border:1px solid var(--line);border-radius:12px;padding:12px;margin:12px 0;
           background:#4f8cff10}
  .demobar p{margin:0 0 4px;font-size:14px;color:var(--dim)}
  .demobar .cap{font-size:13px}
  .btncap{color:var(--dim);font-size:13px;margin:6px 2px 14px}
</style>
</head>
<body>
<header><b>StepSpotter</b><small id="hdr">one step at a time</small></header>
<main>

<section id="screen-start">
  <h1>Fix it one step at a time</h1>
  <div class="intro">
    <p>StepSpotter walks you through a home repair <b>one step at a time</b>, drawn on a
       photo of your own thing — with what to do, what not to touch, and when to stop.</p>
    <p><span class="lock">The next step stays locked</span> until a photo proves the last
       one was really done. That lock is code, not a polite model: a Strands hook cancels
       the tool call.</p>
    <p>If the job turns out to need a licensed professional, it writes no steps at all.</p>
    <div class="links">
      <a href="__REPO_URL__" target="_blank" rel="noopener">Source code on GitHub</a>
      __VIDEO_LINK__
    </div>
  </div>

  <div class="demo hide" id="demoCard">
    <h2>No panel in front of you?</h2>
    <p id="demoTask">Run the whole thing on a real photo from the repo — a real plan, a
       real refusal, a real pass. Nothing is pre-recorded.</p>
    <button id="demoBtn">Try a demo job</button>
    <p class="wait" id="demoWait"></p>
  </div>

  <p class="or" id="orLine">or use your own photo</p>
  <label for="task">The job</label>
  <textarea id="task" placeholder="e.g. Connect the two blue cables to new jacks and test the link"></textarea>
  <label>Your photo</label>
  <label class="filebtn" id="startPhotoLabel" for="startPhoto">Tap to take or choose a photo</label>
  <input id="startPhoto" type="file" accept="image/*" capture="environment" class="hide">
  <button id="startBtn">Plan my steps</button>
  <p class="wait" id="startWait"></p>
  <p class="muted" id="startNote"></p>
</section>

<section id="screen-vendor" class="hide">
  <h1>Please do not do this one yourself</h1>
  <div class="banner stopc"><b id="vendorTitle"></b><p id="vendorReason"></p></div>
  <p class="muted">No steps were written for this job on purpose.</p>
  <button class="ghost" onclick="location.reload()">Start something else</button>
</section>

<section id="screen-step" class="hide">
  <div class="card">
    <div class="stepno" id="stepNo"></div>
    <div class="title" id="stepTitle"></div>
    <img id="cardImg" alt="your photo with this step marked on it">
    <p class="muted" id="cardNote">Boxes show roughly where to look, not exactly.</p>
    <p class="action" id="stepAction"></p>
    <p class="muted" id="stepSource"></p>
    <div id="stepTags"></div>
  </div>
  <p class="muted" id="manualLine"></p>
  <p class="muted" id="researchLine"></p>
  <div id="verdictBox"></div>
  <div id="blockBox"></div>
  <!-- Directly under the verdict on purpose: when a photo passes, the next thing to
       do must be the next thing on screen, not below two other buttons. -->
  <button id="nextBtn" class="hide">Next step</button>
  <!-- The refusal has to be reachable from a browser. "Next step" only appears once a
       photo has passed, so before this the gate — the one mechanic this whole project
       is built on — never showed itself on screen to anyone who did not read the code.
       This button asks anyway, with nothing to show for the step, and is refused. -->
  <button id="skipBtn" class="ghost hide">Skip the photo and move on</button>
  <p class="btncap hide" id="skipCap">Asks to close this step on your word alone. A
     Strands hook cancels the call in code and says which photo it is waiting for.</p>
  <div class="demobar hide" id="demoBar">
    <p><b>Demo</b> — no camera needed. Two real photos, sent to the same checker:</p>
    <button class="ghost" id="demoWrongBtn">Send the wrong photo</button>
    <p class="cap muted" id="demoWrongCap"></p>
    <button id="demoRightBtn">Send the right photo</button>
    <p class="cap muted" id="demoRightCap"></p>
  </div>
  <button id="photoBtn">I did it — take photo</button>
  <input id="stepPhoto" type="file" accept="image/*" capture="environment" class="hide">
  <p class="wait" id="stepWait"></p>
  <div class="row">
    <button class="stop" id="stopBtn">Stop, get a person</button>
    <button class="ghost" id="traceBtn">See what it did</button>
  </div>
</section>

<section id="screen-done" class="hide">
  <h1>All steps are done</h1>
  <div class="verdict pass"><h3 id="doneTitle"></h3>
    <p>The last step was a check, and the photo showed it. Nothing was marked done without a photo.</p></div>
  <button class="ghost" id="traceBtn2">See what it did</button>
  <button class="ghost" onclick="location.reload()">Start another job</button>
</section>

<section id="screen-stopped" class="hide">
  <h1>Stopped — a person has this now</h1>
  <div class="banner stopc"><p id="stoppedReason"></p></div>
  <p class="muted">Nothing else happens on this job until they answer.</p>
  <button class="ghost" id="traceBtn3">See what it did</button>
</section>

<section id="screen-trace" class="hide">
  <h1>Every step it took</h1>
  <p class="sub">Who did what, what came back, and why — plans, cards, photo verdicts
     and every refusal, in order.</p>
  <div class="viewswitch">
    <a id="rawLink">Show the raw log (for engineers)</a>
  </div>
  <ol class="trace" id="traceList"></ol>
  <button class="ghost" id="backBtn">Back</button>
</section>

</main>
<script>
const $ = (id) => document.getElementById(id);
let JOB = null, BUSY = false, DEMO = null;

// A plan is four model calls and takes most of a minute; a photo check takes a few
// seconds. Silence for that long reads as "it broke", so say what is happening now
// and keep a second counter running, which is the part that proves it is still alive.
const PLAN_STAGES = ["Looking at your photo…",
                     "Checking it is safe to do yourself…",
                     "Looking up the manual…",
                     "Writing the steps…"];
const CHECK_STAGES = ["Checking your photo…", "Comparing it with what the step asked for…"];

function waiting(el, stages, every, note){
  const t0 = Date.now(); let i = 0;
  const paint = () => {
    // No spinner here: the button that was pressed already has one, and two of them
    // spinning at different phases reads as two things happening.
    const secs = Math.round((Date.now() - t0) / 1000);
    el.innerHTML = esc(stages[i]) + ' <span class="secs">' + secs + 's</span>'
      + (note ? '<span class="muted">' + esc(note) + '</span>' : '');
  };
  paint();
  const tick = setInterval(paint, 1000);
  const move = setInterval(() => { if(i < stages.length - 1){ i++; paint(); } }, every);
  return () => { clearInterval(tick); clearInterval(move); el.innerHTML = ""; };
}

function show(name){
  ["start","vendor","step","done","stopped","trace"].forEach(s =>
    $("screen-"+s).classList.toggle("hide", s !== name));
  window.scrollTo(0,0);
}
function busy(btn, on, label){
  BUSY = on;
  if(!btn) return;
  btn.disabled = on;
  if(on){ btn.dataset.label = btn.innerHTML; btn.innerHTML = '<span class="spin"></span>'+(label||"Working…"); }
  else if(btn.dataset.label){ btn.innerHTML = btn.dataset.label; }
}
async function api(url, opts){
  const r = await fetch(url, opts||{});
  let body = null;
  try { body = await r.json(); } catch(e) { body = null; }
  if(!r.ok){ throw new Error((body && (body.detail||body.message)) || ("Something went wrong ("+r.status+")")); }
  return body;
}
function esc(s){ return (s==null?"":String(s)).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

// ---- start ---------------------------------------------------------------
$("startPhoto").addEventListener("change", e => {
  const f = e.target.files[0];
  const l = $("startPhotoLabel");
  l.textContent = f ? ("Photo ready: " + f.name) : "Tap to take or choose a photo";
  l.classList.toggle("has", !!f);
});
$("startBtn").addEventListener("click", async () => {
  const task = $("task").value.trim(), file = $("startPhoto").files[0];
  if(!task){ $("startNote").textContent = "Write what you want to do first."; return; }
  if(!file){ $("startNote").textContent = "Add a photo of the thing you are fixing."; return; }
  $("startNote").textContent = "";
  const fd = new FormData(); fd.append("task", task); fd.append("photo", file);
  await plan($("startBtn"), $("startWait"), "/api/jobs", {method:"POST", body:fd});
});

// ---- demo ----------------------------------------------------------------
// The same endpoints a phone hits; only the JPEG bytes come from the repo instead of
// a camera. Nothing here shortcuts the planner, the checker or the gate.
$("demoBtn").addEventListener("click", async () => {
  await plan($("demoBtn"), $("demoWait"), "/api/demo/jobs", {method:"POST"});
});

async function plan(btn, waitEl, url, opts){
  const stop = waiting(waitEl, PLAN_STAGES, 9000,
                       "Usually 20–40 seconds. These are live model calls, not a recording.");
  busy(btn, true, "Planning…");
  try {
    JOB = await api(url, opts);
    history.replaceState(null, "", "?job=" + JOB.job_id);
    render();
  } catch(err){ $("startNote").textContent = err.message; }
  finally { stop(); busy(btn, false); }
}

async function sendDemoPhoto(which, btn){
  const fd = new FormData(); fd.append("which", which);
  $("blockBox").innerHTML = "";
  const stop = waiting($("stepWait"), CHECK_STAGES, 3000, "About 5 seconds.");
  busy(btn, true, "Checking…");
  try {
    const res = await api("/api/jobs/" + JOB.job_id + "/demo-photo", {method:"POST", body:fd});
    JOB = res.job; render();
  } catch(err){ $("blockBox").innerHTML = '<div class="banner">'+esc(err.message)+'</div>'; }
  finally { stop(); busy(btn, false); }
}
$("demoWrongBtn").addEventListener("click", () => sendDemoPhoto("wrong", $("demoWrongBtn")));
$("demoRightBtn").addEventListener("click", () => sendDemoPhoto("right", $("demoRightBtn")));

// ---- step ----------------------------------------------------------------
function render(){
  if(!JOB) return show("start");
  $("hdr").textContent = JOB.job_title || "";
  if(JOB.safety_class === "vendor_required"){
    $("vendorTitle").textContent = JOB.job_title || JOB.task;
    $("vendorReason").textContent = JOB.vendor_reason || "";
    return show("vendor");
  }
  if(JOB.escalated){
    $("stoppedReason").textContent = JOB.verdict && JOB.verdict.stop
      ? JOB.verdict.reason : "You asked for a person to look at this.";
    return show("stopped");
  }
  if(JOB.done){ $("doneTitle").textContent = JOB.job_title + " — " + JOB.total + " steps, all proven by a photo."; return show("done"); }

  const s = JOB.step;
  $("stepNo").textContent = "Step " + JOB.step_number + " of " + JOB.total;
  $("stepTitle").textContent = s.title;
  $("stepAction").textContent = s.action;
  $("stepSource").textContent = s.source ? "Source: " + s.source : "";
  const r = JOB.research || null;
  const manual = (r && r.manual_url) || (JOB.sources || []).filter(u => /\.pdf$/i.test(u))[0];
  $("manualLine").innerHTML = manual
    ? 'Manual: <a href="' + esc(manual) + '" target="_blank" rel="noopener">' + esc(manual) + '</a>'
    : "";
  // Where the manual came from — or, when there is none, what was tried instead.
  // An ungrounded plan has to say so here; on a phone this line is the only warning.
  $("researchLine").textContent = !r ? ""
    : (r.status === "found"
        ? "Manual found via " + (r.source_words || r.source || "an earlier lookup")
          + (r.pages && r.pages.length ? " — pages " + r.pages.join(", ") : "")
        : (r.status === "not_found"
            ? "No manual found, so these steps come from the photo alone"
              + (r.trail && r.trail.length ? " (tried: " + r.trail.join("; ") + ")" : "")
            : ""));
  const img = $("cardImg");
  img.src = JOB.card_url + "&t=" + Date.now();
  img.onerror = () => { img.style.display = "none"; $("cardNote").textContent = "The marked photo could not be drawn; the words below still apply."; };
  img.onload = () => { img.style.display = "block"; $("cardNote").textContent = "Boxes show roughly where to look, not exactly."; };

  let tags = "";
  if(s.do_not_touch && s.do_not_touch.length)
    tags += '<div class="tag avoid"><b>Do not touch</b>' + esc(s.do_not_touch.join(" · ")) + '</div>';
  if(s.stop_condition)
    tags += '<div class="tag stop"><b>Stop and get a person if</b>' + esc(s.stop_condition) + '</div>';
  tags += '<div class="tag act"><b>Your next photo must show</b>' + esc(s.evidence_required) + '</div>';
  $("stepTags").innerHTML = tags;

  const v = JOB.verdict;
  if(v){
    const cls = v.stop ? "halt" : (v.passed ? "pass" : "fail");
    const head = v.stop ? "Stop — that is not safe" : (v.passed ? "That looks done" : "Not yet");
    $("verdictBox").innerHTML = '<div class="verdict '+cls+'">'
      + '<img src="'+v.evidence_url+'?t='+Date.now()+'" alt="the photo you sent">'
      + '<h3>'+head+'</h3><p>'+esc(v.reason)+'</p></div>';
  } else { $("verdictBox").innerHTML = ""; }
  // Exactly one way forward is on screen at a time: "Next step" once a photo has
  // passed, and the skip button — which the gate will refuse — while none has.
  const unlocked = !!(v && v.passed && !v.stop);
  $("nextBtn").classList.toggle("hide", !unlocked);
  $("skipBtn").classList.toggle("hide", unlocked);
  $("skipCap").classList.toggle("hide", unlocked);
  $("photoBtn").innerHTML = v ? "Take another photo" : "I did it — take photo";
  // In demo mode the two repo photos replace the camera; everything else is identical.
  $("demoBar").classList.toggle("hide", !JOB.demo);
  $("photoBtn").classList.toggle("hide", !!JOB.demo);
  show("step");
}

$("photoBtn").addEventListener("click", () => $("stepPhoto").click());
$("stepPhoto").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if(!f) return;
  const fd = new FormData(); fd.append("photo", f);
  $("blockBox").innerHTML = "";
  const stop = waiting($("stepWait"), CHECK_STAGES, 3000, "About 5 seconds.");
  busy($("photoBtn"), true, "Checking…");
  try {
    const res = await api("/api/jobs/"+JOB.job_id+"/photo", {method:"POST", body:fd});
    JOB = res.job; render();
  } catch(err){ $("blockBox").innerHTML = '<div class="banner">'+esc(err.message)+'</div>'; }
  finally { stop(); busy($("photoBtn"), false); e.target.value = ""; }
});

// Both buttons ask the same question, on the same endpoint, through the same hook.
// intent=skip changes nothing about the answer — it only puts the ask on the trace, so
// "the photo passed and they pressed Next" and "they pressed skip with nothing to show"
// do not read as the same event afterwards. The refusal names the photo it wants,
// because "no" without "then what?" is a dead end on a phone.
async function askToAdvance(btn, intent){
  busy(btn, true, "Checking…");
  const opts = {method:"POST"};
  if(intent === "skip"){ const fd = new FormData(); fd.append("intent", "skip"); opts.body = fd; }
  try {
    const res = await api("/api/jobs/"+JOB.job_id+"/advance", opts);
    JOB = res.job;
    if(res.blocked){
      const need = (JOB && JOB.step) ? JOB.step.evidence_required : "";
      $("blockBox").innerHTML = '<div class="banner'+(res.hazard?" stopc":"")+'"><b>'
        + (res.hazard ? "Stopped for a person" : "Blocked by the gate — no photo, no next step")
        + '</b><p>'+esc(res.reason)+'</p>'
        + (!res.hazard && need ? '<p class="muted">The photo it is waiting for: '+esc(need)+'</p>' : "")
        + '</div>';
    } else { $("blockBox").innerHTML = ""; $("verdictBox").innerHTML = ""; }
    render();
  } catch(err){ $("blockBox").innerHTML = '<div class="banner">'+esc(err.message)+'</div>'; }
  finally { busy(btn, false); }
}
$("nextBtn").addEventListener("click", () => askToAdvance($("nextBtn"), "next"));
$("skipBtn").addEventListener("click", () => askToAdvance($("skipBtn"), "skip"));

$("stopBtn").addEventListener("click", async () => {
  const fd = new FormData(); fd.append("reason", "The person pressed Stop on their phone.");
  busy($("stopBtn"), true, "Stopping…");
  try { const res = await api("/api/jobs/"+JOB.job_id+"/escalate", {method:"POST", body:fd});
        JOB = res.job; render(); }
  catch(err){ $("blockBox").innerHTML = '<div class="banner">'+esc(err.message)+'</div>'; }
  finally { busy($("stopBtn"), false); }
});

// The trace a person reads: actor, what they did, how it came out, why. The raw rows
// are a separate request behind the link below — they are full of container paths and
// job ids, which answer a question nobody standing at a panel is asking.
async function openTrace(){
  try {
    const res = await api("/api/jobs/"+JOB.job_id+"/trace?view=human");
    $("traceList").className = "trace";
    $("traceList").innerHTML = res.human.map(r =>
      '<li><div class="tr-head"><span class="tr-actor">'+esc(r.actor)+'</span>'
      + '<span class="tr-at">'+esc(r.at)+'</span></div>'
      + '<div class="tr-what">'+esc(r.what)+'</div>'
      + (r.result ? '<div class="tr-result '+esc(r.tone||"")+'">'+esc(r.result)+'</div>' : "")
      + (r.why ? '<div class="tr-why">'+esc(r.why)+'</div>' : "")
      + '</li>').join("");
    $("rawLink").textContent = "Show the raw log (for engineers)";
    show("trace");
  } catch(err){ alert(err.message); }
}
$("rawLink").addEventListener("click", async () => {
  if($("traceList").classList.contains("raw")) return openTrace();
  try {
    const res = await api("/api/jobs/"+JOB.job_id+"/trace?view=raw");
    $("traceList").className = "trace raw";
    $("traceList").innerHTML = res.rows.map(r => {
      const rest = Object.keys(r).filter(k => !["at","job_id","event"].includes(k))
        .map(k => k+"="+JSON.stringify(r[k])).join("  ");
      return "<li><b>"+esc(r.event)+"</b> <span>"+esc(r.at)+"</span><br>"+esc(rest)+"</li>";
    }).join("");
    $("rawLink").textContent = "Back to the readable one";
  } catch(err){ alert(err.message); }
});
["traceBtn","traceBtn2","traceBtn3"].forEach(id => $(id).addEventListener("click", openTrace));
$("backBtn").addEventListener("click", render);

// The demo button only appears if the photos are actually installed — an install
// without them (or a stripped image) should show no button rather than a broken one.
async function loadDemo(){
  try { DEMO = await api("/api/demo"); } catch(err){ DEMO = null; }
  const on = !!(DEMO && DEMO.available);
  $("demoCard").classList.toggle("hide", !on);
  $("orLine").classList.toggle("hide", !on);
  if(!on) return;
  $("demoTask").textContent = "Runs this job on a real photo of a low-voltage panel, "
    + "from the repo: “" + DEMO.task + "”. Real plan, real refusal, real pass — "
    + "nothing pre-recorded.";
  $("demoWrongBtn").textContent = DEMO.buttons.wrong.label;
  $("demoWrongCap").textContent = DEMO.buttons.wrong.caption;
  $("demoRightBtn").textContent = DEMO.buttons.right.label;
  $("demoRightCap").textContent = DEMO.buttons.right.caption;
}

// A phone reloads, a screen locks, a browser is killed mid-job. ?job=<id> comes back
// to the same step: the job lives on the server, the page holds nothing.
(async function resume(){
  await loadDemo();
  const id = new URLSearchParams(location.search).get("job");
  if(!id){ return show("start"); }
  try { JOB = await api("/api/jobs/"+id); render(); }
  catch(err){ show("start"); $("startNote").textContent = err.message; }
})();
</script>
</body>
</html>
"""

#: What ``app.py`` serves. Built once at import — the page has no per-request state.
PAGE_HTML = render_page()
