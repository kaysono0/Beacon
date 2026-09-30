import Foundation

/// 日志行展开状态：按 run 归属。
///
/// 一次 Run Suite 里每个 case 各是一个 run，日志面板会随执行进度在不同 run 之间切换。
/// 若所有 run 共用一份展开集合，切走再切回时展开状态会串到别的 run 的日志上
/// （同一行 id 命中即被展开），并留下永不清理的过期 id。
struct LogExpansionState: Equatable {
    private var expandedRowIDsByRun: [String: Set<String>] = [:]

    func isExpanded(_ rowID: String, inRun runID: String) -> Bool {
        expandedRowIDsByRun[runID]?.contains(rowID) ?? false
    }

    mutating func toggle(_ rowID: String, inRun runID: String) {
        var rowIDs = expandedRowIDsByRun[runID] ?? []
        if rowIDs.contains(rowID) {
            rowIDs.remove(rowID)
        } else {
            rowIDs.insert(rowID)
        }
        expandedRowIDsByRun[runID] = rowIDs
    }

    func expandedCount(inRun runID: String) -> Int {
        expandedRowIDsByRun[runID]?.count ?? 0
    }
}
