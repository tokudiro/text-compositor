# サードパーティ ライセンス一覧（viewer-csharp）

`viewer-csharp` は、組込版Python（`python-embed/`、配布時にexeと同じフォルダへ同梱）と、
その上で動く `build.py` の依存パッケージを利用している。それぞれのライセンス条件（ライセンス
全文・著作権表示の保持）を満たすため、配布時は `python-embed/` フォルダ全体（Python本体の
`LICENSE.txt` と、各パッケージの `site-packages/*.dist-info/` 内のライセンスファイルを含む）を
exeと同じ場所にそのまま含めること。本ファイルはその内容の一覧である。

| コンポーネント | バージョン | ライセンス | 著作権表示（抜粋） | ライセンス全文の場所 |
| --- | --- | --- | --- | --- |
| Python | 3.10.11 | PSF License | Python Software Foundation | `python-embed/LICENSE.txt` |
| markdown-it-py | 3.0.0 | MIT | Copyright (c) 2020 ExecutableBookProject | `python-embed/site-packages/markdown_it_py-3.0.0.dist-info/LICENSE` |
| markdown-it-py（同梱元・markdown-it／JS版由来部分） | - | MIT | Copyright (c) 2014 Vitaly Puzrin, Alex Kocharin | `python-embed/site-packages/markdown_it_py-3.0.0.dist-info/LICENSE.markdown-it` |
| mdit-py-plugins | 0.6.1 | MIT | Copyright (c) 2020 ExecutableBookProject | `python-embed/site-packages/mdit_py_plugins-0.6.1.dist-info/licenses/LICENSE` |
| mdurl | 0.1.2 | MIT | Copyright (c) 2015 Vitaly Puzrin, Alex Kocharin; Copyright (c) 2021 Taneli Hukkinen | `python-embed/site-packages/mdurl-0.1.2.dist-info/LICENSE` |
| PyYAML | 6.0.2 | MIT | Copyright (c) 2017-2021 Ingy döt Net; Copyright (c) 2006-2016 Kirill Simonov | `python-embed/site-packages/PyYAML-6.0.2.dist-info/LICENSE` |
| typst（pip版、[messense/typst-py](https://github.com/messense/typst-py)） | 0.15.0 | Apache-2.0 | NOTICEファイルの同梱なし（ライセンス全文の保持のみで足りる） | `python-embed/site-packages/typst-0.15.0.dist-info/licenses/LICENSE` |

## 備考

- 上記はすべて `requirements.txt` に記載の直接依存、および組込版Python自体。間接依存で
  ネイティブ拡張を追加で持ち込むパッケージが将来増えた場合は、この表を更新すること。
- Apache-2.0（typst）はNOTICEファイルの保持義務があるが、配布物（PyPIホイール）に
  NOTICEファイルが含まれていないため、ライセンス全文（`LICENSE`）の保持のみで足りる。
- MIT系のライセンスはいずれも全文が短いため、上記の各ファイルパスをそのまま配布物に
  含める運用で対応する（本ファイルへの全文転記はしない）。
