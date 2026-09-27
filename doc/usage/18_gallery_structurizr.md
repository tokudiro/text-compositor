# Structurizrのギャラリー

`structurizr`が対応する図の種類の実例です（[#291の対応表](08_diagrams.md#記法で描ける図の種類対応表)）。記法の説明は「図表」の章の「Structurizr固有の注意点」を参照してください。1フェンス＝1ビューの制約があるため、種類ごとにフェンスを分けています。DSLの識別子（`=`の左側）は英数字・`_`・`-`のみのため、識別子は英語、表示名（`"..."`の中）は日本語にしています。

## System Context図

```structurizr
workspace {
    model {
        user = person "利用者"
        ecSite = softwareSystem "ECサイト"
        payment = softwareSystem "決済代行サービス"
        user -> ecSite "注文する"
        ecSite -> payment "決済を依頼する"
    }
    views {
        systemContext ecSite "SystemContext" {
            include *
            autoLayout
        }
    }
}
```

## コンテナ図

```structurizr
workspace {
    model {
        user = person "利用者"
        ecSite = softwareSystem "ECサイト" {
            webApp = container "Webアプリ"
            api = container "API"
            db = container "データベース"
            webApp -> api "呼び出す"
            api -> db "読み書きする"
        }
        user -> webApp "利用する"
    }
    views {
        container ecSite "Containers" {
            include *
            autoLayout
        }
    }
}
```

## コンポーネント図

```structurizr
workspace {
    model {
        ecSite = softwareSystem "ECサイト" {
            api = container "API" {
                orderController = component "注文コントローラー"
                orderService = component "注文サービス"
                orderRepository = component "注文リポジトリ"
                orderController -> orderService "呼び出す"
                orderService -> orderRepository "呼び出す"
            }
        }
    }
    views {
        component api "Components" {
            include *
            autoLayout
        }
    }
}
```

## コンポーネント図／配置図

```structurizr
workspace {
    model {
        ecSite = softwareSystem "ECサイト" {
            api = container "API" {
                paymentComponent = component "決済連携コンポーネント"
            }
        }
        payment = softwareSystem "決済代行サービス"
        paymentComponent -> payment "決済APIを呼び出す"
    }
    views {
        component api "ComponentAndDeployment" {
            include *
            autoLayout
        }
    }
}
```

## システムランドスケープ図

```structurizr
workspace {
    model {
        user = person "利用者"
        ecSite = softwareSystem "ECサイト"
        inventory = softwareSystem "在庫管理システム"
        payment = softwareSystem "決済代行サービス"
        user -> ecSite "注文する"
        ecSite -> inventory "在庫を照会する"
        ecSite -> payment "決済する"
    }
    views {
        systemLandscape "Landscape" {
            include *
            autoLayout
        }
    }
}
```

## デプロイメント図

```structurizr
workspace {
    model {
        ecSite = softwareSystem "ECサイト" {
            webApp = container "Webアプリ"
            db = container "データベース"
        }
        prod = deploymentEnvironment "本番" {
            deploymentNode "Webサーバー" {
                containerInstance webApp
            }
            deploymentNode "DBサーバー" {
                containerInstance db
            }
        }
    }
    views {
        deployment ecSite "本番" "Deployment" {
            include *
            autoLayout
        }
    }
}
```

## コミュニケーション図

```structurizr
workspace {
    model {
        user = person "利用者"
        ecSite = softwareSystem "ECサイト" {
            webApp = container "Webアプリ"
            api = container "API"
            db = container "データベース"
        }
        user -> webApp "注文操作"
        webApp -> api "注文リクエスト"
        api -> db "注文を保存"
    }
    views {
        dynamic ecSite "Dynamic" {
            user -> webApp "注文操作"
            webApp -> api "注文リクエスト"
            api -> db "注文を保存"
            autoLayout
        }
    }
}
```
