# Track A pipeline. Every target calls pipeline/run_all.py, so `make` and
# `python -m pipeline.run_all` always do the same thing. No make on Windows?
# Use:  .venv\Scripts\python -m pipeline.run_all [--only STEP | --from STEP]

ifeq ($(OS),Windows_NT)
PY ?= .venv/Scripts/python
else
PY ?= .venv/bin/python
endif
RUN = $(PY) -m pipeline.run_all

STEPS = ingest static grid overpass landcover harmonize validate app continuity presets

.PHONY: all $(STEPS) science test sizes list

# every step, raw zips -> data/app + results
all:
	$(RUN)

# one step, e.g. `make harmonize`
$(STEPS):
	$(RUN) --only $@

# refit + revalidate + rebuild app data (skips ingest/grid/overpass)
science:
	$(RUN) --from landcover

test:
	$(PY) -m pytest tests/test_pipeline_*.py -q

sizes:
	$(RUN) --sizes

list:
	$(RUN) --list
