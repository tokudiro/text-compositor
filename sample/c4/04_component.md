# コンポーネント（Component）

APIの中の、部品と、その関係を示します。

```structurizr
workspace {
    model {
        !include model.dsl
    }
    views {
        component api "Component" {
            include *
            autoLayout lr
        }
        styles {
            !include styles.dsl
        }
    }
}
```
