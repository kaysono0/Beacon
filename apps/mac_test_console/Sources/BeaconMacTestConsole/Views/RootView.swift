import AppKit
import SwiftUI

/// Mac 测试控制台主界面。
///
/// 这里负责把用户操作接到 `ConsoleViewModel`：启动时加载 server 暴露的 case，
/// 点击 Run 时提交当前选中的 case，详情和日志由 view model 更新后展示。
struct RootView: View {
    @EnvironmentObject private var appState: AppState
    @StateObject private var viewModel = ConsoleViewModel()
    @State private var serverURLText = ""
    @State private var tokenText = ""
    @State private var isRunHistoryPresented = false
    @State private var isReadinessPresented = false

    var body: some View {
        VStack(spacing: 0) {
            connectionBar
            Divider()
            NavigationSplitView {
                SidebarView(viewModel: viewModel) { sdk in
                    Task { await selectSDKWithRouting(sdk) }
                }
                .navigationSplitViewColumnWidth(min: 180, ideal: 220, max: 280)
            } content: {
                CaseListView(viewModel: viewModel)
                    .navigationSplitViewColumnWidth(min: 220, ideal: 280, max: 320)
            } detail: {
                VSplitView {
                    VStack(alignment: .leading, spacing: 12) {
                        if let selectedCase = viewModel.selectedCase {
                            Text(selectedCase.name)
                                .font(.title2)
                            Text(selectedCase.caseID)
                                .foregroundStyle(.secondary)
                            HStack {
                                Button {
                                    Task {
                                        // Run 使用连接栏当前值创建 client，避免用户改了地址或 token 后仍请求旧 server。
                                        await applyConnectionAndLoadIfNeeded()
                                        let client = BeaconServerClient(baseURL: appState.serverURL, token: appState.token)
                                        await refreshConnectionProbe(client)
                                        await viewModel.runSelectedCase(client: client, nodeID: appState.selectedNodeID)
                                    }
                                } label: {
                                    Text(viewModel.isRunning ? "Running" : "Run")
                                }
                                .buttonStyle(.borderedProminent)
                                .disabled(viewModel.isRunning)
                                .accessibilityLabel(viewModel.isRunning ? "Running" : "Run")
                                .accessibilityIdentifier("runSelectedCaseButton")
                                Button {
                                    Task {
                                        await applyConnectionAndLoadIfNeeded()
                                        let client = BeaconServerClient(baseURL: appState.serverURL, token: appState.token)
                                        await refreshConnectionProbe(client)
                                        do {
                                            _ = try await viewModel.runSelectedSuite(client: client, nodeID: appState.selectedNodeID)
                                        } catch {
                                            viewModel.errorMessage = String(describing: error)
                                        }
                                    }
                                } label: {
                                    Text(viewModel.isRunning ? "Running Suite" : "Run Suite")
                                }
                                .buttonStyle(.bordered)
                                .disabled(viewModel.isRunning || viewModel.suiteRunCases().isEmpty)
                                .accessibilityLabel(viewModel.isRunning ? "Running Suite" : "Run Suite")
                                .accessibilityIdentifier("runSelectedSuiteButton")
                                if viewModel.canCancelRun {
                                    Button {
                                        Task {
                                            // 取消沿用本次执行的连接，不让连接栏改动改变 run 的归属。
                                            let client = BeaconServerClient(
                                                baseURL: appState.serverURL,
                                                token: appState.token
                                            )
                                            await viewModel.cancelCurrentRun(client: client)
                                        }
                                    } label: {
                                        Text("Cancel")
                                    }
                                    .buttonStyle(.bordered)
                                    .accessibilityLabel("Cancel run")
                                    .accessibilityIdentifier("cancelRunButton")
                                }
                            }
                            if viewModel.isRunning {
                                HStack(spacing: 6) {
                                    ProgressView()
                                        .controlSize(.small)
                                    Text(viewModel.runningDescription)
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                }
                                .accessibilityIdentifier("runInProgressBanner")
                            }
                        } else {
                            Text("Select a test case")
                                .foregroundStyle(.secondary)
                        }
                        RunDetailView(
                            run: viewModel.currentRun,
                            observationCursorEnabled: viewModel.currentRunDetail?.observationCursorEnabled == true,
                            observations: viewModel.currentObservations,
                            observationError: viewModel.observationError
                        ) { stepID in
                            viewModel.toggleStepFilter(stepID)
                        }
                        Divider()
                        ReportView(detail: viewModel.currentRunDetail)
                        if let errorMessage = viewModel.errorMessage {
                            Text(errorMessage)
                                .foregroundStyle(.red)
                                .textSelection(.enabled)
                                .accessibilityIdentifier("connectionErrorText")
                        }
                    }
                    .padding()
                    .frame(minHeight: 320)

                    LogPanelView(viewModel: viewModel)
                        .frame(minHeight: 220)
                }
                .navigationSplitViewColumnWidth(min: 620, ideal: 780)
            }
            .navigationSplitViewStyle(.balanced)
        }
        .frame(minWidth: 1100, minHeight: 720)
        .sheet(isPresented: $isRunHistoryPresented) {
            RunHistoryView(
                entries: viewModel.runHistory,
                onOpenRun: { runID in
                    // 先关 sheet，回看结果才立刻出现在详情区，而不是被 sheet 挡住。
                    isRunHistoryPresented = false
                    Task {
                        let client = BeaconServerClient(baseURL: appState.serverURL, token: appState.token)
                        await viewModel.openRun(client: client, runID: runID)
                    }
                },
                onDismiss: { isRunHistoryPresented = false }
            )
        }
        .task {
            initializeConnectionFields()
            await loadCurrentConnection()
            let client = BeaconServerClient(baseURL: appState.serverURL, token: appState.token)
            await runAutorunIfNeeded(client: client)
        }
        .onDisappear {
            viewModel.stopRunDetailPolling()
            shutdownConsoleServerIfNeeded()
        }
    }

    private var connectionBar: some View {
        HStack(spacing: 10) {
            Text("Server")
                .font(.headline)
            TextField("http://127.0.0.1:8000", text: $serverURLText)
                .textFieldStyle(.roundedBorder)
                .frame(minWidth: 280)
                .accessibilityLabel("Server URL")
                .accessibilityIdentifier("serverURLField")
                .disabled(viewModel.isRunning)
            TokenField(token: $tokenText)
                .disabled(viewModel.isRunning)
            Button {
                Task {
                    await applyConnectionAndLoadIfNeeded()
                    await loadCurrentConnection()
                }
            } label: {
                Text("Reload")
            }
            .accessibilityLabel("Reload")
            .accessibilityIdentifier("reloadButton")
            .disabled(viewModel.isRunning)
            connectionStatusIndicator
            Spacer()
            Button {
                Task {
                    // 与 Run 一致使用连接栏当前值，避免用户改了地址或 token 后仍请求旧 server。
                    await applyConnectionAndLoadIfNeeded()
                    let client = BeaconServerClient(baseURL: appState.serverURL, token: appState.token)
                    // 先弹再拉：就绪度是三个并发请求，等结果再弹会让按钮看起来没反应。
                    isReadinessPresented = true
                    await viewModel.loadReadiness(client: client)
                }
            } label: {
                Text("Readiness")
            }
            .buttonStyle(.bordered)
            .popover(isPresented: $isReadinessPresented) {
                ReadinessView(snapshot: viewModel.readiness)
            }
            .accessibilityLabel("Readiness")
            .accessibilityIdentifier("readinessButton")
            Button {
                Task {
                    // 与 Run 一致使用连接栏当前值，避免用户改了地址或 token 后仍请求旧 server。
                    await applyConnectionAndLoadIfNeeded()
                    let client = BeaconServerClient(baseURL: appState.serverURL, token: appState.token)
                    isRunHistoryPresented = true
                    await viewModel.loadRunHistory(client: client)
                }
            } label: {
                Text("History")
            }
            .buttonStyle(.bordered)
            .accessibilityLabel("History")
            .accessibilityIdentifier("runHistoryButton")
            Button {
                NSApplication.shared.terminate(nil)
            } label: {
                Text("Quit")
            }
            .keyboardShortcut("q", modifiers: .command)
            .accessibilityLabel("Quit")
            .accessibilityIdentifier("quitAppButton")
        }
        .padding(12)
    }

    /// 连接栏状态指示：圆点给颜色、短文本给结论，完整错误文本仍由详情区 `connectionErrorText` 承载。
    private var connectionStatusIndicator: some View {
        let status = appState.connectionStatus
        let caseCount = viewModel.testCases.count
        return HStack(spacing: 6) {
            Circle()
                .fill(ConnectionStatusPresenter.color(for: status))
                .frame(width: 9, height: 9)
                .accessibilityLabel(ConnectionStatusPresenter.accessibilityLabel(for: status, caseCount: caseCount))
                .accessibilityIdentifier("connectionStatusDot")
            Text(ConnectionStatusPresenter.text(for: status, caseCount: caseCount))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .accessibilityIdentifier("connectionStatusText")
        }
    }

    private func initializeConnectionFields() {
        if serverURLText.isEmpty {
            serverURLText = appState.serverURL.absoluteString
        }
        if tokenText.isEmpty {
            tokenText = appState.token
        }
    }

    private func applyConnectionAndLoadIfNeeded() async {
        guard !viewModel.isRunning else { return }
        let previousURL = appState.serverURL
        let previousToken = appState.token
        if let url = URL(string: serverURLText), url != appState.serverURL {
            appState.serverURL = url
        }
        if tokenText != appState.token {
            appState.token = tokenText
        }
        if appState.serverURL != previousURL || appState.token != previousToken {
            viewModel.useConnection(BeaconServerClient(baseURL: appState.serverURL, token: appState.token))
            await loadCurrentConnection()
        }
    }

    private func loadCurrentConnection() async {
        let client = BeaconServerClient(baseURL: appState.serverURL, token: appState.token)
        appState.beginConnecting()
        let probe = await probeServer(client)
        guard client.baseURL == appState.serverURL, client.token == appState.token else { return }
        // APP 不扫描本地目录；case summary 由 Beacon Server 的 console API 提供。
        let load = await viewModel.load(client: client)
        guard client.baseURL == appState.serverURL, client.token == appState.token else { return }
        appState.applyConnection(probe: probe, load: load)
        alignSelectedSDKToCurrentServer()
        if case .unreachable(let message) = probe {
            // 探活失败时 load 可能已经清掉 errorMessage，红点旁边必须留下可排查的原因文本。
            viewModel.errorMessage = message
        }
    }

    /// 单 SDK Server 才按路由对齐 SDK；统一 Server 下保留用户刚点击的 SDK。
    private func alignSelectedSDKToCurrentServer() {
        guard let sdk = SDKRouteSelection.automaticallyAlignedSDK(
            capabilities: viewModel.sdkCapabilities,
            routes: appState.sdkRoutes,
            serverURL: appState.serverURL
        ) else {
            return
        }
        viewModel.selectSDK(sdk)
    }

    /// 选择 SDK 即切换环境：路由目标不可达时保持当前连接，只留下文字原因。
    ///
    /// 单环境运行时（如只 `up vc`）点另一个 SDK 不应把窗口甩到没启动的 server 上。
    private func selectSDKWithRouting(_ sdk: SDKCapability) async {
        guard !viewModel.isRunning else { return }
        guard let route = appState.sdkRoutes[sdk.sdk] else {
            viewModel.selectSDK(sdk)
            return
        }
        guard route.url != appState.serverURL || route.nodeID != appState.selectedNodeID else {
            viewModel.selectSDK(sdk)
            return
        }
        let probe = await probeServer(BeaconServerClient(baseURL: route.url, token: appState.token))
        guard case .reachable = probe else {
            viewModel.errorMessage = "\(sdk.sdk) is not running at \(route.url.absoluteString); "
                + "still connected to \(appState.serverURL.absoluteString)"
            return
        }
        guard !viewModel.isRunning else { return }
        appState.serverURL = route.url
        appState.selectedNodeID = route.nodeID
        viewModel.useConnection(BeaconServerClient(baseURL: route.url, token: appState.token))
        serverURLText = route.url.absoluteString
        viewModel.selectSDK(sdk)
        await loadCurrentConnection()
    }

    /// Run / Run Suite 前只探活：重载目录会经 `selectDefaultSDK`/`syncSelectedCase` 换掉用户刚选中的 case。
    ///
    /// 探活端点无鉴权，成功只证明 server 可达，因此这里只允许把状态降级为 failed。
    private func refreshConnectionProbe(_ client: BeaconServerClient) async {
        let previous = appState.connectionStatus
        appState.beginConnecting()
        let probe = await probeServer(client)
        if case .unreachable(let message) = probe {
            // 与 loadCurrentConnection 对称：红点旁边必须留下可排查的原因文本。
            viewModel.errorMessage = message
        }
        appState.applyProbeOnly(probe: probe, previous: previous)
    }

    /// 探活走无鉴权的 `GET /api/v1/status`：token 错误时它仍然可达，鉴权结论由带鉴权的目录加载给出。
    private func probeServer(_ client: BeaconServerClient) async -> ServerProbeResult {
        do {
            let status = try await client.status()
            guard status.status == "ok" else {
                return .unreachable(message: "server status is \(status.status)")
            }
            return .reachable(version: status.version)
        } catch {
            return .unreachable(message: String(describing: error))
        }
    }

    private func runAutorunIfNeeded(client: BeaconServerClient) async {
        guard let prefix = appState.autorunPrefix, let outputPath = appState.autorunOutputPath else {
            return
        }
        do {
            // 自动化模式复用同一条执行链，只是由启动参数选择一组 case，并把结果写给脚本消费。
            let runs = try await viewModel.runAutorunCases(
                client: client,
                prefix: prefix,
                caseIDs: appState.autorunCaseIDs,
                nodeID: appState.selectedNodeID
            )
            try writeAutorunOutput(path: outputPath, prefix: prefix, runs: runs)
        } catch {
            try? writeAutorunFailure(path: outputPath, prefix: prefix, error: String(describing: error))
        }
        NSApp.terminate(nil)
    }

    private func shutdownConsoleServerIfNeeded() {
        guard appState.autorunOutputPath == nil else {
            return
        }
        let client = BeaconServerClient(baseURL: appState.serverURL, token: appState.token)
        Task.detached {
            try? await client.shutdownLocalConsoleServer()
        }
    }

    private func writeAutorunOutput(
        path: String,
        prefix: String,
        runs: [(TestCaseSummary, RunResponse)]
    ) throws {
        let payload: [String: Any] = [
            "status": ConsoleViewModel.autorunStatus(runs: runs.map { $0.1 }, isAborted: viewModel.isRunAborted),
            "prefix": prefix,
            "cases": runs.map { item in
                [
                    "case_id": item.0.caseID,
                    "run_id": item.1.runID,
                    "status": item.1.status,
                ]
            },
        ]
        var data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
        data.append(0x0A)
        try data.write(to: URL(fileURLWithPath: path))
    }

    private func writeAutorunFailure(path: String, prefix: String, error: String) throws {
        let payload: [String: Any] = [
            "status": "failed",
            "prefix": prefix,
            "error": error,
            "cases": [],
        ]
        var data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
        data.append(0x0A)
        try data.write(to: URL(fileURLWithPath: path))
    }

}

/// 连接栏 token 控件：非编辑态固定显示 6 个掩码符，提供复制/临时显示/点击编辑。
/// 编辑态与空值态回落为 SecureField；提交语义与原实现一致（由 Reload/Run 应用连接值）。
private struct TokenField: View {
    @Binding var token: String
    @State private var isEditing = false
    @State private var isRevealed = false

    var body: some View {
        if isEditing || token.isEmpty {
            SecureField("Token", text: $token, onCommit: { isEditing = false })
                .textFieldStyle(.roundedBorder)
                .frame(width: 160)
                .accessibilityLabel("Auth Token")
                .accessibilityIdentifier("authTokenField")
        } else if isRevealed {
            HStack(spacing: 4) {
                Text(token)
                    .font(.system(.caption, design: .monospaced))
                    .lineLimit(1)
                    .truncationMode(.head)
                    .frame(maxWidth: 220)
                    .textSelection(.enabled)
                actionButtons(revealIcon: "eye.slash", revealAction: { isRevealed = false })
            }
        } else {
            HStack(spacing: 4) {
                Text("••••••")
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("tokenMaskedLabel")
                actionButtons(revealIcon: "eye", revealAction: { isRevealed = true })
            }
        }
    }

    private func actionButtons(revealIcon: String, revealAction: @escaping () -> Void) -> some View {
        HStack(spacing: 2) {
            Button(action: revealAction) {
                Image(systemName: revealIcon)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel(isRevealed ? "Hide token" : "Reveal token")
            .accessibilityIdentifier("tokenRevealButton")
            .help(isRevealed ? "Hide token" : "Reveal token")
            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(token, forType: .string)
            } label: {
                Image(systemName: "doc.on.doc")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Copy token")
            .accessibilityIdentifier("tokenCopyButton")
            .help("Copy token")
            Button {
                isRevealed = false
                isEditing = true
            } label: {
                Image(systemName: "square.and.pencil")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Edit token")
            .accessibilityIdentifier("tokenEditButton")
            .help("Edit token")
        }
    }
}
