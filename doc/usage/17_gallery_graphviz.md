# Graphviz（dot/graphviz）のギャラリー

`dot`/`graphviz`が対応する図の種類の実例です（[#291の対応表](08_diagrams.md#記法で描ける図の種類対応表)）。記法の説明は「図表」の章の「Graphvizで使えない記法」を参照してください。

## フローチャート

```dot
digraph {
  rankdir=TB
  受付 -> 審査
  審査 -> 承認 [label="OK"]
  審査 -> 差し戻し [label="NG"]
  差し戻し -> 受付
  承認 -> 発送
}
```

## ノードとエッジ図

```dot
digraph {
  サーバー -> データベース
  サーバー -> キャッシュ
  クライアント -> サーバー
}
```
