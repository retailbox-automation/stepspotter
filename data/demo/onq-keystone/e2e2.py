"""E2E part 2: a job whose first step a real photo can actually prove -> the pass path."""
import sys
sys.path.insert(0, "src")
from stepspotter import store
from stepspotter.gate import StepGate
from stepspotter.guide import JobService, build_tools, run_tool_through_gate

P = "/Users/oskolamicheal/Projects/Retailbox - Agents for Humans Hackathon/docs/design-reference-2026-09-09/raw-photos-onq"
TASK = ("Terminate the blue Cat5e cable into the keystone jack in this office wall box, "
        "then close the box and test the link with a cable tester")

svc = JobService()
gate = StepGate(state_for=svc.get,
                on_block=lambda r, ti: store.trace(ti.get("job_id") or "?", "gate_block", reason=r, tool_input=ti))
tools = build_tools(svc)

state = svc.start(TASK, f"{P}/05-office-jack-open.jpg")
print(f"job_id: {state.job_id} | safety_class: {state.plan.safety_class} | steps: {state.total}")
for s in state.plan.steps:
    print(f"  {s.id}. {s.title} :: evidence: {s.evidence_required}")
if not state.plan.steps:
    print("vendor_reason:", state.plan.vendor_reason); raise SystemExit(0)

print("\n--- card for step 1 ---", flush=True)
card, boxes = svc.card(state)
print("card:", card, f"({len(boxes)} marks)")

print("\n--- WRONG photo (06-dining-node) ---", flush=True)
r = run_tool_through_gate(gate, tools, "submit_photo", {"job_id": state.job_id, "photo_path": f"{P}/06-dining-node-white-cable.jpg"})
print("submit_photo:", r["content"])
r = run_tool_through_gate(gate, tools, "advance_step", {"job_id": state.job_id, "step_id": 1})
print("advance:", r["status"], "| cancelled:", r["cancelled"], "\n  ", r["content"])
print("current:", svc.get(state.job_id).current)

print("\n--- MATCHING photo (05-office-jack-open) ---", flush=True)
r = run_tool_through_gate(gate, tools, "submit_photo", {"job_id": state.job_id, "photo_path": f"{P}/05-office-jack-open.jpg"})
print("submit_photo:", r["content"])
r = run_tool_through_gate(gate, tools, "advance_step", {"job_id": state.job_id, "step_id": 1})
print("advance:", r["status"], "| cancelled:", r["cancelled"], "\n  ", r["content"])
st = svc.get(state.job_id)
print("current:", st.current, "->", st.describe_current())
print("JOB_ID=" + state.job_id)
