import SwiftUI

struct CaseListView: View {
    @ObservedObject var viewModel: ConsoleViewModel

    var body: some View {
        List {
            ForEach(currentCases) { testCase in
                Button {
                    viewModel.selectCase(testCase)
                } label: {
                    HStack(alignment: .top, spacing: 8) {
                        statusIcon(for: testCase)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(testCase.name)
                                .font(.headline)
                            Text(testCase.caseID)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 4)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("caseRow_\(testCase.caseID)")
            }
        }
        .navigationTitle(viewModel.selectedSuite ?? "Cases")
        // 透明 List + 不额外填色：中间列直接露出 NavigationSplitView 自身的列背景，
        // 与左右两窗格同源，避免显式 NSColor 在这套外观下渲染成突兀的白色或深灰板。
        .scrollContentBackground(.hidden)
    }

    /// 会话内最近结果的状态点：SF Symbol 与颜色双编码，未运行的 case 用虚线占位。
    private func statusIcon(for testCase: TestCaseSummary) -> some View {
        let status = viewModel.runResult(for: testCase.caseID)?.status
        return Image(systemName: CaseRunPresenter.symbolName(for: status))
            .foregroundStyle(CaseRunPresenter.color(for: status))
            .accessibilityIdentifier("caseStatusIcon_\(testCase.caseID)")
    }

    private var currentCases: [TestCaseSummary] {
        guard let suite = viewModel.selectedSuite else { return [] }
        return viewModel.cases(in: suite)
    }
}
