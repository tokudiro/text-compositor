# ECサイトのC4モデル。すべてのビューが、このファイルを共有する。
# 要素・関係を直すと、System Context・Container・Component・Dynamic・Deploymentの図が、すべて追従する。
customer = person "顧客" "商品を探して、注文する"
admin = person "運用担当" "在庫と注文を管理する"

ec = softwareSystem "ECサイト" "商品の閲覧と注文を受け付ける" {
    web = container "Webアプリ" "画面を提供する" "TypeScript / React"
    api = container "API" "注文・在庫のビジネスロジックを提供する" "Java / Spring Boot" {
        orderCtl = component "注文コントローラ" "注文リクエストを受け付ける" "Spring MVC"
        orderSvc = component "注文サービス" "注文の確定と取消を行う" "Spring Bean"
        stockClient = component "在庫クライアント" "在庫を引き当てる" "Spring Bean"
        payClient = component "決済クライアント" "決済を依頼する" "Spring Bean"
    }
    db = container "データベース" "注文と在庫を保存する" "PostgreSQL" "Database"
}
pay = softwareSystem "決済代行サービス" "カード決済を処理する" "External"
mail = softwareSystem "メール配信サービス" "注文確認メールを送る" "External"

customer -> web "商品を探して、注文する" "HTTPS"
admin -> web "在庫を更新する" "HTTPS"
web -> api "呼び出す" "JSON / HTTPS"
api -> db "読み書きする" "JDBC"
api -> pay "決済を依頼する" "HTTPS"
api -> mail "確認メールを依頼する" "SMTP"
orderCtl -> orderSvc "委譲する"
orderSvc -> stockClient "在庫を引き当てる"
orderSvc -> payClient "決済する"
stockClient -> db "読み書きする" "JDBC"
payClient -> pay "決済を依頼する" "HTTPS"

production = deploymentEnvironment "本番" {
    deploymentNode "CDN" "" "静的配信" {
        webInstance = containerInstance web
    }
    deploymentNode "アプリケーションサーバー" "" "Linux / Docker" {
        apiInstance = containerInstance api
    }
    deploymentNode "データベースサーバー" "" "マネージドRDB" {
        dbInstance = containerInstance db
    }
}
