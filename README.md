# StepSpotter

One step at a time, on *your* photo — and the next step stays locked until your photo proves the last one was done safely.

Built with **Strands Agents** (AWS) for the Agents for Humans hackathon, Everyday Agents track. Work in progress — submission window 2026-09-02 … 2026-09-14.

## Status
- [x] Spike A: vision verdict + bounding boxes on real photos (verdict 8/8 stable; boxes rough, small parts drift — see spikes/SPIKE-A-RESULT.md)
- [x] Spike B: `BeforeToolCall` gate on `advance_step` (6/6 tests, live cancel proven — spikes/SPIKE-B-RESULT.md)
- [ ] Core: Planner → Marker → Verifier → Gate
- [ ] Web UI (phone-first)
- [ ] Eval set + red-team photos
- [ ] Deploy + demo video

License: MIT (see `LICENSE`).
