# DepExit — macOS/Linux helpers (Windows: use run.ps1)
.PHONY: setup ai api dev test schema

setup:
	python3.12 -m venv ai/.venv && ai/.venv/bin/pip install -q -r ai/requirements.txt
	cd backend && go build -o bin/depexit .

ai:
	cd ai && .venv/bin/python -m uvicorn app.main:app --port 8001

api:
	cd backend && go build -o bin/depexit . && cd .. && ./backend/bin/depexit

dev:
	$(MAKE) -j2 ai api

test:
	cd ai && .venv/bin/python -m pytest -q tests

schema:
	cd ai && .venv/bin/python -c "from app.capsule import write_schema; write_schema()"
