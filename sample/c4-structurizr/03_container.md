# コンテナ（Container）

ECサイトの中の、動くもの（アプリケーション・データベース）と、その間のやり取りを示します。

```structurizr
workspace {
    model {
        !include model.dsl
    }
    views {
        container ec "Container" {
            include *
            autoLayout lr
        }
        styles {
            !include styles.dsl
        }
    }
}
```
