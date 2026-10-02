# Bytefieldのギャラリー

`bytefield`が対応する図の種類の実例です（[#291の対応表](08_diagrams.md#記法で描ける図の種類対応表)）。記法の説明は「図表」の章の「Bytefieldについて」を参照してください。記述は、Clojureの式で書きます。

## パケット構造図（TCPヘッダ）

32ビット幅の行を重ねます。`draw-column-headers`が列の番号、`draw-gap`が可変長の部分、`draw-bottom`が下の線です。

```bytefield
(def boxes-per-row 32)
(def column-labels (mapv str (range 32)))
(defattrs :bg-yellow {:fill "#ffffa0"})
(draw-column-headers)
(draw-box "Source Port" {:span 16})
(draw-box "Destination Port" {:span 16})
(draw-box "Sequence Number" {:span 32})
(draw-box "Acknowledgment Number" {:span 32})
(draw-box "Offset" {:span 4})
(draw-box "Reserved" {:span 6})
(draw-box "U" [{:span 1} :bg-yellow])
(draw-box "A" [{:span 1} :bg-yellow])
(draw-box "P" [{:span 1} :bg-yellow])
(draw-box "R" [{:span 1} :bg-yellow])
(draw-box "S" [{:span 1} :bg-yellow])
(draw-box "F" [{:span 1} :bg-yellow])
(draw-box "Window" {:span 16})
(draw-box "Checksum" {:span 16})
(draw-box "Urgent Pointer" {:span 16})
(draw-box "Options" {:span 24})
(draw-box "Padding" {:span 8})
(draw-gap "Data")
(draw-bottom)
```

## パケット構造図（バイト単位の小さなヘッダ）

幅を8ビットにして、1バイトずつのフィールドを並べます。

```bytefield
(def boxes-per-row 8)
(draw-box "Type" {:span 4})
(draw-box "Flags" {:span 4})
(draw-box "Length" {:span 8})
(draw-box "Payload" {:span 8})
```
