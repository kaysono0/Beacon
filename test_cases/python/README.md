# Python 测试用例

正式 SDK 用例按厂商和通用场景分组，文件名、用例 ID、函数和 metadata 保持不变。

| 目录 | 范围 |
|---|---|
| `agora/` | Agora 生命周期、音视频、媒体播放器、统计与恢复场景 |
| `volcengine/` | 火山 L1 与视频场景 |
| `zego/` | ZEGO L1、双端房间与视频场景 |
| `common/` | 通用 SDK、Mock reference 与 smoke tracer |

Server 从此目录递归发现带 `__beacon_test__` metadata 的函数；Runner 根据 catalog
提供的仓库相对路径加载函数。目录分组不改变用例选择方式，调用者继续提交 case ID。

新增用例见[作者指南](../../docs/python-test-authoring-guide.md)，验证入口见
[验证合同](../../docs/development.md)。组件回归的归属见
[测试目录说明](../../tests/README.md)。
