# D2のギャラリー

`d2`が対応する図の種類の実例です（[#291の対応表](08_diagrams.md#記法で描ける図の種類対応表)）。記法の説明は「図表」の章の「D2固有の注意点」を参照してください。

## シーケンス図

```d2
shape: sequence_diagram
利用者 -> 画面: ログイン操作
画面 -> API: 認証リクエスト
API -> DB: ユーザー照会
DB -> API: ユーザー情報
API -> 画面: トークン発行
画面 -> 利用者: ログイン完了
```

## クラス図

```d2
注文: {
  shape: class
  id: int
  注文日: date
  合計金額(): int
}
明細: {
  shape: class
  数量: int
  単価: int
}
注文 -> 明細: 1..*
```

## フローチャート

```d2
受付 -> 審査
審査 -> 承認: OK
審査 -> 差し戻し: NG
差し戻し -> 受付
承認 -> 発送
```

## ノードとエッジ図

```d2
利用者 -> サーバー
サーバー -> データベース
サーバー -> キャッシュ
```

## ER図

```d2
利用者: {
  shape: sql_table
  id: int {constraint: primary_key}
  氏名: text
}
注文: {
  shape: sql_table
  id: int {constraint: primary_key}
  利用者id: int {constraint: foreign_key}
  合計金額: int
}
利用者.id <-> 注文.利用者id
```

## ネットワーク構成図

```d2
インターネット -> ロードバランサー
ロードバランサー -> Webサーバー1
ロードバランサー -> Webサーバー2
Webサーバー1 -> DBサーバー
Webサーバー2 -> DBサーバー
```
