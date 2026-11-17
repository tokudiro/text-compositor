# システムの全体像（System Context）

システムと、その利用者・連携先の関係を示します。内部の作りは見せません。

```structurizr
workspace {
    model {
        !include model.dsl
    }
    views {
        systemContext ec "Context" {
            include *
            autoLayout lr
        }
        styles {
            !include styles.dsl
        }
    }
}
```
