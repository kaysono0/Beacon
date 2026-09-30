import SwiftUI

/// 环境就绪度 popover：Server / Agents / SDK Capabilities 三段结论，开跑前确认能不能跑。
///
/// 视图自身不持状态，数据源是 `ConsoleViewModel.readiness`；三段各自独立成败，
/// 一段读不到时其余两段照常给出结论，原因文本就地展示在该段下面。
struct ReadinessView: View {
    let snapshot: ReadinessSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            Divider()
            if isUnchecked {
                loadingState
            } else {
                section(ReadinessPresenter.serverSection(of: snapshot)) {
                    EmptyView()
                }
                section(ReadinessPresenter.agentsSection(of: snapshot)) {
                    agentRows
                }
                section(ReadinessPresenter.capabilitiesSection(of: snapshot)) {
                    capabilityRows
                }
            }
        }
        .padding(12)
        .frame(width: 440)
        .accessibilityIdentifier("readinessPopover")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Environment readiness")
                .font(.headline)
            Text("Server health, online agents and loaded SDK capabilities.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    /// 三段都还没有任何事实（既无结果也无错误）时只显示进度，避免加载瞬间闪一片红。
    private var isUnchecked: Bool {
        snapshot.serverStatus == nil && snapshot.serverError == nil
            && snapshot.devices.isEmpty && snapshot.devicesError == nil
            && snapshot.sdkCapabilities.isEmpty && snapshot.capabilitiesError == nil
    }

    private var loadingState: some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.small)
            Text("Checking environment…")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, minHeight: 60)
        .accessibilityIdentifier("readinessLoading")
    }

    private func section<Rows: View>(
        _ section: ReadinessSection,
        @ViewBuilder rows: () -> Rows
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: ReadinessPresenter.symbolName(for: section.level))
                    .foregroundStyle(ReadinessPresenter.color(for: section.level))
                    .accessibilityIdentifier("readinessIcon_\(section.accessibilityKey)")
                Text(section.title)
                    .font(.subheadline)
                    .fontWeight(.semibold)
                Spacer(minLength: 8)
                Text(section.summary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("readinessSummary_\(section.accessibilityKey)")
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(section.title): \(section.summary)")
            if let errorText = section.errorText {
                Text(errorText)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("readinessError_\(section.accessibilityKey)")
            }
            rows()
        }
    }

    private var agentRows: some View {
        VStack(alignment: .leading, spacing: 3) {
            ForEach(snapshot.devices) { device in
                HStack(spacing: 8) {
                    Text(device.nodeID)
                        .font(.system(.caption, design: .monospaced))
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Text(device.platform)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 8)
                    Text(device.status)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(ReadinessPresenter.lastSeenText(milliseconds: device.lastSeenMs, now: Date()))
                        .font(.caption)
                        .monospacedDigit()
                        .foregroundStyle(.secondary)
                        .frame(width: 64, alignment: .trailing)
                }
                .accessibilityIdentifier("readinessAgent_\(device.nodeID)")
            }
        }
    }

    private var capabilityRows: some View {
        VStack(alignment: .leading, spacing: 3) {
            ForEach(snapshot.sdkCapabilities) { capability in
                HStack(spacing: 8) {
                    Text(capability.sdk)
                        .font(.system(.caption, design: .monospaced))
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer(minLength: 8)
                    Text(ReadinessPresenter.capabilitySummary(of: capability))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .accessibilityIdentifier("readinessSDK_\(capability.sdk)")
            }
        }
    }
}
