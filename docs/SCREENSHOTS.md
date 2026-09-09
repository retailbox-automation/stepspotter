# Regenerating the gallery screenshots

`tools/screenshots.py` starts its own uvicorn server against a throwaway
`STEPSPOTTER_DATA` dir, drives it with python-playwright at a phone viewport
(430x932, deviceScaleFactor 2), and saves 9 PNGs to `data/demo/screens/` covering
the empty and filled start screen, the planning spinner, a step card (viewport and
full page), a "Not yet" verdict, a second-try verdict, the trace view, and the
stopped/escalated screen. Run it with the project venv and AWS creds exported in
the same shell:

```
while IFS='=' read -r key val; do
  case "$key" in AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_DEFAULT_REGION) export "$key=$val";; esac
done < /path/to/aws.env
PY=/path/to/venv/bin/python
"$PY" -m pip install -e ".[shots]" && "$PY" -m playwright install chromium
"$PY" tools/screenshots.py
```

The CLI eval run and step-card JPG that round out the gallery are generated
separately and copied in by hand:

```
PYTHONPATH=src "$PY" -m stepspotter.cli eval fixtures/ --repeat 1 > data/demo/screens/09-eval-output.txt
cp data/demo/screens-run/jobs/<job-id>/step-01.jpg data/demo/screens/10-step-card.jpg
```

Gotcha: the verdict box renders below the fold under the card image, so a plain
viewport screenshot taken right after submitting a photo can come out byte-identical
to the step-card shot — `scroll_into_view_if_needed()` on `#verdictBox .verdict`
before snapping.
