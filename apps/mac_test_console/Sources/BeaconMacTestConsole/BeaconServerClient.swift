import Foundation

/// Mac Console 到 Beacon Server 的 HTTP 客户端。
///
/// APP 只通过这些接口读取 SDK/case、创建 test run、查询 run detail。
/// 本地文件读取、Agent 调度和真实 SDK 调用都发生在 server/agent 侧。
struct BeaconServerClient {
    private static let longRunningRunTimeout: TimeInterval = 120

    let baseURL: URL
    let token: String
    var session: URLSession = .shared

    func status() async throws -> StatusResponse {
        try await get("/api/v1/status", authorized: false)
    }

    /// 在线 Agent 池。与无鉴权的 `status()` 不同，本端点带鉴权：
    /// token 错误时会出现「server 可达但读不到 agent」的组合，就绪度面板必须能区分这两段结论。
    func devices() async throws -> DevicesResponse {
        try await get("/api/v1/devices", authorized: true)
    }

    func sdkCapabilities() async throws -> SDKCapabilitiesResponse {
        try await get("/api/v1/console/sdk-capabilities", authorized: true)
    }

    func testCases() async throws -> TestCasesResponse {
        try await get("/api/v1/console/test-cases", authorized: true)
    }

    func createRun(caseSummary: TestCaseSummary, nodeID: String?) async throws -> RunResponse {
        var selector: [String: String] = ["platform": caseSummary.platform]
        if let nodeID {
            selector["node_id"] = nodeID
        }
        // Server 根据 case ID 启动隔离 Runner。
        let request = CreateRunRequest(
            selector: selector,
            caseIDs: [caseSummary.caseID]
        )
        return try await post("/api/v1/test-runs", body: request, timeout: Self.longRunningRunTimeout)
    }

    func runDetail(runID: String) async throws -> ConsoleRunDetail {
        try await get("/api/v1/console/test-runs/\(runID)", authorized: true)
    }

    func observations(runID: String, afterCursor: Int) async throws -> ObservationPage {
        try await get(
            "/api/v1/test-runs/\(runID)/observations",
            authorized: true,
            queryItems: [
                URLQueryItem(name: "after_cursor", value: String(afterCursor)),
                URLQueryItem(name: "limit", value: "200")
            ]
        )
    }

    /// 运行历史摘要：server 按创建时间倒序返回，limit 与 server 端默认值一致。
    func history(limit: Int = 50) async throws -> RunHistoryResponse {
        try await get(
            "/api/v1/console/test-runs",
            authorized: true,
            queryItems: [URLQueryItem(name: "limit", value: String(limit))]
        )
    }

    /// 协作式取消：server 只登记请求并立即返回当前 run 快照。
    ///
    /// 返回的 status 通常仍是 `running`，因为进行中的步骤会自然完成，
    /// run 要等执行器在用例/步骤边界才收敛到 `cancelled`。
    func cancelRun(runID: String) async throws -> RunResponse {
        try await post("/api/v1/test-runs/\(runID)/cancel")
    }

    func shutdownLocalConsoleServer() async throws {
        var request = URLRequest(url: baseURL.appending(path: "/api/v1/console/shutdown"))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BeaconServerClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw BeaconServerClientError.httpStatus(http.statusCode, String(data: data, encoding: .utf8))
        }
    }

    private func get<T: Decodable>(_ path: String, authorized: Bool, queryItems: [URLQueryItem] = []) async throws -> T {
        var request = URLRequest(url: requestURL(path: path, queryItems: queryItems))
        request.httpMethod = "GET"
        if authorized {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BeaconServerClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw BeaconServerClientError.httpStatus(http.statusCode, String(data: data, encoding: .utf8))
        }
        return try JSONDecoder.beacon.decode(T.self, from: data)
    }

    /// query 必须经 URLComponents 组装：`appending(path:)` 会把 `?limit=1` 当路径片段转义成 `%3F`。
    private func requestURL(path: String, queryItems: [URLQueryItem]) -> URL {
        let url = baseURL.appending(path: path)
        guard !queryItems.isEmpty else {
            return url
        }
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        components?.queryItems = queryItems
        return components?.url ?? url
    }

    /// 无请求体的 POST：取消这类控制动作没有 payload，但鉴权与状态码规则与带体请求一致。
    private func post<T: Decodable>(_ path: String) async throws -> T {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BeaconServerClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw BeaconServerClientError.httpStatus(http.statusCode, String(data: data, encoding: .utf8))
        }
        return try JSONDecoder.beacon.decode(T.self, from: data)
    }

    private func post<T: Decodable, Body: Encodable>(
        _ path: String,
        body: Body,
        timeout: TimeInterval? = nil
    ) async throws -> T {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        if let timeout {
            request.timeoutInterval = timeout
        }
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder.beacon.encode(body)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BeaconServerClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw BeaconServerClientError.httpStatus(http.statusCode, String(data: data, encoding: .utf8))
        }
        return try JSONDecoder.beacon.decode(T.self, from: data)
    }
}

enum BeaconServerClientError: Error, Equatable, CustomStringConvertible {
    case invalidResponse
    case httpStatus(Int, String? = nil)

    var description: String {
        switch self {
        case .invalidResponse:
            return "Invalid server response"
        case .httpStatus(401, _):
            return "HTTP 401: auth token is missing or invalid"
        case .httpStatus(403, _):
            return "HTTP 403: server rejected the auth token"
        case .httpStatus(let code, let body):
            let detail = body.map { ": \($0)" } ?? ""
            return "HTTP \(code): server request failed\(detail)"
        }
    }
}

extension JSONDecoder {
    static var beacon: JSONDecoder {
        JSONDecoder()
    }
}

extension JSONEncoder {
    static var beacon: JSONEncoder {
        JSONEncoder()
    }
}
