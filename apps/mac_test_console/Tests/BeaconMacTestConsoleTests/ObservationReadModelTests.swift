import Foundation
import XCTest
@testable import BeaconMacTestConsole

@MainActor
final class ObservationReadModelTests: XCTestCase {
    override func tearDown() {
        URLProtocolStub.requestHandler = nil
        super.tearDown()
    }

    func testCursorResumesAfterFailureAndIgnoresRepeatedPageItems() async throws {
        let feed = ObservationFeed()
        let client = makeClient()
        var failsOnce = true
        URLProtocolStub.requestHandler = { request in
            let cursor = Self.cursor(in: request)
            if cursor == 1 && failsOnce {
                failsOnce = false
                return Self.response(request, status: 503, body: "{}")
            }
            let body: String
            switch cursor {
            case 0: body = Self.page([Self.record(1, value: 0)], hasMore: true)
            case 1: body = Self.page([Self.record(1, value: 0), Self.record(2)], hasMore: false)
            default: body = Self.page([], after: cursor, hasMore: false)
            }
            return Self.response(request, status: 200, body: body)
        }

        do {
            try await feed.refresh(runID: "run-1", client: client)
            XCTFail("second page should fail")
        } catch let error as BeaconServerClientError {
            XCTAssertEqual(error, .httpStatus(503, "{}"))
        }
        XCTAssertEqual(feed.cursor(for: "run-1"), 1)
        XCTAssertEqual(feed.records(for: "run-1").count, 1)

        try await feed.refresh(runID: "run-1", client: client)
        try await feed.refresh(runID: "run-1", client: client)
        XCTAssertEqual(feed.records(for: "run-1").map(\.cursor), [1, 2])
        XCTAssertEqual(feed.records(for: "run-1").first?.valueText, "0")
        XCTAssertEqual(feed.records(for: "run-1").last?.valueText, "Not reported")
        XCTAssertEqual(feed.cursor(for: "run-1"), 2)
    }

    func testLongRunDrainsPagesAndKeepsRunCursorsIndependent() async throws {
        let feed = ObservationFeed()
        let client = makeClient()
        URLProtocolStub.requestHandler = { request in
            let cursor = Self.cursor(in: request)
            let runID = request.url?.path.contains("run-2") == true ? "run-2" : "run-1"
            let last = runID == "run-2" ? 1 : 251
            let end = min(cursor + 200, last)
            let items = cursor < end ? ((cursor + 1)...end).map { Self.record($0) } : []
            return Self.response(
                request, status: 200,
                body: Self.page(items, after: cursor, hasMore: end < last)
            )
        }

        try await feed.refresh(runID: "run-1", client: client)
        try await feed.refresh(runID: "run-2", client: client)
        XCTAssertEqual(feed.records(for: "run-1").count, 251)
        XCTAssertEqual(feed.cursor(for: "run-1"), 251)
        XCTAssertEqual(feed.records(for: "run-2").count, 1)
        XCTAssertEqual(feed.cursor(for: "run-2"), 1)
    }

    func testTargetRunDecodesCaseIdentityWithoutLegacySteps() throws {
        let run = try JSONDecoder.beacon.decode(
            RunResponse.self,
            from: Data(#"{"run_id":"run-1","status":"cancelled","execution_mode":"target","results":[],"cases":[{"case_id":"case-1"}]}"#.utf8)
        )
        XCTAssertEqual(run.cases?.first?.caseID, "case-1")
        XCTAssertTrue(run.isTerminal)
    }

    func testServerProjectionSelectsObservationCursorForCancelledRun() throws {
        let detail = try JSONDecoder.beacon.decode(
            ConsoleRunDetail.self,
            from: Data(#"{"run":{"run_id":"run-1","status":"cancelled","results":[]},"report":{"run_id":"run-1","format":"json","summary":{}},"logs":[],"observation_cursor_enabled":true}"#.utf8)
        )
        XCTAssertEqual(detail.observationCursorEnabled, true)
    }

    func testEmptyPageAndStalledCursorKeepConfirmedState() async throws {
        let feed = ObservationFeed()
        let client = makeClient()
        URLProtocolStub.requestHandler = { request in
            Self.response(request, status: 200, body: Self.page([], hasMore: false))
        }
        try await feed.refresh(runID: "run-1", client: client)
        XCTAssertEqual(feed.records(for: "run-1"), [])
        XCTAssertEqual(feed.cursor(for: "run-1"), 0)

        URLProtocolStub.requestHandler = { request in
            Self.response(request, status: 200, body: Self.page([], hasMore: true))
        }
        do {
            try await feed.refresh(runID: "run-1", client: client)
            XCTFail("non-advancing page must fail")
        } catch ObservationPageError.stalledCursor {
            XCTAssertEqual(feed.cursor(for: "run-1"), 0)
        }
    }

    func testOperationAndMetricDisplayKeepsMissingValueDistinctFromZero() throws {
        let metric = try JSONDecoder.beacon.decode(
            ConsoleObservation.self,
            from: Data(#"{"observation_id":"metric-1","cursor":1,"kind":"metric","case_id":"case-1","device_role":"primary","target":{"sdk":"mock","interface":"metrics","name":"fps"},"payload":{"unit":"fps"}}"#.utf8)
        )
        let operation = try JSONDecoder.beacon.decode(
            ConsoleObservation.self,
            from: Data(#"{"observation_id":"call-1","cursor":2,"kind":"operation","case_id":"case-1","device_role":"primary","target":{"sdk":"mock","interface":"engine","function":"join"},"payload":{"operation_type":"call","outcome":"failed","message":"denied"}}"#.utf8)
        )
        XCTAssertEqual(metric.valueText, "Not reported")
        XCTAssertEqual(operation.title, "call · join")
        XCTAssertEqual(operation.valueText, "failed · denied")
    }

    func testExecutionRecordPresentationRemovesLogNoiseAndKeepsEventValues() throws {
        let event = try JSONDecoder.beacon.decode(
            ConsoleObservation.self,
            from: Data(#"{"observation_id":"event-1","cursor":1,"kind":"event","case_id":"case-1","device_role":"primary","target":{"name":"onJoinChannelSuccess"},"payload":{"channel":"real-smoke","uid":1001,"elapsed":0,"joined":false}}"#.utf8)
        )
        let wait = try JSONDecoder.beacon.decode(
            ConsoleObservation.self,
            from: Data(#"{"observation_id":"wait-1","cursor":2,"kind":"operation","case_id":"case-1","device_role":"unbound","target":{"name":"onJoinChannelSuccess"},"payload":{"operation_type":"wait","outcome":"matched","message":" "}}"#.utf8)
        )
        let log = try JSONDecoder.beacon.decode(
            ConsoleObservation.self,
            from: Data(#"{"observation_id":"log-1","cursor":3,"kind":"log","case_id":"__unscoped__","device_role":"unbound","target":{},"payload":{"message":"Runner process started"}}"#.utf8)
        )
        XCTAssertEqual([log, event, wait].filter(\.isExecutionRecord).map(\.id), ["event-1", "wait-1"])
        XCTAssertEqual(event.detailText, "primary · channel: real-smoke · elapsed: 0 · joined: false · uid: 1001")
        XCTAssertEqual(wait.detailText, "matched")
    }

    private func makeClient() -> BeaconServerClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [URLProtocolStub.self]
        return BeaconServerClient(
            baseURL: URL(string: "http://127.0.0.1:8000")!, token: "token-1",
            session: URLSession(configuration: config)
        )
    }

    private static func cursor(in request: URLRequest) -> Int {
        let components = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)
        return Int(components?.queryItems?.first(where: { $0.name == "after_cursor" })?.value ?? "0") ?? 0
    }

    private static func response(
        _ request: URLRequest, status: Int, body: String
    ) -> (HTTPURLResponse, Data) {
        (HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
    }

    private static func page(_ items: [[String: Any]], after: Int = 0, hasMore: Bool) -> String {
        let data = try! JSONSerialization.data(withJSONObject: [
            "items": items, "next_cursor": items.last?["cursor"] ?? after, "has_more": hasMore
        ])
        return String(decoding: data, as: UTF8.self)
    }

    private static func record(_ cursor: Int, value: Int? = nil) -> [String: Any] {
        [
            "observation_id": "observation-\(cursor)", "cursor": cursor, "kind": "metric",
            "case_id": "case-1", "device_role": "primary",
            "target": ["sdk": "mock", "interface": "metrics", "name": "level"],
            "payload": value.map { ["value": $0] } ?? [:]
        ]
    }
}
