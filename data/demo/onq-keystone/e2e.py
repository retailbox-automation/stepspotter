"""E2E on the real OnQ photos: plan -> card -> wrong photo -> blocked -> right photo -> advance."""
import sys, json
sys.path.insert(0, "src")
from stepspotter import store
from stepspotter.gate import StepGate
from stepspotter.guide import JobService, build_tools, run_tool_through_gate

P = "<photos>"
TASK = ("Connect the two blue Cat5e network cables from the old phone block to new keystone "
        "jacks and join them with a patch cord, then test the link")

svc = JobService()
gate = StepGate(state_for=svc.get,
                on_block=lambda r, ti: store.trace(ti.get("job_id") or "?", "gate_block", reason=r, tool_input=ti))
tools = build_tools(svc)

print("=== 1. PLAN ===", flush=True)
state = svc.start(TASK, f"{P}/03-telecom-module.jpg")
p = state.plan
print(f"job_id: {state.job_id}\nsafety_class: {p.safety_class}\njob: {p.job_title}\ntools: {p.tools_needed}")
for s in p.steps:
    print(f"  {s.id}. {s.title}\n     action: {s.action}\n     do_not_touch: {s.do_not_touch}"
          f"\n     stop_if: {s.stop_condition}\n     evidence: {s.evidence_required}")
if not p.steps:
    print("vendor_reason:", p.vendor_reason); raise SystemExit(0)

print("\n=== 2. SHOW STEP 1 (card) ===", flush=True)
card, boxes = svc.card(state)
print("card:", card)
for b in boxes: print(f"   [{b.kind}] {b.label} ({b.x0:.2f},{b.y0:.2f})-({b.x1:.2f},{b.y1:.2f})")

print("\n=== 3. SUBMIT A NON-MATCHING PHOTO (05-office-jack-open) ===", flush=True)
r = run_tool_through_gate(gate, tools, "submit_photo",
                          {"job_id": state.job_id, "photo_path": f"{P}/05-office-jack-open.jpg"})
print("submit_photo ->", r["content"])

print("\n=== 4. ADVANCE (must be cancelled) ===", flush=True)
r = run_tool_through_gate(gate, tools, "advance_step", {"job_id": state.job_id, "step_id": 1})
print("status:", r["status"], "| cancelled:", r["cancelled"])
print("reason:", r["content"])
print("state.current:", svc.get(state.job_id).current, "(expected 0)")

print("\n=== 5. SUBMIT EACH REMAINING PHOTO AGAINST STEP 1 ===", flush=True)
best = None
for name in ["01-panel-overview", "02-panel-inside", "03-telecom-module", "04-office-jack-front", "06-dining-node-white-cable"]:
    r = run_tool_through_gate(gate, tools, "submit_photo",
                              {"job_id": state.job_id, "photo_path": f"{P}/{name}.jpg"})
    v = svc.get(state.job_id).verdicts[svc.get(state.job_id).current]
    print(f"  {name}: passed={v.passed} stop={v.stop} :: {v.reason}")
    if v.passed and best is None: best = name

print("\n=== 6. ADVANCE AFTER THE LAST VERDICT ===", flush=True)
st = svc.get(state.job_id)
r = run_tool_through_gate(gate, tools, "advance_step", {"job_id": state.job_id, "step_id": st.current + 1})
print("status:", r["status"], "| cancelled:", r["cancelled"])
print("result:", r["content"] if not isinstance(r["content"], dict) else json.dumps(r["content"]))
print("state.current:", svc.get(state.job_id).current)
print("\nfirst photo that satisfied step 1:", best)
print("JOB_ID=" + state.job_id)
