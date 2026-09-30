import Foundation

/// Console 日志投影：将 server detail 转成稳定的 UI 行，并集中筛选与文本导出规则。
@MainActor
struct LogPresenter {
    static func rows(from detail: ConsoleRunDetail) -> [LogRow] {
        var occurrenceByKey: [String: Int] = [:]
        var rows: [LogRow] = []
        var operationByStep: [String: String] = [:]
        for item in detail.logs where !isNoise(item) {
            let operation = operationText(from: item, operationByStep: operationByStep)
            if let stepID = item["step_id"]?.displayValue,
               let dispatchedOperation = dispatchedOperationText(from: item) {
                operationByStep[stepID] = dispatchedOperation
            }
            var row = LogRow(
                level: item["level"]?.displayValue ?? "info",
                message: item["message"]?.displayValue ?? String(describing: item),
                nodeID: item["node_id"]?.displayValue ?? "",
                event: item["event"]?.displayValue ?? "",
                operation: operation,
                outcome: outcomeText(from: item),
                detail: detailText(from: item),
                isKeyEvent: isKey(item),
                timestamp: timestamp(item["timestamp_ms"]),
                module: item["module"]?.displayValue ?? "",
                stepID: item["step_id"]?.displayValue,
                eventID: item["event_id"]?.displayValue ?? ""
            )
            let occurrence = occurrenceByKey[row.id, default: 0]
            occurrenceByKey[row.id] = occurrence + 1
            if occurrence > 0 { row.id += "#\(occurrence)" }
            rows.append(row)
        }
        return rows
    }

    static func filtered(
        _ rows: [LogRow], text: String, level: LogLevelFilter, stepID: String?, showsLifecycle: Bool
    ) -> [LogRow] {
        rows.filter { row in
            if row.isServerLifecycle && !showsLifecycle { return false }
            guard level.matches(row.level) else { return false }
            if let stepID, row.stepID != stepID { return false }
            guard !text.isEmpty else { return true }
            return row.level.localizedCaseInsensitiveContains(text)
                || row.message.localizedCaseInsensitiveContains(text)
                || row.nodeID.localizedCaseInsensitiveContains(text)
                || row.event.localizedCaseInsensitiveContains(text)
                || row.detail.localizedCaseInsensitiveContains(text)
                || row.module.localizedCaseInsensitiveContains(text)
        }
    }

    static func visibleText(_ rows: [LogRow]) -> String { rows.map(line).joined(separator: "\n") }

    static func timestamp(_ value: JSONValue?) -> Date? {
        guard let milliseconds = value?.intValue else { return nil }
        return Date(timeIntervalSince1970: TimeInterval(milliseconds) / 1000)
    }

    static func line(_ row: LogRow) -> String {
        var parts: [String] = []
        if let timestamp = row.timestamp { parts.append(ConsoleViewModel.timeText(from: timestamp)) }
        parts.append(row.level.uppercased())
        parts.append(row.operation)
        parts.append(row.outcome)
        if !row.detail.isEmpty { parts.append(row.detail) }
        return parts.joined(separator: " ")
    }

    private static func isNoise(_ item: [String: JSONValue]) -> Bool {
        item["event"]?.displayValue == "console.run_detail.requested"
    }

    private static func isKey(_ item: [String: JSONValue]) -> Bool {
        if item["level"]?.displayValue.lowercased() == "error" { return true }
        return ["case_started", "case_completed", "step_started", "step_completed", "sdk_call_dispatched",
                "sdk_call_completed", "assertion_failed", "callback_event_observed", "evidence_observed",
                "artifact_recorded"].contains(item["event"]?.displayValue ?? "")
    }

    private static func detailText(from item: [String: JSONValue]) -> String {
        ["event", "module", "node_id", "run_id", "case_id", "step_id", "op_id", "extra"].compactMap { key in
            guard let value = item[key] else { return nil }
            let formatted = format(value)
            return formatted.isEmpty ? nil : "\(key)=\(formatted)"
        }.joined(separator: " ")
    }

    private static func operationText(from item: [String: JSONValue], operationByStep: [String: String]) -> String {
        if let dispatched = dispatchedOperationText(from: item) { return dispatched }
        if let stepID = item["step_id"]?.displayValue, let operation = operationByStep[stepID] {
            return operation
        }
        switch item["event"]?.displayValue {
        case "native.case.declared": return "Declare case"
        case "native.runtime_isolation.undeclared": return "Runtime isolation"
        case "native.runtime_reset.started", "native.runtime_reset.completed", "native.runtime_reset.failed":
            return "Reset agent runtime"
        case "native.step.recorded": return "Record step result"
        default: return item["event"]?.displayValue ?? item["message"]?.displayValue ?? "Log event"
        }
    }

    private static func outcomeText(from item: [String: JSONValue]) -> String {
        let extra = item["extra"]?.objectValue
        if let error = extra?["error"], error.displayValue != "" {
            return "Failed: \(format(error))"
        }
        if let status = extra?["status"]?.displayValue, !status.isEmpty {
            return status.capitalized
        }
        switch item["event"]?.displayValue {
        case "native.step.dispatching": return "Dispatched"
        case "native.runtime_reset.started": return "Started"
        case "native.runtime_reset.completed": return "Completed"
        default: return item["message"]?.displayValue ?? ""
        }
    }

    private static func dispatchedOperationText(from item: [String: JSONValue]) -> String? {
        guard item["event"]?.displayValue == "native.step.dispatching",
              case let .array(targets)? = item["extra"]?.objectValue?["operation_targets"] else {
            return nil
        }
        let functions = targets.compactMap { target -> String? in
            guard case let .object(targetInfo) = target,
                  case let .object(operationTarget)? = targetInfo["target"],
                  let function = operationTarget["function"]?.stringValue,
                  !function.isEmpty else { return nil }
            return function
        }
        guard !functions.isEmpty else { return nil }
        return functions.joined(separator: ", ")
    }

    private static func format(_ value: JSONValue) -> String {
        switch value {
        case .string(let value): return value
        case .int(let value): return String(value)
        case .double(let value): return String(value)
        case .bool(let value): return String(value)
        case .object(let value): return "{\(value.keys.sorted().map { "\($0):\(format(value[$0] ?? .null))" }.joined(separator: ","))}"
        case .array(let value): return "[\(value.map(format).joined(separator: ","))]"
        case .null: return ""
        }
    }
}
