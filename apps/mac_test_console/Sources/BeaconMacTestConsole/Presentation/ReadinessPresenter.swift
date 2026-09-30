import SwiftUI

/// 就绪度面板三段的结论级别：绿=可开跑、黄=能连上但有缺口、红=这一段读不到。
enum ReadinessLevel: Equatable {
    case ready
    case attention
    case unavailable
}

/// 就绪度面板的一段结论（Server / Agents / SDK Capabilities）。
struct ReadinessSection: Equatable, Identifiable {
    let title: String
    let level: ReadinessLevel
    let summary: String
    /// 段级失败原因；为 nil 表示这一段成功读到了事实。
    let errorText: String?

    var id: String { title }

    /// AX identifier 片段由标题派生，避免每个构造点再传一份会与文案漂移的标识。
    var accessibilityKey: String {
        title.lowercased().replacingOccurrences(of: " ", with: "_")
    }
}

/// 就绪度面板的一次快照：三段数据各自独立取得，任一段失败都不影响其余两段给出结论。
///
/// 刻意不折叠成单一 `Result`：`/api/v1/status` 无鉴权而 `/api/v1/devices`、
/// `/api/v1/console/sdk-capabilities` 带鉴权，token 错误时会出现「server 可达但读不到 agent
/// 与能力」的组合，而那正是最有诊断价值的状态（与 B-015 的假绿点同类问题）。
struct ReadinessSnapshot: Equatable {
    var serverStatus: StatusResponse? = nil
    var serverError: String? = nil
    var devices: [DeviceSummary] = []
    var devicesError: String? = nil
    var sdkCapabilities: [SDKCapability] = []
    var capabilitiesError: String? = nil
}

/// 就绪度快照到段结论、能力计数与「上次可见」文本的纯映射，供 Readiness popover 使用。
///
/// 与 `CaseRunPresenter`、`ConnectionStatusPresenter`、`RunHistoryPresenter` 一样不持状态、
/// 不依赖视图层级，可直接单测；刻意放在 `Views/` 之外，才能被 `make coverage-mac-console`
/// 的覆盖率门槛计入。
enum ReadinessPresenter {
    static func serverSection(of snapshot: ReadinessSnapshot) -> ReadinessSection {
        if let error = snapshot.serverError {
            return ReadinessSection(title: "Server", level: .unavailable, summary: "Unavailable", errorText: error)
        }
        guard let status = snapshot.serverStatus else {
            return ReadinessSection(title: "Server", level: .unavailable, summary: "Not checked", errorText: nil)
        }
        let summary = "\(status.service) \(status.version) · \(status.status)"
        // 探活返回非 ok 时 server 进程在但状态异常，属于「能连上有缺口」而不是读不到。
        let level: ReadinessLevel = status.status == "ok" ? .ready : .attention
        return ReadinessSection(title: "Server", level: level, summary: summary, errorText: nil)
    }

    static func agentsSection(of snapshot: ReadinessSnapshot) -> ReadinessSection {
        if let error = snapshot.devicesError {
            return ReadinessSection(title: "Agents", level: .unavailable, summary: "Unavailable", errorText: error)
        }
        if snapshot.devices.isEmpty {
            // 没有在线 Agent 时 run 会因选不到设备失败，必须在开跑前可见。
            return ReadinessSection(
                title: "Agents",
                level: .attention,
                summary: "No agent online",
                errorText: nil
            )
        }
        let offline = snapshot.devices.filter { $0.status != "online" }.count
        if offline > 0 {
            return ReadinessSection(
                title: "Agents",
                level: .attention,
                summary: "\(countText(snapshot.devices.count, "agent")) registered, \(countText(offline, "agent")) not online",
                errorText: nil
            )
        }
        return ReadinessSection(
            title: "Agents",
            level: .ready,
            summary: "\(countText(snapshot.devices.count, "agent")) online",
            errorText: nil
        )
    }

    static func capabilitiesSection(of snapshot: ReadinessSnapshot) -> ReadinessSection {
        if let error = snapshot.capabilitiesError {
            return ReadinessSection(
                title: "SDK capabilities",
                level: .unavailable,
                summary: "Unavailable",
                errorText: error
            )
        }
        if snapshot.sdkCapabilities.isEmpty {
            return ReadinessSection(
                title: "SDK capabilities",
                level: .attention,
                summary: "No SDK capability loaded",
                errorText: nil
            )
        }
        let methods = snapshot.sdkCapabilities.reduce(0) { $0 + methodCount(of: $1) }
        return ReadinessSection(
            title: "SDK capabilities",
            level: .ready,
            summary: "\(countText(snapshot.sdkCapabilities.count, "SDK")) · \(countText(methods, "method"))",
            errorText: nil
        )
    }

    /// 单个 SDK 的能力计数行：接口数与方法/回调数即可判断 registry 是否真的加载了能力。
    static func capabilitySummary(of sdk: SDKCapability) -> String {
        let methods = methodCount(of: sdk)
        let callbacks = sdk.interfaces.reduce(0) { $0 + $1.callbacks.count }
        return [
            countText(sdk.interfaces.count, "interface"),
            countText(methods, "method"),
            countText(callbacks, "callback"),
        ].joined(separator: " · ")
    }

    /// Agent 上次可见的相对时间。`now` 由调用方注入，映射本身可单测。
    static func lastSeenText(milliseconds: Int, now: Date) -> String {
        let seconds = Int(now.timeIntervalSince1970) - milliseconds / 1000
        if seconds < 5 {
            return "just now"
        }
        if seconds < 60 {
            return "\(seconds)s ago"
        }
        if seconds < 3600 {
            return "\(seconds / 60)m ago"
        }
        return "\(seconds / 3600)h ago"
    }

    static func symbolName(for level: ReadinessLevel) -> String {
        switch level {
        case .ready:
            return "checkmark.circle.fill"
        case .attention:
            return "exclamationmark.triangle.fill"
        case .unavailable:
            return "xmark.circle.fill"
        }
    }

    static func color(for level: ReadinessLevel) -> Color {
        switch level {
        case .ready:
            return .green
        case .attention:
            return .yellow
        case .unavailable:
            return .red
        }
    }

    private static func methodCount(of sdk: SDKCapability) -> Int {
        sdk.interfaces.reduce(0) { $0 + $1.methods.count }
    }

    private static func countText(_ count: Int, _ noun: String) -> String {
        count == 1 ? "1 \(noun)" : "\(count) \(noun)s"
    }
}
