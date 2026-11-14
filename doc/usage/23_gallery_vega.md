# Vega-Lite・Vegaのギャラリー

`vega-lite`・`vega`が対応する図の種類の実例です（[#291の対応表](29_diagram_matrix.md#記法で描ける図の種類対応表)）。記法の説明は「図表」の章の「Vega-Lite / Vegaについて」を参照してください。第一選択は`vega-lite`です。`vega`は、Vega-Liteで表現できない図（力学レイアウト・ツリーマップなど）を、最後のほうに載せています。

## 棒グラフ

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"月": "1月", "売上": 120}, {"月": "2月", "売上": 135}, {"月": "3月", "売上": 150},
    {"月": "4月", "売上": 142}, {"月": "5月", "売上": 170}, {"月": "6月", "売上": 188}
  ]},
  "mark": "bar",
  "encoding": {
    "x": {"field": "月", "type": "ordinal", "sort": null},
    "y": {"field": "売上", "type": "quantitative"}
  },
  "width": 300,
  "height": 160
}
````

```vega-lite
{
  "data": {"values": [
    {"月": "1月", "売上": 120}, {"月": "2月", "売上": 135}, {"月": "3月", "売上": 150},
    {"月": "4月", "売上": 142}, {"月": "5月", "売上": 170}, {"月": "6月", "売上": 188}
  ]},
  "mark": "bar",
  "encoding": {
    "x": {"field": "月", "type": "ordinal", "sort": null},
    "y": {"field": "売上", "type": "quantitative"}
  },
  "width": 300,
  "height": 160
}
```
:::

## 積み上げ棒グラフ

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"月": "1月", "地域": "東", "売上": 120}, {"月": "1月", "地域": "西", "売上": 80},
    {"月": "2月", "地域": "東", "売上": 135}, {"月": "2月", "地域": "西", "売上": 95},
    {"月": "3月", "地域": "東", "売上": 150}, {"月": "3月", "地域": "西", "売上": 110}
  ]},
  "mark": "bar",
  "encoding": {
    "x": {"field": "月", "type": "ordinal", "sort": null},
    "y": {"field": "売上", "type": "quantitative", "scale": {"domain": [0, 300]}},
    "color": {"field": "地域", "type": "nominal"}
  },
  "width": 300,
  "height": 160
}
````

```vega-lite
{
  "data": {"values": [
    {"月": "1月", "地域": "東", "売上": 120}, {"月": "1月", "地域": "西", "売上": 80},
    {"月": "2月", "地域": "東", "売上": 135}, {"月": "2月", "地域": "西", "売上": 95},
    {"月": "3月", "地域": "東", "売上": 150}, {"月": "3月", "地域": "西", "売上": 110}
  ]},
  "mark": "bar",
  "encoding": {
    "x": {"field": "月", "type": "ordinal", "sort": null},
    "y": {"field": "売上", "type": "quantitative", "scale": {"domain": [0, 300]}},
    "color": {"field": "地域", "type": "nominal"}
  },
  "width": 300,
  "height": 160
}
```
:::

## 折れ線グラフ

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"月": 1, "地域": "東", "売上": 120}, {"月": 2, "地域": "東", "売上": 135}, {"月": 3, "地域": "東", "売上": 150},
    {"月": 4, "地域": "東", "売上": 142}, {"月": 5, "地域": "東", "売上": 170}, {"月": 6, "地域": "東", "売上": 188},
    {"月": 1, "地域": "西", "売上": 80}, {"月": 2, "地域": "西", "売上": 95}, {"月": 3, "地域": "西", "売上": 110},
    {"月": 4, "地域": "西", "売上": 132}, {"月": 5, "地域": "西", "売上": 141}, {"月": 6, "地域": "西", "売上": 165}
  ]},
  "mark": {"type": "line", "point": true},
  "encoding": {
    "x": {"field": "月", "type": "quantitative", "axis": {"tickMinStep": 1}},
    "y": {"field": "売上", "type": "quantitative"},
    "color": {"field": "地域", "type": "nominal"}
  },
  "width": 300,
  "height": 160
}
````

```vega-lite
{
  "data": {"values": [
    {"月": 1, "地域": "東", "売上": 120}, {"月": 2, "地域": "東", "売上": 135}, {"月": 3, "地域": "東", "売上": 150},
    {"月": 4, "地域": "東", "売上": 142}, {"月": 5, "地域": "東", "売上": 170}, {"月": 6, "地域": "東", "売上": 188},
    {"月": 1, "地域": "西", "売上": 80}, {"月": 2, "地域": "西", "売上": 95}, {"月": 3, "地域": "西", "売上": 110},
    {"月": 4, "地域": "西", "売上": 132}, {"月": 5, "地域": "西", "売上": 141}, {"月": 6, "地域": "西", "売上": 165}
  ]},
  "mark": {"type": "line", "point": true},
  "encoding": {
    "x": {"field": "月", "type": "quantitative", "axis": {"tickMinStep": 1}},
    "y": {"field": "売上", "type": "quantitative"},
    "color": {"field": "地域", "type": "nominal"}
  },
  "width": 300,
  "height": 160
}
```
:::

## 面グラフ

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"月": 1, "売上": 200}, {"月": 2, "売上": 230}, {"月": 3, "売上": 260},
    {"月": 4, "売上": 274}, {"月": 5, "売上": 311}, {"月": 6, "売上": 353}
  ]},
  "mark": {"type": "area", "line": true, "opacity": 0.4},
  "encoding": {
    "x": {"field": "月", "type": "quantitative", "axis": {"tickMinStep": 1}},
    "y": {"field": "売上", "type": "quantitative"}
  },
  "width": 300,
  "height": 160
}
````

```vega-lite
{
  "data": {"values": [
    {"月": 1, "売上": 200}, {"月": 2, "売上": 230}, {"月": 3, "売上": 260},
    {"月": 4, "売上": 274}, {"月": 5, "売上": 311}, {"月": 6, "売上": 353}
  ]},
  "mark": {"type": "area", "line": true, "opacity": 0.4},
  "encoding": {
    "x": {"field": "月", "type": "quantitative", "axis": {"tickMinStep": 1}},
    "y": {"field": "売上", "type": "quantitative"}
  },
  "width": 300,
  "height": 160
}
```
:::

## 円グラフ

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"種類": "Aプラン", "件数": 45}, {"種類": "Bプラン", "件数": 30}, {"種類": "Cプラン", "件数": 25}
  ]},
  "mark": "arc",
  "encoding": {
    "theta": {"field": "件数", "type": "quantitative"},
    "color": {"field": "種類", "type": "nominal"}
  },
  "width": 200,
  "height": 200
}
````

```vega-lite
{
  "data": {"values": [
    {"種類": "Aプラン", "件数": 45}, {"種類": "Bプラン", "件数": 30}, {"種類": "Cプラン", "件数": 25}
  ]},
  "mark": "arc",
  "encoding": {
    "theta": {"field": "件数", "type": "quantitative"},
    "color": {"field": "種類", "type": "nominal"}
  },
  "width": 200,
  "height": 200
}
```
:::

## 散布図

QC7つ道具の散布図としても使えます。2つの量の関係を見ます。`color`で、グループごとに色分け（層別）できます。

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"身長": 152, "体重": 48, "区分": "A"}, {"身長": 158, "体重": 52, "区分": "A"}, {"身長": 163, "体重": 58, "区分": "A"},
    {"身長": 168, "体重": 61, "区分": "B"}, {"身長": 172, "体重": 66, "区分": "B"}, {"身長": 175, "体重": 70, "区分": "B"},
    {"身長": 181, "体重": 78, "区分": "B"}, {"身長": 160, "体重": 55, "区分": "A"}, {"身長": 178, "体重": 74, "区分": "B"}
  ]},
  "mark": {"type": "point", "filled": true, "size": 80},
  "encoding": {
    "x": {"field": "身長", "type": "quantitative", "scale": {"zero": false, "padding": 10}},
    "y": {"field": "体重", "type": "quantitative", "scale": {"zero": false, "padding": 10}},
    "color": {"field": "区分", "type": "nominal"}
  },
  "width": 300,
  "height": 200
}
````

```vega-lite
{
  "data": {"values": [
    {"身長": 152, "体重": 48, "区分": "A"}, {"身長": 158, "体重": 52, "区分": "A"}, {"身長": 163, "体重": 58, "区分": "A"},
    {"身長": 168, "体重": 61, "区分": "B"}, {"身長": 172, "体重": 66, "区分": "B"}, {"身長": 175, "体重": 70, "区分": "B"},
    {"身長": 181, "体重": 78, "区分": "B"}, {"身長": 160, "体重": 55, "区分": "A"}, {"身長": 178, "体重": 74, "区分": "B"}
  ]},
  "mark": {"type": "point", "filled": true, "size": 80},
  "encoding": {
    "x": {"field": "身長", "type": "quantitative", "scale": {"zero": false, "padding": 10}},
    "y": {"field": "体重", "type": "quantitative", "scale": {"zero": false, "padding": 10}},
    "color": {"field": "区分", "type": "nominal"}
  },
  "width": 300,
  "height": 200
}
```
:::

## ヒストグラム

QC7つ道具のヒストグラム（度数分布図）です。`bin`で、値を区間に分けて、件数を数えます。

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"点数": 42}, {"点数": 55}, {"点数": 58}, {"点数": 61}, {"点数": 63}, {"点数": 64}, {"点数": 66},
    {"点数": 67}, {"点数": 68}, {"点数": 70}, {"点数": 71}, {"点数": 72}, {"点数": 73}, {"点数": 74},
    {"点数": 75}, {"点数": 77}, {"点数": 78}, {"点数": 81}, {"点数": 83}, {"点数": 86}, {"点数": 90}, {"点数": 95}
  ]},
  "mark": "bar",
  "encoding": {
    "x": {"field": "点数", "bin": {"step": 10}, "type": "quantitative"},
    "y": {"aggregate": "count", "type": "quantitative", "title": "人数"}
  },
  "width": 300,
  "height": 160
}
````

```vega-lite
{
  "data": {"values": [
    {"点数": 42}, {"点数": 55}, {"点数": 58}, {"点数": 61}, {"点数": 63}, {"点数": 64}, {"点数": 66},
    {"点数": 67}, {"点数": 68}, {"点数": 70}, {"点数": 71}, {"点数": 72}, {"点数": 73}, {"点数": 74},
    {"点数": 75}, {"点数": 77}, {"点数": 78}, {"点数": 81}, {"点数": 83}, {"点数": 86}, {"点数": 90}, {"点数": 95}
  ]},
  "mark": "bar",
  "encoding": {
    "x": {"field": "点数", "bin": {"step": 10}, "type": "quantitative"},
    "y": {"aggregate": "count", "type": "quantitative", "title": "人数"}
  },
  "width": 300,
  "height": 160
}
```
:::

## パレート図

QC7つ道具のパレート図です。件数の多い順に並べた棒グラフに、累積比率の折れ線を重ねます。`window`で累積の合計を、`joinaggregate`で全体の合計を求め、`resolve`で、左右の軸を別々にします。棒は、データに書いた順に並びます（`"sort": null`）ので、件数の多い順に書いてください。

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"種類": "傷", "件数": 42}, {"種類": "汚れ", "件数": 27}, {"種類": "寸法不良", "件数": 15},
    {"種類": "変形", "件数": 9}, {"種類": "その他", "件数": 7}
  ]},
  "transform": [
    {"window": [{"op": "sum", "field": "件数", "as": "累積"}], "frame": [null, 0]},
    {"joinaggregate": [{"op": "sum", "field": "件数", "as": "合計"}]},
    {"calculate": "datum.累積 / datum.合計", "as": "累積比率"}
  ],
  "encoding": {"x": {"field": "種類", "type": "nominal", "sort": null}},
  "layer": [
    {"mark": "bar", "encoding": {"y": {"field": "件数", "type": "quantitative"}}},
    {"mark": {"type": "line", "point": true, "color": "#c00"},
     "encoding": {"y": {"field": "累積比率", "type": "quantitative",
                        "axis": {"format": "%"}, "scale": {"domain": [0, 1]}}}}
  ],
  "resolve": {"scale": {"y": "independent"}},
  "width": 240,
  "height": 160
}
````

```vega-lite
{
  "data": {"values": [
    {"種類": "傷", "件数": 42}, {"種類": "汚れ", "件数": 27}, {"種類": "寸法不良", "件数": 15},
    {"種類": "変形", "件数": 9}, {"種類": "その他", "件数": 7}
  ]},
  "transform": [
    {"window": [{"op": "sum", "field": "件数", "as": "累積"}], "frame": [null, 0]},
    {"joinaggregate": [{"op": "sum", "field": "件数", "as": "合計"}]},
    {"calculate": "datum.累積 / datum.合計", "as": "累積比率"}
  ],
  "encoding": {"x": {"field": "種類", "type": "nominal", "sort": null}},
  "layer": [
    {"mark": "bar", "encoding": {"y": {"field": "件数", "type": "quantitative"}}},
    {"mark": {"type": "line", "point": true, "color": "#c00"},
     "encoding": {"y": {"field": "累積比率", "type": "quantitative",
                        "axis": {"format": "%"}, "scale": {"domain": [0, 1]}}}}
  ],
  "resolve": {"scale": {"y": "independent"}},
  "width": 240,
  "height": 160
}
```
:::

## 管理図

QC7つ道具の管理図です。測定値の折れ線に、上限（UCL）・中心線（CL）・下限（LCL）の線を重ねます。

- 上限・中心線・下限は、計算せず、手で書いた値です（この例は、中心線が50、上下の幅が6.5です）。値を変えるときは、`rule`の層と、文字の層の、両方を直してください。
- 限界を外れた点は、色（赤）だけに頼らず、大きな菱形にしています。白黒で印刷しても、区別できます。

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"回": 1, "値": 50.2}, {"回": 2, "値": 49.1}, {"回": 3, "値": 51.0}, {"回": 4, "値": 50.4}, {"回": 5, "値": 48.7},
    {"回": 6, "値": 49.9}, {"回": 7, "値": 52.1}, {"回": 8, "値": 50.6}, {"回": 9, "値": 47.9}, {"回": 10, "値": 50.0},
    {"回": 11, "値": 51.4}, {"回": 12, "値": 49.5}, {"回": 13, "値": 50.8}, {"回": 14, "値": 57.3}, {"回": 15, "値": 50.1}
  ]},
  "layer": [
    {"mark": "line",
     "encoding": {"x": {"field": "回", "type": "quantitative", "axis": {"tickMinStep": 1}},
                  "y": {"field": "値", "type": "quantitative", "scale": {"zero": false}}}},
    {"mark": {"type": "point", "filled": true, "color": "#000"},
     "encoding": {"x": {"field": "回", "type": "quantitative"},
                  "y": {"field": "値", "type": "quantitative"},
                  "shape": {"condition": {"test": "datum.値 > 56.5 || datum.値 < 43.5", "value": "diamond"}, "value": "circle"},
                  "size": {"condition": {"test": "datum.値 > 56.5 || datum.値 < 43.5", "value": 160}, "value": 40},
                  "color": {"condition": {"test": "datum.値 > 56.5 || datum.値 < 43.5", "value": "#c00"}, "value": "#000"}}},
    {"mark": {"type": "rule", "strokeDash": [6, 4]}, "encoding": {"y": {"datum": 56.5}}},
    {"mark": "rule", "encoding": {"y": {"datum": 50}}},
    {"mark": {"type": "rule", "strokeDash": [6, 4]}, "encoding": {"y": {"datum": 43.5}}},
    {"data": {"values": [{"限界": "UCL", "値": 56.5}, {"限界": "CL", "値": 50}, {"限界": "LCL", "値": 43.5}]},
     "mark": {"type": "text", "align": "left", "dx": 6},
     "encoding": {"x": {"datum": 15}, "y": {"field": "値", "type": "quantitative"}, "text": {"field": "限界"}}}
  ],
  "width": 260,
  "height": 160
}
````

```vega-lite
{
  "data": {"values": [
    {"回": 1, "値": 50.2}, {"回": 2, "値": 49.1}, {"回": 3, "値": 51.0}, {"回": 4, "値": 50.4}, {"回": 5, "値": 48.7},
    {"回": 6, "値": 49.9}, {"回": 7, "値": 52.1}, {"回": 8, "値": 50.6}, {"回": 9, "値": 47.9}, {"回": 10, "値": 50.0},
    {"回": 11, "値": 51.4}, {"回": 12, "値": 49.5}, {"回": 13, "値": 50.8}, {"回": 14, "値": 57.3}, {"回": 15, "値": 50.1}
  ]},
  "layer": [
    {"mark": "line",
     "encoding": {"x": {"field": "回", "type": "quantitative", "axis": {"tickMinStep": 1}},
                  "y": {"field": "値", "type": "quantitative", "scale": {"zero": false}}}},
    {"mark": {"type": "point", "filled": true, "color": "#000"},
     "encoding": {"x": {"field": "回", "type": "quantitative"},
                  "y": {"field": "値", "type": "quantitative"},
                  "shape": {"condition": {"test": "datum.値 > 56.5 || datum.値 < 43.5", "value": "diamond"}, "value": "circle"},
                  "size": {"condition": {"test": "datum.値 > 56.5 || datum.値 < 43.5", "value": 160}, "value": 40},
                  "color": {"condition": {"test": "datum.値 > 56.5 || datum.値 < 43.5", "value": "#c00"}, "value": "#000"}}},
    {"mark": {"type": "rule", "strokeDash": [6, 4]}, "encoding": {"y": {"datum": 56.5}}},
    {"mark": "rule", "encoding": {"y": {"datum": 50}}},
    {"mark": {"type": "rule", "strokeDash": [6, 4]}, "encoding": {"y": {"datum": 43.5}}},
    {"data": {"values": [{"限界": "UCL", "値": 56.5}, {"限界": "CL", "値": 50}, {"限界": "LCL", "値": 43.5}]},
     "mark": {"type": "text", "align": "left", "dx": 6},
     "encoding": {"x": {"datum": 15}, "y": {"field": "値", "type": "quantitative"}, "text": {"field": "限界"}}}
  ],
  "width": 260,
  "height": 160
}
```
:::

## ヒートマップ

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"曜日": "月", "時間帯": "午前", "件数": 12}, {"曜日": "月", "時間帯": "午後", "件数": 30},
    {"曜日": "火", "時間帯": "午前", "件数": 18}, {"曜日": "火", "時間帯": "午後", "件数": 41},
    {"曜日": "水", "時間帯": "午前", "件数": 25}, {"曜日": "水", "時間帯": "午後", "件数": 22},
    {"曜日": "木", "時間帯": "午前", "件数": 9}, {"曜日": "木", "時間帯": "午後", "件数": 35},
    {"曜日": "金", "時間帯": "午前", "件数": 33}, {"曜日": "金", "時間帯": "午後", "件数": 50}
  ]},
  "mark": "rect",
  "encoding": {
    "x": {"field": "曜日", "type": "ordinal", "sort": null},
    "y": {"field": "時間帯", "type": "ordinal", "sort": null},
    "color": {"field": "件数", "type": "quantitative"}
  },
  "width": 250,
  "height": 120
}
````

```vega-lite
{
  "data": {"values": [
    {"曜日": "月", "時間帯": "午前", "件数": 12}, {"曜日": "月", "時間帯": "午後", "件数": 30},
    {"曜日": "火", "時間帯": "午前", "件数": 18}, {"曜日": "火", "時間帯": "午後", "件数": 41},
    {"曜日": "水", "時間帯": "午前", "件数": 25}, {"曜日": "水", "時間帯": "午後", "件数": 22},
    {"曜日": "木", "時間帯": "午前", "件数": 9}, {"曜日": "木", "時間帯": "午後", "件数": 35},
    {"曜日": "金", "時間帯": "午前", "件数": 33}, {"曜日": "金", "時間帯": "午後", "件数": 50}
  ]},
  "mark": "rect",
  "encoding": {
    "x": {"field": "曜日", "type": "ordinal", "sort": null},
    "y": {"field": "時間帯", "type": "ordinal", "sort": null},
    "color": {"field": "件数", "type": "quantitative"}
  },
  "width": 250,
  "height": 120
}
```
:::

## 箱ひげ図

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"班": "A", "値": 52}, {"班": "A", "値": 58}, {"班": "A", "値": 61}, {"班": "A", "値": 65}, {"班": "A", "値": 70}, {"班": "A", "値": 92},
    {"班": "B", "値": 40}, {"班": "B", "値": 55}, {"班": "B", "値": 60}, {"班": "B", "値": 62}, {"班": "B", "値": 64}, {"班": "B", "値": 66},
    {"班": "C", "値": 30}, {"班": "C", "値": 45}, {"班": "C", "値": 58}, {"班": "C", "値": 72}, {"班": "C", "値": 80}, {"班": "C", "値": 85}
  ]},
  "mark": "boxplot",
  "encoding": {
    "x": {"field": "班", "type": "nominal"},
    "y": {"field": "値", "type": "quantitative"}
  },
  "width": 250,
  "height": 160
}
````

```vega-lite
{
  "data": {"values": [
    {"班": "A", "値": 52}, {"班": "A", "値": 58}, {"班": "A", "値": 61}, {"班": "A", "値": 65}, {"班": "A", "値": 70}, {"班": "A", "値": 92},
    {"班": "B", "値": 40}, {"班": "B", "値": 55}, {"班": "B", "値": 60}, {"班": "B", "値": 62}, {"班": "B", "値": 64}, {"班": "B", "値": 66},
    {"班": "C", "値": 30}, {"班": "C", "値": 45}, {"班": "C", "値": 58}, {"班": "C", "値": 72}, {"班": "C", "値": 80}, {"班": "C", "値": 85}
  ]},
  "mark": "boxplot",
  "encoding": {
    "x": {"field": "班", "type": "nominal"},
    "y": {"field": "値", "type": "quantitative"}
  },
  "width": 250,
  "height": 160
}
```
:::

## 対数軸

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"年": 2019, "件数": 12}, {"年": 2020, "件数": 95}, {"年": 2021, "件数": 800},
    {"年": 2022, "件数": 7300}, {"年": 2023, "件数": 61000}
  ]},
  "mark": {"type": "line", "point": true},
  "encoding": {
    "x": {"field": "年", "type": "ordinal"},
    "y": {"field": "件数", "type": "quantitative", "scale": {"type": "log"}}
  },
  "width": 300,
  "height": 160
}
````

```vega-lite
{
  "data": {"values": [
    {"年": 2019, "件数": 12}, {"年": 2020, "件数": 95}, {"年": 2021, "件数": 800},
    {"年": 2022, "件数": 7300}, {"年": 2023, "件数": 61000}
  ]},
  "mark": {"type": "line", "point": true},
  "encoding": {
    "x": {"field": "年", "type": "ordinal"},
    "y": {"field": "件数", "type": "quantitative", "scale": {"type": "log"}}
  },
  "width": 300,
  "height": 160
}
```
:::

## ファセット分割

同じ軸のグラフを、`facet`で、複数に分けて並べます。QC7つ道具の層別（データをグループに分けて比べる）にも使えます。

::: layout-left {left=55 right=45}
````text
{
  "data": {"values": [
    {"地域": "東", "月": 1, "売上": 10}, {"地域": "東", "月": 2, "売上": 20}, {"地域": "東", "月": 3, "売上": 30},
    {"地域": "西", "月": 1, "売上": 100}, {"地域": "西", "月": 2, "売上": 300}, {"地域": "西", "月": 3, "売上": 500}
  ]},
  "mark": "line",
  "encoding": {
    "x": {"field": "月", "type": "quantitative", "axis": {"tickMinStep": 1}},
    "y": {"field": "売上", "type": "quantitative", "scale": {"type": "log"}},
    "facet": {"field": "地域", "type": "nominal"}
  },
  "width": 120,
  "height": 80
}
````

```vega-lite
{
  "data": {"values": [
    {"地域": "東", "月": 1, "売上": 10}, {"地域": "東", "月": 2, "売上": 20}, {"地域": "東", "月": 3, "売上": 30},
    {"地域": "西", "月": 1, "売上": 100}, {"地域": "西", "月": 2, "売上": 300}, {"地域": "西", "月": 3, "売上": 500}
  ]},
  "mark": "line",
  "encoding": {
    "x": {"field": "月", "type": "quantitative", "axis": {"tickMinStep": 1}},
    "y": {"field": "売上", "type": "quantitative", "scale": {"type": "log"}},
    "facet": {"field": "地域", "type": "nominal"}
  },
  "width": 120,
  "height": 80
}
```
:::

## 外部のデータファイル

数百行を超えるデータは、別のファイル（`.csv`・`.tsv`・`.json`）に置き、`data.url`で読み込みます（[#350](https://github.com/tokudiro/text-compositor/issues/350)）。相対パスは、原稿のファイルの場所が基準です。次の例は、`data/monthly-sales.csv`を読みます。

::: layout-left {left=55 right=45}
````text
{
  "data": {"url": "data/monthly-sales.csv"},
  "mark": {"type": "line", "point": true},
  "encoding": {
    "x": {"field": "月", "type": "quantitative", "axis": {"tickMinStep": 1}},
    "y": {"field": "売上", "type": "quantitative"},
    "color": {"field": "地域", "type": "nominal"}
  },
  "width": 300,
  "height": 160
}
````

```vega-lite
{
  "data": {"url": "data/monthly-sales.csv"},
  "mark": {"type": "line", "point": true},
  "encoding": {
    "x": {"field": "月", "type": "quantitative", "axis": {"tickMinStep": 1}},
    "y": {"field": "売上", "type": "quantitative"},
    "color": {"field": "地域", "type": "nominal"}
  },
  "width": 300,
  "height": 160
}
```
:::

## Vega: 力学レイアウト（ネットワーク図）

Vega-Liteでは描けない、ノードが互いに反発・引き合って配置される図です。

::: layout-left {left=55 right=45}
````text
{
  "width": 420,
  "height": 280,
  "padding": 5,
  "signals": [
    {"name": "cx", "update": "width / 2"},
    {"name": "cy", "update": "height / 2"}
  ],
  "data": [
    {"name": "node-data", "values": [
      {"id": "中心", "group": 1}, {"id": "A", "group": 2}, {"id": "B", "group": 2}, {"id": "C", "group": 2},
      {"id": "A1", "group": 3}, {"id": "A2", "group": 3}, {"id": "B1", "group": 4}, {"id": "C1", "group": 5}, {"id": "C2", "group": 5}
    ]},
    {"name": "link-data", "values": [
      {"source": 0, "target": 1}, {"source": 0, "target": 2}, {"source": 0, "target": 3},
      {"source": 1, "target": 4}, {"source": 1, "target": 5}, {"source": 2, "target": 6},
      {"source": 3, "target": 7}, {"source": 3, "target": 8}
    ]}
  ],
  "scales": [
    {"name": "color", "type": "ordinal", "domain": {"data": "node-data", "field": "group"}, "range": {"scheme": "category10"}}
  ],
  "marks": [
    {
      "name": "nodes",
      "type": "symbol",
      "from": {"data": "node-data"},
      "encode": {
        "enter": {"fill": {"scale": "color", "field": "group"}, "stroke": {"value": "white"}},
        "update": {"size": {"value": 700}}
      },
      "transform": [
        {
          "type": "force",
          "signal": "force",
          "static": true,
          "iterations": 300,
          "velocityDecay": 0.4,
          "forces": [
            {"force": "center", "x": {"signal": "cx"}, "y": {"signal": "cy"}},
            {"force": "collide", "radius": 24},
            {"force": "nbody", "strength": -200},
            {"force": "link", "links": "link-data", "distance": 70}
          ]
        }
      ]
    },
    {
      "type": "path",
      "from": {"data": "link-data"},
      "interactive": false,
      "encode": {"update": {"stroke": {"value": "#999"}, "strokeWidth": {"value": 1}}},
      "transform": [
        {
          "type": "linkpath",
          "require": {"signal": "force"},
          "shape": "line",
          "sourceX": "datum.source.x", "sourceY": "datum.source.y",
          "targetX": "datum.target.x", "targetY": "datum.target.y"
        }
      ]
    },
    {
      "type": "text",
      "from": {"data": "nodes"},
      "interactive": false,
      "encode": {
        "update": {
          "x": {"field": "x"}, "y": {"field": "y"},
          "text": {"field": "datum.id"}, "align": {"value": "center"}, "baseline": {"value": "middle"},
          "fill": {"value": "white"}, "fontSize": {"value": 11}
        }
      }
    }
  ]
}
````

```vega
{
  "width": 420,
  "height": 280,
  "padding": 5,
  "signals": [
    {"name": "cx", "update": "width / 2"},
    {"name": "cy", "update": "height / 2"}
  ],
  "data": [
    {"name": "node-data", "values": [
      {"id": "中心", "group": 1}, {"id": "A", "group": 2}, {"id": "B", "group": 2}, {"id": "C", "group": 2},
      {"id": "A1", "group": 3}, {"id": "A2", "group": 3}, {"id": "B1", "group": 4}, {"id": "C1", "group": 5}, {"id": "C2", "group": 5}
    ]},
    {"name": "link-data", "values": [
      {"source": 0, "target": 1}, {"source": 0, "target": 2}, {"source": 0, "target": 3},
      {"source": 1, "target": 4}, {"source": 1, "target": 5}, {"source": 2, "target": 6},
      {"source": 3, "target": 7}, {"source": 3, "target": 8}
    ]}
  ],
  "scales": [
    {"name": "color", "type": "ordinal", "domain": {"data": "node-data", "field": "group"}, "range": {"scheme": "category10"}}
  ],
  "marks": [
    {
      "name": "nodes",
      "type": "symbol",
      "from": {"data": "node-data"},
      "encode": {
        "enter": {"fill": {"scale": "color", "field": "group"}, "stroke": {"value": "white"}},
        "update": {"size": {"value": 700}}
      },
      "transform": [
        {
          "type": "force",
          "signal": "force",
          "static": true,
          "iterations": 300,
          "velocityDecay": 0.4,
          "forces": [
            {"force": "center", "x": {"signal": "cx"}, "y": {"signal": "cy"}},
            {"force": "collide", "radius": 24},
            {"force": "nbody", "strength": -200},
            {"force": "link", "links": "link-data", "distance": 70}
          ]
        }
      ]
    },
    {
      "type": "path",
      "from": {"data": "link-data"},
      "interactive": false,
      "encode": {"update": {"stroke": {"value": "#999"}, "strokeWidth": {"value": 1}}},
      "transform": [
        {
          "type": "linkpath",
          "require": {"signal": "force"},
          "shape": "line",
          "sourceX": "datum.source.x", "sourceY": "datum.source.y",
          "targetX": "datum.target.x", "targetY": "datum.target.y"
        }
      ]
    },
    {
      "type": "text",
      "from": {"data": "nodes"},
      "interactive": false,
      "encode": {
        "update": {
          "x": {"field": "x"}, "y": {"field": "y"},
          "text": {"field": "datum.id"}, "align": {"value": "center"}, "baseline": {"value": "middle"},
          "fill": {"value": "white"}, "fontSize": {"value": 11}
        }
      }
    }
  ]
}
```
:::

## Vega: ツリーマップ

階層のあるデータを、大きさに比例した長方形で、入れ子に並べます。

::: layout-left {left=55 right=45}
````text
{
  "width": 420,
  "height": 240,
  "padding": 5,
  "data": [
    {
      "name": "tree",
      "values": [
        {"id": 1, "name": "全体"},
        {"id": 2, "parent": 1, "name": "開発"}, {"id": 3, "parent": 1, "name": "営業"}, {"id": 4, "parent": 1, "name": "管理"},
        {"id": 5, "parent": 2, "name": "設計", "size": 20}, {"id": 6, "parent": 2, "name": "実装", "size": 30},
        {"id": 7, "parent": 3, "name": "国内", "size": 18}, {"id": 8, "parent": 3, "name": "海外", "size": 12},
        {"id": 9, "parent": 4, "name": "総務", "size": 12}, {"id": 10, "parent": 4, "name": "経理", "size": 8}
      ],
      "transform": [
        {"type": "stratify", "key": "id", "parentKey": "parent"},
        {
          "type": "treemap",
          "field": "size",
          "sort": {"field": "value"},
          "round": true,
          "method": "squarify",
          "paddingInner": 2,
          "paddingOuter": 3,
          "size": [{"signal": "width"}, {"signal": "height"}]
        }
      ]
    },
    {"name": "leaves", "source": "tree", "transform": [{"type": "filter", "expr": "!datum.children"}]}
  ],
  "scales": [
    {"name": "color", "type": "ordinal", "domain": {"data": "tree", "field": "depth"}, "range": ["#dfe8f5", "#9ec1e8", "#4c78a8"]}
  ],
  "marks": [
    {
      "type": "rect",
      "from": {"data": "tree"},
      "encode": {
        "update": {
          "x": {"field": "x0"}, "y": {"field": "y0"}, "x2": {"field": "x1"}, "y2": {"field": "y1"},
          "fill": {"scale": "color", "field": "depth"}, "stroke": {"value": "white"}
        }
      }
    },
    {
      "type": "text",
      "from": {"data": "leaves"},
      "interactive": false,
      "encode": {
        "update": {
          "x": {"signal": "0.5 * (datum.x0 + datum.x1)"}, "y": {"signal": "0.5 * (datum.y0 + datum.y1)"},
          "text": {"field": "name"}, "align": {"value": "center"}, "baseline": {"value": "middle"},
          "fill": {"value": "white"}, "fontSize": {"value": 13}
        }
      }
    }
  ]
}
````

```vega
{
  "width": 420,
  "height": 240,
  "padding": 5,
  "data": [
    {
      "name": "tree",
      "values": [
        {"id": 1, "name": "全体"},
        {"id": 2, "parent": 1, "name": "開発"}, {"id": 3, "parent": 1, "name": "営業"}, {"id": 4, "parent": 1, "name": "管理"},
        {"id": 5, "parent": 2, "name": "設計", "size": 20}, {"id": 6, "parent": 2, "name": "実装", "size": 30},
        {"id": 7, "parent": 3, "name": "国内", "size": 18}, {"id": 8, "parent": 3, "name": "海外", "size": 12},
        {"id": 9, "parent": 4, "name": "総務", "size": 12}, {"id": 10, "parent": 4, "name": "経理", "size": 8}
      ],
      "transform": [
        {"type": "stratify", "key": "id", "parentKey": "parent"},
        {
          "type": "treemap",
          "field": "size",
          "sort": {"field": "value"},
          "round": true,
          "method": "squarify",
          "paddingInner": 2,
          "paddingOuter": 3,
          "size": [{"signal": "width"}, {"signal": "height"}]
        }
      ]
    },
    {"name": "leaves", "source": "tree", "transform": [{"type": "filter", "expr": "!datum.children"}]}
  ],
  "scales": [
    {"name": "color", "type": "ordinal", "domain": {"data": "tree", "field": "depth"}, "range": ["#dfe8f5", "#9ec1e8", "#4c78a8"]}
  ],
  "marks": [
    {
      "type": "rect",
      "from": {"data": "tree"},
      "encode": {
        "update": {
          "x": {"field": "x0"}, "y": {"field": "y0"}, "x2": {"field": "x1"}, "y2": {"field": "y1"},
          "fill": {"scale": "color", "field": "depth"}, "stroke": {"value": "white"}
        }
      }
    },
    {
      "type": "text",
      "from": {"data": "leaves"},
      "interactive": false,
      "encode": {
        "update": {
          "x": {"signal": "0.5 * (datum.x0 + datum.x1)"}, "y": {"signal": "0.5 * (datum.y0 + datum.y1)"},
          "text": {"field": "name"}, "align": {"value": "center"}, "baseline": {"value": "middle"},
          "fill": {"value": "white"}, "fontSize": {"value": 13}
        }
      }
    }
  ]
}
```
:::

## Vega: ワードクラウド

語の出現回数に応じて、文字の大きさを変えて、並べます。

::: layout-left {left=55 right=45}
````text
{
  "width": 400,
  "height": 220,
  "padding": 5,
  "data": [
    {
      "name": "words",
      "values": [
        {"text": "設計", "count": 9}, {"text": "図", "count": 7}, {"text": "Markdown", "count": 8},
        {"text": "PDF", "count": 6}, {"text": "テンプレート", "count": 5}, {"text": "自動化", "count": 4},
        {"text": "レビュー", "count": 3}, {"text": "履歴", "count": 3}, {"text": "文書", "count": 8}, {"text": "図表", "count": 5}
      ]
    }
  ],
  "scales": [
    {"name": "color", "type": "ordinal", "domain": {"data": "words", "field": "text"}, "range": {"scheme": "category10"}}
  ],
  "marks": [
    {
      "type": "text",
      "from": {"data": "words"},
      "encode": {
        "update": {
          "text": {"field": "text"},
          "align": {"value": "center"},
          "baseline": {"value": "alphabetic"},
          "fill": {"scale": "color", "field": "text"}
        }
      },
      "transform": [
        {"type": "wordcloud", "size": [{"signal": "width"}, {"signal": "height"}], "text": {"field": "text"}, "font": "sans-serif", "fontSize": {"field": "datum.count"}, "fontSizeRange": [14, 44], "padding": 3}
      ]
    }
  ]
}
````

```vega
{
  "width": 400,
  "height": 220,
  "padding": 5,
  "data": [
    {
      "name": "words",
      "values": [
        {"text": "設計", "count": 9}, {"text": "図", "count": 7}, {"text": "Markdown", "count": 8},
        {"text": "PDF", "count": 6}, {"text": "テンプレート", "count": 5}, {"text": "自動化", "count": 4},
        {"text": "レビュー", "count": 3}, {"text": "履歴", "count": 3}, {"text": "文書", "count": 8}, {"text": "図表", "count": 5}
      ]
    }
  ],
  "scales": [
    {"name": "color", "type": "ordinal", "domain": {"data": "words", "field": "text"}, "range": {"scheme": "category10"}}
  ],
  "marks": [
    {
      "type": "text",
      "from": {"data": "words"},
      "encode": {
        "update": {
          "text": {"field": "text"},
          "align": {"value": "center"},
          "baseline": {"value": "alphabetic"},
          "fill": {"scale": "color", "field": "text"}
        }
      },
      "transform": [
        {"type": "wordcloud", "size": [{"signal": "width"}, {"signal": "height"}], "text": {"field": "text"}, "font": "sans-serif", "fontSize": {"field": "datum.count"}, "fontSizeRange": [14, 44], "padding": 3}
      ]
    }
  ]
}
```
:::
