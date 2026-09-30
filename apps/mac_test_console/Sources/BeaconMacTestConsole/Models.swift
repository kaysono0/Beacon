import Foundation

enum JSONValue: Codable, Equatable, Hashable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else {
            self = .array(try container.decode([JSONValue].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .int(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }

    var stringValue: String? {
        switch self {
        case .string(let value):
            return value
        case .int(let value):
            return String(value)
        case .double(let value):
            return String(value)
        case .bool(let value):
            return String(value)
        case .object, .array, .null:
            return nil
        }
    }

    var intValue: Int? {
        if case .int(let value) = self {
            return value
        }
        return nil
    }

    var objectValue: [String: JSONValue]? {
        if case .object(let value) = self {
            return value
        }
        return nil
    }

    var displayValue: String {
        switch self {
        case .string(let value):
            return value
        case .int(let value):
            return String(value)
        case .double(let value):
            return String(value)
        case .bool(let value):
            return String(value)
        case .object(let value):
            return "{\(value.keys.sorted().joined(separator: ","))}"
        case .array(let value):
            return "[\(value.count)]"
        case .null:
            return ""
        }
    }
}

struct StatusResponse: Decodable, Equatable {
    let service: String
    let status: String
    let version: String
}

/// `GET /api/v1/devices` 返回的单个在线 Agent。
///
/// server 的 `DeviceRegistry` 只持有当前有效 WebSocket session，因此列表即在线池；
/// 这里只声明就绪度面板需要的字段，`group_id`/`tags`/`capabilities` 由 Decodable 忽略。
struct DeviceSummary: Decodable, Equatable, Identifiable {
    let nodeID: String
    let platform: String
    let status: String
    let lastSeenMs: Int

    var id: String { nodeID }

    enum CodingKeys: String, CodingKey {
        case nodeID = "node_id"
        case platform
        case status
        case lastSeenMs = "last_seen_ms"
    }
}

struct DevicesResponse: Decodable, Equatable {
    let devices: [DeviceSummary]
}

struct SDKCapabilitiesResponse: Decodable, Equatable {
    let sdks: [SDKCapability]
}

struct SDKCapability: Decodable, Equatable, Identifiable {
    let sdk: String
    let interfaces: [SDKInterfaceCapability]

    var id: String { sdk }
}

struct SDKInterfaceCapability: Decodable, Equatable, Identifiable {
    let interface: String
    let methods: [Target]
    let callbacks: [CallbackCapability]
    let metrics: [Target]
    let states: [Target]

    var id: String { interface }
}

struct CallbackCapability: Decodable, Equatable {
    let target: Target
    let filterableFields: [String]
    let evidenceSummaryFields: [String]

    enum CodingKeys: String, CodingKey {
        case target
        case filterableFields = "filterable_fields"
        case evidenceSummaryFields = "evidence_summary_fields"
    }
}

struct Target: Decodable, Encodable, Equatable, Hashable {
    let sdk: String
    let interface: String?
    let className: String
    let function: String

    enum CodingKeys: String, CodingKey {
        case sdk
        case interface
        case className = "class_name"
        case function
    }
}

struct TestCasesResponse: Decodable, Equatable {
    let cases: [TestCaseSummary]
}

/// UI 使用的 test case 摘要。
///
/// `sdkNames` 是运行目录的 SDK 分类；`steps` 只兼容历史详情。
struct TestCaseSummary: Decodable, Equatable, Hashable, Identifiable {
    let caseID: String
    let name: String
    let platform: String
    let suite: String
    let tags: [String]
    var coveredCapabilities: [String] = []
    var scenarioFamily: String = ""
    var implementationStatus: String = ""
    var steps: [JSONValue] = []
    var sdkNames: [String]? = nil
    var requiresRuntimeIsolation: Bool = false

    var id: String { caseID }

    enum CodingKeys: String, CodingKey {
        case caseID = "case_id"
        case name
        case platform
        case suite
        case tags
        case coveredCapabilities = "covered_capabilities"
        case scenarioFamily = "scenario_family"
        case implementationStatus = "implementation_status"
        case steps
        case sdkNames = "sdk_names"
        case requiresRuntimeIsolation = "requires_runtime_isolation"
    }
}

struct CreateRunRequest: Encodable, Equatable {
    let selector: [String: String]
    let caseIDs: [String]

    enum CodingKeys: String, CodingKey {
        case selector
        case caseIDs = "case_ids"
    }
}

struct RunResponse: Codable, Equatable {
    /// run 终态集合：`isTerminal` 与 suite 运行清单的进度计数共用同一判定。
    static let terminalStatuses: Set<String> = ["passed", "failed", "canceled", "cancelled"]

    let runID: String
    let status: String
    let stepResults: [StepResultSummary]
    var cases: [RunCaseReference]? = nil

    var isTerminal: Bool {
        Self.terminalStatuses.contains(status)
    }

    enum CodingKeys: String, CodingKey {
        case runID = "run_id"
        case status
        case stepResults = "results"
        case cases
    }
}

struct RunCaseReference: Codable, Equatable {
    let caseID: String

    enum CodingKeys: String, CodingKey {
        case caseID = "case_id"
    }
}

struct StepResultSummary: Codable, Equatable, Identifiable {
    let caseID: String
    let stepID: String
    let status: String
    let error: [String: JSONValue]?
    let artifacts: [String]
    let durationMs: Int

    var id: String { stepID }

    var code: Int {
        errorCode ?? 0
    }

    var errorCode: Int? {
        error?["code"]?.intValue
    }

    var message: String {
        error?["message"]?.stringValue ?? ""
    }

    var durationLabel: String {
        durationMs > 0 ? "\(durationMs) ms" : ""
    }

    enum CodingKeys: String, CodingKey {
        case caseID = "case_id"
        case stepID = "step_id"
        case status
        case error
        case artifacts
        case durationMs = "duration_ms"
    }
}

/// `GET /api/v1/console/test-runs` 返回的单条运行历史摘要。
///
/// server 按 `created_at_ms` 倒序给出；`finishedAtMs`/`durationMs` 为 nil 表示该 run 尚未结束。
struct RunHistorySummary: Decodable, Equatable, Identifiable {
    let runID: String
    let status: String
    let caseIDs: [String]
    let createdAtMs: Int
    let finishedAtMs: Int?
    let durationMs: Int?

    var id: String { runID }

    var isTerminal: Bool {
        RunResponse.terminalStatuses.contains(status)
    }

    enum CodingKeys: String, CodingKey {
        case runID = "run_id"
        case status
        case caseIDs = "case_ids"
        case createdAtMs = "created_at_ms"
        case finishedAtMs = "finished_at_ms"
        case durationMs = "duration_ms"
    }
}

struct RunHistoryResponse: Decodable, Equatable {
    let runs: [RunHistorySummary]
}

struct ConsoleRunDetail: Codable, Equatable {
    let run: RunResponse
    let report: ReportSummary
    let logs: [[String: JSONValue]]
    var observationCursorEnabled: Bool? = nil

    enum CodingKeys: String, CodingKey {
        case run, report, logs
        case observationCursorEnabled = "observation_cursor_enabled"
    }
}

struct ReportSummary: Codable, Equatable {
    let runID: String
    let format: String
    let summary: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case runID = "run_id"
        case format
        case summary
    }
}

struct RunExportPackage: Encodable, Equatable {
    let schemaVersion: Int
    let run: RunResponse
    let report: ReportSummary
    let logs: [[String: JSONValue]]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case run
        case report
        case logs
    }
}
