SHELL := /bin/sh

.PHONY: report-secrets test-report-secrets test-ci-selection

.PHONY: help format-check sdk-facade sdk-facade-check sdk-native-vocabulary type-server target-runtime-guard target-runtime-inventory coverage-e2e-mock coverage-server coverage-python-sdk coverage-cpp-mock coverage-cpp-agora-real coverage-cpp-volcengine-real coverage-mac-console coverage-local-required coverage-discovery coverage-real-required coverage-all pytest-declaration-check test-evidence-map test-protocol test-agent-core test-server test-server-quiet test-logging test-mac-mock test-e2e-mock test-target-mock-tracer test-mac-direct-agent-mock test-mac-volcengine-real test-mac-zego-real test-mac-direct-agent-agora-real test-mac-agora-real test-mac-console test-mac-console-ui-smoke build-mac-console-app run-mac-console-real-server run-mac-console-app test-mac-console-agora test-mac-console-volcengine test-mac-console-real test-ios test-android test-all report

PYTHON ?= python3
BUILD_DIR ?= .build/default
CPP_COVERAGE_BUILD_DIR ?= .build/coverage/mock
CPP_COVERAGE_LINE_THRESHOLD ?= 95.0
CPP_REAL_COVERAGE_BUILD_DIR ?= .build/coverage/agora-real
CPP_VOLCENGINE_REAL_COVERAGE_BUILD_DIR ?= .build/coverage/volcengine-real
CPP_REAL_COVERAGE_LINE_THRESHOLD ?= 95.0
PYTHON_SDK_COVERAGE_LINE_THRESHOLD ?= 95.0
MAC_CONSOLE_COVERAGE_LINE_THRESHOLD ?= 95.0
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
BEACON_AUTH_TOKEN ?= local-test-token
BEACON_CONSOLE_SERVER_PORT ?= 8000
BEACON_CONSOLE_SERVER_URL ?= http://127.0.0.1:$(BEACON_CONSOLE_SERVER_PORT)
export UV_CACHE_DIR

help:
	@echo "test-ci-selection: CI change selection regression tests"
	@echo "report-secrets / test-report-secrets: report text safety check / regression tests"
	@printf '%s\n' \
		'Targets:' \
		'  format-check      Run basic repository format checks' \
		'  sdk-facade        Regenerate typed Python SDK facades from registry artifacts' \
		'  sdk-facade-check  Check generated Python SDK facades for drift and orphans' \
		'  sdk-native-vocabulary Check generated Mac RTC event vocabularies for drift' \
		'  type-server       Run Server Python mypy type diagnostics' \
		'  coverage-e2e-mock Run Mock E2E with Server coverage diagnostics' \
		'  coverage-server   Run Server Python coverage diagnostics' \
		'  coverage-python-sdk Run Python SDK coverage diagnostics' \
		'  coverage-cpp-mock Run C++ mac mock production .cc coverage diagnostics' \
		'  coverage-cpp-agora-real Run Objective-C++ mac real backend .mm coverage diagnostics' \
		'  coverage-cpp-volcengine-real Run the Volcengine mac real backend .mm coverage diagnostics' \
		'  coverage-mac-console Run Mac Test Console Swift coverage diagnostics' \
		'  coverage-local-required Run local required 95% coverage gates' \
		'  coverage-discovery Run Server layered coverage discovery diagnostics' \
		'  coverage-real-required Run real SDK coverage gates when configured' \
		'  coverage-all      Run all coverage gates and diagnostics' \
		'  test-evidence-map Compare Mock E2E and all-test Server coverage' \
		'  test-protocol     Validate protocol examples and compile test cases' \
		'  test-agent-core   Build and run Agent Core smoke tests' \
		'  test-server       Run Python tests (Server, SDK, tools, integration)' \
		'  test-server-quiet Run Python tests with concise output and full log artifact' \
		'  test-logging      Run Agent Core logging tests' \
		'  test-mac-mock     Run Phase 3 macOS mock adapter tests' \
		'  test-e2e-mock     Run Phase 4A mock E2E tests' \
		'  test-target-mock-tracer Run isolated IR-08 Runner/Mock Agent vertical tracer' \
		'  test-mac-direct-agent-mock Run direct Mac Agent WebSocket mock smoke' \
		'  test-mac-volcengine-real Run the Volcengine real chain (native agent + L1 cases) when configured' \
		'  test-mac-zego-real Run the ZEGO Express real chain (native agent + L1 cases) when configured' \
		'  test-mac-direct-agent-agora-real Run direct Mac Agent WebSocket real Agora smoke when configured' \
		'  test-mac-agora-real Run Phase 4B macOS real SDK smoke tests when configured' \
		'  test-mac-console  Build and test the macOS Beacon Test Console' \
		'  test-mac-console-ui-smoke Build and launch the Mac Console app in interactive mode' \
		'  build-mac-console-app Build dist/BeaconMacTestConsole.app' \
		'  run-mac-console-real-server Run one local Server with Agora, Volcengine, and ZEGO real Agents' \
		'  run-mac-console-app Build and run the unified Mac Console app' \
		'  test-mac-console-agora Run App-driven macOS Agora real validation when configured' \
		'  test-mac-console-volcengine Run App-driven macOS Volcengine real validation when configured' \
		'  test-mac-console-real Run all three SDK Console cases against one Server when configured' \
		'  test-ios          Reserved for Phase 6 iOS tests' \
		'  test-android      Reserved for Phase 7 Android tests' \
		'  test-all          Run local base checks (no Console, coverage, or real SDK)' \
		'  report            Generate reports/latest/report.json'

format-check:
	@$(PYTHON) scripts/validation/format_check.py

sdk-facade:
	@$(PYTHON) scripts/generation/generate_python_sdk_facade.py

sdk-facade-check:
	@$(PYTHON) scripts/generation/generate_python_sdk_facade.py --check

sdk-native-vocabulary:
	@uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/generation/generate_rtc_event_vocabulary.py --check

type-server:
	@$(PYTHON) scripts/validation/run_mypy_reported.py --cwd server --log reports/latest/server.mypy.log --junit reports/latest/server.mypy.junit.xml -- uv run --locked --python 3.11 --extra type mypy --config-file ../mypy.ini app

target-runtime-guard:
	@$(PYTHON) scripts/validation/check_target_runtime_architecture.py

target-runtime-inventory:
	@cd server && uv run --locked --python 3.11 --extra test python ../scripts/validation/inventory_target_runtime.py

coverage-e2e-mock:
	@uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/coverage/run_e2e_coverage_reported.py --reports-dir reports/latest

coverage-server:
	@cd server && uv run --locked --python 3.11 --extra test --extra agora python ../scripts/coverage/run_coverage_reported.py --cwd . --source app --tests tests ../python_sdk/tests ../tests --reports-dir ../reports/latest

coverage-python-sdk:
	@cd server && uv run --locked --python 3.11 --extra test python ../scripts/coverage/run_python_sdk_coverage.py --reports-dir reports/latest --line-threshold $(PYTHON_SDK_COVERAGE_LINE_THRESHOLD)

coverage-cpp-mock:
	@$(PYTHON) scripts/coverage/run_cpp_mock_coverage.py --build-dir $(CPP_COVERAGE_BUILD_DIR) --reports-dir reports/latest --line-threshold $(CPP_COVERAGE_LINE_THRESHOLD)

coverage-cpp-agora-real:
	@set -a; \
		if [ -f ./local.agora.env ]; then . ./local.agora.env; fi; \
		set +a; \
		$(PYTHON) scripts/coverage/run_cpp_agora_real_coverage.py --build-dir $(CPP_REAL_COVERAGE_BUILD_DIR) --reports-dir reports/latest --line-threshold $(CPP_REAL_COVERAGE_LINE_THRESHOLD)

coverage-cpp-volcengine-real:
	@set -a; \
		if [ -f ./local.volcengine.env ]; then . ./local.volcengine.env; fi; \
		set +a; \
		$(PYTHON) scripts/coverage/run_cpp_volcengine_real_coverage.py --build-dir $(CPP_VOLCENGINE_REAL_COVERAGE_BUILD_DIR) --reports-dir reports/latest --line-threshold $(CPP_REAL_COVERAGE_LINE_THRESHOLD)

coverage-mac-console:
	@$(PYTHON) scripts/coverage/run_mac_console_coverage.py --reports-dir reports/latest --line-threshold $(MAC_CONSOLE_COVERAGE_LINE_THRESHOLD)

coverage-local-required: coverage-python-sdk coverage-cpp-mock coverage-mac-console

coverage-discovery: coverage-e2e-mock coverage-server test-evidence-map

coverage-real-required: coverage-cpp-agora-real coverage-cpp-volcengine-real

coverage-all: coverage-local-required coverage-discovery coverage-real-required

test-evidence-map:
	@$(PYTHON) scripts/coverage/build_test_evidence_map.py --e2e reports/latest/server.e2e-mock.coverage.json --all reports/latest/server.coverage.json --output reports/latest/server.test-evidence-map.json --pretty

test-protocol:
	@uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/generation/compile_test_cases.py

test-agent-core:
	@{ cmake -S . -B $(BUILD_DIR) && cmake --build $(BUILD_DIR) && ctest --test-dir $(BUILD_DIR) -R '^UT-' -E '^UT-LOG' --no-tests=error --output-on-failure; } || { $(PYTHON) scripts/support/write_junit.py reports/latest/agent_core.junit.xml UT-P0-AGENT failed; $(PYTHON) scripts/support/generate_report.py failed UT-P0-AGENT agent-core-smoke; exit 1; }
	@$(PYTHON) scripts/support/write_junit.py reports/latest/agent_core.junit.xml UT-P0-AGENT passed
	@$(PYTHON) scripts/support/generate_report.py passed UT-P0-AGENT agent-core-smoke

pytest-declaration-check:
	@$(PYTHON) scripts/validation/check_pytest_test_declarations.py --self-test server/tests
	@$(PYTHON) scripts/validation/check_pytest_test_declarations.py python_sdk/tests
	@$(PYTHON) scripts/validation/check_pytest_test_declarations.py tests

test-server: pytest-declaration-check
	@cd server && uv run --locked --python 3.11 --extra test --extra agora pytest tests ../python_sdk/tests ../tests --junitxml ../reports/latest/server.junit.xml || (cd .. && $(PYTHON) scripts/support/generate_report.py failed IT-SRV-PHASE1 pytest && exit 1)
	@$(PYTHON) scripts/support/generate_report.py passed IT-SRV-PHASE1 server-phase1

test-server-quiet: pytest-declaration-check
	@$(PYTHON) scripts/validation/run_pytest_reported.py --cwd server --log reports/latest/server.pytest.log --name "Python tests" -- uv run --locked --python 3.11 --extra test --extra agora pytest --tb=short --disable-warnings tests ../python_sdk/tests ../tests --junitxml ../reports/latest/server.junit.xml || ($(PYTHON) scripts/support/generate_report.py failed IT-SRV-PHASE1 pytest && exit 1)
	@$(PYTHON) scripts/support/generate_report.py passed IT-SRV-PHASE1 server-phase1

test-logging:
	@{ cmake -S . -B $(BUILD_DIR) && cmake --build $(BUILD_DIR) && ctest --test-dir $(BUILD_DIR) -R '^UT-LOG' --no-tests=error --output-on-failure; } || { $(PYTHON) scripts/support/write_junit.py reports/latest/logging.junit.xml UT-LOG failed; $(PYTHON) scripts/support/generate_report.py failed UT-LOG logging-smoke; exit 1; }
	@$(PYTHON) scripts/support/write_junit.py reports/latest/logging.junit.xml UT-LOG passed
	@$(PYTHON) scripts/support/generate_report.py passed UT-LOG logging-smoke

test-mac-mock:
	@{ cmake -S . -B $(BUILD_DIR) && cmake --build $(BUILD_DIR) --target mac_mock_adapter_test mac_mock_volcengine_test mac_mock_demo && ctest --test-dir $(BUILD_DIR) -R 'BUILD-MAC|BRIDGE-MAC|FI-NETWORK-CONDITION' -E '(^|-)REAL(-|$)' --no-tests=error --output-on-failure --output-junit $(CURDIR)/reports/latest/mac_mock.junit.xml; } || { $(PYTHON) scripts/support/write_junit.py reports/latest/mac_mock.junit.xml BUILD-MAC failed; $(PYTHON) scripts/support/generate_report.py failed BUILD-MAC mac-mock; exit 1; }
	@$(PYTHON) scripts/support/generate_report.py passed BUILD-MAC mac-mock

test-e2e-mock:
	@uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_e2e_mock_tests.py

test-target-mock-tracer:
	@uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_target_mock_tracer.py

test-mac-direct-agent-mock:
	@uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_mac_direct_agent_mock.py

test-mac-volcengine-real:
	@set -a; \
		if [ -f ./local.volcengine.env ]; then . ./local.volcengine.env; fi; \
		set +a; \
		uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_mac_volcengine_real.py

test-mac-zego-real:
	@set -a; \
		if [ -f ./local.agora.env ]; then . ./local.agora.env; fi; \
		set +a; \
		DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
		uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_mac_zego_real.py

test-mac-direct-agent-agora-real:
	@set -a; \
		if [ -f ./local.agora.env ]; then . ./local.agora.env; fi; \
		BEACON_AUTH_TOKEN="$(BEACON_AUTH_TOKEN)"; \
		set +a; \
		uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_mac_direct_agent_agora_real.py

test-mac-agora-real:
	@set -a; \
		if [ -f ./local.agora.env ]; then . ./local.agora.env; fi; \
		set +a; \
		uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_mac_agora_e2e_tests.py

test-mac-console:
	@swift test --package-path apps/mac_test_console
	@swift build --package-path apps/mac_test_console

test-mac-console-ui-smoke:
	@$(PYTHON) scripts/validation/run_mac_console_ui_smoke.py

build-mac-console-app:
	@sh scripts/dev/build_mac_console_app.sh

run-mac-console-real-server:
	@set -a; \
		if [ -f ./local.agora.env ]; then . ./local.agora.env; fi; \
		BEACON_UNIFIED_AUTH_TOKEN="$$BEACON_AUTH_TOKEN"; \
		if [ -f ./local.volcengine.env ]; then . ./local.volcengine.env; fi; \
		if [ -n "$$BEACON_UNIFIED_AUTH_TOKEN" ] && [ "$$BEACON_UNIFIED_AUTH_TOKEN" != "$$BEACON_AUTH_TOKEN" ]; then \
			echo 'local.agora.env and local.volcengine.env must use the same BEACON_AUTH_TOKEN for one Server' >&2; exit 2; \
		fi; \
		unset BEACON_UNIFIED_AUTH_TOKEN; \
		set +a; \
		DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
		uv run --project server --locked --python 3.11 --extra test --extra agora -- python scripts/dev/run_mac_console_real_server.py

run-mac-console-app: build-mac-console-app
	@set -a; \
		if [ -f ./local.agora.env ]; then . ./local.agora.env; fi; \
		if [ -f ./local.volcengine.env ]; then . ./local.volcengine.env; fi; \
		BEACON_CONSOLE_SERVER_URL="$(BEACON_CONSOLE_SERVER_URL)"; \
		BEACON_AUTH_TOKEN="$${BEACON_AUTH_TOKEN:-$(BEACON_AUTH_TOKEN)}"; \
		BEACON_NODE_ID="$${BEACON_NODE_ID:-mac-real-e2e-001}"; \
		BEACON_CONSOLE_SDK_ROUTES="$${BEACON_CONSOLE_SDK_ROUTES:-agora_rtc=$(BEACON_CONSOLE_SERVER_URL)#mac-real-e2e-001,volcengine_rtc=$(BEACON_CONSOLE_SERVER_URL)#mac-volcengine-real-001,zego_express=$(BEACON_CONSOLE_SERVER_URL)#mac-zego-real-001}"; \
		set +a; \
		dist/BeaconMacTestConsole.app/Contents/MacOS/BeaconMacTestConsole

test-mac-console-agora:
	@set -a; \
		if [ -f ./local.agora.env ]; then . ./local.agora.env; fi; \
		set +a; \
		uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_mac_console_agora_validation.py

test-mac-console-volcengine:
	@set -a; \
		if [ -f ./local.volcengine.env ]; then . ./local.volcengine.env; fi; \
		set +a; \
		uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_mac_console_volcengine_validation.py

test-mac-console-real:
	@set -a; \
		if [ -f ./local.agora.env ]; then . ./local.agora.env; fi; \
		BEACON_REAL_AGORA_AUTH_TOKEN="$$BEACON_AUTH_TOKEN"; \
		if [ -f ./local.volcengine.env ]; then . ./local.volcengine.env; fi; \
		if [ -n "$$BEACON_REAL_AGORA_AUTH_TOKEN" ] && [ "$$BEACON_REAL_AGORA_AUTH_TOKEN" != "$$BEACON_AUTH_TOKEN" ]; then \
			echo 'local.agora.env and local.volcengine.env must use the same BEACON_AUTH_TOKEN for one Server' >&2; exit 2; \
		fi; \
		unset BEACON_REAL_AGORA_AUTH_TOKEN; \
		set +a; \
		DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
		uv run --project server --locked --python 3.11 --extra test --extra agora python scripts/validation/run_mac_console_real_validation.py

test-ios test-android:
	@$(PYTHON) scripts/support/generate_report.py skipped $@ reserved

test-all: format-check type-server test-protocol test-agent-core test-logging test-server test-mac-mock test-e2e-mock report

report-secrets:
	$(PYTHON) scripts/validation/scan_report_secrets.py

test-ci-selection:
	$(PYTHON) tests/tooling/test_select_ci_checks.py

test-report-secrets:
	$(PYTHON) tests/tooling/test_scan_report_secrets.py

report:
	@$(PYTHON) scripts/support/generate_report.py passed P1-REPORT generate-report
