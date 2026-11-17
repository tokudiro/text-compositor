# 注文の流れ（Dynamic）

顧客が注文したときの、実行時のやり取りを、順番に示します。

```structurizr
workspace {
    model {
        !include model.dsl
    }
    views {
        dynamic ec "Dynamic" {
            customer -> web "注文を確定する"
            web -> api "注文を依頼する"
            api -> pay "決済を依頼する"
            api -> db "注文を保存する"
            api -> mail "確認メールを依頼する"
            autoLayout lr
        }
        styles {
            !include styles.dsl
        }
    }
}
```
