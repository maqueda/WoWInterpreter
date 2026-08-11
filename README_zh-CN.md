# WoWInterpreter

**面向《魔兽世界》经典怀旧服玩家的英语 ↔ 简体中文交流辅助工具。**

[English README](README.md) · [英文用户指南](Documentation/WoWInterpreter-2.1.4-User-Guide-English.docx) · [简体中文用户指南](Documentation/WoWInterpreter-2.1.4-User-Guide-Chinese-Simplified.docx)

WoWInterpreter 由游戏内插件和 Windows 托盘程序组成。插件把聊天文字通过视觉传输发送给 Windows Bridge，Bridge 在英语和简体中文之间进行翻译，然后把结果显示在可滚动的覆盖窗口中。

## 演示

![WoWInterpreter 英语与简体中文翻译演示](./assets/WoWInterpreter.gif)

*在《魔兽世界》经典怀旧服中实现英语 ↔ 简体中文实时交流。*

上面的演示展示了 WoWInterpreter 如何在游戏过程中翻译玩家之间的交流。游戏内插件与 Windows 翻译桥接程序进行通信，翻译后的消息会直接显示在 WoWInterpreter 覆盖窗口中。

## 功能

- 英语 → 简体中文、简体中文 → 英语。
- 面向密语、队伍、团队、说话、大喊等玩家交流。
- 使用 `/wi <文字>` 直接翻译。
- 使用 `/wi list` 和 `/wi last` 选择最近消息。
- 手动模式和自动翻译模式。
- 可滚动的翻译历史覆盖窗口。
- Windows 托盘菜单：Start、Stop、Status、诊断日志、Exit。
- 只有用户手动选择 **Start translator** 后翻译引擎才会运行。
- Windows 安装程序支持 English / 简体中文。
- 安装时会要求选择 WoW Classic Era 的 `Interface\AddOns` 文件夹。
- 使用 Release 安装包时不需要单独安装 Python。

## 下载和安装

普通用户请在 GitHub **Releases** 页面下载：

`WoWInterpreter-2.1.4-Setup.exe`

安装完成后：

1. 从 Windows 开始菜单启动 **WoWInterpreter**。
2. 在通知区域找到 **WI** 图标。
3. 右键 → **Start translator**。
4. 启动或重新启动 WoW，并确认 **WoWInterpreter** 插件已启用。
5. 输入 `/wi this is a test` 测试。

每次 Start 后第一次翻译可能较慢，因为翻译模型采用按需加载。

## 常用命令

| 命令 | 功能 |
| --- | --- |
| `/wi <文字>` | 翻译文字 |
| `/wi last` | 处理最近一条消息 |
| `/wi list` | 显示最近捕获的消息 |
| `/wi manual` | 手动模式 |
| `/wi auto` | 自动翻译模式 |
| `/wi off` | 关闭自动翻译 |
| `/wi help` | 显示帮助 |

## 工作原理

```text
WoW 聊天 / /wi
      ↓
WoWInterpreter 游戏插件
      ↓
KT06 视觉传输
      ↓
Windows Bridge
      ↓
NLLB 翻译
      ↓
可滚动覆盖窗口
```

发送请求时短暂出现的小网格属于正常的插件 → Windows 传输过程。

## 故障排除

如果网格出现但没有翻译，请右键 **WI** → **Open diagnostic log**。第一次正常加载模型时，日志最终应出现：

```text
[BRIDGE] Loading NLLB model: facebook/nllb-200-distilled-600M
[BRIDGE] NLLB ready.
```

不需要翻译时请选择 **Stop translator**，以停止 Bridge 和翻译引擎。

更完整的说明请查看 `Documentation/` 中的中文用户指南。

## 从源码构建

构建环境需要 Windows、Python、`requirements-runtime.txt` 中的依赖、PyInstaller，以及用于生成最终安装包的 Inno Setup 6。

运行：

```bat
build_release.bat
```

## 翻译模型和许可证说明

WoWInterpreter 通过 Hugging Face Transformers 按需下载/加载 `facebook/nllb-200-distilled-600M`。该模型**不属于本仓库 MIT 许可证的授权范围**。模型由其发布者以 **CC BY-NC 4.0** 单独授权，并且模型说明将其定位为研究模型，而不是生产部署模型。

如果要进行商业分发或商业使用，请先仔细确认模型许可证和相关条款。详情见 `THIRD_PARTY_NOTICES.md`。

## 隐私与免责声明

模型获取完成后，翻译在本地执行。程序使用屏幕捕获读取插件生成的小型视觉传输区域。机器翻译可能出错，请勿把结果当作权威或认证翻译。

WoWInterpreter 是独立社区项目，与 Blizzard Entertainment、Meta、Hugging Face 及其关联方没有隶属、赞助或官方认可关系。《魔兽世界》及相关商标归其各自权利人所有。

## 许可证

本仓库中的 WoWInterpreter 原创源代码使用 MIT License。第三方库和 NLLB 模型继续适用各自的许可证。请查看 `LICENSE` 和 `THIRD_PARTY_NOTICES.md`。
