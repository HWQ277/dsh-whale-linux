# 音效

这些文件全部来自上游发行包 `dsh-whale-widget-0.3.17`（MIT 许可，随包分发），
映射关系照抄它的 `lib/index.js`：

```js
SOUND_SETS = {
  duck: { press: [assets/Ya1.mp3], release: [assets/Ya2.mp3] },
  fx1:  { press: [assets/D1.mp3],  release: [assets/D2.mp3]  },
}
```

| 音效组 | 按下 | 松开 |
|---|---|---|
| `duck`（小黄鸭，默认） | `duck/press.mp3` ← 上游 `Ya1.mp3` | `duck/release.mp3` ← 上游 `Ya2.mp3` |
| `fx1`（音效1） | `fx1/press.mp3` ← 上游 `D1.mp3` | `fx1/release.mp3` ← 上游 `D2.mp3` |

随包还带着两个任务结束音（当前播放逻辑只用到按压/松开两槽，这两个先备用）：

- `minecraft-exp-orb.wav` —— 上游默认的任务结束音
- `task-end-a.wav` —— 上游备选

## 换成自己的音效

把 `press.mp3` / `release.mp3` 放到**本目录**（不是 `duck/`、`fx1/` 子目录里），
然后在设置里把「音效组」选成任意非预设值，或直接改 `config.json` 的
`settings.soundSet`。解析顺序是：预设文件 → `sounds/press.mp3` → `sounds/press.wav`。

播放器按 `paplay → pw-play → aplay → ffplay → canberra-gtk-play` 自动挑；
一个都没有就静音，不会报错。
