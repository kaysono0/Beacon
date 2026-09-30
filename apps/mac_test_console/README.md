# Mac Test Console 源码

SwiftPM 从 `Sources/BeaconMacTestConsole/` 递归读取源码，保留单一 executable target。

| 位置 | 职责 |
|---|---|
| `BeaconMacTestConsoleApp.swift` | App 入口与依赖装配 |
| `Views/` | SwiftUI 页面与组件 |
| `Presentation/` | Case、History、连接、日志与 readiness 的展示转换 |
| 其余源码 | 状态、运行协调、Server client、数据模型、catalog 选择与 Observation read model |
| `Tests/BeaconMacTestConsoleTests/` | XCTest 组件回归 |

Presenter 保留原文件名和类型，仍属于同一个 Swift module；目录分组不增加 target 或接口层。
运行配置见 [Console 操作指南](../../docs/mac-console.md)，验证选择见
[开发与验证](../../docs/development.md)。
