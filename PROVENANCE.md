# 来源与归属说明 (Provenance)

本仓库是 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)
的 **Arch Linux 桌面移植版**，按上游 MIT 许可分发。

## 直接取自上游的素材

以下文件从上游仓库原样复制，版权归上游作者所有：

| 文件 | 用途 | 上游路径 |
|---|---|---|
| `assets/DSniang1.png` | 默认鲸鱼角色贴图 | `assets/DSniang1.png` |
| `assets/DSniang02.png` | 备用鲸鱼角色贴图 | `assets/DSniang02.png` |
| `assets/rua.gif` | 「rua」揉脸动图 | `assets/rua.gif` |
| `assets/bubble-petpet.gif` | 气泡图库：petpet | `assets/bubble-petpet.gif` |
| `assets/bubble-money1.gif` | 气泡图库：money1 | `assets/bubble-money1.gif` |
| `LICENSE` | 上游 MIT 许可证 | `LICENSE` |

## 由上游素材派生的内容

- `packaging/dsh-whale.png`、`packaging/icons/dsh-whale-*.png`
  —— 由 `assets/DSniang1.png` 缩放生成的应用图标。
- `src/dshwhale/bubble_geom.py`
  —— **并非**复制上游代码，而是对上游挂件中气泡 SVG 的**几何描摹**结果：
  用 `rsvg-convert` 渲染上游 `renderer/widget.js` 里的那段
  `<path d="M 827 248 A 373 232 …">` 加两个尾巴 `<ellipse>`，
  再对渲染结果做边界追踪 + Douglas-Peucker 简化，得到归一化多边形顶点。
  这样做的原因是 tkinter 无法渲染 SVG，而 X11 异形窗口需要的是位图轮廓。

## 配色

配色值直接沿用上游挂件的 CSS 变量，以保证外观一致：

| 名称 | 值 | 上游用途 |
|---|---|---|
| navy | `#203170` | 气泡描边、菜单、强调色 |
| white | `#ffffff` | 气泡填充 |
| danger | `#e0433f` | 错误/告警金额 |
| hint | `#9fb0d9` | 次级提示文字 |
| bubble-text | `#536ba9` | 气泡内标题文字 |

## 本移植版新增的代码

`src/dshwhale/` 下除 `bubble_geom.py`（派生数据）以外的全部 Python 代码、
`install.sh`、`PKGBUILD`、`packaging/*.desktop` 均为本移植版新增，同样按 MIT 分发。

## 音效素材（来自上游发行包）

本移植版最初没有分发音频，因为当时无法访问上游仓库、素材授权状况不明。
后来确认**官方发行包 `dsh-whale-widget-0.3.17` 本身就附带这些 mp3/wav 文件**，
随 MIT 许可一同分发，因此现在照搬过来并保持原有的映射关系：

| 本仓库 | 上游文件 | 用途 |
|---|---|---|
| `assets/sounds/duck/press.mp3`   | `assets/Ya1.mp3` | 「小黄鸭」按下 |
| `assets/sounds/duck/release.mp3` | `assets/Ya2.mp3` | 「小黄鸭」松开 |
| `assets/sounds/fx1/press.mp3`    | `assets/D1.mp3`  | 「音效1」按下 |
| `assets/sounds/fx1/release.mp3`  | `assets/D2.mp3`  | 「音效1」松开 |
| `assets/sounds/minecraft-exp-orb.wav` | `assets/minecraft-exp-orb.wav` | 任务结束音（随包备用） |
| `assets/sounds/task-end-a.wav`   | `assets/task-end-a.wav` | 备选任务结束音 |

映射取自上游 `lib/index.js`：

```js
SOUND_SETS = {
  duck: { press: [assets/Ya1.mp3], release: [assets/Ya2.mp3] },
  fx1:  { press: [assets/D1.mp3],  release: [assets/D2.mp3]  },
}
```

## 对照参考的版本

`dsh-whale-widget-0.3.17`（`package.json` 版本号与压缩包名一致）。
本移植版的气泡几何、字号公式、文字锚点、按压形变与音效映射均以该版本为准。

## 上游项目信息

- 仓库：<https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget>
- 许可：MIT
- 本移植版基于上游 `main` 分支（`dsh-whale-widget` v0.3.17）的界面与行为整理
