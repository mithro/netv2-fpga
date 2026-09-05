# NeTV2 modern tree. All Python goes through uv.
UV ?= uv

.PHONY: sync test lint clean

sync:
	$(UV) sync --extra dev

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check netv2 scripts tests/unit tests/hardware

clean:
	rm -rf build .pytest_cache
