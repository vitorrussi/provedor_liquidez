.PHONY: setup conda-env backend-install frontend-install test typecheck

CONDA_ENV := provedor-liquidez
# `make` runs recipes in a non-interactive shell, which never sources
# ~/.bashrc, so `conda` may not be on PATH even after `conda init` -- fall
# back to common install locations (mirrors scripts/dev.sh's find_conda_base).
CONDA_EXE := $(shell command -v conda 2>/dev/null || \
	for d in "$(HOME)/miniforge3" "$(HOME)/miniconda3" "$(HOME)/anaconda3"; do \
		[ -x "$$d/bin/conda" ] && echo "$$d/bin/conda" && break; \
	done)
# `conda run` picks up the env without requiring `conda activate` in this shell.
CONDA_RUN := $(CONDA_EXE) run -n $(CONDA_ENV) --no-capture-output

setup: conda-env backend-install frontend-install

# Creates the conda env (Python 3.12 + Node 24) from environment.yml if it
# doesn't exist yet; `conda env update` keeps it in sync on repeat runs.
conda-env:
	$(CONDA_EXE) env list | grep -qE "^$(CONDA_ENV) " || $(CONDA_EXE) env create -f environment.yml
	$(CONDA_EXE) env update -n $(CONDA_ENV) -f environment.yml --prune

backend-install:
	cd backend && $(CONDA_RUN) pip install -r requirements.txt

frontend-install:
	cd frontend && $(CONDA_RUN) npm install

test:
	cd backend && $(CONDA_RUN) python -m pytest

typecheck:
	cd frontend && $(CONDA_RUN) npx tsc --noEmit -p tsconfig.app.json
