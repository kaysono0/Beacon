import Foundation

/// 单个 SDK 的目标环境：手动多环境并存时（如 Agora:8000 / 火山:8001），
/// 选择 SDK 会把 Console 切到这里的 Server 与节点。
struct SDKRoute: Equatable {
    let url: URL
    let nodeID: String?
}

/// 只有一个 SDK 映射到当前 Server 时，才允许用路由反推 SDK。
/// 统一 Server 同时承载多家 SDK 时，SDK 选择权属于用户，不能按字母序猜测。
enum SDKRouteSelection {
    static func automaticallyAlignedSDK(
        capabilities: [SDKCapability],
        routes: [String: SDKRoute],
        serverURL: URL
    ) -> SDKCapability? {
        let matches = capabilities.filter { routes[$0.sdk]?.url == serverURL }
        return matches.count == 1 ? matches.first : nil
    }
}

/// 解析 Mac Console 的启动配置。
///
/// 手动运行时通常来自环境变量；自动化运行时也可以通过命令行参数覆盖。
/// 这些值只决定 APP 连接哪个 Beacon Server，不直接读取本地 case 文件。
struct AppConfiguration: Equatable {
    let serverURL: URL
    let token: String
    let nodeID: String?
    let sdkRoutes: [String: SDKRoute]
    let autorunPrefix: String?
    let autorunCaseIDs: [String]?
    let autorunOutputPath: String?

    init(arguments: [String] = CommandLine.arguments, environment: [String: String] = ProcessInfo.processInfo.environment) {
        serverURL = Self.urlValue(
            flag: "--server-url",
            arguments: arguments,
            environmentValue: environment["BEACON_CONSOLE_SERVER_URL"],
            defaultValue: URL(string: "http://127.0.0.1:8000")!
        )
        token = Self.stringValue(flag: "--token", arguments: arguments, environmentValue: environment["BEACON_AUTH_TOKEN"])
        nodeID = Self.optionalString(flag: "--node-id", arguments: arguments, environmentValue: environment["BEACON_NODE_ID"])
        sdkRoutes = Self.sdkRoutesValue(
            flag: "--sdk-routes",
            arguments: arguments,
            environmentValue: environment["BEACON_CONSOLE_SDK_ROUTES"]
        )
        autorunPrefix = Self.optionalString(
            flag: "--autorun-prefix",
            arguments: arguments,
            environmentValue: environment["BEACON_CONSOLE_AUTORUN_PREFIX"]
        )
        autorunCaseIDs = Self.optionalCSV(
            flag: "--autorun-case-ids",
            arguments: arguments,
            environmentValue: environment["BEACON_CONSOLE_AUTORUN_CASE_IDS"]
        )
        autorunOutputPath = Self.optionalString(
            flag: "--autorun-output",
            arguments: arguments,
            environmentValue: environment["BEACON_CONSOLE_AUTORUN_OUTPUT"]
        )
    }

    private static func stringValue(flag: String, arguments: [String], environmentValue: String?) -> String {
        if let index = arguments.firstIndex(of: flag), arguments.indices.contains(index + 1) {
            return arguments[index + 1]
        }
        return environmentValue ?? ""
    }

    private static func optionalString(flag: String, arguments: [String], environmentValue: String?) -> String? {
        let value = stringValue(flag: flag, arguments: arguments, environmentValue: environmentValue)
        return value.isEmpty ? nil : value
    }

    private static func optionalCSV(flag: String, arguments: [String], environmentValue: String?) -> [String]? {
        guard let value = optionalString(flag: flag, arguments: arguments, environmentValue: environmentValue) else {
            return nil
        }
        let items = value.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        return items.isEmpty ? nil : items
    }

    /// 路由格式：`sdk=url#node,sdk=url`（node 可省略）；条目不合法就跳过，不阻断启动。
    private static func sdkRoutesValue(flag: String, arguments: [String], environmentValue: String?) -> [String: SDKRoute] {
        guard let value = optionalString(flag: flag, arguments: arguments, environmentValue: environmentValue) else {
            return [:]
        }
        var routes: [String: SDKRoute] = [:]
        for entry in value.split(separator: ",") {
            let parts = entry.split(separator: "=", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            guard parts.count == 2, !parts[0].isEmpty else { continue }
            let target = parts[1].split(separator: "#", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            guard !target[0].isEmpty, let url = URL(string: target[0]) else { continue }
            let nodeID = target.count == 2 && !target[1].isEmpty ? target[1] : nil
            routes[parts[0]] = SDKRoute(url: url, nodeID: nodeID)
        }
        return routes
    }

    private static func urlValue(flag: String, arguments: [String], environmentValue: String?, defaultValue: URL) -> URL {
        let value = stringValue(flag: flag, arguments: arguments, environmentValue: environmentValue)
        if value.isEmpty {
            return defaultValue
        }
        return URL(string: value) ?? defaultValue
    }
}

@MainActor
/// 保存窗口级共享状态。
///
/// `serverURL` 和 `token` 会被顶部连接栏编辑，并传给 `BeaconServerClient`。
/// `sdkRoutes` 只在配置了 SDK→环境路由时非空，选择 SDK 会据此切换 `serverURL`/`selectedNodeID`。
/// `autorun*` 字段只用于命令行自动验证模式，普通 UI 运行不会自动退出。
final class AppState: ObservableObject {
    @Published var serverURL: URL
    @Published var token: String
    @Published var connectionStatus: ConnectionStatus
    @Published var selectedNodeID: String?
    let sdkRoutes: [String: SDKRoute]
    let autorunPrefix: String?
    let autorunCaseIDs: [String]?
    let autorunOutputPath: String?

    init(
        configuration: AppConfiguration = AppConfiguration(),
        connectionStatus: ConnectionStatus = .disconnected
    ) {
        self.serverURL = configuration.serverURL
        self.token = configuration.token
        self.selectedNodeID = configuration.nodeID
        self.sdkRoutes = configuration.sdkRoutes
        self.autorunPrefix = configuration.autorunPrefix
        self.autorunCaseIDs = configuration.autorunCaseIDs
        self.autorunOutputPath = configuration.autorunOutputPath
        self.connectionStatus = connectionStatus
    }

    /// 探活或加载开始前先进入 `connecting`，避免上一次的 connected/failed 在请求期间继续冒充当前事实。
    func beginConnecting() {
        connectionStatus = .connecting
    }

    /// 把一次带目录加载的连接刷新结果落到 `connectionStatus`。
    ///
    /// `connected` 结论必须由带鉴权的目录加载给出；只探活的路径走 `applyProbeOnly`。
    func applyConnection(probe: ServerProbeResult, load: CaseLoadResult) {
        connectionStatus = ConnectionStatus.resolve(probe: probe, load: load)
    }

    /// 只探活的刷新（Run / Run Suite 前）：只允许降级，不允许升级为 `connected`。
    ///
    /// `/api/v1/status` 无鉴权，探活成功只证明 server 可达，不能证明当前 token 可用；
    /// 若此处写入 `connected`，token 改错后点 Run 会在 401 之上显示绿点。
    func applyProbeOnly(probe: ServerProbeResult, previous: ConnectionStatus) {
        if case .unreachable(let message) = probe {
            connectionStatus = .failed(message: message)
        } else {
            connectionStatus = previous
        }
    }
}

enum ConnectionStatus: Equatable {
    case disconnected
    case connecting
    case connected(version: String)
    case failed(message: String)
}

extension ConnectionStatus {
    /// 探活失败优先于加载失败：探活不通说明 server 本身不可达，加载错误只是它的后果。
    ///
    /// `connected` 只能由带鉴权的目录加载给出；只探活的路径见 `AppState.applyProbeOnly`。
    static func resolve(probe: ServerProbeResult, load: CaseLoadResult) -> ConnectionStatus {
        switch probe {
        case .unreachable(let message):
            return .failed(message: message)
        case .reachable(let version):
            if case .failed(let message) = load {
                return .failed(message: message)
            }
            return .connected(version: version)
        }
    }
}

/// `GET /api/v1/status` 探活结果；该端点无鉴权，因此 token 错误时仍可探活成功。
enum ServerProbeResult: Equatable {
    case reachable(version: String)
    case unreachable(message: String)
}

/// case 目录加载结果，由 `ConsoleViewModel.load` 回报给连接状态的持有方。
enum CaseLoadResult: Equatable {
    case loaded(caseCount: Int)
    case failed(message: String)
}
