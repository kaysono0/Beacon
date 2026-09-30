import Foundation

/// Server Observation 分页响应；cursor 只表示摄入顺序。
struct ObservationPage: Decodable {
    let items: [ConsoleObservation]
    let nextCursor: Int
    let hasMore: Bool

    enum CodingKeys: String, CodingKey {
        case items
        case nextCursor = "next_cursor"
        case hasMore = "has_more"
    }
}

struct ConsoleObservation: Decodable, Equatable, Identifiable {
    let observationID: String
    let cursor: Int
    let kind: String
    let caseID: String
    let deviceRole: String
    let target: [String: JSONValue]
    let payload: [String: JSONValue]

    var id: String { observationID }

    // 普通日志由 LogPanelView 展示，执行列表只展示调用、回调及其他结构化记录。
    var isExecutionRecord: Bool { kind != "log" }

    var detailText: String {
        let role = deviceRole == "unbound" ? "" : deviceRole
        return [role, valueText].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    var title: String {
        let name = target["function"]?.stringValue ?? target["name"]?.stringValue ?? kind
        if kind == "operation" {
            let operation = payload["operation_type"]?.stringValue ?? "operation"
            return "\(operation) · \(name)"
        }
        return "\(kind) · \(name)"
    }

    var valueText: String {
        if kind == "operation" {
            let outcome = payload["outcome"]?.stringValue ?? "Not reported"
            if outcome != "succeeded", let message = payload["message"]?.stringValue,
               !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return "\(outcome) · \(message)"
            }
            return outcome
        }
        if kind == "metric" {
            return payload["value"]?.displayValue.nonEmpty ?? "Not reported"
        }
        if kind == "event" {
            return payload.keys.sorted().compactMap { key in
                guard let value = payload[key]?.displayValue.nonEmpty else { return nil }
                return "\(key): \(value)"
            }.joined(separator: " · ").nonEmpty ?? "Received"
        }
        return payload.isEmpty ? "Not reported" : JSONValue.object(payload).displayValue
    }

    enum CodingKeys: String, CodingKey {
        case observationID = "observation_id"
        case cursor, kind, target, payload
        case caseID = "case_id"
        case deviceRole = "device_role"
    }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}

enum ObservationPageError: Error {
    case stalledCursor
}

/// 在 MainActor 上按 run 缓存 Observation 与最后确认的 cursor。
/// `await` 期间仍可重入：同一 run 的重复刷新合并为待补拉请求，不另开分页循环。
/// 请求失败或取消时保留已确认的页，下一次刷新从该 cursor 继续。
@MainActor
final class ObservationFeed {
    private var cursors: [String: Int] = [:]
    private var recordsByRun: [String: [ConsoleObservation]] = [:]
    /// 正在分页的 run；不同 run 可以各自拉取。
    private var loading: Set<String> = []
    /// 分页期间收到的刷新请求；同一 run 多次请求只合并为一次补拉。
    private var pending: Set<String> = []

    func records(for runID: String) -> [ConsoleObservation] {
        recordsByRun[runID] ?? []
    }

    func cursor(for runID: String) -> Int {
        cursors[runID] ?? 0
    }

    func refresh(runID: String, client: BeaconServerClient) async throws {
        guard loading.insert(runID).inserted else {
            pending.insert(runID)
            return
        }
        defer { loading.remove(runID) }
        repeat {
            pending.remove(runID)
            while true {
                let after = cursor(for: runID)
                let page = try await client.observations(runID: runID, afterCursor: after)
                try Task.checkCancellation()
                let fresh = page.items.filter { $0.cursor > after }
                if page.hasMore && (fresh.isEmpty || page.nextCursor <= after) {
                    throw ObservationPageError.stalledCursor
                }
                // 页校验与取消检查通过后才确认记录；cursor 跟随实际保存的最后一条。
                recordsByRun[runID, default: []].append(contentsOf: fresh)
                cursors[runID] = fresh.last?.cursor ?? after
                if !page.hasMore { break }
            }
        } while pending.remove(runID) != nil
    }
}
