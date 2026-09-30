import Foundation

/// 运行历史行的时间、case 数与时长文本映射，供 History sheet 使用。
///
/// 与 `CaseRunPresenter`、`ConnectionStatusPresenter` 一样不持状态、不依赖视图层级；
/// 刻意放在 `Views/` 之外，才能被 `make coverage-mac-console` 的覆盖率门槛计入。
enum RunHistoryPresenter {
    /// server 返回的是 epoch 毫秒；历史可能跨天，因此带上月日而不只是时分秒。
    static func createdDate(milliseconds: Int) -> Date {
        Date(timeIntervalSince1970: TimeInterval(milliseconds) / 1000)
    }

    static func createdTimeText(milliseconds: Int) -> String {
        createdTimeFormatter.string(from: createdDate(milliseconds: milliseconds))
    }

    /// server 契约是一 run 一 case，但摘要按 `case_ids` 数组给出，文案因此保留复数形态。
    static func caseCountText(_ caseIDs: [String]) -> String {
        caseIDs.count == 1 ? "1 case" : "\(caseIDs.count) cases"
    }

    /// 未结束的 run 没有 `duration_ms`，显示占位符而不是 0 ms，避免被读成“瞬间跑完”。
    static func durationText(of summary: RunHistorySummary) -> String {
        guard let durationMs = summary.durationMs else {
            return "—"
        }
        return CaseRunPresenter.durationText(milliseconds: durationMs)
    }

    private static let createdTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "MM-dd HH:mm:ss"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter
    }()
}
