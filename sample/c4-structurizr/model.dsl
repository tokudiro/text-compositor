# ECサイトのC4モデル。すべてのビューが、このファイルを共有する。
# 要素・関係を直すと、System Context・Container・Component・Dynamic・Deploymentの図が、すべて追従する。
customer = person "利用者" "商品を探して、注文する"
operator = person "運用担当" "商品と在庫を管理し、出荷を指示する"

ec = softwareSystem "ECサイト" "商品の閲覧、注文、在庫の管理、出荷指示の出力を行う" {
    web = container "Webアプリ" "画面を提供する" "TypeScript / React"
    api = container "API" "注文・在庫のビジネスロジックを提供する" "Java 21 / Spring Boot" {
        orderCtl = component "注文コントローラ" "注文リクエストを受け付ける" "Spring MVC"
        adminCtl = component "在庫・出荷コントローラ" "運用担当の操作を受け付ける" "Spring MVC"
        orderSvc = component "注文サービス" "注文の確定と取消を行う" "Spring Bean"
        stockClient = component "在庫クライアント" "在庫を引き当て、戻す" "Spring Bean"
        payClient = component "決済クライアント" "決済を依頼する" "Spring Bean"
        mailClient = component "メール通知クライアント" "メールの送信を依頼する" "Spring Bean"
        collector = component "未確定の注文の回収" "止まった注文を取り消す" "Spring Scheduled"
        recon = component "夜間の照合" "決済の記録と照合する" "Spring Scheduled"
    }
    db = container "データベース" "注文と在庫を保存する" "PostgreSQL（マネージドサービス）" "Database"
}
pay = softwareSystem "決済代行サービス" "カード決済を処理する。カード情報を受け取る" "External"
mail = softwareSystem "メール配信サービス" "利用者と運用担当に、メールを送る" "External"
logistics = softwareSystem "物流倉庫" "商品を保管し、出荷する" "External"

# 人・外部システムとの関係
customer -> web "商品を探して、注文する" "HTTPS"
operator -> web "在庫を更新し、出荷指示を出力する" "HTTPS"
operator -> logistics "出荷指示のCSVを渡す"
operator -> pay "管理画面で返金する" "HTTPS"
mail -> customer "確認・取消のメールを送る"
mail -> operator "通知のメールを送る"

# コンテナ間の関係
web -> api "呼び出す" "REST（JSON）/ HTTPS"
api -> db "読み書きする" "JDBC"
api -> pay "決済・返金を依頼する。記録を取得する" "HTTPS"
api -> mail "メールの送信を依頼する" "SMTP"

# コンポーネント間の関係
web -> orderCtl "POST・DELETE /orders" "REST"
web -> adminCtl "PUT /stock、GET /shipments.csv" "REST"
orderCtl -> orderSvc "confirm・cancel"
adminCtl -> stockClient "在庫の更新"
adminCtl -> db "出荷前の注文の取得" "JDBC"
orderSvc -> stockClient "reserve・release"
orderSvc -> payClient "charge・refund"
orderSvc -> mailClient "send"
orderSvc -> db "注文の保存" "JDBC"
collector -> orderSvc "cancel"
collector -> db "未確定の注文の取得" "JDBC"
recon -> payClient "listPayments"
recon -> db "取消した注文の取得" "JDBC"
recon -> mailClient "send"
stockClient -> db "読み書きする" "JDBC"
payClient -> pay "決済・返金・記録の取得" "HTTPS"
mailClient -> mail "メールの送信" "SMTP"

production = deploymentEnvironment "本番" {
    deploymentNode "利用者・運用担当のブラウザ" "" "Chrome / Safari / Edge" {
        webInstance = containerInstance web
    }
    deploymentNode "CDN" "" "クラウドの配信サービス" {
        staticFiles = infrastructureNode "静的ファイルの置き場" "Webアプリのファイル（HTML / JS / CSS）を置く" "オブジェクトストレージ"
    }
    deploymentNode "クラウド" "" "東京リージョン" {
        lb = infrastructureNode "ロードバランサ" "負荷分散とヘルスチェック" "マネージドサービス（HTTPS、TLS終端）"
        deploymentNode "コンテナ実行サービス" "" "マネージドサービス。平常時2台、最大6台" {
            deploymentNode "コンテナ（API）" "" "1 vCPU / 2 GB" "" 2 {
                apiInstance = containerInstance api
            }
        }
        deploymentNode "データベース" "" "マネージドのPostgreSQL。2つのゾーンに冗長化" {
            dbInstance = containerInstance db
        }
    }
    staticFiles -> webInstance "配信する" "HTTPS"
    webInstance -> lb "API呼び出し" "REST / HTTPS"
    lb -> apiInstance "振り分ける" "HTTP"
}
