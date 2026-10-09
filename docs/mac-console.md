# Mac Console 操作指南

本文负责本地真实 Server 与 Mac Console 的配置、启动、关闭和专项运行。首次体验框架可先走[无需 SDK 的 Mock 链路](quickstart.md)。

## 准备环境

- 新开发者可运行 `bash scripts/dev/setup_macos.sh` 安装 Homebrew 的 CMake、uv，并准备锁定的 Python 3.11 开发环境。仅准备 Agora 可用 `bash scripts/dev/setup_macos.sh --with-agora`；一起准备 Agora 和火山则运行 `bash scripts/dev/setup_macos.sh --with-sdks` 。脚本依次复用已导出的 SDK root、本地 env 中的路径、`third_party/<vendor>/macos/sdk/` 和此前 `.build/vendor-sdks/` 中的下载；没有可用 SDK 时，按提示提供厂商 HTTPS ZIP 链接，脚本会在确认厂商条款后下载并安装到 Git 忽略的 `.build/vendor-sdks/`，并更新本地 env 文件中的 SDK 路径。Agora 下载链接从[官方 SDK 下载页](https://docs.agora.io/en/api-reference/sdks)选择 macOS RTC 完整包后复制；可能需要登录厂商控制台。脚本只修改 SDK 路径，保留已有凭证。
- macOS 13+、CMake 3.16+、Xcode 命令行工具及兼容系统 SDK 的 Swift 工具链。用 `swift --version` 确认实际解析到的工具链；swiftly 等管理器可能覆盖 Xcode 工具链。
- 准备各 vendor 的本地 SDK，分发边界见 [THIRD-PARTY.md](../THIRD-PARTY.md)。
- 从 `local.agora.env.example`、`local.volcengine.env.example` 创建 git-ignored 的本地 env。`local.agora.env` 存放 Agora 与 ZEGO 配置，`local.volcengine.env` 存放火山配置；两者使用同一 `BEACON_AUTH_TOKEN`。
- 从有摄像头权限的终端启动画面用例。同一台 Mac 不并行运行争用真实摄像头的用例。

macOS 将摄像头权限归属于启动命令链的 App，而非测试二进制。首次运行接受系统提示，或在“系统设置 → 隐私与安全性 → 摄像头”中授权终端。IDE/agent 宿主未获授权时可能出现零帧；出现零帧时，先确认启动终端的摄像头授权，再关闭争用摄像头的其他用例并重试。

## 必填配置

setup 只准备工具、Python 环境和 SDK 路径，不创建厂商项目，也不生成 App ID、App Certificate、App Key、App Sign 或用户 token。模板中的 `your-*` 与示例路径必须替换为自己的值；真实验证返回 `skipped` 表示缺少环境，不是通过。

若本地 env 不存在，从对应 `.example` 复制；若已存在（包括 setup 生成的文件），直接编辑，避免覆盖现有 SDK 路径和凭证。Makefile 的真实入口会自动加载这些文件，无需另行 `source`。

| SDK | 配置文件 | 必填字段 |
|---|---|---|
| Agora | `local.agora.env` | `AGORA_MAC_SDK_ROOT`、`AGORA_APP_ID`、`AGORA_APP_CERT`、`BEACON_AUTH_TOKEN` |
| 火山引擎 | `local.volcengine.env` | `VOLCENGINE_MAC_SDK_ROOT`、`VOLCENGINE_RTC_ID`、`VOLCENGINE_RTC_APPKEY`、`BEACON_AUTH_TOKEN` |
| ZEGO | 追加到 `local.agora.env` | `ZEGO_MAC_SDK_ROOT`、`ZEGO_APP_ID`、`ZEGO_APP_SIGN`、`ZEGO_USER1_ID`、`ZEGO_USER2_ID`、`ZEGO_USER1_TOKEN`、`ZEGO_USER2_TOKEN` |

Agora 的 App ID 和 App Certificate 必须来自同一项目，Server 据此签发 RTC token。火山使用自己的 RTC App ID 与 App Key（变量名为 `VOLCENGINE_RTC_ID` 和 `VOLCENGINE_RTC_APPKEY`）。ZEGO 两个用户使用不同 ID，分别提供与所用项目、用户匹配的有效 token；当前入口检查 App Sign 和两个用户 token，不能只填 App ID。

`local.agora.env.example` 当前不包含 ZEGO 字段。运行统一 Console 时，在本地 `local.agora.env` 中追加以下配置并替换所有占位值：

```bash
ZEGO_MAC_SDK_ROOT='/absolute/path/to/zego-macos-sdk'
ZEGO_APP_ID='your-zego-app-id'
ZEGO_APP_SIGN='your-zego-app-sign'
ZEGO_USER1_ID='your-first-user-id'
ZEGO_USER2_ID='your-second-user-id'
ZEGO_USER1_TOKEN='your-first-user-token'
ZEGO_USER2_TOKEN='your-second-user-token'
```

SDK root 指向包含对应 framework / xcframework 的目录；路径含空格时加引号。两份 env 使用相同的 `BEACON_AUTH_TOKEN`，它是 Beacon 本地认证值，不是厂商 RTC token。凭证只保存在 Git 忽略的本地 env 中。

只配置 Agora 时，可运行 `make test-mac-agora-real` 或 `make test-mac-console-agora`。后者自行编排 Agora 的 App autorun 验证；手工统一 Console 的 `make run-mac-console-real-server` 则要求三家的 SDK 与全部必填字段齐备，任一家缺失都会阻止启动。`--with-sdks` 不负责 ZEGO SDK 下载。

统一 Server 的 Makefile 入口显式设置 `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`，因此需要完整 Xcode 位于该路径并完成首次启动初始化；仅有 Command Line Tools 不足以运行这一入口。

## 手工运行：两个终端

终端一启动一个 Server 和 Agora、火山、ZEGO 的真实 Agent：

```bash
make run-mac-console-real-server
```

终端二启动 App：

```bash
make run-mac-console-app
```

默认连接 `http://127.0.0.1:8000`。统一 Server 下选择 SDK 只切换该 SDK 的默认 Agent 节点；配置 `BEACON_CONSOLE_SDK_ROUTES` 指向多个 Server 时，Console 会先探活目标服务，再切换 Server URL 和节点并重载目录。选择 SDK 不会启动或回收 Agent；统一启动脚本按 runnable Agora 用例所需角色启动 Agora Agent，并启动 Volcengine、ZEGO 的 primary/peer Agent。切换时不调用已退役的 `/api/v1/sdk/call` 隐藏视频窗口；视频资源由用例清理和 Agent reset 回收。

三家 SDK 共用的原生 Video Host 会监听本机 Console APP 的激活：从其他应用切回 Beacon 时，已显示且未最小化的视频窗口会以临时浮动层级回到前台，并支持 Console 的全屏空间，同时保持 Console 的键盘焦点；切到其他应用时恢复原始层级与空间设置。Console 已激活后新出现的视频也沿用这一层级。隐藏或已清理的视频窗口不会被重新打开；无需额外控制按钮或 HTTP SDK 调用。

界面保留三栏：左侧 SDK/套件导航，中间用例列表，右侧详情与日志。中间列表宽度限制为 220–320 点，右侧至少 620 点并获得剩余空间；分隔线可拖动调整。右侧调用／回调信息列表高度为 150 点，更多记录通过滚动查看。用例操作区保留 Run、Run Suite，以及运行时的 Cancel；不再显示 Export、Show、Hide、Bring Forward、Recenter。

Agora 音视频演示每阶段 10 秒的展示等待运行在 Python Runner 内，不下发长时间 `SystemClock.waitInMs` 占住 Agent。Cancel 结束 Runner 后，由 Server 的后置 reset 停止媒体、退出房间并隐藏视频窗口；界面以实际清理后的 `cancelled` 报告收敛。已经进入 SDK 的调用仍按协作式取消约定等待完成，不承诺对所有 SDK 调用即时中断。

Python target run 的详情区以 `Execution records` 为标题，显示 SDK 回调、调用／等待结果和其他结构化 Observation；普通日志统一在下方 Logs 查看。每行省略重复 Case ID 与 `unbound` 占位，回调摘要显示实际字段值。Run ID 仍在报告区显示并可复制。Console 根据运行详情响应中的 `observation_cursor_enabled` 选择该列表，最终通过与失败状态由报告显示。

App 不拥有 Server 或 Agent，退出 App 后环境继续运行。完成后在终端一按 `Ctrl-C`，等待 Server 回收所有 Agent。

同端口重复启动必须失败。不要在该环境旁另起裸 Uvicorn 或重复 node ID 的 bridge 进程。检查端口占用：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

需要独立环境时用 `BEACON_CONSOLE_SERVER_PORT` 选择端口。

## 手工运行：tmux

```bash
bash scripts/dev/run_manual_env.sh up
bash scripts/dev/run_manual_env.sh status
bash scripts/dev/run_manual_env.sh down
```

默认 session 为 `beacon-mac-console`，包含 `server` 和 `app` 窗口。`Ctrl-b d` 只离开 tmux，环境继续运行；`down` 会中断 Server、回收 Agent 后关闭 session。

## 自动验证与官方用例子集

```bash
make test-mac-agora-real
make test-mac-console-agora
```

Agora Console gate 构建 bridge，启动 Server 和所需 Agent，通过 Console autorun 执行用例并自动清理。默认运行两轮，输出 `reports/latest/mac_console_agora.json`。

运行指定用例：

```bash
BEACON_MAC_CONSOLE_AGORA_CASE_IDS=TC-MAC-AGORA-1V1-REMOTE-VIDEO-RENDERED \
BEACON_MAC_CONSOLE_AGORA_ROUNDS=2 \
make test-mac-console-agora
```

火山、ZEGO 和三家统一 Console 的命令、配置要求与产物见 [CI 验证合同](development.md)。SDK 或凭证缺失时的 `skipped` 不证明行为通过。

## 本地录制演示

4/9 宫格使用仓库内的精简片源 `test_cases/media/grid_segments.mp4`（640×360、15 fps、8 分钟，含 48 kHz 双声道 AAC 音轨，约 20.2 MiB）。primary 第一个 tile 使用摄像头，其余由独立 Agora MediaPlayer 从第 0、60……420 秒开始发布不同片段，每个用例观察 10 秒。当前用例的自动断言覆盖视频统计和截图；声音由各 MediaPlayer 本地播放，听感仍需人工确认。

普通 `animated_clip` 使用 `test_cases/media/animated_clip.mp4`（320×180、15 fps、30 秒，无音轨），由 Native 解码器循环播放。Agora 配对视频与 MediaPlayer 使用 `test_cases/sample_960x400_ocean_with_audio.mp4`，自定义音频使用 `test_cases/sample_960x400_ocean_audio.m4a`。默认路径相对仓库根；启动器在该目录运行 Agent。需要自备素材时，使用 `BEACON_SYNTHETIC_VIDEO_CLIP_PATH`、`BEACON_SYNTHETIC_PAIRED_MEDIA_CLIP_PATH` 或 `BEACON_SYNTHETIC_AUDIO_CLIP_PATH` 指定路径。

初始化时会检查上述四份默认片源非空；它们直接由 Git 跟随 clone 下载，不需要另取本机原始 MOV。初始化不代替凭证配置：Agora 仍需在 `local.agora.env` 填写 App ID、App Certificate 和认证 token。仅准备 Agora 后可运行 `make test-mac-agora-real`；统一 Console 的启动入口仍要求三家 SDK 和凭证齐全。

展示等待缩短不改变 SDK 就绪与首帧超时。播放／暂停／恢复、发声／静音／恢复用例仍保留各阶段断言和 10 秒观察。

```bash
BEACON_MAC_CONSOLE_AGORA_CASE_IDS=TC-MAC-AGORA-4-GRID-CAMERA-MEDIA-SEGMENTS \
BEACON_MAC_CONSOLE_AGORA_ROUNDS=1 \
make test-mac-console-agora

BEACON_MAC_CONSOLE_AGORA_CASE_IDS=TC-MAC-AGORA-9-GRID-CAMERA-MEDIA-SEGMENTS \
BEACON_MAC_CONSOLE_AGORA_ROUNDS=1 \
make test-mac-console-agora
```

## Console 参数

| 环境变量 | CLI 参数 | 用途 |
|---|---|---|
| `BEACON_CONSOLE_SERVER_URL` | `--server-url` | Server URL |
| `BEACON_AUTH_TOKEN` | `--token` | 认证 token |
| `BEACON_NODE_ID` | `--node-id` | 目标 Agent |
| `BEACON_CONSOLE_SDK_ROUTES` | `--sdk-routes` | SDK 到环境的映射：`sdk=url#node,sdk=url` |
| `BEACON_CONSOLE_AUTORUN_PREFIX` | `--autorun-prefix` | autorun case ID 前缀 |
| `BEACON_CONSOLE_AUTORUN_OUTPUT` | `--autorun-output` | autorun 报告位置 |

显式使用多个 Server 时，每个 Console 使用一致的 `BEACON_CONSOLE_SDK_ROUTES`，所有 Server 使用同一认证 token。
