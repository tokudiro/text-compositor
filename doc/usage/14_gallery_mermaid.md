# Mermaidのギャラリー

`mermaid`が対応する図の種類の実例です（[#291の対応表](08_diagrams.md#記法で描ける図の種類対応表)）。記法の説明は「図表」の章の「Mermaid固有の注意点」を参照してください。

## シーケンス図

```mermaid
sequenceDiagram
    利用者 ->> 画面: ログイン操作
    画面 ->> API: 認証リクエスト
    API ->> DB: ユーザー照会
    DB -->> API: ユーザー情報
    API -->> 画面: トークン発行
    画面 -->> 利用者: ログイン完了
```

## クラス図

```mermaid
classDiagram
    class 注文 {
      +int id
      +Date 注文日
      +合計金額() int
    }
    class 明細 {
      +int 数量
      +int 単価
    }
    注文 "1" --> "*" 明細
```

## 状態遷移図

```mermaid
stateDiagram-v2
    [*] --> 受付中
    受付中 --> 審査中 : 提出
    審査中 --> 承認済み : OK
    審査中 --> 差し戻し中 : NG
    差し戻し中 --> 受付中 : 再提出
    承認済み --> [*]
```

## 要求図

```mermaid
requirementDiagram
    requirement orderRequirement {
      id: 1
      text: "利用者は商品を注文できる"
      risk: medium
      verifymethod: test
    }
    element orderService {
      type: "サービス"
    }
    orderService - satisfies -> orderRequirement
```

## フローチャート

```mermaid
flowchart TD
    A[受付] --> B{承認?}
    B -->|はい| C[発送]
    B -->|いいえ| D[差し戻し]
    D --> A
```

## ノードとエッジ図

```mermaid
graph LR
    利用者 --> サーバー
    サーバー --> データベース
    サーバー --> キャッシュ
```

## ER図

```mermaid
erDiagram
    利用者 ||--o{ 注文 : 行う
    注文 ||--|{ 明細 : 含む
    利用者 {
      int id
      string 氏名
    }
    注文 {
      int id
      date 注文日
    }
```

## ガントチャート

```mermaid
gantt
    title 開発スケジュール
    dateFormat YYYY-MM-DD
    axisFormat %m/%d
    section 設計
    要件整理 :a1, 2026-04-01, 5d
    画面設計 :a2, after a1, 8d
    section 実装
    バックエンド :a3, after a2, 15d
    フロントエンド :a4, after a2, 12d
```

## データ可視化

```mermaid
xychart-beta
    title "月別の注文件数"
    x-axis ["1月", "2月", "3月", "4月", "5月"]
    y-axis "件数" 0 --> 1000
    bar [320, 450, 600, 580, 720]
    line [320, 450, 600, 580, 720]
```

## マインドマップ

```mermaid
mindmap
  root(ECサイト刷新)
    設計
      画面設計
      API設計
    実装
      バックエンド
      フロントエンド
    運用
      監視
      障害対応
```

## Git履歴図

```mermaid
gitGraph
    commit id: "初期化"
    branch develop
    checkout develop
    commit id: "機能追加"
    commit id: "修正"
    checkout main
    merge develop
    commit id: "リリース"
```

## タイムライン

```mermaid
timeline
    title 製品リリースの歴史
    2024 : v1.0公開
    2025 : v2.0公開 : 多言語対応
    2026 : v3.0公開 : AI機能追加
```

## カンバン

```mermaid
kanban
  未着手
    task1[要件整理]
    task2[画面設計]
  作業中
    task3[API実装]
  完了
    task4[環境構築]
```

## アーキテクチャ図

`architecture-beta`の`[...]`ラベルは、日本語などの非ASCII文字に対応していません（レクサーのエラーになります。実機確認）。この図だけ、ラベルを英語にしています。

```mermaid
architecture-beta
    group api(cloud)[API Platform]

    service db(database)[Database] in api
    service server(server)[API Server] in api
    service disk(disk)[Storage] in api

    server:R --> L:db
    server:B --> T:disk
```

## ポジションマップ（クアドラントチャート）

```mermaid
quadrantChart
    title 施策の優先度
    x-axis 低コスト --> 高コスト
    y-axis 低効果 --> 高効果
    quadrant-1 優先着手
    quadrant-2 計画的に実施
    quadrant-3 保留
    quadrant-4 効率化
    検索改善: [0.3, 0.8]
    決済多様化: [0.7, 0.7]
    UI刷新: [0.6, 0.3]
    ログ整備: [0.2, 0.2]
```

## パケット構造図

```mermaid
packet-beta
    0-15: "送信元ポート"
    16-31: "宛先ポート"
    32-63: "シーケンス番号"
    64-95: "確認応答番号"
```
