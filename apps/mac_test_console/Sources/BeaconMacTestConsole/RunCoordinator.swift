import Foundation

/// Console run 生命周期协调器：拥有批次中止意图和唯一的 detail 轮询任务。
@MainActor
final class RunCoordinator {
    private var pollingTask: Task<Void, Never>?
    /// Cancel 置位后，suite / autorun 在 case 与 cleanup 边界停止提交下一条用例。
    /// 当前 run 由本协调器固定的 client 与确切 ID 取消。
    private(set) var isAborted = false
    private var executionClient: BeaconServerClient?
    private var activeRunID: String?

    func beginBatch(client: BeaconServerClient? = nil) {
        isAborted = false
        executionClient = client
        activeRunID = nil
    }

    func abortBatch() {
        isAborted = true
    }

    /// 创建响应未返回时只登记意图；拿到本批确切的 run ID 后再取消。
    func cancelActiveRun() async throws {
        abortBatch()
        guard let client = executionClient, let runID = activeRunID else { return }
        _ = try await client.cancelRun(runID: runID)
    }

    private func createRun(_ testCase: TestCaseSummary, client: BeaconServerClient, nodeID: String?) async throws -> RunResponse {
        activeRunID = nil
        let run = try await client.createRun(caseSummary: testCase, nodeID: nodeID)
        activeRunID = run.runID
        if isAborted && !run.isTerminal {
            _ = try await client.cancelRun(runID: run.runID)
        }
        return run
    }

    func startPolling(
        client: BeaconServerClient,
        runID: String,
        intervalNanoseconds: UInt64,
        onDetail: @escaping (ConsoleRunDetail) -> Void,
        onError: @escaping (String) -> Void
    ) {
        stopPolling()
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    try await Task.sleep(nanoseconds: intervalNanoseconds)
                    guard !Task.isCancelled else { return }
                    let detail = try await client.runDetail(runID: runID)
                    guard !Task.isCancelled else { return }
                    onDetail(detail)
                    if detail.run.isTerminal {
                        self?.stopPolling()
                        return
                    }
                } catch is CancellationError {
                    return
                } catch {
                    guard !Task.isCancelled else { return }
                    onError(String(describing: error))
                }
            }
        }
    }

    func stopPolling() {
        pollingTask?.cancel()
        pollingTask = nil
    }

    func runSingle(
        _ testCase: TestCaseSummary,
        client: BeaconServerClient,
        nodeID: String?,
        onRunCreated: (TestCaseSummary, RunResponse, Bool) -> Void,
        onDetail: @escaping (ConsoleRunDetail, Bool) -> Void
    ) async throws -> RunResponse {
        beginBatch(client: client)
        return try await submit(
            testCase, shouldDisplayDetail: true, client: client, nodeID: nodeID,
            onRunCreated: onRunCreated, onDetail: onDetail
        )
    }

    func runSuite(
        _ testCases: [TestCaseSummary],
        client: BeaconServerClient,
        nodeID: String?,
        onRunCreated: (TestCaseSummary, RunResponse, Bool) -> Void,
        onDetail: @escaping (ConsoleRunDetail, Bool) -> Void,
        onProgress: (SuiteRunProgress?) -> Void
    ) async throws -> [(TestCaseSummary, RunResponse)] {
        beginBatch(client: client)
        onProgress(SuiteRunProgress(done: 0, total: testCases.count))
        defer { onProgress(nil) }
        var runs: [(TestCaseSummary, RunResponse)] = []
        for (index, testCase) in testCases.enumerated() {
            if isAborted { break }
            let run = try await submit(
                testCase, shouldDisplayDetail: false, client: client, nodeID: nodeID,
                onRunCreated: onRunCreated, onDetail: onDetail
            )
            runs.append((testCase, run))
            onProgress(SuiteRunProgress(done: index + 1, total: testCases.count))
            if run.status == "cancelled" { break }
        }
        return runs
    }

    func runAutorun(
        _ testCases: [TestCaseSummary],
        catalog: [TestCaseSummary],
        client: BeaconServerClient,
        nodeID: String?,
        onRunCreated: (TestCaseSummary, RunResponse, Bool) -> Void,
        onDetail: @escaping (ConsoleRunDetail, Bool) -> Void,
        onProgress: (SuiteRunProgress?) -> Void
    ) async throws -> [(TestCaseSummary, RunResponse)] {
        beginBatch(client: client)
        onProgress(SuiteRunProgress(done: 0, total: testCases.count))
        defer { onProgress(nil) }
        var runs: [(TestCaseSummary, RunResponse)] = []
        for (index, testCase) in testCases.enumerated() {
            if isAborted { break }
            if index > 0 && testCase.requiresRuntimeIsolation {
                let cleanupCase = try cleanupCase(for: testCase, catalog: catalog)
                let created = try await createRun(cleanupCase, client: client, nodeID: nodeID)
                let cleanup = try await awaitTerminal(created, client: client)
                if (isAborted && cleanup.status == "passed") || cleanup.status == "cancelled" || cleanup.status == "canceled" {
                    runs.append((cleanupCase, cleanup))
                    return runs
                }
                try requirePassedCleanup(cleanup)
            }
            let run = try await submit(
                testCase, shouldDisplayDetail: false, client: client, nodeID: nodeID,
                onRunCreated: onRunCreated, onDetail: onDetail
            )
            runs.append((testCase, run))
            onProgress(SuiteRunProgress(done: index + 1, total: testCases.count))
            if run.status == "cancelled" { break }
        }
        if !isAborted, let lastIsolated = testCases.last(where: \.requiresRuntimeIsolation) {
            let cleanupCase = try cleanupCase(for: lastIsolated, catalog: catalog)
            let created = try await createRun(cleanupCase, client: client, nodeID: nodeID)
            let cleanup = try await awaitTerminal(created, client: client)
            if (isAborted && cleanup.status == "passed") || cleanup.status == "cancelled" || cleanup.status == "canceled" {
                runs.append((cleanupCase, cleanup))
                return runs
            }
            try requirePassedCleanup(cleanup)
        }
        return runs
    }

    /// 每份 detail 都交给消费方缓存；`shouldDisplayDetail` 只控制是否切换当前详情。
    private func submit(
        _ testCase: TestCaseSummary,
        shouldDisplayDetail: Bool,
        client: BeaconServerClient,
        nodeID: String?,
        onRunCreated: (TestCaseSummary, RunResponse, Bool) -> Void,
        onDetail: @escaping (ConsoleRunDetail, Bool) -> Void
    ) async throws -> RunResponse {
        let run = try await createRun(testCase, client: client, nodeID: nodeID)
        onRunCreated(testCase, run, shouldDisplayDetail)
        return try await awaitTerminal(run, client: client) { detail in onDetail(detail, shouldDisplayDetail) }
    }

    private func awaitTerminal(
        _ run: RunResponse,
        client: BeaconServerClient,
        onDetail: ((ConsoleRunDetail) -> Void)? = nil
    ) async throws -> RunResponse {
        defer { activeRunID = nil }
        if run.isTerminal && onDetail == nil { return run }
        for _ in 0..<240 {
            let detail = try await client.runDetail(runID: run.runID)
            onDetail?(detail)
            if detail.run.isTerminal { return detail.run }
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        throw ConsoleAutorunError.cleanupFailed(runID: run.runID, status: "timed_out")
    }

    private func requirePassedCleanup(_ run: RunResponse) throws {
        guard run.status == "passed" else {
            throw ConsoleAutorunError.cleanupFailed(runID: run.runID, status: run.status)
        }
    }

    private func cleanupCase(for testCase: TestCaseSummary, catalog: [TestCaseSummary]) throws -> TestCaseSummary {
        let sdkNames = testCase.containedSDKNames()
        let candidates = catalog.filter { candidate in
            candidate.platform == testCase.platform
                && candidate.implementationStatus == "runnable"
                && candidate.tags.contains(AutorunCaseTag.runtimeResetBaseline)
                && candidate.containedSDKNames().contains(where: sdkNames.contains)
        }
        guard candidates.count == 1, let cleanup = candidates.first else {
            throw ConsoleAutorunError.cleanupCaseNotFound(caseID: testCase.caseID)
        }
        return cleanup
    }
}
