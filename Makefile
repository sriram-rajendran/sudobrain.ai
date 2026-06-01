.PHONY: verify verify-fast swift-build python-compile scan-secrets clean

verify:
	python3 scripts/verify_public_repo.py

verify-fast:
	SUDOBRAIN_ALLOW_MISSING_GITLEAKS=1 python3 scripts/verify_public_repo.py

swift-build:
	cd app && swift build

python-compile:
	python3 -m compileall -q backend scripts
	find backend scripts -type d -name __pycache__ -exec rm -rf {} +

scan-secrets:
	gitleaks detect --source . --redact --verbose

clean:
	rm -rf app/.build
	find backend scripts -type d -name __pycache__ -exec rm -rf {} +
