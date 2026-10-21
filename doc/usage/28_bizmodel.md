# ビジネスモデル図（bizmodel）

`bizmodel`は、ビジネスの「モノの流れ」と「カネの流れ」を、短いテキストから図にします。Markdownの` ```bizmodel `フェンスと、単体ファイル（`.bizmodel`。短い別名は`.bmv`）の両方で使えます。外部ツールは要りません（Pythonだけで描きます）。

「誰が、誰に、何を、いくらで」を、決まった記号だけで描くので、設計書や企画書の中に、事業の仕組みを、文字で書いて入れられます。

記法は、2つあります。1行目の`type`で切り替えます。

| `type` | 描くもの | この章の節 |
|---|---|---|
| `flow`（既定） | モノの流れと、カネの流れ | 「書き方」から「制限」まで |
| `canvas` | ビジネスモデルキャンバス（9つの枠に、箇条書きを入れる） | 「ビジネスモデルキャンバス」 |

## 書き方

売り手と買い手を宣言し、取引を1行で書きます。

```text
title "サブスクリプション型"
company Provider "配信事業者"
person User "ユーザー"
Provider -> User : goods "視聴権" / money "月額500円"
```

```bizmodel {alt="配信事業者がユーザーに視聴権を渡し、ユーザーが月額500円を払う"}
title "サブスクリプション型"
company Provider "配信事業者"
person User "ユーザー"
Provider -> User : goods "視聴権" / money "月額500円"
```

| 文 | 書き方 | 意味 |
|---|---|---|
| `company ID "表示名"` | 法人の宣言 | 縦長の長方形。名前は、中に1文字ずつ縦に並べます |
| `person ID "表示名"` | 個人の宣言 | 人型。名前は、下に書きます |
| `売り手 -> 買い手 : goods "…" / money "…"` | 取引 | 売り手から買い手へのモノと、買い手から売り手へのカネの、2本1組 |
| `title "…"` | 題名 | 省略できます。図の上に出ます |
| `type flow` | 記法の種類 | 1行目に書きます。`flow`と`canvas`があり、省略すると`flow`です |
| `# …` | コメント | 行頭にも、行の途中にも書けます |

- 識別子（`Provider`・`User`）は、英数字と`_`です。日本語は、引用符の中の表示名に書きます。
- `goods`と`money`は、必ず両方書きます。順番は、どちらでも構いません。
- 図の見た目は、黒の単色です。上の矢印（先端を塗りつぶす）がモノ、下の矢印（先端が開いている）がカネです。

## 無料と、分からない値

無料の取引は、カネを`0円`と書きます。取引がない場合は、取引そのものを書きません。「取引がない」と「0円の取引」は、ビジネス上の意味が違うためです。

```bizmodel
company Search "検索事業者"
person User "利用者"
Search -> User : goods "検索" / money "0円"
```

値が分からないときは、`？`と書きます。空欄にすると、書き忘れとして、エラーになります。

```bizmodel
company Maker "メーカー"
person Customer "顧客"
Maker -> Customer : goods "商品" / money "？円"
```

## 同時に買う（まとめ）

同じ相手に、同時に複数の取引があるときは、`bundle`で、まとめます。買い手の記号は、1つだけ描きます。

```text
bundle {
  Maker -> Customer : goods "商品A" / money "100円"
  Maker -> Customer : goods "商品B" / money "200円"
}
```

```bizmodel
company Maker "企業"
person Customer "顧客"
bundle {
  Maker -> Customer : goods "商品A" / money "100円"
  Maker -> Customer : goods "商品B" / money "200円"
}
```

## 時間差で買う（タイムライン）

購入のタイミングに時間差があるときは、`timeline`を使います。上の取引が先、下の取引が後です。買い手の下に、時間の経過を表す矢印（`T`）が出ます。

```bizmodel
company Maker "企業"
person Customer "顧客"
timeline {
  Maker -> Customer : goods "本体" / money "12,000円"
  Maker -> Customer : goods "消耗品" / money "2,000円"
}
```

## 顧客が別の場合

買い手が別の人物なら、別の識別子で宣言します。ヒトの記号は、人物ごとに別に描かれます。同じ識別子への取引は、1つの記号にまとまります。

```bizmodel
company Service "サービス事業者"
person Free "無料の利用者"
person Paid "有料の利用者"
Service -> Free : goods "基本機能" / money "0円"
Service -> Paid : goods "高度な機能" / money "月額980円"
```

## 3者以上の取引（一列・プラットフォーム）

売り手が複数の図も描けます。列は、取引の向き（売り手 → 買い手）に沿って、左から右へ増えます。同じ企業が、左側で仕入れ（買い手）、右側で販売（売り手）の取引を持てます。企業の記号の高さは、左右の取引の数が多いほうに合わせます。

メーカー → 卸 → 小売 → 顧客のような一列の図です。

```bizmodel
title "仕入れと小売"
company Maker "メーカー"
company Wholesale "卸"
company Shop "小売店"
person Customer "顧客"
Maker -> Wholesale : goods "商品" / money "100円"
Wholesale -> Shop : goods "商品" / money "150円"
Shop -> Customer : goods "商品" / money "200円"
```

複数の供給者・中央の企業・複数の顧客を描く、プラットフォーム型の図です。広告主への取引は、`bundle`でまとめています。`bundle`・`timeline`も、3者以上の図で使えます。

```bizmodel
title "広告つきのプラットフォーム"
person Seller1 "供給者A"
person Seller2 "供給者B"
company Platform "基盤企業"
person User "利用者"
person Advertiser "広告主"
Seller1 -> Platform : goods "出品" / money "手数料10%"
Seller2 -> Platform : goods "出品" / money "手数料10%"
Platform -> User : goods "サービス" / money "0円"
bundle {
  Platform -> Advertiser : goods "広告枠" / money "10万円"
  Platform -> Advertiser : goods "分析" / money "2万円"
}
```

## ビジネスモデルキャンバス

1行目に`type canvas`と書くと、ビジネスモデルキャンバスを描きます。9つの枠に、箇条書きの文字を入れた図です。

```text
type canvas
title "ネットの古書店"
partners "古書の仕入れ先"
activities "古書の買い取りと出品"
resources "在庫の管理システム"
value "探している本が、すぐ見つかる"
relationships "メールでの問い合わせ対応"
channels "自社サイト"
segments "古書を探している個人"
costs "仕入れ費"
costs "配送費"
revenue "書籍の販売代金"
```

```bizmodel {alt="ネットの古書店のビジネスモデルキャンバス"}
type canvas
title "ネットの古書店"
partners "古書の仕入れ先"
activities "古書の買い取りと出品"
resources "在庫の管理システム"
value "探している本が、すぐ見つかる"
relationships "メールでの問い合わせ対応"
channels "自社サイト"
segments "古書を探している個人"
costs "仕入れ費"
costs "配送費"
revenue "書籍の販売代金"
```

| 文 | 書き方 | 意味 |
|---|---|---|
| `type canvas` | 記法の種類 | 1行目に書きます |
| `title "…"` | 題名 | 省略できます。図の上に出ます |
| `キー "…"` | 箇条書きの1項目 | そのキーの枠に、1項目を足します |
| `# …` | コメント | 行頭にも、行の途中にも書けます |

| キー | 枠 | 略号 |
|---|---|---|
| `partners` | パートナー | KP |
| `activities` | 主要活動 | KA |
| `resources` | リソース | KR |
| `value` | 価値提案 | VP |
| `relationships` | 顧客との関係 | CR |
| `channels` | チャネル | CH |
| `segments` | 顧客セグメント | CS |
| `costs` | コスト構造 | C$ |
| `revenue` | 収益の流れ | R$ |

- 同じキーを、何回でも書けます。書いた順に、枠の中に、箇条書きで並びます。
- 文を書く順は、自由です。書かなかった枠は、空の枠として描きます。
- 項目は、1行に1つです。長い項目は、枠の幅で、自動的に折り返します。枠は、内容に応じて、高さが伸びます。
- 1項目が空（`value ""`）だと、E02になります。未知のキーや、`flow`の文（`company`・`->`など）を書くと、E06になります。箇条書きが1つも無いと、E08です。

### 出典の表記

図の下に、必ず、次の1行が入ります。**消したり、変えたりはできません。**

`Business Model Canvas: Strategyzer.com (CC BY-SA 3.0)`

ビジネスモデルキャンバスは、Creative Commonsのライセンス（CC BY-SA 3.0）で公開されており、利用の条件が、出典の明示だからです（公式ページ「Usage of our tools」）。図を、文書に載せるときも、この行を、そのまま残してください。

### 例

売り手と買い手の流れは、`flow`で描き、事業の全体は、`canvas`で描く、という使い分けもできます。

```bizmodel
type canvas
title "無料の検索サービス"
activities "検索の品質の改善"
resources "検索の仕組み"
value "知りたいことを、無料で調べられる"
channels "ウェブサイト"
segments "インターネットの利用者"
segments "広告を出したい企業"
costs "サーバー費"
costs "開発の人件費"
revenue "広告収入"
```

```bizmodel
type canvas
title "月額制の動画配信"
partners "映像の権利者"
activities "作品の調達と配信"
resources "配信の仕組み"
resources "契約している作品"
value "見たい作品を、いつでも見られる"
relationships "おすすめの表示"
channels "アプリ"
segments "動画をよく見る個人"
costs "作品の使用料"
costs "配信の費用"
revenue "月額の利用料"
```

## 単体ファイルとして使う

`.bizmodel`（短い別名は`.bmv`）は、`chapters`に直接指定できます（1ファイル＝1章）。Viewerでも、そのまま開けます。どちらの拡張子でも、同じ図になります。

## エラー

構文や意味の誤りは、エラー番号と、原稿の行つきで、ビルドが止まります。

| 番号 | 内容 |
|---|---|
| E01 | 取引に、`goods`または`money`の片方がない |
| E02 | `goods`または`money`の値が空（分からないときは`？`、無料は`0円`） |
| E03 | 宣言していない識別子を使っている |
| E04 | 売り手と買い手が、同じ識別子 |
| E05 | `bundle`・`timeline`の中の取引が、2つ未満、または売り手・買い手がそろっていない |
| E06 | 構文エラー（未知のキーワード、閉じていない`"`や`{`、`type`の誤りなど） |
| E07 | 識別子を、二重に宣言している |
| E08 | 取引が1つもない |
| E09 | 扱えない図（下の「制限」を参照） |

## 制限

次の図は、描けません（E09）。

- 列を飛ばす取引（メーカー → 卸 → 小売に、メーカー → 小売の直接取引を足すなど）。
- 同じ2者の間の、逆向きの取引（循環）。
- 矢印が交差する図（同じ買い手への取引が、離れて並ぶ場合）。
- `timeline`を受ける買い手が、別の取引にも加わる図。
- 同じ売り手・買い手の組が、`bundle`・`timeline`と、別の取引の両方に現れる図。

E09のメッセージに、理由が出ます。

## 設定

`plugins.bizmodel`（既定`true`）を`false`にすると、` ```bizmodel `フェンスを描かず、素のコード表示にします（「プラグインと入力」の章を参照）。図の大きさと代替テキストは、他の図と同じく、フェンス属性（`{width=60%}`・`{alt="…"}`）で指定できます。

## 由来と謝辞

この記法は、板橋悟氏が考案し、体系化された手法「ピクト図解」（登録商標）に着想を得ています。「ビジネスとは交換である」という大原則と、わずか5つの表記ルールで、ビジネスモデルを誰もが描けるようにした設計に、深く敬意を表します。

本記法は、非公式の取り組みです。公式のツールではなく、原典の代わりにもなりません。手法そのものを学びたい方は、考案者の書籍『ビジネスモデルを見える化する ピクト図解』と、公式サイト（pictozukai.jp）を、ぜひご覧ください。図と文章は、原典から写さず、自前で作っています。

ビジネスモデルキャンバスは、Strategyzerが、Creative Commonsのライセンスで公開してくださっています。誰もが使える形で公開されていることに、感謝します。出典は、すべての図の下に、お示ししています。
