import Foundation
import XCTest
@testable import BeaconMacTestConsole

@MainActor
final class ConsoleViewModelTests: XCTestCase {
    func testCasesAreGroupedBySuite() {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            TestCaseSummary(caseID: "TC-1", name: "One", platform: "mac", suite: "Smoke", tags: []),
            TestCaseSummary(caseID: "TC-2", name: "Two", platform: "mac", suite: "Callback", tags: []),
            TestCaseSummary(caseID: "TC-3", name: "Three", platform: "mac", suite: "Smoke", tags: []),
        ]

        XCTAssertEqual(viewModel.suites.map(\.name), ["Callback", "Smoke"])
        XCTAssertEqual(viewModel.cases(in: "Smoke").map(\.caseID), ["TC-1", "TC-3"])
    }

    func testSelectsFirstSDKAfterLoad() {
        let viewModel = ConsoleViewModel()
        viewModel.sdkCapabilities = [
            SDKCapability(sdk: "agora_rtc", interfaces: []),
            SDKCapability(sdk: "other_sdk", interfaces: []),
        ]
        viewModel.selectDefaultSDK()

        XCTAssertEqual(viewModel.selectedSDK?.sdk, "agora_rtc")
    }

    func testCatalogReloadKeepsExplicitAvailableSDKSelection() {
        let viewModel = ConsoleViewModel()
        let agora = SDKCapability(sdk: "agora_rtc", interfaces: [])
        let volcengine = SDKCapability(sdk: "volcengine_rtc", interfaces: [])
        let zego = SDKCapability(sdk: "zego_express", interfaces: [])
        viewModel.sdkCapabilities = [agora, volcengine, zego]

        viewModel.selectSDK(volcengine)
        viewModel.selectDefaultSDK()

        XCTAssertEqual(viewModel.selectedSDK?.sdk, "volcengine_rtc")
    }

    func testCasesAreFilteredBySelectedSDK() {
        let viewModel = ConsoleViewModel()
        let agora = SDKCapability(sdk: "agora_rtc", interfaces: [])
        let other = SDKCapability(sdk: "other_sdk", interfaces: [])
        viewModel.sdkCapabilities = [agora, other]
        viewModel.testCases = [
            makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-OTHER-1", suite: "other", sdk: "other_sdk"),
        ]

        viewModel.selectSDK(agora)

        XCTAssertEqual(viewModel.suites.map(\.name), ["rtc"])
        XCTAssertEqual(viewModel.cases(in: "rtc").map(\.caseID), ["TC-AGORA-1"])
    }

    func testSelectingSDKResetsSuiteAndCaseToAvailableCase() {
        let viewModel = ConsoleViewModel()
        let agora = SDKCapability(sdk: "agora_rtc", interfaces: [])
        let other = SDKCapability(sdk: "other_sdk", interfaces: [])
        viewModel.testCases = [
            makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-OTHER-1", suite: "other", sdk: "other_sdk"),
        ]
        viewModel.selectSDK(agora)
        viewModel.selectSuite(TestSuiteSummary(name: "rtc", count: 1))

        viewModel.selectSDK(other)

        XCTAssertEqual(viewModel.selectedSuite, "other")
        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-OTHER-1")
    }

    func testSelectingDifferentCaseClearsDisplayedRunState() {
        let viewModel = ConsoleViewModel()
        let firstCase = makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc")
        let secondCase = makeCase(caseID: "TC-AGORA-2", suite: "rtc", sdk: "agora_rtc")
        viewModel.selectedCase = firstCase
        viewModel.currentRun = RunResponse(runID: "run-1", status: "passed", stepResults: [])
        viewModel.currentRunDetail = ConsoleRunDetail(
            run: RunResponse(runID: "run-1", status: "passed", stepResults: []),
            report: ReportSummary(runID: "run-1", format: "json", summary: ["passed": .int(1)]),
            logs: [["message": .string("old log")]]
        )
        viewModel.logRows = [LogRow(level: "info", message: "old log", nodeID: "mac-1")]
        viewModel.logFilter = "old"
        viewModel.logLevelFilter = .error
        viewModel.logStepFilter = "old-step"
        viewModel.showsLifecycleLogs = true

        viewModel.selectCase(secondCase)

        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-AGORA-2")
        XCTAssertNil(viewModel.currentRun)
        XCTAssertNil(viewModel.currentRunDetail)
        XCTAssertEqual(viewModel.logRows, [])
        XCTAssertEqual(viewModel.logFilter, "")
        XCTAssertEqual(viewModel.logLevelFilter, .all)
        XCTAssertNil(viewModel.logStepFilter)
        XCTAssertFalse(viewModel.showsLifecycleLogs)
    }

    func testSelectingSameCaseKeepsDisplayedRunState() {
        let viewModel = ConsoleViewModel()
        let testCase = makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc")
        let run = RunResponse(runID: "run-1", status: "passed", stepResults: [])
        viewModel.selectedCase = testCase
        viewModel.currentRun = run

        viewModel.selectCase(testCase)

        XCTAssertEqual(viewModel.currentRun?.runID, "run-1")
    }

    func testReselectingCaseRestoresItsSessionRunDetail() async throws {
        let viewModel = ConsoleViewModel()
        let firstCase = makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc")
        let secondCase = makeCase(caseID: "TC-AGORA-2", suite: "rtc", sdk: "agora_rtc")
        viewModel.testCases = [firstCase, secondCase]
        viewModel.selectedCase = firstCase
        let session = makeStubSession(responses: [
            createRunJSON(runID: "run-1", status: "passed"),
            #"""
            {"run":{"run_id":"run-1","status":"passed","results":[
              {"case_id":"TC-AGORA-1","step_id":"step-1","status":"passed","artifacts":[],"duration_ms":120}]},
             "report":{"run_id":"run-1","format":"json","summary":{"passed":1}},
             "logs":[{"level":"info","message":"join ok","node_id":"mac-1","event":"case_completed","step_id":"step-1"}]}
            """#,
        ])
        let client = makeClient(session: session)

        await viewModel.runSelectedCase(client: client, nodeID: nil)

        viewModel.selectCase(secondCase)

        XCTAssertNil(viewModel.currentRun)
        XCTAssertNil(viewModel.currentRunDetail)
        XCTAssertEqual(viewModel.logRows, [])

        viewModel.selectCase(firstCase)

        // 切回已跑过的 case：run、报告与日志都从会话内 detail 缓存恢复，且不需要重新请求 server。
        XCTAssertEqual(viewModel.currentRun?.runID, "run-1")
        XCTAssertEqual(viewModel.currentRunDetail?.report.summary["passed"], .int(1))
        XCTAssertEqual(viewModel.logRows.map(\.message), ["join ok"])
        XCTAssertEqual(viewModel.logRows.first?.stepID, "step-1")
        // 恢复不产生新的 HTTP 请求：本用例只配了 createRun 与首次 detail 两条响应。
        XCTAssertEqual(URLProtocolSequenceStub.requests.count, 2)
        // 列表状态点与详情来自同一份缓存，不再出现「列表有状态点、详情区却是空的」。
        XCTAssertEqual(viewModel.caseResults["TC-AGORA-1"]?.runID, "run-1")
        XCTAssertEqual(viewModel.runResult(for: "TC-AGORA-1")?.runID, "run-1")
        XCTAssertNil(viewModel.runResult(for: "TC-AGORA-2"))
    }

    func testOpenCancelledTargetRunShowsObservationWithoutLegacySteps() async throws {
        let viewModel = ConsoleViewModel()
        let session = makePathStubSession(responses: [
            "/api/v1/console/test-runs/run-target": #"""
            {"run":{"run_id":"run-target","status":"cancelled","execution_mode":"target",
                    "results":[],"cases":[{"case_id":"case-target"}]},
             "report":{"run_id":"run-target","format":"json","summary":{"status":"cancelled"}},
             "logs":[],"observation_cursor_enabled":true}
            """#,
            "/api/v1/test-runs/run-target/observations": #"""
            {"items":[{"observation_id":"call-1","cursor":1,"kind":"operation","case_id":"case-target",
                       "device_role":"primary","target":{"sdk":"mock","interface":"echo","function":"apply"},
                       "payload":{"operation_type":"call","outcome":"succeeded"}}],
             "next_cursor":1,"has_more":false}
            """#,
        ])

        await viewModel.openRun(client: makeClient(session: session), runID: "run-target")

        XCTAssertEqual(viewModel.currentRun?.status, "cancelled")
        XCTAssertEqual(viewModel.currentObservations.map(\.title), ["call · apply"])
        XCTAssertEqual(viewModel.caseResults["case-target"]?.runID, "run-target")
        XCTAssertNil(viewModel.observationError)
    }

    func testSelectingNoCaseKeepsSessionResultsWithoutRestoringDisplay() async throws {
        let viewModel = ConsoleViewModel()
        let testCase = makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc")
        viewModel.testCases = [testCase]
        viewModel.selectedCase = testCase
        let session = makeStubSession(responses: [
            createRunJSON(runID: "run-1", status: "passed"),
            runDetailJSON(runID: "run-1", status: "passed", caseID: "TC-AGORA-1", durationMs: 120),
        ])
        let client = makeClient(session: session)

        await viewModel.runSelectedCase(client: client, nodeID: nil)

        viewModel.selectCase(nil)

        XCTAssertNil(viewModel.selectedCase)
        XCTAssertNil(viewModel.currentRunDetail)
        XCTAssertEqual(viewModel.logRows, [])
        // 取消选中只清展示位，会话结果仍留给列表状态点。
        XCTAssertEqual(viewModel.caseResults["TC-AGORA-1"]?.status, "passed")
    }

    func testLoadKeepsOnlyRealMacVendorSDKsAndCasesFromConsoleAPIs() async throws {
        let viewModel = ConsoleViewModel()
        let session = makePathStubSession(responses: [
            "/api/v1/console/sdk-capabilities": #"""
            {"sdks":[{"sdk":"agora_rtc","interfaces":[]},{"sdk":"volcengine_rtc","interfaces":[]},{"sdk":"zego_express","interfaces":[]},{"sdk":"other_sdk","interfaces":[]}]}
            """#,
            "/api/v1/console/test-cases": #"""
            {"cases":[
              {
                "case_id":"TC-OTHER-1",
                "name":"Other",
                "platform":"mac",
                "suite":"other",
                "tags":[],
                "covered_capabilities":[],
                "scenario_family":"direct_call",
                "implementation_status":"runnable",
                "requires_runtime_isolation":false,
                "steps":[{"target":{"sdk":"other_sdk"}}]
              },
              {
                "case_id":"TC-AGORA-1",
                "name":"Agora",
                "platform":"mac",
                "suite":"rtc",
                "tags":[],
                "covered_capabilities":["join_success_fact"],
                "scenario_family":"direct_call",
                "implementation_status":"runnable",
                "requires_runtime_isolation":true,
                "steps":[{"target":{"sdk":"agora_rtc"}}]
              },
              {
                "case_id":"TC-VOLCENGINE-1",
                "name":"Volcengine",
                "platform":"mac",
                "suite":"rtc",
                "tags":[],
                "covered_capabilities":[],
                "scenario_family":"direct_call",
                "implementation_status":"runnable",
                "requires_runtime_isolation":true,
                "steps":[{"target":{"sdk":"volcengine_rtc"}}]
              },
              {
                "case_id":"TC-ZEGO-1",
                "name":"ZEGO",
                "platform":"mac",
                "suite":"rtc",
                "tags":[],
                "covered_capabilities":[],
                "scenario_family":"direct_call",
                "implementation_status":"runnable",
                "requires_runtime_isolation":true,
                "steps":[{"target":{"sdk":"zego_express"}}]
              },
              {
                "case_id":"TC-SYSTEM-1",
                "name":"System",
                "platform":"server",
                "suite":"system",
                "tags":[],
                "covered_capabilities":[],
                "scenario_family":"direct_call",
                "implementation_status":"runnable",
                "requires_runtime_isolation":false,
                "steps":[{"target":{"sdk":"agora_rtc"}}]
              }
            ]}
            """#,
        ])
        let client = BeaconServerClient(baseURL: URL(string: "http://127.0.0.1:8000")!, token: "token-1", session: session)

        let loadResult = await viewModel.load(client: client)

        XCTAssertEqual(loadResult, .loaded(caseCount: 3))
        XCTAssertNil(viewModel.errorMessage)
        XCTAssertEqual(viewModel.sdkCapabilities.map(\.sdk), ["agora_rtc", "volcengine_rtc", "zego_express"])
        XCTAssertEqual(viewModel.testCases.map(\.caseID), ["TC-AGORA-1", "TC-VOLCENGINE-1", "TC-ZEGO-1"])
        XCTAssertEqual(viewModel.testCases.first { $0.caseID == "TC-AGORA-1" }?.requiresRuntimeIsolation, true)
        XCTAssertEqual(viewModel.testCases.first { $0.caseID == "TC-VOLCENGINE-1" }?.requiresRuntimeIsolation, true)
        XCTAssertEqual(viewModel.testCases.first { $0.caseID == "TC-ZEGO-1" }?.requiresRuntimeIsolation, true)
        XCTAssertEqual(viewModel.selectedSDK?.sdk, "agora_rtc")
        XCTAssertEqual(viewModel.selectedSuite, "rtc")
        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-AGORA-1")
    }

    func testLoadSurfacesConsoleAPIFailure() async throws {
        let viewModel = ConsoleViewModel()
        let session = makePathStubSession(
            responses: [
                "/api/v1/console/sdk-capabilities": #"{"detail":"missing token"}"#,
                "/api/v1/console/test-cases": #"{"cases":[]}"#,
            ],
            statusCodes: ["/api/v1/console/sdk-capabilities": 401]
        )
        let client = BeaconServerClient(baseURL: URL(string: "http://127.0.0.1:8000")!, token: "bad-token", session: session)

        let loadResult = await viewModel.load(client: client)

        XCTAssertEqual(loadResult, .failed(message: "HTTP 401: auth token is missing or invalid"))
        XCTAssertTrue(viewModel.sdkCapabilities.isEmpty)
        XCTAssertTrue(viewModel.testCases.isEmpty)
        XCTAssertEqual(viewModel.errorMessage, "HTTP 401: auth token is missing or invalid")
    }

    func testLoadRunHistoryKeepsServerOrderAndLeavesDisplayedRunStateAlone() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.currentRun = RunResponse(runID: "run-displayed", status: "passed", stepResults: [])
        let session = makePathStubSession(responses: [
            "/api/v1/console/test-runs": #"""
            {"runs":[
              {"run_id":"run-new","status":"running","case_ids":["TC-AGORA-1"],"created_at_ms":300,"finished_at_ms":null,"duration_ms":null},
              {"run_id":"run-old","status":"passed","case_ids":["TC-AGORA-1"],"created_at_ms":100,"finished_at_ms":150,"duration_ms":50}
            ]}
            """#
        ])
        let client = makeClient(session: session)

        await viewModel.loadRunHistory(client: client)

        XCTAssertNil(viewModel.errorMessage)
        // 倒序是 server 契约：console 不再排序，sheet 展示顺序就是 server 给的事实顺序。
        XCTAssertEqual(viewModel.runHistory.map(\.runID), ["run-new", "run-old"])
        XCTAssertNil(viewModel.runHistory[0].durationMs)
        XCTAssertFalse(viewModel.runHistory[0].isTerminal)
        XCTAssertEqual(viewModel.runHistory[1].finishedAtMs, 150)
        XCTAssertTrue(viewModel.runHistory[1].isTerminal)
        // 打开 History 只读列表，不能顺带清掉详情区正在看的 run。
        XCTAssertEqual(viewModel.currentRun?.runID, "run-displayed")
        let request = try XCTUnwrap(URLProtocolPathStub.requests.first)
        XCTAssertEqual(request.url?.query, "limit=50")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
    }

    func testLoadRunHistoryClearsPreviousConnectionEntriesWhenCredentialsChange() async throws {
        let viewModel = ConsoleViewModel()
        let loadedSession = makePathStubSession(responses: [
            "/api/v1/console/test-runs": #"""
            {"runs":[{"run_id":"run-old","status":"passed","case_ids":["TC-AGORA-1"],"created_at_ms":100,"finished_at_ms":150,"duration_ms":50}]}
            """#
        ])
        await viewModel.loadRunHistory(client: makeClient(session: loadedSession))
        XCTAssertEqual(viewModel.runHistory.map(\.runID), ["run-old"])

        // 凭证改变后，旧连接的历史不属于新连接；请求失败也不能保留旧条目。
        let failingSession = makePathStubSession(
            responses: ["/api/v1/console/test-runs": #"{"detail":"missing token"}"#],
            statusCodes: ["/api/v1/console/test-runs": 401]
        )
        await viewModel.loadRunHistory(client: makeClient(session: failingSession, token: "bad-token"), limit: 5)

        XCTAssertEqual(viewModel.errorMessage, "HTTP 401: auth token is missing or invalid")
        XCTAssertTrue(viewModel.runHistory.isEmpty)
        XCTAssertEqual(URLProtocolPathStub.requests.last?.url?.query, "limit=5")
    }

    func testCanCancelRunCoversInFlightCreateRunAndNonTerminalDisplayedRun() {
        let viewModel = ConsoleViewModel()
        XCTAssertFalse(viewModel.canCancelRun)

        // createRun 在整个执行期间挂着 HTTP 请求：此时 currentRun 还是上一个终态 run，
        // 创建响应未返回时也必须保留 Cancel 入口。
        viewModel.currentRun = RunResponse(runID: "run-previous", status: "passed", stepResults: [])
        XCTAssertFalse(viewModel.canCancelRun)
        viewModel.isRunning = true
        XCTAssertTrue(viewModel.canCancelRun)

        viewModel.isRunning = false
        viewModel.currentRun = RunResponse(runID: "run-active", status: "running", stepResults: [])
        XCTAssertTrue(viewModel.canCancelRun)

        viewModel.currentRun = RunResponse(runID: "run-active", status: "cancelled", stepResults: [])
        XCTAssertFalse(viewModel.canCancelRun)
    }

    func testCancelCurrentRunTargetsDisplayedNonTerminalRunWithoutInventingTerminalStatus() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.currentRun = RunResponse(runID: "run-displayed", status: "running", stepResults: [])
        let session = makePathStubSession(responses: [
            "/api/v1/test-runs/run-displayed/cancel": createRunJSON(runID: "run-displayed", status: "running"),
            "/api/v1/console/test-runs/run-displayed": runDetailJSON(
                runID: "run-displayed",
                status: "cancelled",
                caseID: "TC-AGORA-1"
            ),
        ])

        await viewModel.cancelCurrentRun(client: makeClient(session: session))
        viewModel.stopRunDetailPolling()

        XCTAssertNil(viewModel.errorMessage)
        let requests = URLProtocolPathStub.requests
        XCTAssertEqual(requests.compactMap(\.url?.path), [
            "/api/v1/test-runs/run-displayed/cancel",
            "/api/v1/console/test-runs/run-displayed",
        ])
        let cancelRequest = try XCTUnwrap(requests.first)
        XCTAssertEqual(cancelRequest.httpMethod, "POST")
        XCTAssertEqual(cancelRequest.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
        XCTAssertNil(cancelRequest.value(forHTTPHeaderField: "Content-Type"))
        XCTAssertNil(httpBodyData(for: cancelRequest))
        // 已知 runID 就不回查历史；终态来自 server 的详情刷新，不是 console 本地伪造。
        XCTAssertEqual(viewModel.currentRun?.status, "cancelled")
    }

    func testCancelCurrentRunSurfacesMissingTargetAndRequestFailure() async throws {
        let viewModel = ConsoleViewModel()
        let emptySession = makePathStubSession(responses: ["/api/v1/console/test-runs": #"{"runs":[]}"#])

        await viewModel.cancelCurrentRun(client: makeClient(session: emptySession))

        // 取消目标缺失必须写成可见错误，不能静默当作成功。
        XCTAssertEqual(viewModel.errorMessage, ConsoleViewModel.cancelRunUnavailableText)
        XCTAssertFalse(URLProtocolPathStub.requests.contains { $0.url?.path.hasSuffix("/cancel") ?? false })

        viewModel.errorMessage = nil
        viewModel.currentRun = RunResponse(runID: "run-missing", status: "running", stepResults: [])
        let failingSession = makePathStubSession(
            responses: ["/api/v1/test-runs/run-missing/cancel": #"{"detail":"run not found"}"#],
            statusCodes: ["/api/v1/test-runs/run-missing/cancel": 404]
        )

        await viewModel.cancelCurrentRun(client: makeClient(session: failingSession))

        XCTAssertEqual(viewModel.errorMessage, #"HTTP 404: server request failed: {"detail":"run not found"}"#)
        XCTAssertEqual(viewModel.currentRun?.status, "running")
    }

    func testLoadReadinessCollectsThreeSectionsIndependently() async throws {
        let viewModel = ConsoleViewModel()
        let session = makePathStubSession(responses: [
            "/api/v1/status": #"{"service":"beacon-server","status":"ok","version":"0.1.0-p0"}"#,
            "/api/v1/devices": #"""
            {"devices":[
              {"node_id":"mac-local-001","platform":"macos","group_id":"g","tags":["t"],
               "capabilities":["rtc"],"status":"online","last_seen_ms":1700000000000},
              {"node_id":"mac-real-001","platform":"macos","status":"online","last_seen_ms":1700000000000}
            ]}
            """#,
            "/api/v1/console/sdk-capabilities": #"""
            {"sdks":[{"sdk":"agora_rtc","interfaces":[{"interface":"core","methods":[],"callbacks":[],"metrics":[],"states":[]}]}]}
            """#,
        ])

        await viewModel.loadReadiness(client: makeClient(session: session))

        XCTAssertNil(viewModel.errorMessage)
        XCTAssertEqual(viewModel.readiness.serverStatus?.version, "0.1.0-p0")
        XCTAssertNil(viewModel.readiness.serverError)
        XCTAssertEqual(viewModel.readiness.devices.map(\.nodeID), ["mac-local-001", "mac-real-001"])
        XCTAssertNil(viewModel.readiness.devicesError)
        XCTAssertEqual(viewModel.readiness.sdkCapabilities.map(\.sdk), ["agora_rtc"])
        XCTAssertNil(viewModel.readiness.capabilitiesError)

        // 三段并发拉取，顺序不确定，因此按集合断言。
        let paths = Set(URLProtocolPathStub.requests.compactMap(\.url?.path))
        XCTAssertEqual(paths, ["/api/v1/status", "/api/v1/devices", "/api/v1/console/sdk-capabilities"])
        // 探活端点无鉴权，另两个带鉴权：就绪度面板要能区分「server 可达」与「读得到事实」。
        let statusRequest = try XCTUnwrap(URLProtocolPathStub.requests.first { $0.url?.path == "/api/v1/status" })
        XCTAssertNil(statusRequest.value(forHTTPHeaderField: "Authorization"))
        let devicesRequest = try XCTUnwrap(URLProtocolPathStub.requests.first { $0.url?.path == "/api/v1/devices" })
        XCTAssertEqual(devicesRequest.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
    }

    func testLoadReadinessKeepsSectionFailureOutOfDetailError() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.errorMessage = "previous run failure"
        // token 错误的典型组合：无鉴权探活成功，两个带鉴权端点 401。
        let session = makePathStubSession(
            responses: [
                "/api/v1/status": #"{"service":"beacon-server","status":"ok","version":"0.1.0-p0"}"#,
                "/api/v1/devices": #"{"detail":"missing token"}"#,
                "/api/v1/console/sdk-capabilities": #"{"detail":"missing token"}"#,
            ],
            statusCodes: ["/api/v1/devices": 401, "/api/v1/console/sdk-capabilities": 401]
        )

        await viewModel.loadReadiness(client: makeClient(session: session, token: "bad-token"))

        // 段级失败就地留在快照里由 popover 展示，不覆盖详情区属于当前 run 的排查文本。
        XCTAssertEqual(viewModel.errorMessage, "previous run failure")
        XCTAssertEqual(viewModel.readiness.serverStatus?.status, "ok")
        XCTAssertNil(viewModel.readiness.serverError)
        XCTAssertEqual(viewModel.readiness.devicesError, "HTTP 401: auth token is missing or invalid")
        XCTAssertTrue(viewModel.readiness.devices.isEmpty)
        XCTAssertEqual(viewModel.readiness.capabilitiesError, "HTTP 401: auth token is missing or invalid")
        XCTAssertTrue(viewModel.readiness.sdkCapabilities.isEmpty)
    }

    func testLoadReadinessReplacesStaleSnapshotWhenEverySectionFails() async throws {
        let viewModel = ConsoleViewModel()
        let healthySession = makePathStubSession(responses: [
            "/api/v1/status": #"{"service":"beacon-server","status":"ok","version":"0.1.0-p0"}"#,
            "/api/v1/devices": #"{"devices":[{"node_id":"mac-local-001","platform":"macos","status":"online","last_seen_ms":1}]}"#,
            "/api/v1/console/sdk-capabilities": #"{"sdks":[{"sdk":"agora_rtc","interfaces":[]}]}"#,
        ])
        await viewModel.loadReadiness(client: makeClient(session: healthySession))
        XCTAssertEqual(viewModel.readiness.devices.map(\.nodeID), ["mac-local-001"])

        // server 关停后再开面板：上一次的事实必须整体消失，否则会把陈旧在线状态当成当前就绪度。
        let failingSession = makePathStubSession(
            responses: [
                "/api/v1/status": #"{"detail":"unavailable"}"#,
                "/api/v1/devices": #"{"detail":"unavailable"}"#,
                "/api/v1/console/sdk-capabilities": #"{"detail":"unavailable"}"#,
            ],
            statusCodes: ["/api/v1/status": 500, "/api/v1/devices": 500, "/api/v1/console/sdk-capabilities": 500]
        )
        await viewModel.loadReadiness(client: makeClient(session: failingSession))

        XCTAssertNil(viewModel.readiness.serverStatus)
        XCTAssertNotNil(viewModel.readiness.serverError)
        XCTAssertTrue(viewModel.readiness.devices.isEmpty)
        XCTAssertNotNil(viewModel.readiness.devicesError)
        XCTAssertTrue(viewModel.readiness.sdkCapabilities.isEmpty)
        XCTAssertNotNil(viewModel.readiness.capabilitiesError)
    }

    func testLogFilteringMatchesLevelAndKeyword() {
        let viewModel = ConsoleViewModel()
        viewModel.logRows = [
            LogRow(level: "info", message: "join ok", nodeID: "mac-1"),
            LogRow(level: "error", message: "callback timeout", nodeID: "mac-1"),
        ]
        viewModel.logFilter = "timeout"

        XCTAssertEqual(viewModel.filteredLogs.map(\.message), ["callback timeout"])
    }

    func testUpdateLogsDropsRunDetailPollingNoiseAndMarksKeyEvents() {
        let viewModel = ConsoleViewModel()
        let detail = ConsoleRunDetail(
            run: RunResponse(runID: "run-1", status: "passed", stepResults: []),
            report: ReportSummary(runID: "run-1", format: "json", summary: ["passed": .int(1)]),
            logs: [
                [
                    "level": .string("info"),
                    "node_id": .string("beacon-server"),
                    "event": .string("console.run_detail.requested"),
                    "message": .string("console requested run detail and report projection"),
                ],
                [
                    "level": .string("info"),
                    "node_id": .string("mac-1"),
                    "event": .string("sdk_call_completed"),
                    "message": .string("joinChannel returned"),
                    "step_id": .string("join-step"),
                ],
                [
                    "level": .string("info"),
                    "node_id": .string("mac-1"),
                    "event": .string("debug_trace"),
                    "message": .string("verbose trace"),
                ],
                [
                    "level": .string("info"),
                    "node_id": .string("beacon-server"),
                    "event": .string("native.runtime_reset.completed"),
                    "message": .string("agent runtime session reset completed"),
                ],
            ]
        )

        viewModel.updateLogs(from: detail)

        XCTAssertEqual(
            viewModel.logRows.map(\.message),
            ["joinChannel returned", "verbose trace", "agent runtime session reset completed"]
        )
        // runtime_reset 是隔离 case 的常规动作，不再作为 Key Events 展示。
        XCTAssertEqual(viewModel.keyLogRows.map(\.message), ["joinChannel returned"])
        XCTAssertFalse(viewModel.logRows[2].isKeyEvent)
        XCTAssertFalse(viewModel.logRows[2].isServerLifecycle)
    }

    func testUpdateLogsCapturesTimestampModuleAndStepID() {
        let viewModel = ConsoleViewModel()
        let detail = ConsoleRunDetail(
            run: RunResponse(runID: "run-1", status: "failed", stepResults: []),
            report: ReportSummary(runID: "run-1", format: "json", summary: ["failed": .int(1)]),
            logs: [
                [
                    "level": .string("error"),
                    "node_id": .string("mac-1"),
                    "event": .string("assertion_failed"),
                    "message": .string("joinChannel failed"),
                    "module": .string("beacon.server.test_runtime"),
                    "step_id": .string("join"),
                    "timestamp_ms": .int(1_720_000_000_000),
                ]
            ]
        )

        viewModel.updateLogs(from: detail)

        let row = viewModel.logRows[0]
        XCTAssertEqual(row.module, "beacon.server.test_runtime")
        XCTAssertEqual(row.stepID, "join")
        XCTAssertEqual(row.timestamp, Date(timeIntervalSince1970: 1_720_000_000))
        XCTAssertEqual(viewModel.keyLogRows.map(\.message), ["joinChannel failed"])
    }

    func testServerLifecycleLogsHiddenByDefaultAndToggleable() {
        let viewModel = ConsoleViewModel()
        viewModel.logRows = [
            LogRow(level: "info", message: "run selected", nodeID: "beacon-server", event: "native.run.selected"),
            LogRow(level: "info", message: "join ok", nodeID: "mac-1", event: "sdk_call_completed"),
            LogRow(level: "info", message: "reset done", nodeID: "mac-1", event: "native.runtime_reset.completed"),
        ]

        XCTAssertEqual(viewModel.hiddenLifecycleLogCount, 1)
        XCTAssertEqual(viewModel.filteredLogs.map(\.message), ["join ok", "reset done"])

        viewModel.showsLifecycleLogs = true

        XCTAssertEqual(viewModel.filteredLogs.map(\.message), ["run selected", "join ok", "reset done"])
    }

    func testLevelAndStepFiltersCombineWithTextFilter() {
        let viewModel = ConsoleViewModel()
        viewModel.logRows = [
            LogRow(level: "info", message: "join ok", nodeID: "mac-1", stepID: "join"),
            LogRow(level: "warning", message: "slow join", nodeID: "mac-1", stepID: "join"),
            LogRow(level: "error", message: "callback timeout", nodeID: "mac-1", stepID: "wait-callback"),
        ]

        viewModel.logLevelFilter = .error
        XCTAssertEqual(viewModel.filteredLogs.map(\.message), ["callback timeout"])

        viewModel.logLevelFilter = .warning
        XCTAssertEqual(viewModel.filteredLogs.map(\.message), ["slow join"])

        viewModel.logLevelFilter = .all
        viewModel.toggleStepFilter("join")
        XCTAssertEqual(viewModel.filteredLogs.map(\.message), ["join ok", "slow join"])

        viewModel.logFilter = "timeout"
        XCTAssertEqual(viewModel.filteredLogs.map(\.message), [])

        viewModel.toggleStepFilter("join")
        viewModel.logFilter = ""
        XCTAssertEqual(viewModel.filteredLogs.count, 3)
    }

    func testFailedStepResultsOnlyForFailedRun() {
        let viewModel = ConsoleViewModel()
        let passed = StepResultSummary(
            caseID: "TC-1", stepID: "step-passed", status: "passed", error: nil, artifacts: [], durationMs: 10
        )
        let failed = StepResultSummary(
            caseID: "TC-1",
            stepID: "step-failed",
            status: "failed",
            error: ["code": .int(408), "message": .string("missing evidence")],
            artifacts: [],
            durationMs: 15_000
        )

        viewModel.currentRun = RunResponse(runID: "run-1", status: "failed", stepResults: [passed, failed])
        XCTAssertEqual(viewModel.failedStepResults.map(\.stepID), ["step-failed"])

        viewModel.currentRun = RunResponse(runID: "run-2", status: "passed", stepResults: [failed])
        XCTAssertTrue(viewModel.failedStepResults.isEmpty)
    }

    func testFailureOffsetTextUsesEarliestStepLogRelativeToRunStart() {
        let viewModel = ConsoleViewModel()
        viewModel.logRows = [
            LogRow(level: "info", message: "case started", nodeID: "mac-1", timestamp: Date(timeIntervalSince1970: 100)),
            LogRow(
                level: "info",
                message: "join started",
                nodeID: "mac-1",
                timestamp: Date(timeIntervalSince1970: 101.25),
                stepID: "join"
            ),
        ]
        let failed = StepResultSummary(
            caseID: "TC-1", stepID: "join", status: "failed", error: nil, artifacts: [], durationMs: 5
        )

        XCTAssertEqual(viewModel.failureOffsetText(for: failed), "+1.25s")

        viewModel.logRows = []
        XCTAssertNil(viewModel.failureOffsetText(for: failed))
    }

    func testRelativeOffsetAndTimeFormattingHelpers() {
        XCTAssertEqual(
            ConsoleViewModel.relativeOffsetText(
                from: Date(timeIntervalSince1970: 10),
                to: Date(timeIntervalSince1970: 11.5)
            ),
            "+1.50s"
        )
        XCTAssertNil(ConsoleViewModel.relativeOffsetText(from: nil, to: Date(timeIntervalSince1970: 11.5)))

        let timeText = ConsoleViewModel.timeText(from: Date(timeIntervalSince1970: 0))
        XCTAssertTrue(timeText.range(of: #"^\d{2}:\d{2}:\d{2}\.\d{3}$"#, options: .regularExpression) != nil)
    }

    func testVisibleLogsTextUsesFilteredRowsWithStructuredFields() {
        let viewModel = ConsoleViewModel()
        viewModel.logRows = [
            LogRow(
                level: "error",
                message: "join failed",
                nodeID: "mac-1",
                event: "assertion_failed",
                detail: "step_id=join",
                timestamp: Date(timeIntervalSince1970: 1000),
                module: "beacon.server",
                stepID: "join"
            ),
            LogRow(level: "info", message: "join ok", nodeID: "mac-1"),
        ]
        viewModel.logLevelFilter = .error

        let text = viewModel.visibleLogsText()

        XCTAssertTrue(text.contains("ERROR"))
        XCTAssertTrue(text.contains("assertion_failed join failed"))
        XCTAssertTrue(text.contains("step_id=join"))
        XCTAssertFalse(text.contains("join ok"))
    }

    func testLogLevelFilterCoversLabelsIDsAndLevelMatching() {
        XCTAssertEqual(LogLevelFilter.allCases.count, 4)
        XCTAssertEqual(LogLevelFilter.all.label, "All")
        XCTAssertEqual(LogLevelFilter.info.label, "Info")
        XCTAssertEqual(LogLevelFilter.warning.label, "Warn")
        XCTAssertEqual(LogLevelFilter.error.label, "Error")
        XCTAssertEqual(LogLevelFilter.error.id, "error")

        XCTAssertTrue(LogLevelFilter.all.matches("error"))
        XCTAssertTrue(LogLevelFilter.info.matches("info"))
        XCTAssertFalse(LogLevelFilter.info.matches("error"))
        XCTAssertTrue(LogLevelFilter.warning.matches("warning"))
        XCTAssertTrue(LogLevelFilter.warning.matches("warn"))
        XCTAssertFalse(LogLevelFilter.warning.matches("info"))
        XCTAssertTrue(LogLevelFilter.error.matches("error"))
        XCTAssertTrue(LogLevelFilter.error.matches("fatal"))
        XCTAssertFalse(LogLevelFilter.error.matches("warning"))
    }

    func testStepFilterOptionsComeFromCurrentRunStepResults() {
        let viewModel = ConsoleViewModel()
        XCTAssertEqual(viewModel.stepFilterOptions, [])

        viewModel.currentRun = RunResponse(
            runID: "run-1",
            status: "failed",
            stepResults: [
                StepResultSummary(caseID: "TC-1", stepID: "join", status: "passed", error: nil, artifacts: [], durationMs: 1),
                StepResultSummary(
                    caseID: "TC-1",
                    stepID: "wait-callback",
                    status: "failed",
                    error: ["code": .int(2), "message": .string("x")],
                    artifacts: [],
                    durationMs: 2
                ),
            ]
        )

        XCTAssertEqual(viewModel.stepFilterOptions, ["join", "wait-callback"])
    }

    func testUpdateLogsFallsBackWhenLevelOrMessageMissing() {
        let viewModel = ConsoleViewModel()
        let detail = ConsoleRunDetail(
            run: RunResponse(runID: "run-1", status: "passed", stepResults: []),
            report: ReportSummary(runID: "run-1", format: "json", summary: ["passed": .int(1)]),
            logs: [
                ["node_id": .string("mac-1")],
                ["level": .string("info"), "message": .string("fallback message"), "extra": .null],
            ]
        )

        viewModel.updateLogs(from: detail)

        XCTAssertEqual(viewModel.logRows[0].level, "info")
        XCTAssertFalse(viewModel.logRows[0].message.isEmpty)
        XCTAssertEqual(viewModel.logRows[1].message, "fallback message")
        XCTAssertEqual(viewModel.logRows[1].detail, "")
    }

    func testUpdateLogsFormatsStructuredDetailsAndMarksErrorLevelAsKeyEvent() {
        let viewModel = ConsoleViewModel()
        let detail = ConsoleRunDetail(
            run: RunResponse(runID: "run-1", status: "failed", stepResults: []),
            report: ReportSummary(runID: "run-1", format: "json", summary: ["failed": .int(1)]),
            logs: [
                [
                    "level": .string("error"),
                    "node_id": .string("mac-1"),
                    "event": .string("debug_trace"),
                    "message": .string("joinChannel failed"),
                    "run_id": .string("run-1"),
                    "case_id": .string("TC-MAC-AGORA-REAL-JOIN-CALLBACK"),
                    "step_id": .string("join"),
                    "op_id": .int(17),
                    "extra": .object([
                        "channel": .string("real-smoke"),
                        "uid": .int(1001),
                        "retry": .bool(false),
                        "jitter": .double(1.5),
                        "events": .array([.string("join"), .null]),
                    ]),
                ],
                [
                    "level": .string("info"),
                    "message": .string("fallback message"),
                    "extra": .null,
                ],
            ]
        )

        viewModel.updateLogs(from: detail)

        XCTAssertEqual(viewModel.keyLogRows.map(\.message), ["joinChannel failed"])
        XCTAssertEqual(viewModel.logRows[0].level, "error")
        XCTAssertEqual(viewModel.logRows[0].nodeID, "mac-1")
        XCTAssertTrue(viewModel.logRows[0].detail.contains("run_id=run-1"))
        XCTAssertTrue(viewModel.logRows[0].detail.contains("case_id=TC-MAC-AGORA-REAL-JOIN-CALLBACK"))
        XCTAssertTrue(viewModel.logRows[0].detail.contains("op_id=17"))
        XCTAssertTrue(viewModel.logRows[0].detail.contains("channel:real-smoke"))
        XCTAssertTrue(viewModel.logRows[0].detail.contains("events:[join,]"))
        XCTAssertEqual(viewModel.logRows[1].message, "fallback message")
        XCTAssertEqual(viewModel.logRows[1].detail, "")
    }

    func testUpdateLogsKeepsRowIdentityStableAcrossPolls() {
        let viewModel = ConsoleViewModel()
        let logs: [[String: JSONValue]] = [
            [
                "level": .string("info"),
                "node_id": .string("mac-1"),
                "event": .string("step_started"),
                "message": .string("step started"),
                "timestamp_ms": .int(1_720_000_000_000),
            ],
            [
                "level": .string("error"),
                "node_id": .string("mac-1"),
                "event": .string("assertion_failed"),
                "message": .string("joinChannel failed"),
                "timestamp_ms": .int(1_720_000_000_100),
            ],
        ]

        viewModel.updateLogs(from: makeLogDetail(logs))
        let firstPollIDs = viewModel.logRows.map(\.id)
        viewModel.updateLogs(from: makeLogDetail(logs))

        XCTAssertEqual(firstPollIDs.count, 2)
        // 轮询重建整批行时身份必须不变，否则日志面板里已展开的详情每轮都会被收起。
        XCTAssertEqual(viewModel.logRows.map(\.id), firstPollIDs)
    }

    func testUpdateLogsKeepsExistingRowIdentityWhenNewLogsAppend() {
        let viewModel = ConsoleViewModel()
        let first: [String: JSONValue] = [
            "level": .string("info"),
            "node_id": .string("mac-1"),
            "event": .string("step_started"),
            "message": .string("step started"),
            "timestamp_ms": .int(1_720_000_000_000),
        ]
        let appended: [String: JSONValue] = [
            "level": .string("info"),
            "node_id": .string("mac-1"),
            "event": .string("step_completed"),
            "message": .string("step completed"),
            "timestamp_ms": .int(1_720_000_001_000),
        ]

        viewModel.updateLogs(from: makeLogDetail([first]))
        let initialIDs = viewModel.logRows.map(\.id)
        viewModel.updateLogs(from: makeLogDetail([first, appended]))

        XCTAssertEqual(Array(viewModel.logRows.map(\.id).prefix(1)), initialIDs)
        XCTAssertEqual(viewModel.logRows.count, 2)
    }

    func testUpdateLogsGivesDuplicateRowsDistinctStableIdentities() {
        let viewModel = ConsoleViewModel()
        let duplicate: [String: JSONValue] = [
            "level": .string("info"),
            "node_id": .string("mac-1"),
            "event": .string("debug_trace"),
            "message": .string("repeated probe"),
        ]

        viewModel.updateLogs(from: makeLogDetail([duplicate, duplicate]))
        let firstPollIDs = viewModel.logRows.map(\.id)
        viewModel.updateLogs(from: makeLogDetail([duplicate, duplicate]))

        // 同内容多行必须各自可区分，且轮询后仍与上一轮逐位一致。
        XCTAssertEqual(Set(firstPollIDs).count, 2)
        XCTAssertEqual(viewModel.logRows.map(\.id), firstPollIDs)
    }

    func testUpdateLogsPrefersServerEventIDForRowIdentity() {
        let viewModel = ConsoleViewModel()
        let logs: [[String: JSONValue]] = [
            [
                "event_id": .string("evt-1"),
                "level": .string("info"),
                "node_id": .string("mac-1"),
                "event": .string("step_started"),
                "message": .string("identical text"),
                "timestamp_ms": .int(1_720_000_000_000),
            ],
            [
                "event_id": .string("evt-2"),
                "level": .string("info"),
                "node_id": .string("mac-1"),
                "event": .string("step_started"),
                "message": .string("identical text"),
                "timestamp_ms": .int(1_720_000_000_000),
            ],
        ]

        viewModel.updateLogs(from: makeLogDetail(logs))
        let firstPollIDs = viewModel.logRows.map(\.id)
        viewModel.updateLogs(from: makeLogDetail(logs))

        // 真实链路每条日志都带 event_id：身份直接取 `node|event_id`，即便内容完全一致也唯一。
        XCTAssertEqual(firstPollIDs, ["mac-1|evt-1", "mac-1|evt-2"])
        XCTAssertEqual(viewModel.logRows.map(\.id), firstPollIDs)
    }

    func testUpdateLogsSeparatesRowsSharingAnEventIDAcrossNodes() {
        let viewModel = ConsoleViewModel()
        let logs: [[String: JSONValue]] = [
            [
                "event_id": .string("evt-1"),
                "level": .string("info"),
                "node_id": .string("mac-1"),
                "message": .string("same event on two nodes"),
            ],
            [
                "event_id": .string("evt-1"),
                "level": .string("info"),
                "node_id": .string("beacon-server"),
                "message": .string("same event on two nodes"),
            ],
        ]

        viewModel.updateLogs(from: makeLogDetail(logs))

        XCTAssertEqual(viewModel.logRows.map(\.id), ["mac-1|evt-1", "beacon-server|evt-1"])
    }

    func testUpdateLogsFallbackIdentitySurvivesSuffixLikeMessageText() {
        let viewModel = ConsoleViewModel()
        // 无 event_id 的回退路径：重复行与「文本长得像出现序号」的行不能撞身份。
        let duplicate: [String: JSONValue] = ["level": .string("info"), "message": .string("probe")]
        let suffixLike: [String: JSONValue] = ["level": .string("info"), "message": .string("probe#1")]

        viewModel.updateLogs(from: makeLogDetail([duplicate, duplicate, suffixLike]))

        let ids = viewModel.logRows.map(\.id)
        XCTAssertEqual(ids.count, 3)
        XCTAssertEqual(Set(ids).count, 3)
    }

    func testLogRowIdentityFollowsContentSoPollsKeepExpandedRows() {
        let row = LogRow(level: "warning", message: "slow callback", nodeID: "mac-1")

        // 身份由内容派生：同内容重建成同一行（展开状态得以保留），内容不同才是不同行。
        XCTAssertEqual(row.id, LogRow(level: "warning", message: "slow callback", nodeID: "mac-1").id)
        XCTAssertNotEqual(row.id, LogRow(level: "warning", message: "slow callback", nodeID: "mac-2").id)
        XCTAssertNotEqual(row.id, LogRow(level: "warning", message: "slow join", nodeID: "mac-1").id)
    }

    func testLogRowIdentitySeparatesRowsDifferingOnlyByStepOrTimestamp() {
        let row = LogRow(level: "info", message: "callback observed", nodeID: "mac-1", stepID: "step-1")

        XCTAssertNotEqual(
            row.id,
            LogRow(level: "info", message: "callback observed", nodeID: "mac-1", stepID: "step-2").id
        )
        XCTAssertNotEqual(
            LogRow(level: "info", message: "callback observed", nodeID: "mac-1", timestamp: Date(timeIntervalSince1970: 100)).id,
            LogRow(level: "info", message: "callback observed", nodeID: "mac-1", timestamp: Date(timeIntervalSince1970: 101)).id
        )
    }

    private func makeLogDetail(_ logs: [[String: JSONValue]]) -> ConsoleRunDetail {
        ConsoleRunDetail(
            run: RunResponse(runID: "run-1", status: "passed", stepResults: []),
            report: ReportSummary(runID: "run-1", format: "json", summary: ["passed": .int(1)]),
            logs: logs
        )
    }

    func testStepResultExposesErrorCodeOnlyWhenErrorExists() {
        let passed = StepResultSummary(
            caseID: "TC-1",
            stepID: "step-passed",
            status: "passed",
            error: nil,
            artifacts: [],
            durationMs: 17
        )
        let failed = StepResultSummary(
            caseID: "TC-1",
            stepID: "step-failed",
            status: "failed",
            error: ["code": .int(408), "message": .string("missing evidence")],
            artifacts: [],
            durationMs: 15000
        )

        XCTAssertNil(passed.errorCode)
        XCTAssertEqual(passed.durationLabel, "17 ms")
        XCTAssertEqual(failed.errorCode, 408)
        XCTAssertEqual(failed.message, "missing evidence")
    }

    func testAutorunCasesOnlyIncludeRunnableCasesMatchingPrefix() {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            makeCase(caseID: "TC-MAC-AGORA-RUNNABLE", suite: "rtc", sdk: "agora_rtc", implementationStatus: "runnable"),
            makeCase(caseID: "TC-MAC-AGORA-PARTIAL", suite: "rtc", sdk: "agora_rtc", implementationStatus: "runnable_or_partial"),
            makeCase(caseID: "TC-MAC-AGORA-BLOCKED", suite: "rtc", sdk: "agora_rtc", implementationStatus: "designed_but_blocked"),
            makeCase(caseID: "TC-OTHER-RUNNABLE", suite: "rtc", sdk: "agora_rtc", implementationStatus: "runnable"),
        ]

        let cases = viewModel.autorunCases(matching: "TC-MAC-AGORA-")

        XCTAssertEqual(cases.map(\.caseID), ["TC-MAC-AGORA-RUNNABLE"])
    }

    func testSuiteRunCasesOnlyIncludeRunnableCasesInSelectedSuite() {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            makeCase(caseID: "TC-SUITE-B", suite: "rtc", sdk: "agora_rtc", implementationStatus: "runnable"),
            makeCase(caseID: "TC-SUITE-A", suite: "rtc", sdk: "agora_rtc", implementationStatus: "runnable"),
            makeCase(caseID: "TC-SUITE-PARTIAL", suite: "rtc", sdk: "agora_rtc", implementationStatus: "runnable_or_partial"),
            makeCase(caseID: "TC-OTHER", suite: "other", sdk: "agora_rtc", implementationStatus: "runnable"),
        ]
        viewModel.selectedSuite = "rtc"

        let cases = viewModel.suiteRunCases()

        XCTAssertEqual(cases.map(\.caseID), ["TC-SUITE-A", "TC-SUITE-B"])
    }

    func testAutorunCasesMatchingPrefixSelectsAllAgoraRealCases() {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            TestCaseSummary(caseID: "TC-MAC-SMOKE", name: "Smoke", platform: "mac", suite: "mac", tags: [], implementationStatus: "runnable"),
            TestCaseSummary(caseID: "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE", name: "Join Leave", platform: "mac", suite: "mac", tags: ["autorun-order:2"], implementationStatus: "runnable"),
            TestCaseSummary(caseID: "TC-MAC-AGORA-REAL-LIFECYCLE", name: "Lifecycle", platform: "mac", suite: "mac", tags: ["autorun-order:0"], implementationStatus: "runnable"),
            TestCaseSummary(caseID: "TC-MAC-AGORA-REAL-JOIN-CALLBACK", name: "Join", platform: "mac", suite: "mac", tags: ["autorun-order:1"], implementationStatus: "runnable"),
        ]

        XCTAssertEqual(
            viewModel.autorunCases(matching: "TC-MAC-AGORA-REAL").map(\.caseID),
            [
                "TC-MAC-AGORA-REAL-LIFECYCLE",
                "TC-MAC-AGORA-REAL-JOIN-CALLBACK",
                "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE",
            ]
        )
    }

    func testAutorunCasesSortTaggedCasesBeforeUntaggedCaseIDOrder() {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            TestCaseSummary(caseID: "TC-MAC-AGORA-REAL-JOIN-CALLBACK", name: "Join", platform: "mac", suite: "mac", tags: ["autorun-order:1"], implementationStatus: "runnable"),
            TestCaseSummary(caseID: "TC-MAC-AGORA-PREVIEW-CONTROL", name: "Preview", platform: "mac", suite: "mac", tags: [], implementationStatus: "runnable"),
        ]

        XCTAssertEqual(
            viewModel.autorunCases(matching: "TC-MAC-AGORA-").map(\.caseID),
            ["TC-MAC-AGORA-REAL-JOIN-CALLBACK", "TC-MAC-AGORA-PREVIEW-CONTROL"]
        )
    }

    func testAutorunCasesCanBeRestrictedToExactRunnableIDs() {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            TestCaseSummary(caseID: "TC-MAC-AGORA-REAL-JOIN-CALLBACK", name: "Join", platform: "mac", suite: "mac", tags: ["autorun-order:1"], implementationStatus: "runnable"),
            TestCaseSummary(caseID: "TC-MAC-AGORA-PREVIEW-CONTROL", name: "Preview", platform: "mac", suite: "mac", tags: [], implementationStatus: "runnable"),
            TestCaseSummary(caseID: "TC-MAC-AGORA-SMALL-ROOM-BASELINE", name: "Blocked", platform: "mac", suite: "mac", tags: [], implementationStatus: "designed_but_blocked"),
        ]

        XCTAssertEqual(
            viewModel.autorunCases(
                matching: "TC-MAC-AGORA-",
                caseIDs: ["TC-MAC-AGORA-PREVIEW-CONTROL", "TC-MAC-AGORA-REAL-JOIN-CALLBACK"]
            ).map(\.caseID),
            [
                "TC-MAC-AGORA-REAL-JOIN-CALLBACK",
                "TC-MAC-AGORA-PREVIEW-CONTROL",
            ]
        )
    }

    func testRunSelectedCaseIncludesSelectedNodeIDInCreateRunRequest() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.selectedCase = makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc")
        let session = makeStubSession(responses: [
            #"""
            {"run_id":"run-1","status":"passed","results":[]}
            """#,
            #"""
            {"run":{"run_id":"run-1","status":"passed","results":[]},"report":{"run_id":"run-1","format":"json","summary":{"passed":1}},"logs":[]}
            """#,
        ])
        let client = BeaconServerClient(
            baseURL: URL(string: "http://127.0.0.1:8000")!,
            token: "token-1",
            session: session
        )

        await viewModel.runSelectedCase(client: client, nodeID: "mac-real-e2e-001")

        let request = try XCTUnwrap(URLProtocolSequenceStub.requests.first)
        let body = try XCTUnwrap(httpBodyData(for: request))
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        let selector = try XCTUnwrap(payload["selector"] as? [String: String])
        XCTAssertEqual(selector["node_id"], "mac-real-e2e-001")
        XCTAssertEqual(payload["case_ids"] as? [String], ["TC-AGORA-1"])
        XCTAssertNil(payload["cases"])
    }

    func testRunAutorunCasesInsertsCleanupRunBeforeSecondIsolatedCase() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            makeCase(caseID: "TC-MAC-AGORA-REAL-LIFECYCLE", suite: "rtc", sdk: "agora_rtc", requiresRuntimeIsolation: true),
            makeCase(caseID: "TC-MAC-AGORA-PREVIEW-CONTROL", suite: "rtc", sdk: "agora_rtc", requiresRuntimeIsolation: true),
            makeCase(caseID: "TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE", suite: "rtc", sdk: "agora_rtc", tags: ["runtime-reset-baseline"]),
        ]
        let session = makeStubSession(responses: [
            #"""
            {"run_id":"run-1","status":"passed","results":[]}
            """#,
            #"""
            {"run":{"run_id":"run-1","status":"passed","results":[]},"report":{"run_id":"run-1","format":"json","summary":{"passed":1}},"logs":[]}
            """#,
            #"""
            {"run_id":"run-cleanup","status":"passed","results":[]}
            """#,
            #"""
            {"run_id":"run-2","status":"passed","results":[]}
            """#,
            #"""
            {"run":{"run_id":"run-2","status":"passed","results":[]},"report":{"run_id":"run-2","format":"json","summary":{"passed":1}},"logs":[]}
            """#,
            #"""
            {"run_id":"run-cleanup-tail","status":"passed","results":[]}
            """#,
        ])
        let client = BeaconServerClient(
            baseURL: URL(string: "http://127.0.0.1:8000")!,
            token: "token-1",
            session: session
        )

        _ = try await viewModel.runAutorunCases(
            client: client,
            prefix: "TC-MAC-AGORA-",
            caseIDs: ["TC-MAC-AGORA-REAL-LIFECYCLE", "TC-MAC-AGORA-PREVIEW-CONTROL"],
            nodeID: "mac-real-e2e-001"
        )

        XCTAssertEqual(URLProtocolSequenceStub.requests.count, 6)
        let cleanupRequest = try XCTUnwrap(URLProtocolSequenceStub.requests[safe: 2])
        let cleanupBody = try XCTUnwrap(httpBodyData(for: cleanupRequest))
        let cleanupPayload = try XCTUnwrap(JSONSerialization.jsonObject(with: cleanupBody) as? [String: Any])
        XCTAssertEqual(cleanupPayload["case_ids"] as? [String], ["TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE"])
        XCTAssertNil(cleanupPayload["cases"])

        let finalCleanupRequest = try XCTUnwrap(URLProtocolSequenceStub.requests[safe: 5])
        let finalCleanupBody = try XCTUnwrap(httpBodyData(for: finalCleanupRequest))
        let finalCleanupPayload = try XCTUnwrap(JSONSerialization.jsonObject(with: finalCleanupBody) as? [String: Any])
        XCTAssertEqual(finalCleanupPayload["case_ids"] as? [String], ["TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE"])
        XCTAssertNil(finalCleanupPayload["cases"])
    }

    func testRunAutorunCasesFailsFastWhenInsertedCleanupFails() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            makeCase(caseID: "TC-MAC-AGORA-REAL-LIFECYCLE", suite: "rtc", sdk: "agora_rtc", requiresRuntimeIsolation: true),
            makeCase(caseID: "TC-MAC-AGORA-PREVIEW-CONTROL", suite: "rtc", sdk: "agora_rtc", requiresRuntimeIsolation: true),
            makeCase(caseID: "TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE", suite: "rtc", sdk: "agora_rtc", tags: ["runtime-reset-baseline"]),
        ]
        let session = makeStubSession(responses: [
            #"""
            {"run_id":"run-1","status":"passed","results":[]}
            """#,
            #"""
            {"run":{"run_id":"run-1","status":"passed","results":[]},"report":{"run_id":"run-1","format":"json","summary":{"passed":1}},"logs":[]}
            """#,
            #"""
            {"run_id":"run-cleanup","status":"failed","results":[]}
            """#,
        ])
        let client = BeaconServerClient(
            baseURL: URL(string: "http://127.0.0.1:8000")!,
            token: "token-1",
            session: session
        )

        do {
            _ = try await viewModel.runAutorunCases(
                client: client,
                prefix: "TC-MAC-AGORA-",
                caseIDs: ["TC-MAC-AGORA-REAL-LIFECYCLE", "TC-MAC-AGORA-PREVIEW-CONTROL"],
                nodeID: "mac-real-e2e-001"
            )
            XCTFail("cleanup failure should stop autorun before the next case")
        } catch let error as ConsoleAutorunError {
            XCTAssertEqual(error, .cleanupFailed(runID: "run-cleanup", status: "failed"))
        }

        XCTAssertEqual(URLProtocolSequenceStub.requests.count, 3)
    }

    func testRunAutorunCasesFailsClosedWhenCleanupBaselineMissing() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            makeCase(caseID: "TC-MAC-AGORA-REAL-LIFECYCLE", suite: "rtc", sdk: "agora_rtc", requiresRuntimeIsolation: true),
            makeCase(caseID: "TC-MAC-AGORA-PREVIEW-CONTROL", suite: "rtc", sdk: "agora_rtc", requiresRuntimeIsolation: true),
            makeCase(caseID: "TC-OTHER-RUNTIME-CLEANUP-BASELINE", suite: "rtc", sdk: "other_sdk", tags: ["runtime-reset-baseline"]),
        ]
        let session = makeStubSession(responses: [
            #"""
            {"run_id":"run-1","status":"passed","results":[]}
            """#,
            #"""
            {"run":{"run_id":"run-1","status":"passed","results":[]},"report":{"run_id":"run-1","format":"json","summary":{"passed":1}},"logs":[]}
            """#,
        ])
        let client = BeaconServerClient(
            baseURL: URL(string: "http://127.0.0.1:8000")!,
            token: "token-1",
            session: session
        )

        do {
            _ = try await viewModel.runAutorunCases(
                client: client,
                prefix: "TC-MAC-AGORA-",
                caseIDs: ["TC-MAC-AGORA-REAL-LIFECYCLE", "TC-MAC-AGORA-PREVIEW-CONTROL"],
                nodeID: "mac-real-e2e-001"
            )
            XCTFail("missing cleanup baseline should fail closed before the next isolated case")
        } catch let error as ConsoleAutorunError {
            // 两个 case 都未声明 autorun-order，caseID 排序后 PREVIEW-CONTROL 先执行，
            // 第二个 case TC-MAC-AGORA-REAL-LIFECYCLE 触发 cleanup 查找失败。
            XCTAssertEqual(error, .cleanupCaseNotFound(caseID: "TC-MAC-AGORA-REAL-LIFECYCLE"))
        }

        XCTAssertEqual(URLProtocolSequenceStub.requests.count, 2)
    }

    func testRunSelectedSuiteSubmitsRunnableCasesInSuiteOrder() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.selectedSuite = "rtc"
        viewModel.testCases = [
            makeCase(caseID: "TC-SUITE-B", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-A", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-PARTIAL", suite: "rtc", sdk: "agora_rtc", implementationStatus: "runnable_or_partial"),
            makeCase(caseID: "TC-OTHER", suite: "other", sdk: "agora_rtc"),
        ]
        let session = makeStubSession(responses: [
            #"""
            {"run_id":"run-a","status":"passed","results":[]}
            """#,
            #"""
            {"run":{"run_id":"run-a","status":"passed","results":[]},"report":{"run_id":"run-a","format":"json","summary":{"passed":1}},"logs":[]}
            """#,
            #"""
            {"run_id":"run-b","status":"passed","results":[]}
            """#,
            #"""
            {"run":{"run_id":"run-b","status":"passed","results":[]},"report":{"run_id":"run-b","format":"json","summary":{"passed":1}},"logs":[]}
            """#,
        ])
        let client = BeaconServerClient(
            baseURL: URL(string: "http://127.0.0.1:8000")!,
            token: "token-1",
            session: session
        )

        let runs = try await viewModel.runSelectedSuite(client: client, nodeID: "mac-1")

        XCTAssertEqual(runs.map { $0.0.caseID }, ["TC-SUITE-A", "TC-SUITE-B"])
        // 批量运行不改展示目标：结果只进会话缓存，详情区留在用户看的那条 run 上（owner 决策 B）。
        XCTAssertNil(viewModel.currentRun)
        XCTAssertNil(viewModel.currentRunDetail)
        XCTAssertEqual(viewModel.caseResults.keys.sorted(), ["TC-SUITE-A", "TC-SUITE-B"])
        XCTAssertEqual(URLProtocolSequenceStub.requests.count, 4)
        let firstBody = try XCTUnwrap(httpBodyData(for: URLProtocolSequenceStub.requests[0]))
        let firstPayload = try XCTUnwrap(JSONSerialization.jsonObject(with: firstBody) as? [String: Any])
        XCTAssertEqual(firstPayload["case_ids"] as? [String], ["TC-SUITE-A"])
    }

    func testSuiteRunKeepsTheRunYouAreReadingInsteadOfFollowingTheBatch() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.selectedSuite = "rtc"
        viewModel.testCases = [
            makeCase(caseID: "TC-SUITE-A", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-B", suite: "rtc", sdk: "agora_rtc"),
        ]
        // 用户正在读的一条 run：批量运行期间日志面板不能把它换掉（否则正在看的日志/展开状态会离开屏幕）。
        viewModel.currentRun = RunResponse(runID: "run-displayed", status: "passed", stepResults: [])
        let displayedDetail = ConsoleRunDetail(
            run: RunResponse(runID: "run-displayed", status: "passed", stepResults: []),
            report: ReportSummary(runID: "run-displayed", format: "json", summary: ["passed": .int(1)]),
            logs: [["level": .string("info"), "message": .string("still readable"), "node_id": .string("mac-1")]]
        )
        viewModel.currentRunDetail = displayedDetail
        viewModel.updateLogs(from: displayedDetail)
        viewModel.stopRunDetailPolling()
        let session = makeStubSession(responses: [
            createRunJSON(runID: "run-a", status: "passed"),
            runDetailJSON(runID: "run-a", status: "passed", caseID: "TC-SUITE-A"),
            createRunJSON(runID: "run-b", status: "passed"),
            runDetailJSON(runID: "run-b", status: "passed", caseID: "TC-SUITE-B"),
        ])
        let client = BeaconServerClient(
            baseURL: URL(string: "http://127.0.0.1:8000")!,
            token: "token-1",
            session: session
        )

        _ = try await viewModel.runSelectedSuite(client: client, nodeID: "mac-1")
        viewModel.stopRunDetailPolling()

        XCTAssertEqual(viewModel.currentRun?.runID, "run-displayed")
        XCTAssertEqual(viewModel.currentRunDetail?.run.runID, "run-displayed")
        XCTAssertEqual(viewModel.logRows.map(\.message), ["still readable"])
        // 批量结果仍在：每个 case 都能从会话缓存里点开。
        XCTAssertEqual(viewModel.caseResults.keys.sorted(), ["TC-SUITE-A", "TC-SUITE-B"])
    }

    func testRunSelectedSuiteStopsBatchWhenRunComesBackCancelled() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.selectedSuite = "rtc"
        viewModel.testCases = [
            makeCase(caseID: "TC-SUITE-A", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-B", suite: "rtc", sdk: "agora_rtc"),
        ]
        viewModel.stopRunDetailPolling()
        // createRun 一律返回 cancelled：模拟用户 Cancel 后 server 把飞行中的 run 协作收敛成 cancelled。
        // 用 path stub 而非 sequence stub，第二条 case 若误发 createRun 只会多记一次请求而不会崩在 removeFirst。
        let session = makePathStubSession(responses: [
            "/api/v1/test-runs": createRunJSON(runID: "run-a", status: "cancelled"),
            "/api/v1/console/test-runs/run-a": runDetailJSON(runID: "run-a", status: "cancelled", caseID: "TC-SUITE-A", durationMs: 800),
        ])
        let client = makeClient(session: session)

        let runs = try await viewModel.runSelectedSuite(client: client, nodeID: "mac-1")
        viewModel.stopRunDetailPolling()

        // 第一条 case 回来即 cancelled：批量在此停止，第二条 case 的 createRun 不再发起。
        XCTAssertEqual(runs.map { $0.0.caseID }, ["TC-SUITE-A"])
        XCTAssertEqual(viewModel.caseResults.keys.sorted(), ["TC-SUITE-A"])
        XCTAssertEqual(viewModel.caseResults["TC-SUITE-A"]?.status, "cancelled")
        XCTAssertNil(viewModel.suiteRunProgress)
        XCTAssertNil(viewModel.currentRun)
        XCTAssertEqual(
            URLProtocolPathStub.requests.map { $0.url?.path },
            ["/api/v1/test-runs", "/api/v1/console/test-runs/run-a"]
        )
    }

    func testRunSelectedSuiteRecordsCancelIntentWhileCreationResponseIsPending() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.selectedSuite = "rtc"
        viewModel.testCases = [
            makeCase(caseID: "TC-SUITE-A", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-B", suite: "rtc", sdk: "agora_rtc"),
        ]
        // gate 把创建响应挂起；Cancel 只留下意图，已终态响应返回后整批停止。
        let session = makePathStubSession(
            responses: [
                "/api/v1/test-runs": createRunJSON(runID: "run-a", status: "passed"),
                "/api/v1/console/test-runs": #"{"runs":[]}"#,
                "/api/v1/console/test-runs/run-a": runDetailJSON(
                    runID: "run-a",
                    status: "passed",
                    caseID: "TC-SUITE-A",
                    durationMs: 12
                ),
            ],
            gatedPaths: ["/api/v1/test-runs"]
        )
        let client = makeClient(session: session)

        let batch = Task { try await viewModel.runSelectedSuite(client: client, nodeID: "mac-1") }
        try await waitForRecordedRequest(path: "/api/v1/test-runs")
        XCTAssertTrue(URLProtocolPathStub.requests.contains { $0.url?.path == "/api/v1/test-runs" })
        XCTAssertTrue(viewModel.isRunning)
        XCTAssertEqual(viewModel.runningDescription, "Running suite (0/2)")

        await viewModel.cancelCurrentRun(client: client)

        // 创建响应尚未返回：保留取消意图，不查询或取消别人的 run。
        XCTAssertNil(viewModel.errorMessage)
        URLProtocolPathStub.release("/api/v1/test-runs")
        let runs = try await batch.value

        XCTAssertEqual(runs.map { $0.0.caseID }, ["TC-SUITE-A"])
        XCTAssertEqual(viewModel.caseResults.keys.sorted(), ["TC-SUITE-A"])
        XCTAssertNil(viewModel.currentRun)
        XCTAssertEqual(viewModel.caseResults["TC-SUITE-A"]?.status, "passed")
        // 第二条 case 的 createRun 不再发起：批量中止后 /test-runs 只被请求过一次。
        XCTAssertEqual(
            URLProtocolPathStub.requests.filter { $0.url?.path == "/api/v1/test-runs" }.count,
            1
        )
        XCTAssertNil(viewModel.suiteRunProgress)
        XCTAssertFalse(viewModel.isRunning)
        // 批结束后进度清除，运行中文案回退到当前选中的 case。
        viewModel.selectedCase = viewModel.testCases[0]
        XCTAssertEqual(viewModel.runningDescription, "Running TC-SUITE-A")
    }

    func testRunAutorunCasesSkipsTrailingCleanupWhenBatchAbortedBetweenCases() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            makeCase(caseID: "TC-MAC-AGORA-A", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-MAC-AGORA-B", suite: "rtc", sdk: "agora_rtc", requiresRuntimeIsolation: true),
            makeCase(
                caseID: "TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE",
                suite: "rtc",
                sdk: "agora_rtc",
                tags: ["runtime-reset-baseline"]
            ),
        ]
        let session = makePathStubSession(
            responses: [
                "/api/v1/test-runs": createRunJSON(runID: "run-a", status: "passed"),
                "/api/v1/console/test-runs": #"{"runs":[]}"#,
                "/api/v1/console/test-runs/run-a": runDetailJSON(
                    runID: "run-a",
                    status: "passed",
                    caseID: "TC-MAC-AGORA-A",
                    durationMs: 9
                ),
            ],
            gatedPaths: ["/api/v1/test-runs"]
        )
        let client = makeClient(session: session)

        let batch = Task {
            try await viewModel.runAutorunCases(
                client: client,
                prefix: "TC-MAC-AGORA-",
                caseIDs: ["TC-MAC-AGORA-A", "TC-MAC-AGORA-B"],
                nodeID: "mac-real-001"
            )
        }
        try await waitForRecordedRequest(path: "/api/v1/test-runs")
        XCTAssertTrue(URLProtocolPathStub.requests.contains { $0.url?.path == "/api/v1/test-runs" })

        await viewModel.cancelCurrentRun(client: client)
        URLProtocolPathStub.release("/api/v1/test-runs")
        let runs = try await batch.value
        viewModel.stopRunDetailPolling()

        // 本地中止：后续 case 与其前置/收尾 cleanup run 都不再发起，只剩第一条 case 的 run。
        XCTAssertEqual(runs.map { $0.0.caseID }, ["TC-MAC-AGORA-A"])
        XCTAssertEqual(
            URLProtocolPathStub.requests.filter { $0.url?.path == "/api/v1/test-runs" }.count,
            1
        )
        XCTAssertNil(viewModel.errorMessage)
        XCTAssertNil(viewModel.suiteRunProgress)
        XCTAssertFalse(viewModel.isRunning)
    }

    func testRunDetailPollingRefreshesLogs() async throws {
        let viewModel = ConsoleViewModel()
        let session = makeStubSession(responses: [
            #"""
            {"run":{"run_id":"run-stream","status":"running","results":[]},"report":{"run_id":"run-stream","format":"json","summary":{"running":1}},"logs":[{"level":"info","message":"first","node_id":"mac-1"}]}
            """#,
            #"""
            {"run":{"run_id":"run-stream","status":"passed","results":[]},"report":{"run_id":"run-stream","format":"json","summary":{"passed":1}},"logs":[{"level":"info","message":"second","node_id":"mac-1"}]}
            """#,
            #"""
            {"run":{"run_id":"run-stream","status":"passed","results":[]},"report":{"run_id":"run-stream","format":"json","summary":{"passed":1}},"logs":[{"level":"info","message":"third","node_id":"mac-1"}]}
            """#,
        ])
        let client = BeaconServerClient(
            baseURL: URL(string: "http://127.0.0.1:8000")!,
            token: "token-1",
            session: session
        )

        viewModel.startRunDetailPolling(client: client, runID: "run-stream", intervalNanoseconds: 10_000_000)
        while URLProtocolSequenceStub.requests.count < 2 {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        try await Task.sleep(nanoseconds: 40_000_000)

        XCTAssertEqual(viewModel.currentRunDetail?.run.runID, "run-stream")
        XCTAssertEqual(viewModel.logRows.last?.message, "second")
        XCTAssertEqual(URLProtocolSequenceStub.requests.count, 2)
    }

    func testExportCurrentRunPackageWritesRunReportAndLogs() throws {
        let viewModel = ConsoleViewModel()
        viewModel.currentRunDetail = ConsoleRunDetail(
            run: RunResponse(runID: "run-1", status: "passed", stepResults: []),
            report: ReportSummary(runID: "run-1", format: "json", summary: ["passed": .int(1)]),
            logs: [["level": .string("info"), "message": .string("join ok")]]
        )
        let outputURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("json")

        try viewModel.exportCurrentRunPackage(to: outputURL)

        let data = try Data(contentsOf: outputURL)
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(payload["schema_version"] as? Int, 1)
        let run = try XCTUnwrap(payload["run"] as? [String: Any])
        XCTAssertEqual(run["run_id"] as? String, "run-1")
        let report = try XCTUnwrap(payload["report"] as? [String: Any])
        XCTAssertEqual(report["run_id"] as? String, "run-1")
        let logs = try XCTUnwrap(payload["logs"] as? [[String: Any]])
        XCTAssertEqual(logs.first?["message"] as? String, "join ok")
    }

    func testExportCurrentRunPackageRequiresLoadedRunDetail() {
        let viewModel = ConsoleViewModel()
        let outputURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("json")

        XCTAssertThrowsError(try viewModel.exportCurrentRunPackage(to: outputURL)) { error in
            XCTAssertEqual(error as? ConsoleExportError, .missingRunDetail)
            XCTAssertEqual(String(describing: error), "No run detail is available to export")
        }
    }

    func testValueTypeDescriptionsUsedByConsoleUIAndAutorunErrors() {
        let suite = TestSuiteSummary(name: "mac", count: 3)
        let row = LogRow(level: "warning", message: "slow callback", nodeID: "mac-1")
        let error = ConsoleAutorunError.cleanupFailed(runID: "run-cleanup", status: "failed")

        XCTAssertEqual(suite.id, "mac")
        XCTAssertEqual(row.id, LogRow(level: "warning", message: "slow callback", nodeID: "mac-1").id)
        XCTAssertEqual(String(describing: error), "Autorun cleanup failed: run-cleanup status=failed")
    }

    func testSuiteRunKeepsPerCaseResultsAndClearsProgressAfterCompletion() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.selectedSuite = "rtc"
        viewModel.testCases = [
            makeCase(caseID: "TC-SUITE-B", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-A", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-PARTIAL", suite: "rtc", sdk: "agora_rtc", implementationStatus: "runnable_or_partial"),
        ]
        let session = makeStubSession(responses: [
            createRunJSON(runID: "run-a", status: "queued"),
            runDetailJSON(runID: "run-a", status: "passed", caseID: "TC-SUITE-A", durationMs: 1200),
            createRunJSON(runID: "run-b", status: "queued"),
            runDetailJSON(runID: "run-b", status: "failed", caseID: "TC-SUITE-B", durationMs: 15_000),
        ])
        let client = makeClient(session: session)

        let runs = try await viewModel.runSelectedSuite(client: client, nodeID: "mac-1")

        XCTAssertEqual(runs.map { $0.0.caseID }, ["TC-SUITE-A", "TC-SUITE-B"])
        // suite 顺序运行不再互相覆盖：两条 case 的结果同时保留在会话内。
        XCTAssertEqual(viewModel.caseResults.keys.sorted(), ["TC-SUITE-A", "TC-SUITE-B"])
        XCTAssertEqual(viewModel.caseResults["TC-SUITE-A"]?.status, "passed")
        XCTAssertEqual(viewModel.caseResults["TC-SUITE-B"]?.status, "failed")
        // 批量进度只在运行期间存在，结束后必须清空，避免残留状态被读成"仍在运行"。
        XCTAssertNil(viewModel.suiteRunProgress)
        XCTAssertEqual(URLProtocolSequenceStub.requests.count, 4)
    }

    func testSuiteAggregateUsesRunnableCasesAsDenominator() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.selectedSuite = "rtc"
        viewModel.testCases = [
            makeCase(caseID: "TC-SUITE-A", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-B", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-PARTIAL", suite: "rtc", sdk: "agora_rtc", implementationStatus: "runnable_or_partial"),
            makeCase(caseID: "TC-OTHER", suite: "other", sdk: "agora_rtc"),
        ]
        let session = makeStubSession(responses: [
            createRunJSON(runID: "run-a", status: "passed"),
            runDetailJSON(runID: "run-a", status: "passed", caseID: "TC-SUITE-A", durationMs: 10),
            createRunJSON(runID: "run-b", status: "queued"),
            runDetailJSON(runID: "run-b", status: "failed", caseID: "TC-SUITE-B"),
        ])
        let client = makeClient(session: session)
        viewModel.stopRunDetailPolling()

        _ = try await viewModel.runSelectedSuite(client: client, nodeID: nil)
        viewModel.stopRunDetailPolling()

        // 分母只计 runnable case；非 runnable case 即使有历史结果也不进聚合。
        XCTAssertEqual(viewModel.runnableCases(in: "rtc").map(\.caseID), ["TC-SUITE-A", "TC-SUITE-B"])
        let aggregate = CaseRunPresenter.suiteAggregate(
            of: viewModel.runnableCases(in: "rtc"),
            results: viewModel.caseResults.merging(
                ["TC-SUITE-PARTIAL": RunResponse(runID: "run-stale", status: "passed", stepResults: [])]
            ) { current, _ in current }
        )
        XCTAssertEqual(aggregate, CaseRunPresenter.SuiteAggregate(done: 2, total: 2, passed: 1, failed: 1))
    }

    func testRunDetailPollingUpdatesExistingCaseResultEntry() async throws {
        let viewModel = ConsoleViewModel()
        let session = makeStubSession(responses: [
            runDetailJSON(runID: "run-stream", status: "running", caseID: "TC-STREAM", durationMs: 100),
            runDetailJSON(runID: "run-stream", status: "passed", caseID: "TC-STREAM", durationMs: 250),
            runDetailJSON(runID: "run-stream", status: "passed", caseID: "TC-STREAM", durationMs: 250),
        ])
        let client = makeClient(session: session)

        viewModel.startRunDetailPolling(client: client, runID: "run-stream", intervalNanoseconds: 10_000_000)
        while URLProtocolSequenceStub.requests.count < 2 {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        try await Task.sleep(nanoseconds: 40_000_000)

        // 轮询刷新收敛到同一条目：case 数不增，状态与耗时随 run 推进更新。
        XCTAssertEqual(viewModel.caseResults.count, 1)
        let result = try XCTUnwrap(viewModel.caseResults["TC-STREAM"])
        XCTAssertEqual(result.status, "passed")
        XCTAssertEqual(CaseRunPresenter.totalDurationMs(of: result), 250)
        XCTAssertEqual(URLProtocolSequenceStub.requests.count, 2)
    }

    func testAutorunCleanupRunStaysOutOfCaseResults() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [
            makeCase(caseID: "TC-MAC-AGORA-REAL-LIFECYCLE", suite: "rtc", sdk: "agora_rtc", requiresRuntimeIsolation: true),
            makeCase(caseID: "TC-MAC-AGORA-PREVIEW-CONTROL", suite: "rtc", sdk: "agora_rtc", requiresRuntimeIsolation: true),
            makeCase(caseID: "TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE", suite: "rtc", sdk: "agora_rtc", tags: ["runtime-reset-baseline"]),
        ]
        let session = makeStubSession(responses: [
            createRunJSON(runID: "run-1", status: "passed"),
            runDetailJSON(runID: "run-1", status: "passed"),
            createRunJSON(runID: "run-cleanup", status: "passed"),
            createRunJSON(runID: "run-2", status: "passed"),
            runDetailJSON(runID: "run-2", status: "passed"),
            createRunJSON(runID: "run-cleanup-tail", status: "passed"),
        ])
        let client = makeClient(session: session)

        _ = try await viewModel.runAutorunCases(
            client: client,
            prefix: "TC-MAC-AGORA-",
            caseIDs: ["TC-MAC-AGORA-REAL-LIFECYCLE", "TC-MAC-AGORA-PREVIEW-CONTROL"],
            nodeID: "mac-real-e2e-001"
        )
        viewModel.stopRunDetailPolling()

        // cleanup 是机器内部动作：既不进会话结果，也不占用批量进度。
        XCTAssertEqual(
            viewModel.caseResults.keys.sorted(),
            ["TC-MAC-AGORA-PREVIEW-CONTROL", "TC-MAC-AGORA-REAL-LIFECYCLE"]
        )
        XCTAssertNil(viewModel.suiteRunProgress)
    }

    func testOpenRunSwitchesSelectedCaseWithoutClearingDisplayedState() async throws {
        let viewModel = ConsoleViewModel()
        let firstCase = makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc")
        let secondCase = makeCase(caseID: "TC-AGORA-2", suite: "rtc", sdk: "agora_rtc")
        viewModel.testCases = [firstCase, secondCase]
        viewModel.selectedCase = firstCase
        viewModel.currentRun = RunResponse(runID: "run-0", status: "passed", stepResults: [])
        viewModel.logFilter = "keep"
        viewModel.logLevelFilter = .error
        viewModel.logStepFilter = "keep-step"
        viewModel.showsLifecycleLogs = true
        let session = makeStubSession(responses: [
            runDetailJSON(runID: "run-9", status: "passed", caseID: "TC-AGORA-2", durationMs: 800),
            runDetailJSON(runID: "run-8", status: "failed", caseID: "TC-AGORA-1", durationMs: 900),
        ])
        let client = makeClient(session: session)

        await viewModel.openRun(client: client, runID: "run-9")

        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-AGORA-2")
        XCTAssertEqual(viewModel.currentRun?.runID, "run-9")
        XCTAssertEqual(viewModel.caseResults["TC-AGORA-2"]?.status, "passed")
        // 回看绕过 resetDisplayedRunState：过滤态与展示内容原样保留。
        XCTAssertEqual(viewModel.logFilter, "keep")
        XCTAssertEqual(viewModel.logLevelFilter, .error)
        XCTAssertEqual(viewModel.logStepFilter, "keep-step")
        XCTAssertTrue(viewModel.showsLifecycleLogs)

        await viewModel.openRun(client: client, runID: "run-8")

        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-AGORA-1")
        XCTAssertEqual(viewModel.caseResults.keys.sorted(), ["TC-AGORA-1", "TC-AGORA-2"])
        XCTAssertEqual(viewModel.logFilter, "keep")
    }

    func testOpenRunAlignsSuiteAndSDKSelectionAcrossSuites() async throws {
        let viewModel = ConsoleViewModel()
        let firstCase = makeCase(caseID: "TC-COMPLEX-1", suite: "suite-a", sdk: "mock_complex_sdk")
        let secondCase = makeCase(caseID: "TC-AGORA-1", suite: "suite-b", sdk: "agora_rtc")
        viewModel.testCases = [firstCase, secondCase]
        viewModel.sdkCapabilities = [
            SDKCapability(sdk: "agora_rtc", interfaces: []),
            SDKCapability(sdk: "mock_complex_sdk", interfaces: []),
        ]
        viewModel.selectedSDK = SDKCapability(sdk: "mock_complex_sdk", interfaces: [])
        viewModel.selectedSuite = "suite-a"
        viewModel.selectedCase = firstCase
        let session = makeStubSession(responses: [
            runDetailJSON(runID: "run-9", status: "passed", caseID: "TC-AGORA-1", durationMs: 10),
        ])
        let client = makeClient(session: session)

        await viewModel.openRun(client: client, runID: "run-9")

        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-AGORA-1")
        XCTAssertEqual(viewModel.selectedSuite, "suite-b")
        XCTAssertEqual(viewModel.selectedSDK?.sdk, "agora_rtc")
        // 对齐后的选择必须能通过 Reload 的 syncSelectedCase，回看内容不被清掉。
        viewModel.syncSelectedCase()
        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-AGORA-1")
        XCTAssertEqual(viewModel.currentRun?.runID, "run-9")
    }

    func testOpenRunKeepsSelectionWhenRunCannotBeAttributedToAKnownCase() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc")]
        viewModel.selectedCase = viewModel.testCases.first
        let session = makeStubSession(responses: [
            // run 尚无 stepResults 且不在创建期索引中：结果无处归属，选中态不动。
            runDetailJSON(runID: "run-x", status: "passed"),
            // 归属到一个已不在目录中的 case：结果照常记录，但不切换选中态。
            runDetailJSON(runID: "run-y", status: "passed", caseID: "TC-RETIRED"),
        ])
        let client = makeClient(session: session)

        await viewModel.openRun(client: client, runID: "run-x")

        XCTAssertTrue(viewModel.caseResults.isEmpty)
        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-AGORA-1")

        await viewModel.openRun(client: client, runID: "run-y")

        XCTAssertEqual(viewModel.caseResults.keys.sorted(), ["TC-RETIRED"])
        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-AGORA-1")
    }

    func testOpenRunSurfacesFetchFailureWithoutTouchingSelection() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.testCases = [makeCase(caseID: "TC-AGORA-1", suite: "rtc", sdk: "agora_rtc")]
        viewModel.selectedCase = viewModel.testCases.first
        let session = makePathStubSession(
            responses: ["/api/v1/console/test-runs/run-missing": #"{"detail":"missing token"}"#],
            statusCodes: ["/api/v1/console/test-runs/run-missing": 401]
        )
        let client = makeClient(session: session, token: "bad-token")

        await viewModel.openRun(client: client, runID: "run-missing")

        XCTAssertEqual(viewModel.errorMessage, "HTTP 401: auth token is missing or invalid")
        XCTAssertEqual(viewModel.selectedCase?.caseID, "TC-AGORA-1")
        XCTAssertTrue(viewModel.caseResults.isEmpty)
    }

    func testSingleCaseRunKeepsSessionResultsAndClearsProgress() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.selectedSuite = "rtc"
        viewModel.testCases = [
            makeCase(caseID: "TC-SUITE-A", suite: "rtc", sdk: "agora_rtc"),
            makeCase(caseID: "TC-SUITE-B", suite: "rtc", sdk: "agora_rtc"),
        ]
        viewModel.selectedCase = viewModel.testCases.first
        let session = makeStubSession(responses: [
            createRunJSON(runID: "run-a", status: "passed"),
            runDetailJSON(runID: "run-a", status: "passed", caseID: "TC-SUITE-A", durationMs: 100),
            createRunJSON(runID: "run-b", status: "passed"),
            runDetailJSON(runID: "run-b", status: "passed", caseID: "TC-SUITE-B", durationMs: 200),
            createRunJSON(runID: "run-c", status: "passed"),
            // detail 尚无 stepResults：结果靠创建期的 runID -> caseID 索引归属。
            runDetailJSON(runID: "run-c", status: "passed"),
        ])
        let client = makeClient(session: session)

        _ = try await viewModel.runSelectedSuite(client: client, nodeID: nil)
        XCTAssertNil(viewModel.suiteRunProgress)

        await viewModel.runSelectedCase(client: client, nodeID: nil)

        // 单 case 运行不改变会话结果：suite 跑出的结果仍在，仅更新当前 case 的 run。
        XCTAssertNil(viewModel.suiteRunProgress)
        XCTAssertEqual(viewModel.caseResults.keys.sorted(), ["TC-SUITE-A", "TC-SUITE-B"])
        XCTAssertEqual(viewModel.caseResults["TC-SUITE-A"]?.runID, "run-c")
    }

    func testCancelDuringCreationIgnoresCompetingRunsAndHistoricalDisplay() async throws {
        for displayedStatus in ["passed", "running"] {
            let viewModel = ConsoleViewModel()
            viewModel.selectedCase = makeCase(caseID: "TC-OWN", suite: "rtc", sdk: "agora_rtc")
            viewModel.currentRun = RunResponse(runID: "run-history", status: displayedStatus, stepResults: [])
            let session = makePathStubSession(
                responses: [
                    "/api/v1/test-runs": createRunJSON(runID: "run-own", status: "running"),
                    "/api/v1/console/test-runs": #"{"runs":[{"run_id":"run-other-new","status":"running","case_ids":["TC-OTHER"],"created_at_ms":300},{"run_id":"run-other-old","status":"queued","case_ids":["TC-OTHER"],"created_at_ms":100}]}"#,
                    "/api/v1/test-runs/run-history/cancel": createRunJSON(runID: "run-history", status: "cancelled"),
                    "/api/v1/console/test-runs/run-history": runDetailJSON(runID: "run-history", status: "cancelled"),
                    "/api/v1/test-runs/run-other-new/cancel": createRunJSON(runID: "run-other-new", status: "cancelled"),
                    "/api/v1/console/test-runs/run-other-new": runDetailJSON(runID: "run-other-new", status: "cancelled"),
                    "/api/v1/test-runs/run-own/cancel": createRunJSON(runID: "run-own", status: "cancelled"),
                    "/api/v1/console/test-runs/run-own": runDetailJSON(runID: "run-own", status: "cancelled", caseID: "TC-OWN"),
                ],
                gatedPaths: ["/api/v1/test-runs"]
            )
            let client = makeClient(session: session)
            let run = Task { await viewModel.runSelectedCase(client: client, nodeID: "mac-own") }
            try await waitForRecordedRequest(path: "/api/v1/test-runs")

            await viewModel.cancelCurrentRun(client: makeClient(session: session, token: "different-current-token"))

            XCTAssertFalse(URLProtocolPathStub.requests.contains { $0.url?.path.hasSuffix("/cancel") == true })
            XCTAssertFalse(URLProtocolPathStub.requests.contains { $0.url?.path == "/api/v1/console/test-runs" })
            URLProtocolPathStub.release("/api/v1/test-runs")
            await run.value
            let cancellations = URLProtocolPathStub.requests.filter { $0.url?.path.hasSuffix("/cancel") == true }
            XCTAssertEqual(cancellations.map { $0.url?.path }, ["/api/v1/test-runs/run-own/cancel"])
            XCTAssertEqual(cancellations.first?.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
            XCTAssertEqual(viewModel.currentRun?.runID, "run-own")
            XCTAssertEqual(viewModel.currentRun?.status, "cancelled")
        }
    }

    func testSlowOldServerDetailCannotOverwriteNewServerOrRepopulateCache() async throws {
        let viewModel = ConsoleViewModel()
        let session = makePathStubSession(
            responses: [
                "/api/v1/console/test-runs/run-old": runDetailJSON(runID: "run-old", status: "failed", caseID: "TC-OLD"),
                "/api/v1/console/test-runs/run-new": runDetailJSON(runID: "run-new", status: "passed", caseID: "TC-NEW"),
            ],
            gatedPaths: ["/api/v1/console/test-runs/run-old"]
        )
        let oldClient = makeClient(session: session)
        let newClient = BeaconServerClient(baseURL: URL(string: "http://new-server.invalid")!, token: "token-1", session: session)
        let oldRead = Task { await viewModel.openRun(client: oldClient, runID: "run-old") }
        try await waitForRecordedRequest(path: "/api/v1/console/test-runs/run-old")
        await viewModel.openRun(client: newClient, runID: "run-new")
        URLProtocolPathStub.release("/api/v1/console/test-runs/run-old")
        await oldRead.value

        XCTAssertEqual(viewModel.currentRun?.runID, "run-new")
        XCTAssertEqual(viewModel.caseResults.keys.sorted(), ["TC-NEW"])
        XCTAssertNil(viewModel.errorMessage)
    }

    func testCancelKnownExecutionKeepsItsClientAndIDWhileHistoryIsDisplayed() async throws {
        let viewModel = ConsoleViewModel()
        viewModel.selectedCase = makeCase(caseID: "TC-OWN", suite: "rtc", sdk: "agora_rtc")
        let session = makePathStubSession(
            responses: [
                "/api/v1/test-runs": createRunJSON(runID: "run-own", status: "queued"),
                "/api/v1/console/test-runs/run-own": runDetailJSON(runID: "run-own", status: "cancelled", caseID: "TC-OWN"),
                "/api/v1/console/test-runs/run-history": runDetailJSON(runID: "run-history", status: "running", caseID: "TC-HISTORY"),
                "/api/v1/test-runs/run-own/cancel": createRunJSON(runID: "run-own", status: "running"),
            ],
            gatedPaths: ["/api/v1/console/test-runs/run-own"]
        )
        let client = makeClient(session: session)
        let run = Task { await viewModel.runSelectedCase(client: client, nodeID: "mac-own") }
        try await waitForRecordedRequest(path: "/api/v1/console/test-runs/run-own")
        await viewModel.openRun(client: client, runID: "run-history")
        XCTAssertEqual(viewModel.currentRun?.runID, "run-history")
        let unrelatedClient = BeaconServerClient(baseURL: URL(string: "http://unrelated.invalid")!, token: "other-token", session: session)

        await viewModel.cancelCurrentRun(client: unrelatedClient)
        URLProtocolPathStub.release("/api/v1/console/test-runs/run-own")
        await run.value

        let cancellations = URLProtocolPathStub.requests.filter { $0.url?.path.hasSuffix("/cancel") == true }
        XCTAssertEqual(cancellations.map { $0.url?.path }, ["/api/v1/test-runs/run-own/cancel"])
        XCTAssertEqual(cancellations.first?.url?.host, "127.0.0.1")
        XCTAssertEqual(cancellations.first?.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
        XCTAssertEqual(viewModel.currentRun?.status, "cancelled")
    }

    func testConnectionSwitchClearsCachedResultBeforeTheSameCaseRunsElsewhere() async throws {
        let viewModel = ConsoleViewModel()
        let session = makePathStubSession(responses: [
            "/api/v1/console/test-runs/run-old": runDetailJSON(runID: "run-old", status: "failed", caseID: "TC-SHARED"),
        ])
        await viewModel.openRun(client: makeClient(session: session), runID: "run-old")
        XCTAssertEqual(viewModel.caseResults["TC-SHARED"]?.status, "failed")
        let newClient = BeaconServerClient(baseURL: URL(string: "http://new-server.invalid")!, token: "token-1", session: session)

        viewModel.useConnection(newClient)
        viewModel.selectCase(makeCase(caseID: "TC-SHARED", suite: "rtc", sdk: "agora_rtc"))

        XCTAssertNil(viewModel.currentRun)
        XCTAssertNil(viewModel.currentRunDetail)
        XCTAssertTrue(viewModel.caseRunDetails.isEmpty)
        XCTAssertTrue(viewModel.currentObservations.isEmpty)
        XCTAssertTrue(viewModel.logRows.isEmpty)
    }

    func testAutorunOutputStatusPreservesFailureBeforeCancellationAndNeverPassesAnAbortedBatch() {
        let samples: [(statuses: [String], aborted: Bool, expected: String)] = [
            (["passed"], false, "passed"),
            (["passed"], true, "cancelled"),
            (["passed", "cancelled"], false, "cancelled"),
            (["passed", "canceled"], false, "cancelled"),
            (["failed", "cancelled"], true, "failed"),
            ([], true, "cancelled"),
            (["queued"], false, "failed"),
        ]
        for sample in samples {
            let runs = sample.statuses.enumerated().map { index, status in
                RunResponse(runID: "run-\(index)", status: status, stepResults: [])
            }
            XCTAssertEqual(ConsoleViewModel.autorunStatus(runs: runs, isAborted: sample.aborted), sample.expected)
        }
    }

    private func makeClient(session: URLSession, token: String = "token-1") -> BeaconServerClient {
        BeaconServerClient(baseURL: URL(string: "http://127.0.0.1:8000")!, token: token, session: session)
    }

    private func createRunJSON(runID: String, status: String) -> String {
        #"{"run_id":"\#(runID)","status":"\#(status)","results":[]}"#
    }

    /// 构造 console run detail 响应；省略 `caseID` 表示该 run 尚无 stepResults。
    private func runDetailJSON(runID: String, status: String, caseID: String? = nil, durationMs: Int = 0) -> String {
        let results: String
        if let caseID {
            results = #"[{"case_id":"\#(caseID)","step_id":"step-1","status":"\#(status)","artifacts":[],"duration_ms":\#(durationMs)}]"#
        } else {
            results = "[]"
        }
        return #"{"run":{"run_id":"\#(runID)","status":"\#(status)","results":\#(results)},"report":{"run_id":"\#(runID)","format":"json","summary":{}},"logs":[]}"#
    }

    private func makeCase(
        caseID: String,
        suite: String,
        sdk: String,
        implementationStatus: String = "runnable",
        tags: [String] = [],
        requiresRuntimeIsolation: Bool = false
    ) -> TestCaseSummary {
        TestCaseSummary(
            caseID: caseID,
            name: caseID,
            platform: "mac",
            suite: suite,
            tags: tags,
            implementationStatus: implementationStatus,
            steps: [
                .object([
                    "packet": .object([
                        "data": .object([
                            "target": .object([
                                "sdk": .string(sdk),
                                "class_name": .string("RtcEngine"),
                                "function": .string("initialize"),
                            ])
                        ])
                    ])
                ])
            ],
            requiresRuntimeIsolation: requiresRuntimeIsolation
        )
    }

    private func makeStubSession(responses: [String]) -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [URLProtocolSequenceStub.self]
        URLProtocolSequenceStub.requests = []
        URLProtocolSequenceStub.responses = responses.map { Data($0.utf8) }
        return URLSession(configuration: config)
    }

    private func makePathStubSession(
        responses: [String: String],
        statusCodes: [String: Int] = [:],
        gatedPaths: Set<String> = []
    ) -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [URLProtocolPathStub.self]
        URLProtocolPathStub.configure(
            responses: responses.mapValues { Data($0.utf8) },
            statusCodes: statusCodes,
            gatedPaths: gatedPaths
        )
        return URLSession(configuration: config)
    }

    /// 有界等待指定 path 的请求被记录；超时不抛错，失败信息由调用方紧跟的断言给出。
    private func waitForRecordedRequest(path: String, timeoutTicks: Int = 400) async throws {
        var waits = 0
        while !URLProtocolPathStub.requests.contains(where: { $0.url?.path == path }), waits < timeoutTicks {
            try await Task.sleep(nanoseconds: 1_000_000)
            waits += 1
        }
    }

    private func httpBodyData(for request: URLRequest) -> Data? {
        if let body = request.httpBody {
            return body
        }
        guard let stream = request.httpBodyStream else {
            return nil
        }
        stream.open()
        defer { stream.close() }
        let bufferSize = 4096
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: bufferSize)
        defer { buffer.deallocate() }
        var data = Data()
        while stream.hasBytesAvailable {
            let read = stream.read(buffer, maxLength: bufferSize)
            if read <= 0 {
                break
            }
            data.append(buffer, count: read)
        }
        return data
    }
}

final class URLProtocolSequenceStub: URLProtocol {
    static var requests: [URLRequest] = []
    static var responses: [Data] = []

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        Self.requests.append(request)
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Self.responses.removeFirst())
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class URLProtocolPathStub: URLProtocol {
    private static let lock = NSLock()
    static var requests: [URLRequest] = []
    private static var responses: [String: Data] = [:]
    private static var statusCodes: [String: Int] = [:]
    /// 挂起集合：命中的 path 在 `release(_:)` 放行前不返回响应，用于确定性地制造
    /// 「请求仍在飞行中」的窗口；放行后该 path 恢复为立即响应。
    private static var gatedPaths: Set<String> = []
    private static var pendingDeliveries: [String: [() -> Void]] = [:]

    static func configure(
        responses: [String: Data],
        statusCodes: [String: Int],
        gatedPaths: Set<String> = []
    ) {
        lock.withLock {
            requests = []
            self.responses = responses
            self.statusCodes = statusCodes
            self.gatedPaths = gatedPaths
            pendingDeliveries = [:]
        }
    }

    /// 放行挂起的 path：已挂起的响应立即送达，该 path 之后的请求直接通过。
    static func release(_ path: String) {
        let deliveries = lock.withLock { () -> [() -> Void] in
            gatedPaths.remove(path)
            return pendingDeliveries.removeValue(forKey: path) ?? []
        }
        deliveries.forEach { $0() }
    }

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        let path = request.url?.path ?? ""
        let responsePayload = Self.lock.withLock {
            Self.requests.append(request)
            return (
                statusCode: Self.statusCodes[path] ?? 200,
                data: Self.responses[path] ?? Data(#"{"detail":"missing stub response"}"#.utf8),
                isGated: Self.gatedPaths.contains(path)
            )
        }
        let deliver = {
            let response = HTTPURLResponse(
                url: self.request.url!,
                statusCode: responsePayload.statusCode,
                httpVersion: nil,
                headerFields: nil
            )!
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: responsePayload.data)
            self.client?.urlProtocolDidFinishLoading(self)
        }
        if responsePayload.isGated {
            Self.lock.withLock { Self.pendingDeliveries[path, default: []].append(deliver) }
            return
        }
        deliver()
    }

    override func stopLoading() {}
}

private extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
