# Pikchrのギャラリー

`pikchr`が対応する図の種類の実例です（[#291の対応表](08_diagrams.md#記法で描ける図の種類対応表)）。記法の説明は「図表」の章の「Pikchrについて」を参照してください。

## フローチャート

```pikchr
box "受付" fit
arrow
D1: diamond "承認?" fit
arrow "はい" right from D1.e
box "発送" fit
arrow "いいえ" down from D1.s
box "差し戻し" fit
```

## ノードとエッジ図

```pikchr
A: circle "サーバー" fit
arrow right 150% from A.e "問い合わせ" aligned above
B: circle "DB" fit
arrow right 150% from B.e "取得" aligned above
C: circle "キャッシュ" fit
```

## 幾何図形・自由描画

```pikchr
box wid 200% ht 100% "外枠" fit
circle at 0.6in right of last box.e rad 40% "丸"
ellipse at 0.6in right of last circle.e wid 150% "楕円" fit
```
