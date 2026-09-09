"""E2E part 3 — the PASS path, end to end, with the real Bedrock verifier.

The plan here is hand-written, not planner-generated, and the run says so. Reason:
the Planner writes close-up evidence lines ("a photo of the T568B label on the jack")
and our six archive photos are wide shots taken months earlier for another purpose,
so no photo satisfies its step 1. The step below asks for exactly what photo 05 does
show. Nothing else is faked: the verdict is a live Bedrock call and the gate is the
same gate.
"""
import sys
sys.path.insert(0, "src")
from stepspotter import store
from stepspotter.gate import StepGate
from stepspotter.guide import JobService, build_tools, run_tool_through_gate
from stepspotter.models import JobState, Plan, Step

P = "/Users/oskolamicheal/Projects/Retailbox - Agents for Humans Hackathon/docs/design-reference-2026-09-09/raw-photos-onq"

plan = Plan(
    job_title="Terminate the office jack",
    safety_class="diy_ok",
    tools_needed=["punch-down tool", "cable tester"],
    steps=[
        Step(id=1, title="Open the jack and seat the pairs",
             action="Take the faceplate off the office box and push each coloured wire pair into the matching slot on the keystone jack (the snap-in socket the cable plugs into).",
             do_not_touch=["the black coax cable", "the other cables in the box"],
             stop_condition="if any wire is warm, scorched or smells burnt, stop and contact a human",
             evidence_required="the wall jack open with the faceplate off and the coloured wire pairs terminated into the keystone module",
             highlight_targets=["keystone jack", "terminated wire pairs"]),
        Step(id=2, title="Test the link",
             action="Plug the cable tester into both ends and read the lights.",
             evidence_required="the tester showing all eight lights in order"),
    ],
)

svc = JobService()
gate = StepGate(state_for=svc.get,
                on_block=lambda r, ti: store.trace(ti.get("job_id") or "?", "gate_block", reason=r, tool_input=ti))
tools = build_tools(svc)

job_id = store.new_job_id()
state = JobState(job_id=job_id, task="terminate the office jack", start_photo=f"{P}/05-office-jack-open.jpg", plan=plan)
svc.put(state)
store.trace(job_id, "plan", note="hand-written plan (see docstring)", steps=len(plan.steps), safety_class=plan.safety_class)
print(f"job_id: {job_id} (plan hand-written, verdicts live)")

print("\n--- card for step 1 ---", flush=True)
card, boxes = svc.card(state)
print("card:", card)
for b in boxes: print(f"   [{b.kind}] {b.label} ({b.x0:.2f},{b.y0:.2f})-({b.x1:.2f},{b.y1:.2f})")

print("\n--- WRONG photo (04-office-jack-front: closed faceplate) ---", flush=True)
r = run_tool_through_gate(gate, tools, "submit_photo", {"job_id": job_id, "photo_path": f"{P}/04-office-jack-front.jpg"})
print("submit_photo:", r["content"])
r = run_tool_through_gate(gate, tools, "advance_step", {"job_id": job_id, "step_id": 1})
print("advance:", r["status"], "| cancelled:", r["cancelled"], "\n  ", r["content"])
print("current:", svc.get(job_id).current, "(expected 0)")

print("\n--- MATCHING photo (05-office-jack-open) ---", flush=True)
r = run_tool_through_gate(gate, tools, "submit_photo", {"job_id": job_id, "photo_path": f"{P}/05-office-jack-open.jpg"})
print("submit_photo:", r["content"])
r = run_tool_through_gate(gate, tools, "advance_step", {"job_id": job_id, "step_id": 1})
print("advance:", r["status"], "| cancelled:", r["cancelled"], "\n  ", r["content"])
st = svc.get(job_id)
print("current:", st.current, "->", st.describe_current())
print("JOB_ID=" + job_id)
