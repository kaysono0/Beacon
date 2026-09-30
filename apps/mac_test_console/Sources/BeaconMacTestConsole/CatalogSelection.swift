import Foundation

/// Console 目录选择规则：SDK、suite 与 case 选择只在此处归一化。
struct CatalogSelection {
    struct State: Equatable {
        var selectedSDK: SDKCapability?
        var selectedSuite: String?
        var selectedCase: TestCaseSummary?
    }

    static func filteredCases(_ testCases: [TestCaseSummary], sdk: SDKCapability?) -> [TestCaseSummary] {
        guard let sdk else { return testCases }
        return testCases.filter { $0.referencesSDK(sdk.sdk) }
    }

    static func cases(_ testCases: [TestCaseSummary], sdk: SDKCapability?, in suite: String) -> [TestCaseSummary] {
        filteredCases(testCases, sdk: sdk)
            .filter { $0.suite == suite }
            .sorted { $0.caseID < $1.caseID }
    }

    static func suites(_ testCases: [TestCaseSummary], sdk: SDKCapability?) -> [TestSuiteSummary] {
        let filtered = filteredCases(testCases, sdk: sdk)
        return Set(filtered.map(\.suite)).sorted().map { suite in
            TestSuiteSummary(name: suite, count: filtered.filter { $0.suite == suite }.count)
        }
    }

    static func defaultSDK(in capabilities: [SDKCapability]) -> SDKCapability? {
        capabilities.sorted { $0.sdk < $1.sdk }.first
    }

    static func synchronized(_ state: State, testCases: [TestCaseSummary]) -> State {
        var state = state
        let availableSuites = suites(testCases, sdk: state.selectedSDK)
        if !availableSuites.contains(where: { $0.name == state.selectedSuite }) {
            state.selectedSuite = availableSuites.first?.name
        }
        guard let suite = state.selectedSuite else {
            state.selectedCase = nil
            return state
        }
        let availableCases = cases(testCases, sdk: state.selectedSDK, in: suite)
        if !availableCases.contains(where: { $0.caseID == state.selectedCase?.caseID }) {
            state.selectedCase = availableCases.first
        }
        return state
    }
}
