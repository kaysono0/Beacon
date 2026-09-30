import Foundation

@MainActor
/// Mac Console 的界面状态与执行编排。
///
/// 本类不直接访问本地测试目录，只消费 `BeaconServerClient` 返回的 DTO。
/// 本地 case 文件由 Beacon Server 读取并通过 `/api/v1/console/test-cases` 返回。
final class ConsoleViewModel: ObservableObject {
    /// Mac Console 是真实 RTC SDK 的人工验证入口；通用系统/Mock case 留在其所属的底层测试门禁，
    /// 不进入这里的目录或可执行面。
    private static let supportedSDKs: Set<String> = ["agora_rtc", "volcengine_rtc", "zego_express"]
    @Published var sdkCapabilities: [SDKCapability] = []
    @Published var testCases: [TestCaseSummary] = []
    @Published var selectedSDK: SDKCapability?
    @Published var selectedSuite: String?
    @Published var selectedCase: TestCaseSummary?
    @Published var errorMessage: String?
    @Published var currentRun: RunResponse?
    @Published var currentRunDetail: ConsoleRunDetail?
    @Published private(set) var currentObservations: [ConsoleObservation] = []
    @Published private(set) var observationError: String?
    @Published var isRunning = false
    /// 会话内每个 case 的 run detail 缓存（run 摘要 + report + logs）；suite 顺序运行不再互相覆盖，
    /// App 重启即清空。切换 case 时详情区从这里恢复，不重新请求 server。
    ///
    /// 语义是「最近一次刷新到的 run」而不是「最近一次创建的 run」：History 回看旧 run 也会覆盖同一条目，
    /// 回看后列表状态点随之显示被回看的那条 run。
    @Published private(set) var caseRunDetails: [String: ConsoleRunDetail] = [:]
    /// 会话内每个 case 的最近一次 run 摘要，供列表状态点、耗时与 suite 聚合读取。
    ///
    /// 由 `caseRunDetails` 派生：摘要与详情必须来自同一次 run 刷新，各自缓存会漂移出
    /// 「列表显示失败、详情区却是上一次通过」这类自相矛盾的界面。
    var caseResults: [String: RunResponse] {
        caseRunDetails.mapValues(\.run)
    }

    /// 单个 case 的会话结果：列表按行读取走这里，避免每行都重建整份摘要字典。
    func runResult(for caseID: String) -> RunResponse? {
        caseRunDetails[caseID]?.run
    }
    /// 批量运行进度（Run Suite / autorun）：开跑前确定 total，每个 case 结束推进 done，结束即清空。
    @Published private(set) var suiteRunProgress: SuiteRunProgress?
    /// 最近一次拉取的 server 端运行历史摘要（倒序）；跨 App 重启仍可见，因为事实来自 server。
    @Published private(set) var runHistory: [RunHistorySummary] = []
    /// 最近一次拉取的就绪度快照；空快照表示三段都还没检查过，popover 会显示未检查态。
    @Published private(set) var readiness = ReadinessSnapshot()
    @Published var logRows: [LogRow] = []
    @Published var logFilter: String = ""
    @Published var logLevelFilter: LogLevelFilter = .all
    @Published var logStepFilter: String?
    @Published var showsLifecycleLogs = false
    private let runCoordinator = RunCoordinator()
    private var observationFeed = ObservationFeed()
    private var connectionURL: URL?
    private var connectionToken: String?
    private var connectionRevision = 0
    /// `runID -> caseID` 兜底索引：run detail 尚无 stepResults 时仍能把结果归属到 case。
    private var runCaseIndex: [String: String] = [:]

    /// Server 或凭证改变后，旧连接的目录、运行缓存和在途读取都不能进入新会话。
    func useConnection(_ client: BeaconServerClient) {
        guard connectionURL != client.baseURL || connectionToken != client.token else { return }
        let replacingConnection = connectionURL != nil
        connectionURL = client.baseURL
        connectionToken = client.token
        connectionRevision += 1
        guard replacingConnection else { return }
        resetDisplayedRunState()
        caseRunDetails = [:]
        runCaseIndex = [:]
        runHistory = []
        readiness = ReadinessSnapshot()
        observationFeed = ObservationFeed()
        sdkCapabilities = []
        testCases = []
        selectedSDK = nil
        selectedSuite = nil
        selectedCase = nil
        errorMessage = nil
    }

    /// autorun 输出消费批次中止意图；它不改变 Server 的各 run 终态。
    var isRunAborted: Bool { runCoordinator.isAborted }

    static func autorunStatus(runs: [RunResponse], isAborted: Bool) -> String {
        if runs.contains(where: { $0.status == "failed" }) { return "failed" }
        if isAborted || runs.contains(where: { $0.status == "cancelled" || $0.status == "canceled" }) {
            return "cancelled"
        }
        return runs.allSatisfy { $0.status == "passed" } ? "passed" : "failed"
    }

    var suites: [TestSuiteSummary] {
        CatalogSelection.suites(testCases, sdk: selectedSDK)
    }

    /// 运行中提示文案：批量运行给 (已完成/总数) 进度，单 case 运行给 caseID。
    var runningDescription: String {
        if let progress = suiteRunProgress {
            return "Running suite (\(progress.done)/\(progress.total))"
        }
        return "Running \(selectedCase?.caseID ?? "case")"
    }

    func cases(in suite: String) -> [TestCaseSummary] {
        CatalogSelection.cases(testCases, sdk: selectedSDK, in: suite)
    }

    func selectDefaultSDK() {
        if let selectedSDK,
           let refreshedSDK = sdkCapabilities.first(where: { $0.sdk == selectedSDK.sdk }) {
            self.selectedSDK = refreshedSDK
            return
        }
        selectedSDK = CatalogSelection.defaultSDK(in: sdkCapabilities)
    }

    func selectSDK(_ sdk: SDKCapability) {
        selectedSDK = sdk
        syncSelectedCase()
    }

    func selectSuite(_ suite: TestSuiteSummary) {
        selectedSuite = suite.name
        selectCase(cases(in: suite.name).first)
    }

    func selectCase(_ testCase: TestCaseSummary?) {
        let previousCaseID = selectedCase?.caseID
        selectedCase = testCase
        if previousCaseID != testCase?.caseID {
            resetDisplayedRunState()
            restoreCachedRunState(for: testCase?.caseID)
        }
    }

    func syncSelectedCase() {
        let current = CatalogSelection.State(
            selectedSDK: selectedSDK, selectedSuite: selectedSuite, selectedCase: selectedCase
        )
        let resolved = CatalogSelection.synchronized(current, testCases: testCases)
        selectedSDK = resolved.selectedSDK
        selectedSuite = resolved.selectedSuite
        selectCase(resolved.selectedCase)
    }

    var filteredLogs: [LogRow] {
        LogPresenter.filtered(
            logRows, text: logFilter, level: logLevelFilter, stepID: logStepFilter,
            showsLifecycle: showsLifecycleLogs
        )
    }

    var keyLogRows: [LogRow] {
        logRows.filter(\.isKeyEvent)
    }

    var hiddenLifecycleLogCount: Int {
        logRows.filter(\.isServerLifecycle).count
    }

    var stepFilterOptions: [String] {
        currentRun?.stepResults.map(\.stepID) ?? []
    }

    /// run 失败时给出失败步骤摘要；通过或运行中的 run 返回空。
    var failedStepResults: [StepResultSummary] {
        guard currentRun?.status == "failed" else { return [] }
        return (currentRun?.stepResults ?? []).filter { $0.status == "failed" }
    }

    /// Cancel 是否可用：本地有 run 在飞行中，或当前展示的 run 还没到终态。
    ///
    /// 创建响应尚未返回时也必须允许取消：此时先记录意图，取得确切 ID 后提交。
    var canCancelRun: Bool {
        isRunning || currentRun?.isTerminal == false
    }

    var runStartTimestamp: Date? {
        logRows.compactMap(\.timestamp).min()
    }

    /// 失败步骤相对 run 起始的偏移，取该步骤最早一条日志的时间；缺时间戳时返回 nil。
    func failureOffsetText(for result: StepResultSummary) -> String? {
        let stepStart = logRows
            .filter { $0.stepID == result.stepID }
            .compactMap(\.timestamp)
            .min()
        return Self.relativeOffsetText(from: runStartTimestamp, to: stepStart)
    }

    /// 再次点击同一步骤时清除过滤，方便在日志面板里一键切换回全量。
    func toggleStepFilter(_ stepID: String) {
        logStepFilter = logStepFilter == stepID ? nil : stepID
    }

    /// 加载 SDK 能力与 case 目录，并把结果回报给调用方。
    ///
    /// 连接状态属于 app 级状态，由调用方（RootView）写入 `AppState`；本方法只负责 `errorMessage` 与目录数据。
    @discardableResult
    func load(client: BeaconServerClient) async -> CaseLoadResult {
        useConnection(client)
        let revision = connectionRevision
        do {
            errorMessage = nil
            // 两个接口互不依赖：SDK 能力用于左侧 SDK 列表，case 列表来自 server 的 Python-native registry。
            async let capabilitiesResponse = client.sdkCapabilities()
            async let casesResponse = client.testCases()
            let loadedCapabilities = try await capabilitiesResponse
            let loadedCases = try await casesResponse
            guard connectionRevision == revision else { return .failed(message: "Connection changed") }
            sdkCapabilities = loadedCapabilities.sdks.filter { Self.supportedSDKs.contains($0.sdk) }
            testCases = loadedCases.cases.filter { testCase in
                testCase.platform == "mac" && Self.supportedSDKs.contains(where: testCase.referencesSDK)
            }
            // 重载目录时保留用户仍可用的 SDK；首次加载才使用稳定默认值。
            selectDefaultSDK()
            syncSelectedCase()
            return .loaded(caseCount: testCases.count)
        } catch {
            let message = String(describing: error)
            guard connectionRevision == revision else { return .failed(message: message) }
            errorMessage = message
            return .failed(message: message)
        }
    }

    func runSelectedCase(client: BeaconServerClient, nodeID: String?) async {
        guard !isRunning else { return }
        useConnection(client)
        let revision = connectionRevision
        guard let selectedCase else { return }
        isRunning = true
        defer { isRunning = false }
        do {
            logStepFilter = nil
            _ = try await runCoordinator.runSingle(
                selectedCase,
                client: client,
                nodeID: nodeID,
                onRunCreated: { [weak self] testCase, run, _ in
                    guard let self, self.connectionRevision == revision else { return }
                    self.runCaseIndex[run.runID] = testCase.caseID
                    self.currentRun = run
                },
                onDetail: { [weak self] detail, shouldDisplayDetail in
                    self?.receivePolledDetail(detail, shouldDisplayDetail: shouldDisplayDetail, client: client, revision: revision)
                }
            )
        } catch {
            guard connectionRevision == revision else { return }
            errorMessage = String(describing: error)
        }
    }

    func suiteRunCases() -> [TestCaseSummary] {
        guard let selectedSuite else { return [] }
        return runnableCases(in: selectedSuite)
    }

    /// suite 内可运行的 case：批量运行清单与 suite 聚合分母都以它为准。
    func runnableCases(in suite: String) -> [TestCaseSummary] {
        cases(in: suite).filter { $0.implementationStatus == "runnable" }
    }

    func runSelectedSuite(client: BeaconServerClient, nodeID: String?) async throws -> [(TestCaseSummary, RunResponse)] {
        guard !isRunning else { throw CancellationError() }
        useConnection(client)
        let revision = connectionRevision
        isRunning = true
        defer {
            isRunning = false
        }
        logStepFilter = nil
        return try await runCoordinator.runSuite(
            suiteRunCases(),
            client: client,
            nodeID: nodeID,
            onRunCreated: { [weak self] testCase, run, _ in
                guard let self, self.connectionRevision == revision else { return }
                self.runCaseIndex[run.runID] = testCase.caseID
            },
            onDetail: { [weak self] detail, shouldDisplayDetail in
                self?.receivePolledDetail(detail, shouldDisplayDetail: shouldDisplayDetail, client: client, revision: revision)
            },
            onProgress: { [weak self] progress in
                guard let self, self.connectionRevision == revision else { return }
                self.suiteRunProgress = progress
            }
        )
    }

    func exportCurrentRunPackage(to url: URL) throws {
        guard let currentRunDetail else {
            throw ConsoleExportError.missingRunDetail
        }
        let package = RunExportPackage(
            schemaVersion: 1,
            run: currentRunDetail.run,
            report: currentRunDetail.report,
            logs: currentRunDetail.logs
        )
        let encoder = JSONEncoder.beacon
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        var data = try encoder.encode(package)
        data.append(0x0A)
        try data.write(to: url, options: [.atomic])
    }

    func autorunCases(matching prefix: String, caseIDs: [String]? = nil) -> [TestCaseSummary] {
        let allowedCaseIDs = caseIDs.map(Set.init)
        return testCases
            .filter { testCase in
                guard testCase.caseID.hasPrefix(prefix) else {
                    return false
                }
                guard testCase.implementationStatus == "runnable" else {
                    return false
                }
                guard let allowedCaseIDs else {
                    return true
                }
                return allowedCaseIDs.contains(testCase.caseID)
            }
            .sorted {
                autorunPriority($0) == autorunPriority($1)
                    ? $0.caseID < $1.caseID
                    : autorunPriority($0) < autorunPriority($1)
            }
    }

    func runAutorunCases(
        client: BeaconServerClient,
        prefix: String,
        caseIDs: [String]? = nil,
        nodeID: String?
    ) async throws -> [(TestCaseSummary, RunResponse)] {
        guard !isRunning else { throw CancellationError() }
        useConnection(client)
        let revision = connectionRevision
        isRunning = true
        defer {
            isRunning = false
        }
        logStepFilter = nil
        let selectedCases = autorunCases(matching: prefix, caseIDs: caseIDs)
        return try await runCoordinator.runAutorun(
            selectedCases,
            catalog: testCases,
            client: client,
            nodeID: nodeID,
            onRunCreated: { [weak self] testCase, run, _ in
                guard let self, self.connectionRevision == revision else { return }
                self.runCaseIndex[run.runID] = testCase.caseID
            },
            onDetail: { [weak self] detail, shouldDisplayDetail in
                self?.receivePolledDetail(detail, shouldDisplayDetail: shouldDisplayDetail, client: client, revision: revision)
            },
            onProgress: { [weak self] progress in
                guard let self, self.connectionRevision == revision else { return }
                self.suiteRunProgress = progress
            }
        )
    }

    func startRunDetailPolling(
        client: BeaconServerClient,
        runID: String,
        intervalNanoseconds: UInt64 = 1_000_000_000,
        shouldDisplayDetail: Bool = true
    ) {
        useConnection(client)
        let revision = connectionRevision
        runCoordinator.startPolling(
            client: client, runID: runID, intervalNanoseconds: intervalNanoseconds,
            onDetail: { [weak self] detail in self?.receivePolledDetail(detail, shouldDisplayDetail: shouldDisplayDetail, client: client, revision: revision) },
            onError: { [weak self] message in
                guard let self, self.connectionRevision == revision else { return }
                self.errorMessage = message
            }
        )
    }

    func stopRunDetailPolling() {
        runCoordinator.stopPolling()
    }

    /// 拉取 server 端运行历史摘要（倒序、限量），供 History sheet 展示与回看。
    ///
    /// 历史事实属于 server：App 重启后仍能看到之前的 run，这与只在会话内有效的 `caseRunDetails` 不同。
    func loadRunHistory(client: BeaconServerClient, limit: Int = 50) async {
        useConnection(client)
        let revision = connectionRevision
        do {
            let history = try await client.history(limit: limit).runs
            guard connectionRevision == revision else { return }
            runHistory = history
        } catch {
            guard connectionRevision == revision else { return }
            errorMessage = String(describing: error)
        }
    }

    /// 拉取就绪度三段事实：server 健康、在线 Agent 池、SDK 能力计数，全部复用既有端点。
    ///
    /// 段级失败只写进 `readiness` 由 popover 就地展示，不写 `errorMessage`：详情区的错误文本
    /// 属于当前 case/run 的排查上下文，就绪度缺一段（例如 token 错导致读不到 agent）不该覆盖它。
    func loadReadiness(client: BeaconServerClient) async {
        useConnection(client)
        let revision = connectionRevision
        async let server = Self.fetchServerStatus(client)
        async let agents = Self.fetchDevices(client)
        async let capabilities = Self.fetchSDKCapabilities(client)
        let (serverResult, agentResult, capabilityResult) = await (server, agents, capabilities)
        guard connectionRevision == revision else { return }
        readiness = ReadinessSnapshot(
            serverStatus: serverResult.status,
            serverError: serverResult.error,
            devices: agentResult.devices?.devices ?? [],
            devicesError: agentResult.error,
            sdkCapabilities: capabilityResult.capabilities?.sdks ?? [],
            capabilitiesError: capabilityResult.error
        )
    }

    /// 三段各自一个 do/catch：`/api/v1/status` 无鉴权而另两个带鉴权，
    /// 合成一个 catch 会把「server 可达但读不到 agent 与能力」这一最有诊断价值的组合抹平。
    private static func fetchServerStatus(
        _ client: BeaconServerClient
    ) async -> (status: StatusResponse?, error: String?) {
        do {
            return (try await client.status(), nil)
        } catch {
            return (nil, String(describing: error))
        }
    }

    private static func fetchDevices(
        _ client: BeaconServerClient
    ) async -> (devices: DevicesResponse?, error: String?) {
        do {
            return (try await client.devices(), nil)
        } catch {
            return (nil, String(describing: error))
        }
    }

    private static func fetchSDKCapabilities(
        _ client: BeaconServerClient
    ) async -> (capabilities: SDKCapabilitiesResponse?, error: String?) {
        do {
            return (try await client.sdkCapabilities(), nil)
        } catch {
            return (nil, String(describing: error))
        }
    }

    /// 没有本次执行或明确展示的非终态 run 时，取消目标缺失必须可见。
    static let cancelRunUnavailableText = "No cancellable run selected"
    /// 正在创建或执行时只取消本批的确切 run；未取得 ID 时保留中止意图。
    func cancelCurrentRun(
        client: BeaconServerClient,
        pollingIntervalNanoseconds: UInt64 = 1_000_000_000
    ) async {
        if isRunning {
            let revision = connectionRevision
            do {
                try await runCoordinator.cancelActiveRun()
            } catch {
                guard connectionRevision == revision else { return }
                errorMessage = String(describing: error)
            }
            return
        }
        useConnection(client)
        let revision = connectionRevision
        guard let runID = currentRun?.runID, currentRun?.isTerminal == false else {
            errorMessage = Self.cancelRunUnavailableText
            return
        }
        do {
            _ = try await client.cancelRun(runID: runID)
            guard connectionRevision == revision else { return }
            try await refreshRunDetail(client: client, runID: runID)
            if currentRun?.isTerminal != true {
                startRunDetailPolling(client: client, runID: runID, intervalNanoseconds: pollingIntervalNanoseconds)
            }
        } catch {
            guard connectionRevision == revision else { return }
            errorMessage = String(describing: error)
        }
    }

    /// 回看会话内已记录的 run：停轮询后重取 detail，并按 run 归属切换选中 case。
    ///
    /// 这里直接赋值 `selectedCase`，绕过 `selectCase` 的 `resetDisplayedRunState`，
    /// 已展示内容与会话结果都不被清空。
    func openRun(client: BeaconServerClient, runID: String) async {
        useConnection(client)
        let revision = connectionRevision
        stopRunDetailPolling()
        do {
            try await refreshRunDetail(client: client, runID: runID)
            guard connectionRevision == revision else { return }
        } catch {
            guard connectionRevision == revision else { return }
            errorMessage = String(describing: error)
            return
        }
        guard
            let caseID = currentRun?.stepResults.first?.caseID ?? currentRun?.cases?.first?.caseID ?? runCaseIndex[runID],
            let testCase = testCases.first(where: { $0.caseID == caseID })
        else {
            return
        }
        // SDK/suite 选择必须跟随回看的 case，否则跨 suite 回看后 syncSelectedCase 会把它当非法选择清掉。
        if let sdk = sdkCapabilities.first(where: { testCase.referencesSDK($0.sdk) }) {
            selectedSDK = sdk
        }
        selectedSuite = testCase.suite
        selectedCase = testCase
    }

    /// 取一轮 run detail。`shouldDisplayDetail` 为 false 时只落会话缓存、不改展示目标（批量运行用：
    /// 详情区停在你正在看的 case 上，刚跑完的 case 结果先缓存，点它的 case 行即可查看）。
    @discardableResult
    private func refreshRunDetail(
        client: BeaconServerClient,
        runID: String,
        shouldDisplayDetail: Bool = true
    ) async throws -> ConsoleRunDetail {
        let revision = connectionRevision
        let detail = try await client.runDetail(runID: runID)
        guard connectionRevision == revision else { throw CancellationError() }
        recordRunDetail(detail)
        if shouldDisplayDetail {
            showRunDetail(detail)
        }
        if detail.observationCursorEnabled == true {
            await refreshObservations(client: client, runID: runID)
        }
        return detail
    }

    /// run 状态的唯一落地处：会话内 per-case 结果只在这里写，轮询刷新因此是覆盖而不是新增。
    private func recordRunDetail(_ detail: ConsoleRunDetail) {
        // server 契约是一 run 一 case：优先取 stepResults，run 尚无 stepResults 时用创建期索引兜底。
        guard let caseID = caseID(of: detail.run) else { return }
        caseRunDetails[caseID] = detail
    }

    /// 轮询已由 `RunCoordinator` 取得 detail；这里仅保留 ViewModel 的界面投影职责。
    private func receivePolledDetail(_ detail: ConsoleRunDetail, shouldDisplayDetail: Bool, client: BeaconServerClient, revision: Int) {
        guard connectionRevision == revision else { return }
        recordRunDetail(detail)
        if shouldDisplayDetail {
            showRunDetail(detail)
        }
        if detail.observationCursorEnabled == true {
            Task { [weak self] in
                guard let self, self.connectionRevision == revision else { return }
                await self.refreshObservations(client: client, runID: detail.run.runID)
            }
        }
    }

    private func refreshObservations(client: BeaconServerClient, runID: String) async {
        let revision = connectionRevision
        let feed = observationFeed
        do {
            try await feed.refresh(runID: runID, client: client)
            if connectionRevision == revision && currentRun?.runID == runID {
                currentObservations = feed.records(for: runID)
                observationError = nil
            }
        } catch {
            if connectionRevision == revision && currentRun?.runID == runID {
                currentObservations = feed.records(for: runID)
                observationError = "Observation read failed: \(error)"
            }
        }
    }

    /// run 归属的 case：旧链取 stepResults，目标链取 cases，创建期索引仅作兜底。
    private func caseID(of run: RunResponse) -> String? {
        run.stepResults.first?.caseID ?? run.cases?.first?.caseID ?? runCaseIndex[run.runID]
    }

    /// 把一份 run detail 铺到当前展示位（run 摘要、报告、日志）。
    private func showRunDetail(_ detail: ConsoleRunDetail) {
        currentRunDetail = detail
        currentRun = detail.run
        currentObservations = observationFeed.records(for: detail.run.runID)
        observationError = nil
        updateLogs(from: detail)
    }

    /// 切回本会话已跑过的 case 时恢复上次展示。
    ///
    /// 只铺缓存、不发请求：缓存里就是那次 run 的完整 detail，重新拉取会为一次纯 UI 切换引入网络失败面。
    private func restoreCachedRunState(for caseID: String?) {
        guard let caseID, let detail = caseRunDetails[caseID] else { return }
        showRunDetail(detail)
    }

    func updateLogs(from detail: ConsoleRunDetail) {
        logRows = LogPresenter.rows(from: detail)
    }

    private static let logTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter
    }()

    static func timeText(from date: Date) -> String {
        logTimeFormatter.string(from: date)
    }

    static func relativeOffsetText(from start: Date?, to end: Date?) -> String? {
        guard let start, let end else { return nil }
        return String(format: "%+.2fs", end.timeIntervalSince(start))
    }

    /// 导出当前过滤后可见日志为纯文本，复制与保存共用同一格式。
    func visibleLogsText() -> String {
        LogPresenter.visibleText(filteredLogs)
    }

    /// autorun 执行顺序：`autorun-order:N` tag 声明优先级，未声明的 case 排在最后。
    private func autorunPriority(_ testCase: TestCaseSummary) -> Int {
        for tag in testCase.tags where tag.hasPrefix(AutorunCaseTag.orderPrefix) {
            if let order = Int(tag.dropFirst(AutorunCaseTag.orderPrefix.count)) {
                return order
            }
        }
        return Int.max
    }

    /// 只清展示态：会话内 `caseRunDetails` 跨 case 切换保留，切回已跑过的 case 时由
    /// `restoreCachedRunState` 重新铺开那份 detail。
    private func resetDisplayedRunState() {
        stopRunDetailPolling()
        currentRun = nil
        currentRunDetail = nil
        currentObservations = []
        observationError = nil
        logRows = []
        logFilter = ""
        logLevelFilter = .all
        logStepFilter = nil
        showsLifecycleLogs = false
    }
}

struct TestSuiteSummary: Equatable, Identifiable {
    let name: String
    let count: Int

    var id: String { name }
}

/// 批量运行进度：total 在开跑前确定，done 随每个 case 结束推进。
struct SuiteRunProgress: Equatable {
    let done: Int
    let total: Int
}

struct LogRow: Equatable, Identifiable {
    /// 稳定身份，跨轮询重建保持不变：
    /// 优先用 server 事件的稳定 id（`node|event_id`，同一 run 的日志可能来自多个节点，
    /// 因此必须带上节点）；没有该 id 的行（例如测试夹具）回退到内容复合键。
    /// `updateLogs` 对同内容多行追加出现序号后缀，保证同一列表内身份唯一。
    var id: String
    let level: String
    let message: String
    let nodeID: String
    let event: String
    /// 主列表的排障摘要：先看调了什么，再看结果；事件名和关联字段留在 Details。
    let operation: String
    let outcome: String
    let detail: String
    let timestamp: Date?
    let module: String
    let stepID: String?
    let isKeyEvent: Bool

    init(
        level: String,
        message: String,
        nodeID: String,
        event: String = "",
        operation: String = "",
        outcome: String = "",
        detail: String = "",
        isKeyEvent: Bool = false,
        timestamp: Date? = nil,
        module: String = "",
        stepID: String? = nil,
        eventID: String = ""
    ) {
        self.id = eventID.isEmpty
            ? Self.contentIdentity(
                level: level,
                message: message,
                nodeID: nodeID,
                event: event,
                timestamp: timestamp,
                module: module,
                stepID: stepID
            )
            : "\(nodeID)|\(eventID)"
        self.level = level
        self.message = message
        self.nodeID = nodeID
        self.event = event
        self.operation = operation.isEmpty ? (event.isEmpty ? message : event) : operation
        self.outcome = outcome.isEmpty ? message : outcome
        self.detail = detail
        self.timestamp = timestamp
        self.module = module
        self.stepID = stepID
        self.isKeyEvent = isKeyEvent
    }

    /// 回退身份键：每段带长度前缀再拼接。日志文本里可能出现任意字符（包括分隔符与 `#N`
    /// 形态），长度前缀使「不同内容拼出的键必不相同」，也不会被出现序号后缀伪造出同值。
    private static func contentIdentity(
        level: String,
        message: String,
        nodeID: String,
        event: String,
        timestamp: Date?,
        module: String,
        stepID: String?
    ) -> String {
        func part(_ value: String) -> String { "\(value.count):\(value)" }
        return [
            part(timestamp.map { String($0.timeIntervalSince1970) } ?? ""),
            part(level),
            part(module),
            part(nodeID),
            part(event),
            part(stepID ?? ""),
            part(message),
        ].joined()
    }

    /// Server 生命周期事件（run 编排、console 轮询）默认折叠，不参与 case 排查。
    var isServerLifecycle: Bool {
        event.hasPrefix("native.run.") || event.hasPrefix("console.")
    }
}

enum LogLevelFilter: String, CaseIterable, Identifiable {
    case all
    case info
    case warning
    case error

    var id: String { rawValue }

    var label: String {
        switch self {
        case .all:
            return "All"
        case .info:
            return "Info"
        case .warning:
            return "Warn"
        case .error:
            return "Error"
        }
    }

    func matches(_ level: String) -> Bool {
        switch self {
        case .all:
            return true
        case .info:
            return level == "info"
        case .warning:
            return level.hasPrefix("warn")
        case .error:
            // agent_core 日志会把致命错误记为 fatal，排查时必须与 error 一起可见。
            return level == "error" || level == "fatal"
        }
    }
}

enum ConsoleExportError: Error, Equatable, CustomStringConvertible {
    case missingRunDetail

    var description: String {
        switch self {
        case .missingRunDetail:
            return "No run detail is available to export"
        }
    }
}

enum ConsoleAutorunError: Error, Equatable, CustomStringConvertible {
    case cleanupFailed(runID: String, status: String)
    case cleanupCaseNotFound(caseID: String)

    var description: String {
        switch self {
        case let .cleanupFailed(runID, status):
            return "Autorun cleanup failed: \(runID) status=\(status)"
        case let .cleanupCaseNotFound(caseID):
            return "Autorun cleanup case not found for \(caseID): expected exactly one runnable runtime-reset-baseline case on the same platform covering the same SDK"
        }
    }
}

enum AutorunCaseTag {
    static let runtimeResetBaseline = "runtime-reset-baseline"
    static let orderPrefix = "autorun-order:"
}

extension TestCaseSummary {
    func referencesSDK(_ sdk: String) -> Bool {
        containedSDKNames().contains(sdk)
    }

    func containedSDKNames() -> Set<String> {
        Set(sdkNames ?? []).union(steps.reduce(into: Set<String>()) { $0.formUnion($1.containedSDKNames()) })
    }
}

private extension JSONValue {
    func containedSDKNames() -> Set<String> {
        switch self {
        case .object(let object):
            var names = Set(object.values.flatMap { $0.containedSDKNames() })
            if case .string(let sdk) = object["sdk"] {
                names.insert(sdk)
            }
            return names
        case .array(let array):
            return Set(array.flatMap { $0.containedSDKNames() })
        case .string, .int, .double, .bool, .null:
            return []
        }
    }
}
