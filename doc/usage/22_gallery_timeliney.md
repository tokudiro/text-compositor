# timelineyのギャラリー

`timeliney`が対応する図の種類の実例です（[#291の対応表](08_diagrams.md#記法で描ける図の種類対応表)）。記法の説明は「図表」の章の「timelineyについて」を参照してください。

## ガントチャート

```timeliney
headerline(group(([*4月*], 2), ([*5月*], 2), ([*6月*], 2)))
headerline(
  group(..range(6).map(n => strong("第" + str(n + 1) + "週")))
)

taskgroup(title: [設計], {
  task("要件整理", (0, 1))
  task("画面設計", (1, 3))
})
taskgroup(title: [実装], {
  task("バックエンド", (2, 5))
  task("フロントエンド", (3, 6))
})

milestone(
  at: 5.9,
  style: (stroke: (dash: "dashed")),
  align(center, [*リリース*])
)
```
