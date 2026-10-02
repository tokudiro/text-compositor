# WaveDromのギャラリー

`wavedrom`が対応する図の種類の実例です（[#291の対応表](08_diagrams.md#記法で描ける図の種類対応表)）。記法の説明は「図表」の章の「WaveDromについて」を参照してください。仕様は、厳密なJSONで書きます。

## タイミング図

クロック（`p`）・要求・データ・応答の4つの信号です。`wave`の文字は、`0`・`1`が低・高、`x`が不定、`.`が直前の状態の継続、`3`〜`5`が、`data`の値を載せたバスです。

```wavedrom
{ "signal": [
  { "name": "clk",  "wave": "p......." },
  { "name": "req",  "wave": "0.1..0.." },
  { "name": "data", "wave": "x.345x..", "data": ["a", "b", "c"] },
  { "name": "ack",  "wave": "1.0...10" }
]}
```

## パケット構造図（レジスタ図）

ビット幅つきのフィールドを並べます。`reg`で書きます。

```wavedrom
{ "reg": [
  { "name": "opcode", "bits": 7 },
  { "name": "rd",     "bits": 5 },
  { "name": "funct3", "bits": 3 },
  { "name": "rs1",    "bits": 5 },
  { "name": "imm",    "bits": 12 }
]}
```
