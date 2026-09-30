import XCTest

@testable import BeaconMacTestConsole

@MainActor
final class RunCoordinatorTests: XCTestCase {
    func testBeginningNewBatchClearsPriorAbortIntent() {
        let coordinator = RunCoordinator()

        coordinator.abortBatch()
        XCTAssertTrue(coordinator.isAborted)

        coordinator.beginBatch()

        XCTAssertFalse(coordinator.isAborted)
    }

    func testCancellingPreCaseCleanupStopsBeforeTheNextCase() async throws {
        try await assertCleanupCancellation(testCases: [makeCase("TC-FIRST"), makeCase("TC-NEXT", isolated: true)])
    }

    func testCancellingFinalCleanupPreservesItsCancelledOutcome() async throws {
        try await assertCleanupCancellation(testCases: [makeCase("TC-FIRST", isolated: true)])
    }

    func testRealCleanupFailureStillThrowsAndStopsBeforeNextCase() async throws {
        let coordinator = RunCoordinator()
        let cases = [makeCase("TC-FIRST"), makeCase("TC-NEXT", isolated: true)]
        let client = makeClient(cleanupStatus: "failed", gated: false)
        do {
            _ = try await autorun(coordinator, cases: cases, client: client)
            XCTFail("真正失败的 cleanup 必须拒绝继续执行")
        } catch let error as ConsoleAutorunError {
            XCTAssertEqual(error, .cleanupFailed(runID: "run-cleanup", status: "failed"))
        }
        XCTAssertEqual(AutorunCleanupURLProtocol.createdCaseIDs, ["TC-FIRST", "TC-CLEANUP"])
    }

    func testAbortAfterPreCaseCleanupPassesStillStopsBeforeTheNextCase() async throws {
        try await assertCleanupCancellation(
            testCases: [makeCase("TC-FIRST"), makeCase("TC-NEXT", isolated: true)], cleanupStatus: "passed"
        )
    }

    func testAbortAfterFinalCleanupPassesKeepsThePassedFactAndCancelledBatch() async throws {
        try await assertCleanupCancellation(testCases: [makeCase("TC-FIRST", isolated: true)], cleanupStatus: "passed")
    }

    func testFailedCleanupRemainsFailureEvenWhenTheUserAborts() async throws {
        let coordinator = RunCoordinator()
        let cases = [makeCase("TC-FIRST"), makeCase("TC-NEXT", isolated: true)]
        let client = makeClient(cleanupStatus: "failed", gated: true)
        let batch = Task { try await self.autorun(coordinator, cases: cases, client: client) }
        for _ in 0..<400 {
            if AutorunCleanupURLProtocol.cleanupReadIsPending { break }
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        XCTAssertTrue(AutorunCleanupURLProtocol.cleanupReadIsPending)
        coordinator.abortBatch()
        AutorunCleanupURLProtocol.releaseCleanupRead()
        do {
            _ = try await batch.value
            XCTFail("用户中止不能掩盖实际失败的 cleanup")
        } catch let error as ConsoleAutorunError {
            XCTAssertEqual(error, .cleanupFailed(runID: "run-cleanup", status: "failed"))
        }
        XCTAssertEqual(AutorunCleanupURLProtocol.createdCaseIDs, ["TC-FIRST", "TC-CLEANUP"])
    }

    private func assertCleanupCancellation(testCases: [TestCaseSummary], cleanupStatus: String = "cancelled") async throws {
        let coordinator = RunCoordinator()
        let client = makeClient(cleanupStatus: cleanupStatus, gated: true)
        let batch = Task { try await self.autorun(coordinator, cases: testCases, client: client) }
        for _ in 0..<400 {
            if AutorunCleanupURLProtocol.cleanupReadIsPending { break }
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        XCTAssertTrue(AutorunCleanupURLProtocol.cleanupReadIsPending)
        try await coordinator.cancelActiveRun()
        AutorunCleanupURLProtocol.releaseCleanupRead()
        do {
            let runs = try await batch.value
            XCTAssertEqual(runs.map { $0.0.caseID }, ["TC-FIRST", "TC-CLEANUP"])
            XCTAssertEqual(runs.last?.1.status, cleanupStatus)
            XCTAssertEqual(ConsoleViewModel.autorunStatus(runs: runs.map { $0.1 }, isAborted: coordinator.isAborted), "cancelled")
        } catch {
            XCTFail("用户取消 cleanup 应自然结束，不能变成 cleanupFailed: \(error)")
        }
        XCTAssertEqual(AutorunCleanupURLProtocol.createdCaseIDs, ["TC-FIRST", "TC-CLEANUP"])
        XCTAssertEqual(AutorunCleanupURLProtocol.cancelledRunIDs, ["run-cleanup"])
    }

    private func autorun(
        _ coordinator: RunCoordinator,
        cases: [TestCaseSummary],
        client: BeaconServerClient
    ) async throws -> [(TestCaseSummary, RunResponse)] {
        try await coordinator.runAutorun(
            cases, catalog: cases + [makeCase("TC-CLEANUP", tags: [AutorunCaseTag.runtimeResetBaseline])],
            client: client, nodeID: "mac-own",
            onRunCreated: { _, _, _ in }, onDetail: { _, _ in }, onProgress: { _ in }
        )
    }

    private func makeCase(_ caseID: String, isolated: Bool = false, tags: [String] = []) -> TestCaseSummary {
        TestCaseSummary(
            caseID: caseID, name: caseID, platform: "mac", suite: "rtc", tags: tags,
            implementationStatus: "runnable", sdkNames: ["agora_rtc"], requiresRuntimeIsolation: isolated
        )
    }

    private func makeClient(cleanupStatus: String, gated: Bool) -> BeaconServerClient {
        AutorunCleanupURLProtocol.configure(cleanupStatus: cleanupStatus, gated: gated)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AutorunCleanupURLProtocol.self]
        return BeaconServerClient(
            baseURL: URL(string: "http://console-test.invalid")!, token: "test-token",
            session: URLSession(configuration: configuration)
        )
    }

}


/// 只挂起 cleanup detail，确定性保留取得 cleanup ID 后的取消窗口。
private final class AutorunCleanupURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var cleanupStatus = "passed"
    private static var gated = false
    private static var pendingCleanup: (() -> Void)?
    private static var creations: [String] = []
    private static var cancellations: [String] = []

    static var createdCaseIDs: [String] { lock.withLock { creations } }
    static var cancelledRunIDs: [String] { lock.withLock { cancellations } }
    static var cleanupReadIsPending: Bool { lock.withLock { pendingCleanup != nil } }

    static func configure(cleanupStatus: String, gated: Bool) {
        lock.withLock {
            self.cleanupStatus = cleanupStatus
            self.gated = gated
            pendingCleanup = nil
            creations = []
            cancellations = []
        }
    }

    static func releaseCleanupRead() {
        let delivery = lock.withLock { () -> (() -> Void)? in
            gated = false
            defer { pendingCleanup = nil }
            return pendingCleanup
        }
        delivery?()
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let path = request.url!.path
        let payload: String = Self.lock.withLock {
            if path == "/api/v1/test-runs" {
                let body = requestBody()
                let requestJSON = try! JSONSerialization.jsonObject(with: body) as! [String: Any]
                let caseID = (requestJSON["case_ids"] as! [String]).first!
                Self.creations.append(caseID)
                let runID = caseID == "TC-CLEANUP" ? "run-cleanup" : "run-\(caseID)"
                return #"{"run_id":"\#(runID)","status":"queued","results":[]}"#
            }
            if path.hasSuffix("/cancel") {
                let runID = String(path.split(separator: "/").dropLast().last!)
                Self.cancellations.append(runID)
                return #"{"run_id":"\#(runID)","status":"running","results":[]}"#
            }
            let runID = String(path.split(separator: "/").last!)
            let status = runID == "run-cleanup" ? Self.cleanupStatus : "passed"
            return #"{"run":{"run_id":"\#(runID)","status":"\#(status)","results":[]},"report":{"run_id":"\#(runID)","format":"json","summary":{}},"logs":[]}"#
        }
        let delivery = {
            let response = HTTPURLResponse(url: self.request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: Data(payload.utf8))
            self.client?.urlProtocolDidFinishLoading(self)
        }
        let held = Self.lock.withLock { () -> Bool in
            guard path == "/api/v1/console/test-runs/run-cleanup", Self.gated else { return false }
            Self.pendingCleanup = delivery
            return true
        }
        if !held { delivery() }
    }

    private func requestBody() -> Data {
        if let body = request.httpBody { return body }
        let stream = request.httpBodyStream!
        stream.open()
        defer { stream.close() }
        var body = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            body.append(contentsOf: buffer.prefix(count))
        }
        return body
    }

    override func stopLoading() {}
}
