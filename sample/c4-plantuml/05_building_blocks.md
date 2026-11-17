# 5 構成要素の見方

ECサイトの構造を、2つのレベルで示す。レベル1はECサイト全体（コンテナ）、レベル2はAPIの内部（コンポーネント）である。

## 5.1 レベル1: ECサイト

```plantuml
@startuml
!include <C4/C4_Container>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Person(customer, $customer_name, $customer_desc)
Person(operator, $operator_name, $operator_desc)

System_Boundary(ec, $ec_name) {
    Container(web, $web_name, $web_tech, $web_desc)
    Container(api, $api_name, $api_tech, $api_desc)
    ContainerDb(db, $db_name, $db_tech, $db_desc)
}
System_Ext(pay, $pay_name, $pay_desc)
System_Ext(mail, $mail_name, $mail_desc)

Rel(customer, web, "商品を探して、注文する", "HTTPS")
Rel(operator, web, "在庫を更新し、出荷指示を出力する", "HTTPS")
Rel(web, api, "呼び出す", "REST（JSON）/ HTTPS")
Rel(api, db, "読み書きする", "JDBC")
Rel(api, pay, "決済・返金を依頼する。記録を取得する", "HTTPS")
Rel(api, mail, "メールの送信を依頼する", "SMTP")
Rel(operator, pay, "管理画面で返金する", "HTTPS")
Rel(mail, customer, "確認・取消のメールを送る")
Rel(mail, operator, "通知のメールを送る")
@enduml
```

| 構成要素 | 責務 | 技術 |
| --- | --- | --- |
| Webアプリ | 画面を提供する。[[利用者]]の操作を、APIへの呼び出しに変える | TypeScript / React |
| API | 注文・在庫のビジネスロジックを提供する。定期的な処理（未確定の注文の回収、夜間の[[照合]]）も、ここで動く | Java 21 / Spring Boot |
| データベース | 注文・在庫・利用者を保存する（8.5） | PostgreSQL（マネージドサービス） |

Webアプリは、`/api`以下のREST（JSON・HTTPS）で、APIを呼ぶ（C4）。APIだけが、データベースにつながる。

<!-- pagebreak -->

## 5.2 レベル2: API

```plantuml
@startuml
!include <C4/C4_Component>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Container(web, $web_name, $web_tech, "")
ContainerDb(db, $db_name, $db_tech, "")
System_Ext(pay, $pay_name, "")
System_Ext(mail, $mail_name, "")

Container_Boundary(api, $api_name) {
    Component(orderCtl, $orderCtl_name, $orderCtl_tech, $orderCtl_desc)
    Component(adminCtl, $adminCtl_name, $adminCtl_tech, $adminCtl_desc)
    Component(orderSvc, $orderSvc_name, $orderSvc_tech, $orderSvc_desc)
    Component(stockClient, $stockClient_name, $stockClient_tech, $stockClient_desc)
    Component(payClient, $payClient_name, $payClient_tech, $payClient_desc)
    Component(mailClient, $mailClient_name, $mailClient_tech, $mailClient_desc)
    Component(collector, $collector_name, $collector_tech, $collector_desc)
    Component(recon, $recon_name, $recon_tech, $recon_desc)
}

Rel(web, orderCtl, "POST・DELETE /orders", "REST")
Rel(web, adminCtl, "PUT /stock、GET /shipments.csv", "REST")
Rel(orderCtl, orderSvc, "confirm・cancel")
Rel(adminCtl, stockClient, "在庫の更新")
Rel(adminCtl, db, "出荷前の注文の取得", "JDBC")
Rel(orderSvc, stockClient, "reserve・release")
Rel(orderSvc, payClient, "charge・refund")
Rel(orderSvc, mailClient, "send")
Rel(collector, orderSvc, "cancel")
Rel(recon, payClient, "listPayments")
Rel(recon, db, "取消した注文の取得", "JDBC")
Rel(recon, mailClient, "send")
Rel(collector, db, "未確定の注文の取得", "JDBC")
Rel(stockClient, db, "読み書きする", "JDBC")
Rel(orderSvc, db, "注文の保存", "JDBC")
Rel(payClient, pay, "決済・返金・記録の取得", "HTTPS")
Rel(mailClient, mail, "メールの送信", "SMTP")
@enduml
```

<!-- pagebreak -->

**レベル2の構成要素の一覧**

| 構成要素 | 責務 |
| --- | --- |
| 注文コントローラ | 利用者の注文リクエストを受け付け、入力を検証する |
| 在庫・出荷コントローラ | [[運用担当]]の、在庫の更新と、[[出荷指示]]の出力を受け付ける |
| 注文サービス | 注文の確定と取消を行う。在庫・決済・メールの呼び出しを、順序立てる |
| 在庫クライアント | 在庫を引き当て、戻し、更新する |
| 決済クライアント | [[決済代行サービス]]へ、決済・返金・記録の取得を依頼する |
| メール通知クライアント | メール配信サービスへ、送信を依頼する。失敗したときは、再試行する |
| 未確定の注文の回収 | 止まった注文（`PENDING`のまま30分超）を取り消す |
| 夜間の照合 | 決済代行サービスの記録と、取り消された注文を照合する |

依存の向きは、コントローラとジョブ → サービス → クライアント、の一方向である。この向きは、テストで検査する（ADR-1）。

<!-- pagebreak -->

## 5.3 注文コントローラ

**責務**: 利用者の注文リクエストを受け付け、入力を検証して、注文サービスへ渡す。業務の判断は、行わない。

**インターフェース**

| インターフェース | 入力 | 出力 | 失敗したとき |
| --- | --- | --- | --- |
| `POST /orders` | 商品ID・数量の一覧（1〜20行）、[[決済トークン]]、配送先 | `201 Created`と、注文ID | 入力の不備は`400`。在庫不足は`409`。決済の失敗は`402`。決済の[[打切り]]は`504` |
| `DELETE /orders/{id}` | 注文ID | `204 No Content` | 自分の注文でなければ`404`。出荷済みは`409`。返金の失敗は`502` |

**内部の決まり**
- 数量は、1行につき1〜99。範囲外は、`400`とする。
- 同じ決済トークンでの重複した`POST /orders`は、2回目以降を`409`とする（二重送信を防ぐ）。
- 認証は、8.1の方式に従う。注文は、認証済みの利用者の、自分の注文だけを操作できる。

**関連**: Q4（入力の検証）、C4（RESTの規約）

<!-- pagebreak -->

## 5.4 在庫・出荷コントローラ

**責務**: 運用担当の、在庫の更新と、出荷指示の出力を、受け付ける。ロールが`OPERATOR`でなければ、拒否する。

**インターフェース**

| インターフェース | 入力 | 出力 | 失敗したとき |
| --- | --- | --- | --- |
| `PUT /stock/{itemId}` | 在庫の数（0以上の整数） | `204 No Content` | 数が負なら`400`。商品がなければ`404`。ロールが違えば`403` |
| `GET /shipments.csv` | なし | CSV（UTF-8）。列は、注文ID・配送先・商品ID・数量 | ロールが違えば`403` |

**内部の決まり**
- 出力の対象は、`CONFIRMED`で、出荷前の注文だけである。
- 出力した注文は、出荷指示済みの印を付ける。同じ注文を、2回、出力しない。

**関連**: Q4（ロールによる制限）、F4・F5

<!-- pagebreak -->

## 5.5 注文サービス

**責務**: 注文の確定と取消を行う。[[在庫の引き当て]]、決済の順に呼び、決済が失敗したときは、在庫を戻して、注文を取り消す。確定と取消のときは、メールの送信を、依頼する。

**インターフェース**

| インターフェース | 入力 | 出力 | 失敗したとき |
| --- | --- | --- | --- |
| `confirm(order)` | 注文（商品・数量・決済トークン） | 確定した注文ID | 在庫不足は`OutOfStock`、決済の失敗は`PaymentFailed`、打切りは`PaymentTimeout`。いずれも、在庫を戻して終了する |
| `cancel(orderId)` | 注文ID | なし | 確定前は`NotConfirmed`、出荷済みは`AlreadyShipped`、返金の失敗は`RefundFailed`。取消済みなら、何もしない（何度呼んでも、同じ結果になる） |

**内部の決まり**
- 注文の状態は、`PENDING`（受付）→`CONFIRMED`（確定）または`CANCELLED`（取消）の3つ。
- 在庫の引き当てと、`PENDING`の注文の保存は、同じトランザクションで行う。決済は、そのトランザクションの外で呼ぶ（長く待つ呼び出しの間、ロックを保持しないため。ADR-3）。
- 決済が成功したら、注文を`CONFIRMED`にする。失敗か、打切りなら、在庫を戻し、`CANCELLED`にする。
- `PENDING`の注文を取り消すとき（回収）は、決済が行われていないので、返金は呼ばない。`CONFIRMED`の注文を取り消すときは、返金を呼ぶ。

**関連**: Q1・Q2、S1・S2、ADR-1・ADR-2・ADR-3

<!-- pagebreak -->

## 5.6 在庫クライアント

**責務**: 在庫の引き当てと、戻しと、更新を行う。在庫は、データベースの`stock`表にある。

**インターフェース**

| インターフェース | 入力 | 出力 | 失敗したとき |
| --- | --- | --- | --- |
| `reserve(items)` | 商品IDと数量の一覧 | 引き当て済みの一覧 | 1つでも在庫が足りなければ、全体を失敗にして、`OutOfStock`を返す（途中まで引き当てた分は、トランザクションごと戻る） |
| `release(items)` | 商品IDと数量の一覧 | なし | 商品がなければ、無視して、警告をログに残す |
| `set(itemId, qty)` | 商品ID、在庫の数 | なし | 商品がなければ`NotFound`。数が負なら`InvalidQuantity` |

**内部の決まり**
- 引き当ては、商品ごとに、`UPDATE stock SET qty = qty - :n WHERE item_id = :id AND qty >= :n`を1回実行し、更新された行が0なら、不足とする（ADR-3）。
- 複数の商品を含むときは、商品IDの昇順で更新する（デッドロックを避ける）。
- [[在庫の戻し]]は、[[冪等]]にはしない。呼び出し側（注文サービス）が、1つの注文につき、1回だけ呼ぶ。

**関連**: Q1、S1、ADR-3

<!-- pagebreak -->

## 5.7 決済クライアント

**責務**: 決済代行サービスへ、決済・返金・記録の取得を依頼する。カード番号は扱わない。決済手段ごとの違いは、このコンポーネントの中に閉じる。

**インターフェース**

| インターフェース | 入力 | 出力 | 失敗したとき |
| --- | --- | --- | --- |
| `PaymentGateway.charge(token, amount)` | 決済用のトークン、金額（円） | [[決済ID]] | 決済の拒否は`PaymentFailed`。3秒を超えたときは`PaymentTimeout` |
| `PaymentGateway.refund(paymentId)` | 決済ID | なし | 返金の失敗は`RefundFailed`。取消済みなら、何もしない |
| `PaymentGateway.listPayments(date)` | 日付 | その日の決済の一覧（決済ID・金額・状態） | 取得の失敗は`ReconciliationUnavailable`（呼び出し側が、運用担当に通知する） |

**内部の決まり**
- 決済代行サービスへの呼び出しは、HTTPSで、3秒で打ち切る。再試行はしない（ADR-2）。ただし、`listPayments`は、夜間の処理のため、30秒で打ち切り、3回まで再試行する。
- トークンと金額以外の、利用者の情報（氏名・住所）は、決済代行サービスに、送らない。
- 決済代行サービスの実装は、`PaymentGateway`を実装する1つのクラスである。決済手段を追加するときは、実装を1つ追加する（ADR-5）。

**関連**: Q3・Q4、S3・S4、TC2、OC5、ADR-2・ADR-4・ADR-5

<!-- pagebreak -->

## 5.8 メール通知クライアント

**責務**: メール配信サービスへ、メールの送信を依頼する。注文の確定や取消の応答を、待たせない。

**インターフェース**

| インターフェース | 入力 | 出力 | 失敗したとき |
| --- | --- | --- | --- |
| `send(notification)` | 宛先、件名、本文のテンプレートIDと値 | なし（非同期。受け付けただけで返す） | キューに入れられなければ、警告をログに残す（注文には影響させない） |

**内部の決まり**
- 送信の依頼は、いったんデータベースのキューに入れ、別のスレッドで送る。注文の確定の応答は、送信を待たない（8.3）。
- 送信は、5秒で打ち切る。5分間隔で、最大3回、再試行する。3回失敗したら、運用担当への通知に回す。
- 件名と本文に、カード情報は、含めない。

**関連**: Q1・Q2、8.3

<!-- pagebreak -->

## 5.9 未確定の注文の回収

**責務**: 障害などで、処理が途中で止まった注文（`PENDING`のまま）を、取り消して、在庫を戻す。

**インターフェース**: 外部へは公開しない。起動時と、5分ごとに、動く。

**内部の決まり**
- 対象は、`PENDING`のまま、30分を過ぎた注文。30分は、APIの再起動と、決済の最大待ち時間（3秒）に、十分な余裕を持たせた値である。
- 1件ずつ、注文サービスの`cancel`を呼ぶ。1件の失敗で、残りを止めない。失敗は、ログに残し、次の回に再試行する。
- APIは、2台以上で動くため（ADR-6）、同じ注文を、2台が同時に取り消さないよう、データベースの行を、先に取った側だけが処理する。

**関連**: Q2、S2、6.3

<!-- pagebreak -->

## 5.10 夜間の照合

**責務**: 打ち切りなどで取り消された注文と、決済代行サービスの記録を、突き合わせる。食い違いを、運用担当に、通知する。

**インターフェース**: 外部へは公開しない。毎日、午前3時に、動く。

**内部の決まり**
- 前日に`CANCELLED`になった注文と、`listPayments`で取得した前日の決済を、決済IDで突き合わせる。
- 食い違い（注文は取り消されているが、決済は成功している）を、一覧にして、メール通知クライアントで、運用担当に、送る。0件のときは、送らない。
- 照合の取得に失敗したときは、その旨を、運用担当に通知する。翌日の処理で、2日分を、取得する。

**関連**: Q2、ADR-2、6.5
