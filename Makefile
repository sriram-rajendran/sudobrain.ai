.PHONY: verify verify-fast swift-build python-compile test scan-secrets demo smoke mcp-server docker-up docker-full-up clean

verify:
	python3 scripts/verify_public_repo.py

verify-fast:
	SUDOBRAIN_ALLOW_MISSING_GITLEAKS=1 python3 scripts/verify_public_repo.py

demo:
	python3 scripts/load_demo_data.py

smoke:
	python3 scripts/smoke_test_startup.py

mcp-server:
	python3 scripts/sudobrain_mcp_server.py

docker-up:
	docker compose up -d postgres neo4j

docker-full-up:
	docker compose -f docker-compose.full.yml up --build

swift-build:
	cd app && swift build

python-compile:
	python3 -m compileall -q backend scripts tests
	find backend scripts tests -type d -name __pycache__ -exec rm -rf {} +

test:
	python3 -m unittest discover -s tests

scan-secrets:
	gitleaks detect --source . --redact --verbose

clean:
	rm -rf app/.build
	find backend scripts tests -type d -name __pycache__ -exec rm -rf {} +
