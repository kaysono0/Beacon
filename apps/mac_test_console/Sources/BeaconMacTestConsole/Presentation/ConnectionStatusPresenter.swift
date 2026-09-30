import SwiftUI

/// 连接状态到圆点颜色、连接栏短文本与 AX 标签的纯映射。
///
/// 本类型不持状态、不依赖视图层级，可直接单测；着色约定与 `CaseRunPresenter` 一致
/// （绿=成功、红=失败、中性=尚无结论），连接栏只给结论，完整错误文本由详情区承载。
/// 刻意放在 `Views/` 外，使其进入 `coverage-mac-console` 的 95% 阈值口径而非被排除。
enum ConnectionStatusPresenter {
    static func color(for status: ConnectionStatus) -> Color {
        switch status {
        case .connected:
            return .green
        case .connecting:
            return .yellow
        case .failed:
            return .red
        case .disconnected:
            return .secondary
        }
    }

    static func text(for status: ConnectionStatus, caseCount: Int) -> String {
        switch status {
        case .connected:
            return "Connected (\(caseCount) cases)"
        case .connecting:
            return "Connecting…"
        case .failed:
            return "Connection failed"
        case .disconnected:
            return "Disconnected"
        }
    }

    /// 圆点本身没有可读内容，AX 标签在它上面补齐版本号，让状态可被读出而不只是被看见。
    static func accessibilityLabel(for status: ConnectionStatus, caseCount: Int) -> String {
        if case .connected(let version) = status {
            return "Connected to Beacon Server \(version), \(caseCount) cases loaded"
        }
        return text(for: status, caseCount: caseCount)
    }
}
