# 配置（Deployment）

本番環境で、各コンテナが、どこで動くかを示します。

```structurizr
workspace {
    model {
        !include model.dsl
    }
    views {
        deployment ec "本番" "Deployment" {
            include *
            autoLayout lr
        }
        styles {
            !include styles.dsl
        }
    }
}
```
