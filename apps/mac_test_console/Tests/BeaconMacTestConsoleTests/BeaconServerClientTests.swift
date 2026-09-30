import Foundation
import XCTest
@testable import BeaconMacTestConsole

final class BeaconServerClientTests: XCTestCase {
    override func tearDown() {
        URLProtocolStub.requestHandler = nil
        super.tearDown()
    }

    func testStatusDecodesServerStatus() async throws {
        let client = makeClient(body: #"{"service":"beacon-server","status":"ok","version":"0.1.0-p0"}"#)

        let status = try await client.status()

        XCTAssertEqual(status.version, "0.1.0-p0")
        // 连接状态机依赖探活不带鉴权：token 错误时探活仍应成功，鉴权结论由目录加载给出。
        XCTAssertNil(URLProtocolStub.lastRequest?.value(forHTTPHeaderField: "Authorization"))
    }

    func testAuthorizedRequestAddsBearerToken() async throws {
        let client = makeClient(body: #"{"sdks":[]}"#)

        _ = try await client.sdkCapabilities()

        XCTAssertEqual(URLProtocolStub.lastRequest?.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
    }

    func testObservationPageUsesAuthorizedCursorQuery() async throws {
        let client = makeClient(body: #"{"items":[],"next_cursor":42,"has_more":false}"#)

        let page = try await client.observations(runID: "run-1", afterCursor: 42)

        let request = try XCTUnwrap(URLProtocolStub.lastRequest)
        XCTAssertEqual(request.url?.path, "/api/v1/test-runs/run-1/observations")
        XCTAssertEqual(request.url?.query, "after_cursor=42&limit=200")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
        XCTAssertEqual(page.nextCursor, 42)
        XCTAssertTrue(page.items.isEmpty)
    }

    func testTestCasesDecodeAgoraMetadata() async throws {
        let client = makeClient(
            body: #"""
            {
              "cases": [
                {
                  "case_id": "TC-MAC-AGORA-REAL-JOIN-CALLBACK",
                  "name": "macOS Agora real join callback",
                  "platform": "mac",
                  "suite": "mac",
                  "tags": [],
                  "covered_capabilities": ["join_success_fact", "leave_cleanup"],
                  "scenario_family": "direct_call",
                  "implementation_status": "runnable",
                  "requires_runtime_isolation": true,
                  "steps": []
                }
              ]
            }
            """#
        )

        let response = try await client.testCases()

        XCTAssertEqual(response.cases.count, 1)
        XCTAssertEqual(response.cases[0].scenarioFamily, "direct_call")
        XCTAssertEqual(response.cases[0].implementationStatus, "runnable")
        XCTAssertEqual(response.cases[0].coveredCapabilities, ["join_success_fact", "leave_cleanup"])
        XCTAssertTrue(response.cases[0].requiresRuntimeIsolation)
    }

    func testAuthorizedGetSurfacesHTTPStatusAndBody() async throws {
        let client = makeClient(statusCode: 401, body: #"{"detail":"missing token"}"#)

        do {
            _ = try await client.sdkCapabilities()
            XCTFail("unauthorized SDK capabilities request should throw")
        } catch let error as BeaconServerClientError {
            XCTAssertEqual(error, .httpStatus(401, #"{"detail":"missing token"}"#))
            XCTAssertEqual(error.description, "HTTP 401: auth token is missing or invalid")
        }
    }

    func testCreateRunSurfacesServerRejectionBody() async throws {
        let client = makeClient(statusCode: 403, body: #"{"detail":"forbidden"}"#)
        let testCase = TestCaseSummary(caseID: "TC-1", name: "One", platform: "mac", suite: "Smoke", tags: [])

        do {
            _ = try await client.createRun(caseSummary: testCase, nodeID: nil)
            XCTFail("rejected create run request should throw")
        } catch let error as BeaconServerClientError {
            XCTAssertEqual(error, .httpStatus(403, #"{"detail":"forbidden"}"#))
            XCTAssertEqual(error.description, "HTTP 403: server rejected the auth token")
        }
    }

    func testCreateRunAllowsLongRunningManualObservation() async throws {
        let client = makeClient(body: #"{"run_id":"run-1","status":"passed","results":[]}"#)
        let testCase = TestCaseSummary(caseID: "TC-1", name: "One", platform: "mac", suite: "Smoke", tags: [])

        _ = try await client.createRun(caseSummary: testCase, nodeID: nil)

        XCTAssertEqual(URLProtocolStub.lastRequest?.timeoutInterval, 120)
    }

    func testShutdownPostsAuthorizedConsoleShutdownRequest() async throws {
        let client = makeClient(body: "{}")

        try await client.shutdownLocalConsoleServer()

        let request = try XCTUnwrap(URLProtocolStub.lastRequest)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/console/shutdown")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
    }

    func testShutdownSurfacesServerFailureDescription() async throws {
        let client = makeClient(statusCode: 500, body: "shutdown failed")

        do {
            try await client.shutdownLocalConsoleServer()
            XCTFail("failed shutdown request should throw")
        } catch let error as BeaconServerClientError {
            XCTAssertEqual(error, .httpStatus(500, "shutdown failed"))
            XCTAssertEqual(error.description, "HTTP 500: server request failed: shutdown failed")
        }
    }

    func testRunHistoryCarriesLimitAsQueryAndDecodesSummaries() async throws {
        let client = makeClient(
            body: #"""
            {
              "runs": [
                {
                  "run_id": "run-new",
                  "status": "running",
                  "case_ids": ["TC-MAC-SMOKE"],
                  "created_at_ms": 300,
                  "finished_at_ms": null,
                  "duration_ms": null
                },
                {
                  "run_id": "run-old",
                  "status": "passed",
                  "case_ids": ["TC-PY-AGORA-JOIN-CALLBACK"],
                  "created_at_ms": 100,
                  "finished_at_ms": 150,
                  "duration_ms": 50
                }
              ]
            }
            """#
        )

        let response = try await client.history(limit: 2)

        let request = try XCTUnwrap(URLProtocolStub.lastRequest)
        XCTAssertEqual(request.httpMethod, "GET")
        XCTAssertEqual(request.url?.path, "/api/v1/console/test-runs")
        // limit 必须是 query：拼进 path 会被 `appending(path:)` 转义成 `%3F`，server 侧只会看到默认值。
        XCTAssertEqual(request.url?.query, "limit=2")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
        // server 已按创建时间倒序，client 不再重排，保持列表顺序就是事实顺序。
        XCTAssertEqual(response.runs.map(\.runID), ["run-new", "run-old"])
        XCTAssertNil(response.runs[0].finishedAtMs)
        XCTAssertNil(response.runs[0].durationMs)
        XCTAssertFalse(response.runs[0].isTerminal)
        XCTAssertEqual(response.runs[1].finishedAtMs, 150)
        XCTAssertEqual(response.runs[1].durationMs, 50)
        XCTAssertEqual(response.runs[1].caseIDs, ["TC-PY-AGORA-JOIN-CALLBACK"])
    }

    func testRunHistoryDefaultsToServerLimit() async throws {
        let client = makeClient(body: #"{"runs":[]}"#)

        let response = try await client.history()

        XCTAssertEqual(URLProtocolStub.lastRequest?.url?.query, "limit=50")
        XCTAssertTrue(response.runs.isEmpty)
    }

    func testRunHistorySurfacesUnauthorizedRequest() async throws {
        let client = makeClient(statusCode: 401, body: #"{"detail":"missing token"}"#)

        do {
            _ = try await client.history()
            XCTFail("unauthorized run history request should throw")
        } catch let error as BeaconServerClientError {
            XCTAssertEqual(error, .httpStatus(401, #"{"detail":"missing token"}"#))
        }
    }

    func testCancelRunPostsWithoutBodyAndDecodesRunSnapshot() async throws {
        let client = makeClient(body: #"{"run_id":"run-1","status":"running","results":[]}"#)

        let run = try await client.cancelRun(runID: "run-1")

        let request = try XCTUnwrap(URLProtocolStub.lastRequest)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/test-runs/run-1/cancel")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
        // 取消是控制动作而非资源提交，没有 payload。
        XCTAssertNil(request.value(forHTTPHeaderField: "Content-Type"))
        XCTAssertNil(request.httpBody)
        // 协作式取消：server 只登记请求，返回的通常仍是还没收敛到终态的 running。
        XCTAssertEqual(run.runID, "run-1")
        XCTAssertEqual(run.status, "running")
        XCTAssertFalse(run.isTerminal)
    }

    func testCancelRunSurfacesMissingRun() async throws {
        let client = makeClient(statusCode: 404, body: #"{"detail":"run not found"}"#)

        do {
            _ = try await client.cancelRun(runID: "run-missing")
            XCTFail("cancelling an unknown run should throw")
        } catch let error as BeaconServerClientError {
            XCTAssertEqual(error, .httpStatus(404, #"{"detail":"run not found"}"#))
        }
    }

    func testDevicesDecodesOnlineAgentPool() async throws {
        let client = makeClient(
            body: #"""
            {
              "devices": [
                {
                  "node_id": "mac-1",
                  "platform": "mac",
                  "status": "online",
                  "last_seen_ms": 1700000000000,
                  "group_id": "lab",
                  "tags": ["real"],
                  "capabilities": ["agora_rtc"]
                }
              ]
            }
            """#
        )

        let response = try await client.devices()

        let request = try XCTUnwrap(URLProtocolStub.lastRequest)
        XCTAssertEqual(request.httpMethod, "GET")
        XCTAssertEqual(request.url?.path, "/api/v1/devices")
        // 就绪度面板要区分「server 可达但读不到 agent」，因此这里必须带鉴权，与无鉴权的 status() 相反。
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer token-1")
        XCTAssertEqual(response.devices.count, 1)
        XCTAssertEqual(response.devices[0].nodeID, "mac-1")
        XCTAssertEqual(response.devices[0].platform, "mac")
        XCTAssertEqual(response.devices[0].status, "online")
        XCTAssertEqual(response.devices[0].lastSeenMs, 1_700_000_000_000)
    }

    func testDevicesSurfacesUnauthorizedRequest() async throws {
        let client = makeClient(statusCode: 401, body: #"{"detail":"missing token"}"#)

        do {
            _ = try await client.devices()
            XCTFail("unauthorized devices request should throw")
        } catch let error as BeaconServerClientError {
            XCTAssertEqual(error, .httpStatus(401, #"{"detail":"missing token"}"#))
        }
    }

    private func makeClient(statusCode: Int = 200, body: String) -> BeaconServerClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: config)
        URLProtocolStub.requestHandler = { request in
            URLProtocolStub.lastRequest = request
            let response = HTTPURLResponse(url: request.url!, statusCode: statusCode, httpVersion: nil, headerFields: nil)!
            return (response, Data(body.utf8))
        }
        return BeaconServerClient(baseURL: URL(string: "http://127.0.0.1:8000")!, token: "token-1", session: session)
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

final class URLProtocolStub: URLProtocol {
    static var requestHandler: ((URLRequest) throws -> (HTTPURLResponse, Data))?
    static var lastRequest: URLRequest?

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        do {
            let (response, data) = try Self.requestHandler!(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
