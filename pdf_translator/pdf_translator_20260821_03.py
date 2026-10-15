#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
PDF Gemini 翻訳ツール

version : 20260821_03
purpose : 英語PDFなどを Gemini API で翻訳し、レイアウト（位置・フォントサイズ・文字色・
          背景）をできる限り保持したまま翻訳版PDFを生成する。

v20260821_03での変更点（「一部のフォントが崩れる・文字がはみ出す。可能な限りフォント
サイズを維持し、横にはみ出すなら折り返せないか」という要望を受けての改善。実際の
日本語資料（12ページ）とその英訳出力を突き合わせて原因を特定した）:

    - **【最も目立つ不具合】表の結合セルの行が、濃い帯で塗り潰されて読めなくなっていた。**
      表セルの背景色は、セルの左右の内側2点だけをサンプリングしていた。3列にまたがる
      結合セルでは文字がセルの端から端まで入るため、**2点とも文字の上に落ちる**ことが
      ある。その場合は「文字色と同じサンプルを除外する」仕組みが働かず（全部除外すると
      候補が無くなるため）、文字色そのものが背景色として採用され、濃い色で塗った上に
      同じ色で書いていた。
      → 文字は上下に余白を持つので、**セル内側の上端・下端からも採る**ようにして
      サンプル点を2点から8点へ増やした。
    - **結合セルの文字が、割り当てられた1マスの幅で折り返されていた。**
      セルへの割り当ては「文字の中心がどのマスに入るか」で決まるため、3列にまたがる行は
      真ん中の1マスに割り当てられる。そのマス幅で折り返すと極端に縮小されるか、はみ出す。
      → 文字が元々そのマスの外まで伸びている場合は、実際に文字があった範囲まで枠を
      広げる。ただし、はみ出しがマス幅の15%未満なら普通のセルとみなして広げない
      （広げすぎると隣の列へ文字が流れ込むため）。
    - **縮小する前に、使える範囲まで枠を広げて折り返すようにした。**
      v20260821_02までは「枠に入らない→まず縮小→下限で枠を広げる」という順序だった。
      これを「入らない→**まず枠を広げて元のサイズで折り返す**→それでも駄目なら縮小」に
      改めた。あわせて、枠の幅の上限（元の1.6倍）を撤廃した。実データで測ると、自由配置
      テキスト129件すべてに8pt以上の横の余地が残っており、使える幅の中央値954ptに対して
      実際に使っていたのは364pt（38%）だけだった。
      → 元のフォントサイズを保てたブロックが47件から56件に増加。
    - **折り返しの単位を「フォントの切れ目」から「語」に変更した。**
      "Shindo 5-kyō" のように欧文の語の途中に欧文フォントで描けない文字が入ると、そこが
      独立した折り返し単位になり、"5-ky" と "ō" が離れて配置されていた。
      欧文の語は途中で切らず、日本語を含む語だけ1文字ずつ折り返す。1語で枠幅を超える
      長い語（URL等）は文字単位で折り返す。
    - **墨消しで塗る範囲を「元の文字があった場所」だけに限定した。**
      流し込み先の枠を広げても塗る面積は増えないため、背景色の推定がわずかにずれても
      被害が広がらない。
    - **翻訳プロンプトに「簡潔に訳す」指示を追加した。** 実データでは、日本語31文字の
      表セルが英語114文字（約3.7倍）になっていた。訳自体は正しいが、日本語の専門的な
      短縮表記（「震度5弱」→"Seismic Intensity 5 Lower"）は英語で大きく膨らむ。
      罫線で高さが決まっているセルでは、これがフォント縮小の直接の原因になる。
      **この指示の効果は実際にGemini APIを呼ばないと測れないため、未検証。**

    **改善できない（原理的な限界として残る）**:
    - 罫線で高さが1行分に固定された表セルに、3〜4倍の長さの英文を読めるサイズで収める
      方法は無い。上記の対策を尽くしても、元が詰まった表では文字が小さくなる。
      どうしても避けたい場合は、GUIの「表・グラフに重なるテキストを翻訳しない」を
      ONにして、その部分を原文のまま残す運用が現実的。
v20260821_02での変更点（v20260821_01を実際の日本語資料（19ページ）で試したところ、
「前バージョン(20260812_01)の方がきれいに変換されている箇所がある」という報告を受けた。
原本・前版出力・新版出力の3つを突き合わせて原因を特定し修正した）:

    - **【主原因】記号を1文字含むだけで、行全体がCJKフォントに切り替わっていた。**
      v20260821_01は「Latin-1に収まらない文字が1つでもあれば、その文字列全体を
      CJKフォントで描く」という粒度だった。実データでは、CJKフォントで描かれた
      1,882文字のうち**1,855文字がただの英数字**で、本当に日本語フォントが必要な記号は
      27文字（■13・①4・②4・※3・◎2・③1）しかなかった。
      さらに `insert_textbox(fontname="japan")` は Adobe-Japan1 のCID参照で描くため、
      **英数字まで全角送り**になる（出力PDFでの実測: Helveticaが0.459em/文字に対し
      1.000em/文字＝約2.2倍）。その結果、行幅が2倍以上に膨らんで縮小フィットが働き、
      24ptの見出しが11.5ptまで潰れていた（■を含まないページだけ24ptを維持していたことが
      決定的な証拠）。
      → **フォントの割り当てを文字単位に変更**した。英数字はHelvetica、記号だけをCJK
      フォントで描く。`fitz.TextWriter` を使って1行の中でフォントを混在させている。
    - **CJKフォントがPDFへ埋め込まれていなかった。** 上記の "Gothic"（Adobe-Japan1）は
      参照のみで埋め込まれないため、日本語フォントが無い環境のビューアでは該当箇所が
      表示されない恐れがあった。→ `fitz.Font("japan")` を TextWriter 経由で使うと
      Droid Sans Fallback（実体のあるTTF）として**サブセット埋め込み**される。
      これにより①と③が同時に解決した。環境変数 `PDF_TRANSLATOR_CJK_FONT` で
      別のフォントファイルを指定することもできる。
      （Helvetica / Helvetica-Bold は埋め込まれないが、これはPDFの標準14フォントで
      どのビューアも必ず持っているため問題にならない。）
    - **縮小しすぎを止めた。** 縮小の下限を「元サイズの70%、かつ6pt以上」とした。
      下限まで縮めても収まらない場合は、**周囲に他の要素が無いと分かっている範囲まで**
      枠を下へ広げて対応する。無制限に広げると図の中の小さなラベルが下の要素へ重なる
      ことを開発中に実データで確認したため、広げてよい限界は抽出時に障害物と背景色から
      求めた値に限っている。
      なお `insert_textbox` は収まらないと**何も描かない**仕様のため、単純に「はみ出しを
      許容」すると翻訳文が丸ごと消える。最後の手段では必ず文字単位描画（はみ出してでも
      描く）を通すようにして、文字が失われないことを保証している。
    - **中央寄せの要素が右へずれていた。** v20260821_01は寄せの種類にかかわらず矩形を
      常に右方向へ拡張していたため、中央寄せの文字が広げた分の半分だけ右へずれていた
      （実データの最終ページのURLで、ページ中央390.0ptに対し出力は489.3pt＝約99ptのずれ）。
      → 中央寄せは元の中心を保ったまま左右対称に、右寄せは右端を固定して左方向へ
      拡張するようにした。

    実データ（19ページの日本語スライド）での効果:

    | 指標 | v20260821_01 | v20260821_02 |
    |---|---|---|
    | 24pt級の見出しを保てたページ | 3/19 | **7/19** |
    | 最も小さくなった見出し | 11.5pt | **17.0pt** |
    | 5pt未満の文字 | 524文字 | **438文字** |
    | 中央寄せURLの中心（正中390pt） | 489.3pt | **390.0pt** |
    | 埋め込まれていないフォント | Gothic ほか | **標準14フォントのみ** |

v20260821_01での変更点（**日本語→英語**の翻訳で成功率が低いという報告を受け、実際の
資料PDF（13ページの日本語スライド）とその英訳出力を突き合わせて原因を特定し修正した。
v01〜v20260812_01は英語→日本語だけを想定していたため、逆方向で複数の不具合が出ていた）:

    - **【最も致命的】翻訳文が背景と同じ色で塗り潰され、完全に読めなくなっていた**
      （全252ブロック中38件、15%）。
      原因は3つ重なっていた。
        1. 背景色のサンプリングを「拡張後の矩形（box_rect）」の外側で行っていた。v08で
           導入した矩形拡張はページ端近くまで伸びるため、その外側はページの装飾枠
           （実データでは濃紺の縁取り）で、本文とは無関係な色を背景として拾っていた。
        2. サンプル4点のうち2点が白・2点が紺という同数の場合、`max(set(...), key=count)`
           は集合の反復順で勝者が決まるため実質「運任せ」だった（252ブロック中107件、
           42%がこの同数状態）。
        3. 拾った紺色が文字色とほぼ同じだったため、紺で塗った上に紺で書き、文字が消えた。
      対策として、(a)サンプリングは必ず拡張前の元の矩形の周囲で行う、(b)サンプル点を
      4点から12点に増やし同数時は先に出現した色を採る決定的な規則にする、(c)文字色と
      同じ色のサンプルは「文字の上を拾った」とみなして除外する、の3つを入れた。
      実データで**38件 → 0件**になったことを確認済み。
    - **矩形の拡張がページの縁取りや隣の色帯を塗り潰していた**。v08の拡張は「他のテキスト・
      表セル・図形と重なるか」しか見ておらず、ページ全面の背景や縁取りは面積が大きすぎる
      ため図形一覧から意図的に除外されていて障害物にならなかった。実際にページを見て
      背景色が変わる手前で拡張を止めるようにした（`_clip_expansion_to_background`）。
    - **2文字の日本語が翻訳されずに残っていた**（22件）。`is_translatable()` の
      「2文字以下は翻訳しない」は英語向けの規則で、日本語では「企業」「震度」「時刻」の
      ように2文字で完全な単語になる。CJK文字を含む場合は1文字から翻訳対象にした。
    - **丸数字「③」や「※」が "?" に化けていた**（12箇所）。英語出力時のフォントは
      helv（Helvetica）で字形がLatin-1の範囲しかないが、翻訳文には原文由来の
      「①②③」「※」「～」「（）」が残ることがある。挿入する文字列がLatin-1に収まらない
      場合は内蔵CJKフォント（"japan"）へ自動的に切り替えるようにした。
    - **中央寄せのタイトルが左へずれていた**。表セル以外は一律で左寄せにしていたところへ
      v08の矩形拡張が加わったため、拡張後の広い矩形の左端に置かれてずれていた。
      元の矩形がページ左右に対称なら中央寄せ、右端に寄っていれば右寄せと推定する
      ようにした（自由配置142件のうち48件が中央配置だった）。
    - **太字が失われていた**。スパンの太字情報を捨てていたため、書き戻すと一律で
      レギュラーになっていた。太字は Helvetica-Bold（"hebo"）で書き戻すようにした。
    - **同じ段落の各行がバラバラに翻訳されていた**。PyMuPDFはスライド系PDFでは段落の
      各行を別ブロックとして返すことがあり（実データで本文3行が3ブロックに分離）、
      文が途中で切れたまま翻訳される・行ごとに別々に縮小されてフォントサイズが
      12.5/13.0/14.0ptと不揃いになる、という2つの実害があった。フォントサイズ・
      文字色・左端・行間から同一段落と判断できる連続行を1つの翻訳単位へまとめた。
    - **字送りで「2004」が「2 0 0 4」、「96%」が「9 6 %」に割れて翻訳AIへ渡っていた**。
      PyMuPDFが文字間隔の広さから擬似的な空白を挿入するため。CJKを含むテキストと、
      数字が1文字ずつ割れた並びに限って空白を詰めるようにした（英語原文では空白そのものが
      単語の区切りなので、従来どおり一切手を加えない）。

    **改善できない（原理的な限界として残るもの）**:
    - 日本語→英語では文字数が約2.6倍に増える（実測 5,142文字 → 13,599文字）。固定
      レイアウトのPDFに可変長の翻訳文を必ず収める一般解は存在しないため、狭い欄では
      依然としてフォント縮小やはみ出しが起きる。矩形拡張と段落結合で緩和はできるが、
      ゼロにはできない。
    - 下線・網掛け・文字装飾は再現されない（PyMuPDFのテキスト挿入では表現できない）。
    - スキャン画像PDF（テキストレイヤーなし）は従来どおり非対応。

v20260812_01での変更点（会社PCからGemini APIへの直接アクセスが遮断された件への対応。
PDFのレイアウト処理には一切手を加えていない）:
    - **背景**: 2026-08-10頃から会社PCでGemini APIへの直接アクセスが遮断された。対策として
      共通モジュール `gemini_client.py` の `generate_advanced()` を経由し、直接呼び出しが
      失敗したら自宅PCのプロキシへ自動フォールバックする方式へ移行する
      （rtocs_organizer / analog_ic_se_strategy_organizer / outlook_total_organizer /
      excel_translation と同じ方式）。
    - **本ツール固有の事情**: 旧版は起動時の `init_gemini()` で `genai.list_models()` を
      呼んで使用可能モデルを自動検出していた。これはネットワークアクセスを伴うため、
      遮断下では必ず例外になり「API初期化エラー」で `sys.exit(1)` する。つまり本ツールは
      移行しない限り**起動すらできない**状態だった（先行ツールとの最大の違い）。
      自動モデル検出は廃止し、固定モデル名（環境変数 `GEMINI_MODEL` で上書き可、既定は
      `gemini-2.5-flash`）を使う方式に変更した。
    - 旧SDK `google.generativeai` への依存を廃止し、`genai.Client` 相当の薄い互換シム
      （`_CommonGeminiClient`）を1つ用意して、クライアント生成箇所だけを差し替えた。
      レスポンス解析（`[番号] 訳文` の正規表現パース）・3回リトライ・3バッチ連続エラーでの
      フェイルファスト・進捗表示のロジックは一切変更していない。
    - `safety_settings`（BLOCK_NONE ×4）は REST の `safetySettings` としてpayloadへ載せる。
      載せ忘れると資料の内容によっては応答が空になり「一部バッチだけ翻訳されない」という
      切り分けにくい症状になるため、シム側で明示的に転送している。
    - `response.parts` による空応答判定を維持するため、シムのレスポンスにも `.parts` を
      持たせた（空応答なら `[]` を返すので、従来の「空なら ValueError を投げてリトライ」
      という挙動がそのまま保たれる）。
    - `request_options={"timeout": 40}` は共通モジュールに同等機能が無いため削除した。
      タイムアウトは `gemini_client.py` 側の固定値（直接15秒 / プロキシ60秒）になる。
      **挙動差**: 遮断下では最初のバッチだけ直接呼び出しの15秒タイムアウトを待つぶん
      遅くなる。一度失敗すると以降はプロキシ直行になるため2バッチ目以降は影響しない
      （仕様どおりの挙動であり、不具合ではない）。
    - PDFのレイアウト処理（罫線グリッド検出・ブロック抽出・墨消し・再配置・背景色
      サンプリング等）は**1行も変更していない**。v02〜v08で積み上げた調整はそのまま。

v08での変更点（「翻訳後のフォントサイズがバラバラになる」問題への対策。実際の資料PDFで
定量検証済み）:
    - **原因**: 自由配置テキスト（表セル以外）の翻訳文挿入矩形（box_rect）を、元の英語
      テキストぴったりのサイズ（1行なら1行分の高さ・幅）にしていた。日本語は英語と
      文字幅の性質が異なるため、同じフォントサイズでは元の矩形に収まらないことが多く、
      「収まるまでフォントサイズを0.5pt刻みで下げる」ロジックが働き続けていた。特に
      見出し（1行しか高さの無い矩形）は改行の余地が無いため、極端に縮小されていた
      （実データで定量検証: 200ブロック中195ブロックが縮小、平均縮小量2.4pt、見出しは
      最大20pt近く縮小されるケースもあった）。
    - **対策**: 自由配置テキストの矩形を、周囲の他のテキスト・表セル・図に重ならない
      範囲で右方向・下方向に安全に拡張してから、まず元のフォントサイズでの挿入を試みる
      ように変更（表セルは罫線という明確な境界があるため対象外）。それでも収まらない
      場合のみ、従来通りフォントサイズを縮小する。
    - 実データで再検証した結果、縮小されるブロックが195/200から54/200に減少し、元の
      フォントサイズを維持できたブロックは5/200から146/200に増加、平均縮小量も2.4pt
      から1.0ptに改善した。罫線つき表（合成テスト）でのセル単位翻訳・段落の複数行判定が
      引き続き正しく機能することも確認済み。

v07での変更点（新機能: ページ指定翻訳）:
    - これまで常に全ページを翻訳していたが、必要なページのみを指定して翻訳できる機能を
      追加した。GUIの言語選択ダイアログに「翻訳するページ」入力欄を追加し、
      "1-3,5,7-9" のようなカンマ区切り・範囲指定（1始まり）でページを指定できる。
      空欄の場合は従来通り全ページが対象になる。
    - 指定範囲外のページは extract_translatable_blocks() の時点で完全にスキップされる
      （テキスト抽出も墨消しも一切行わない）ため、対象外ページのレイアウトは座標レベルで
      100%元のまま保持されることを実データで確認済み。
    - 不正な指定（範囲外のページ番号、逆順の範囲、数値以外など）は翻訳開始前に検証し、
      エラーダイアログで具体的に指摘する。

v06での変更点（v05でも一部ページの棒グラフが崩れる問題への対策。実際の資料PDF
Page 19以降で再現・検証済み）:
    - **原因**: v05の「同一行内でスパン間の空白が大きい場合に分割する」ロジックは、
      Y座標が完全に一致する場合しか「同一行」と判定できなかった。実データでは、
      文章（1行目）・カテゴリ名（2行目）・パーセント値（文章とほぼ同じ高さだが
      数pt異なるY座標）が、それぞれ微妙に異なるY座標で配置されるレイアウトが
      あり、「文章」と「パーセント値」はY座標が数pt違うだけで「同一行」と
      判定されず、依然として1つの巨大なブロックとして結合され、間の棒グラフが
      塗り潰されていた。
    - **対策**: 分割の判定基準を「Y座標が同一か」から「X座標の区間（の和集合）に
      隙間があるか」に変更。ブロック内の全スパインをX座標でソートし、区間同士の
      隙間が30pt以上離れている場合に分割する（Y座標のズレは問わない）。これにより、
      多少Y座標がズレていても、遠く離れた列（棒グラフを挟んだ先のパーセント値等）
      を正しく別の翻訳単位として分離できる。複数行にまたがる通常の段落（各行の
      X区間がほぼ連続している）は誤って分割されないことも確認済み。
    - 実際の資料PDF（Page 19〜のような、文章＋カテゴリ名＋離れた列のパーセント値
      という構成のページ）で、棒グラフが正しい幅・色で保持されることを確認済み。

v05での変更点（v04で「表は崩れないが、表内のグラフの色味・文字位置がまだ大きく損なわれる」
問題への対策。実際の資料PDFで再現・検証済み）:
    - **原因1（本質的な原因）**: PyMuPDFのテキストブロックは、同じ行にあるだけで、間に
      大きな空白（＝実際にはチャートの棒グラフ等、無関係な図形が挟まっている）があっても
      1つのブロックとしてまとめてしまうことがある。実データでは、「Wellbeing」（カテゴリ名、
      左端）と「66.6% (+13.4)」（合計値、右端）の間に棒グラフを挟むレイアウトで、この2つが
      1つのブロックとして扱われ、行全体を覆う1つの巨大な矩形が生成されていた。そこに単色
      （矩形の外側からサンプリングした、多くの場合は白に近い背景色）で墨消しが行われ、
      間に挟まっていた棒グラフの色がまるごと塗り潰されていた。
    - **対策1**: 同一行内でもスパン間の水平方向の空白が一定以上（30pt）離れている場合は、
      別々の翻訳単位として分割するようにした。これにより「Wellbeing」と「66.6% (+13.4)」は
      それぞれ独立した小さな矩形として扱われ、間の棒グラフには一切触れなくなった。
    - **原因2**: 棒グラフのような角丸（パイル型）の色付き領域は、矩形の四隅が実際には
      塗りつぶし範囲の外（角の丸まった部分）に外れていることがあり、背景色を1点だけ
      サンプリングする方式では、角がたまたま塗りつぶし範囲外に外れて白や隣接色を誤って
      拾ってしまうことがあった（特に、幅の狭い色領域＝「Unfavorable」の赤色部分などで
      顕著だった）。
    - **対策2**: 背景色のサンプリングを、矩形の四辺（上下左右）付近の複数点から取得し、
      最も多く出現した色（多数決）を採用するように変更。角の誤サンプリングに引きずられ
      にくくした。
    - 実際の資料PDF（棒グラフ付きの表を含む24ページの人事survey資料）を用いて、対策1・2の
      両方を適用した結果、棒グラフの青・グレー・赤の配色が正しく保持されることを確認済み。
      また、罫線つき表（合成テスト）でのセル単位翻訳が引き続き正しく機能することも確認済み。

v04での変更点（v03で「翻訳されるページとされないページのバラつきが大きい」問題への対策。
実際の資料PDFで再現・検証済み）:
    - **原因**: 「表・グラフに重なるテキストを保護する」オプションが既定でONだった。
      このオプションは、罫線グリッドとして認識できない図形（画像・チャート等）に
      矩形が少しでも重なるテキストを一律で保護（未翻訳のまま）する仕様のため、
      タイトルページの色帯や、グラフの棒グラフの上に書かれた文字など、実際には
      翻訳しても問題ない箇所まで広く保護対象になってしまい、ページによって
      翻訳される/されないが大きくバラつく原因になっていた。
    - **対策**: v03で墨消し（redaction）自体が表・グラフを破壊する根本原因（罫線誤検出）
      を修正済みであり、図形に重なるテキストを翻訳しても、v03の対策1〜3により
      表・グラフの構造そのものが壊れるリスクは大幅に下がっている。そのため、
      GUIのチェックボックスの既定値を「保護する（ON）」から「保護しない（OFF、
      翻訳する）」に変更した。安全性を最優先したい場合は、引き続きチェックボックス
      をONにすることで、v01〜v03と同様の保護動作を選択できる。

v03での変更点（v02で「表・グラフが完全に消失する」不具合への対策。実際の資料PDFで再現・
検証済み）:
    - **根本原因**: v02の罫線グリッド検出は、ページ全面を覆う背景矩形やヘッダー帯の
      「辺」も罫線候補として拾ってしまっていた。実データでは、この背景矩形の辺と
      ヘッダー帯の境界線が偶然「交差」と判定され、ページのほぼ全域（面積100%近く）を
      覆う1つの巨大な"セル"が生成された。そこに該当ページの全テキストが1つの翻訳
      単位として飲み込まれ、単色で墨消し→再配置されたことで、色付きの棒グラフ・
      帯・区切り線がすべて上から塗り潰されて消失していた。
    - **対策1**: 罫線候補として採用するのは「細い」矩形の辺のみとする（太さ3pt超の
      矩形＝背景の色ブロックや棒グラフの塗りつぶしは、罫線ではなく図形そのものと
      みなして除外）。
    - **対策2**: 「外枠＋行の区切り線のみ（内部に列の区切りが無い一覧レイアウト）」は
      表とみなさないよう、縦横それぞれに"内部"の区切り線が実質2本以上（＝外枠だけ
      でなく本当に複数列・複数行に分かれている）場合のみ表として扱うよう厳格化。
      あわせて、二重ストロークで描かれた外枠（近接した2本の線が実質1本の線である
      ケース）を1本に統合してから本数を数えるようにした。
    - **対策3（多重の安全策）**: 1セルあたりの面積がページ面積の30%を超える場合は
      採用しない上限を追加。
    - 実際の資料PDF（棒グラフ付きの表を含む24ページの人事survey資料）を用いて、
      修正前は完全に消失していた棒グラフ・帯・罫線が、修正後はすべて保持される
      ことを確認済み。

v02での変更点（v01で「表やグラフの位置がズレる」問題への対策）:
    - 原因1: PyMuPDFの墨消し(redaction)はデフォルトで、矩形に重なる罫線やベクター図形
      ・画像も消去し得る設定になっていた。→ apply_redactions(images=PDF_REDACT_IMAGE_NONE,
      graphics=PDF_REDACT_LINE_ART_NONE) を指定し、表罫線やグラフの図形要素そのものは
      一切消去・上書きしないよう変更。
    - 原因2: 翻訳文を常に左寄せで再配置していたため、元がセンター/右寄せの表セル
      （数値列など）では、文字が本来の位置からズレて見えていた。→ ページ上の罫線
      （水平・垂直の直線）から実際の表グリッド（セル境界）を検出し、セルの矩形
      ・元の寄せ（左/中央/右、罫線とテキストの間隔から推定）を復元したうえで、
      セル内部だけを墨消しして翻訳文を差し込むように変更（罫線そのものには一切
      手を加えない＝表の外枠・格子線は座標レベルで100%元のまま）。
    - 罫線グリッドとして認識できない図（グラフ・チャート・画像）に重なるテキストは、
      安全のため既定で「保護」し、翻訳せず原文のまま残す（＝レイアウトが崩れる
      リスクをゼロにする）。GUI側のチェックボックスでON/OFF切り替え可能。

設計方針:
    - UI／進捗表示／Gemini呼び出し（リトライ・フェイルファスト・ロギング）は
      ppt_translation_20260309_03.py の設計を踏襲する。Gemini APIの呼び出しだけは
      共通モジュール gemini_client.py 経由（直接呼び出し→失敗時は自宅PCプロキシへ
      自動フォールバック）に移行しており、環境変数 GEMINI_API_KEY /
      GEMINI_PROXY_URL のどちらか一方でも設定されていれば動作する。
      自動モデル検出はネットワークアクセスを伴い遮断下で起動できなくなるため廃止した。
    - PDFにはPowerPointの「run」に相当する編集単位がないため、PyMuPDF (fitz) で
      テキストブロック単位（≒段落）に抽出・翻訳し、元のブロック矩形（表セルの
      場合は罫線から検出した実際のセル矩形）へ「墨消し（redaction、罫線・画像は
      保護）→ 背景色サンプリング→ 再配置（元の寄せを推定＋フォントサイズ自動
      縮小）」で書き戻す。日本語／中国語／韓国語は PyMuPDF 内蔵のCJKフォント
      （"japan" 等）を使用するため追加のフォントファイルは不要。

既知の制限（技術的な原理限界。100%保証はできない領域）:
    - スキャン画像PDF（テキストレイヤーなし）は翻訳対象を検出できない（OCR非対応）。
    - 「表・グラフに重なるテキストを翻訳しない」をONにすると、罫線グリッドとして
      認識できない自由配置の図（チャートの凡例・軸ラベル等）に重なるテキストは
      未翻訳のまま残る。OFF（既定）のまま翻訳した場合も、可変長の翻訳文を固定
      レイアウトの図形に安全に収める一般解は存在しないため、狭い図形の中の文字
      などでは稀にレイアウトが窮屈になることがある（＝実装のバグではなく、PDF
      という形式そのものの制約）。
    - ブロック単位の翻訳のため、1つの文が複数ブロックに分割されている場合は
      文脈が失われることがある。
    - 表セル以外の自由テキストの背景色はブロック付近の1点サンプリングによる近似
      のため、グラデーション等では完全には一致しない場合がある。

使い方:
    1. pip install -r requirements.txt
    2. 環境変数を設定する（どちらか一方でも可）
         GEMINI_API_KEY   … Gemini APIキー（直接呼び出し用）
         GEMINI_PROXY_URL … 自宅PCプロキシのURL（直接呼び出し失敗時のフォールバック先）
       ※ 共通モジュール gemini_client.py が別フォルダにある場合は GEMINI_COMMON_DIR で
         その場所を指定できる（通常は自動探索されるため不要）。
    3. python pdf_translator_20260821_03.py
    4. 「ファイル選択」からPDFを選び、翻訳先言語・翻訳するページ・保護オプションを
       選んで「翻訳開始」を押す
    5. 完了すると同じフォルダに `元ファイル名_ja.pdf`（英語翻訳なら `_en.pdf`）のように
       末尾2文字の言語コード付きで保存される
"""
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import sys
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import traceback

# ============================================================
# Gemini 共通クライアント(gemini_client.py)への互換シム
# ============================================================
# 会社PCからGemini APIへの直接アクセスが遮断される事象(2026-08-10頃)を受け、
# rtocs_organizer / analog_ic_se_strategy_organizer / outlook_total_organizer /
# excel_translation と同様に、共通モジュール gemini_client.py の generate_advanced()
# 経由(直接呼び出しが失敗したら自宅PCプロキシへ自動フォールバック)へ移行した。
#
# 本ツールは旧SDK(google.generativeai)の genai.GenerativeModel(...).generate_content()
# を1箇所で使っていただけだが、他ツールと実装を揃えるため、同じ形の薄い互換シム
# (_CommonGeminiClient)を用意し、そこを経由する方式にした。これにより、レスポンスを
# 読む側(response.parts で空判定 → response.text を正規表現で番号付きリストへ戻す処理)や
# リトライ・フェイルファスト・進捗表示のロジックは一切変更しないで済んでいる。
# 旧SDK(google-generativeai)への依存は本バージョンで無くなった。
#
# 必要な環境変数(会社PC):
#   GEMINI_API_KEY   … 直接呼び出し用(gemini_client.py 側が読む)
#   GEMINI_PROXY_URL … 自宅PCプロキシのURL(直接呼び出し失敗時のフォールバック先)
#   GEMINI_MODEL     … 使用モデルを変えたい場合のみ(任意。既定 gemini-2.5-flash)
#   GEMINI_COMMON_DIR… gemini_client.py の置き場所を明示したい場合のみ(任意)

_GEMINI_COMMON_DIR_ENV = os.environ.get("GEMINI_COMMON_DIR")
if _GEMINI_COMMON_DIR_ENV:
    _COMMON_DIR_CANDIDATES = [_GEMINI_COMMON_DIR_ENV]
else:
    # 会社PCでは本スクリプトが PythonScripts\PDF_translation\pdf_translator\ に、
    # gemini_client.py が PythonScripts\common\ に置かれるため、正解は「1つ上」では
    # なく「2つ上」の common になる。他ツール(1つ上が common)と同じ配置に置かれた
    # 場合でも動くよう、上位ディレクトリを順に探して最初に見つかったものを使う。
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    _COMMON_DIR_CANDIDATES = [
        os.path.abspath(os.path.join(_SCRIPT_DIR, *([os.pardir] * _n + ["common"])))
        for _n in (1, 2, 3)
    ]

_COMMON_DIR = next(
    (_d for _d in _COMMON_DIR_CANDIDATES
     if os.path.isfile(os.path.join(_d, "gemini_client.py"))),
    _COMMON_DIR_CANDIDATES[0])

if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

# gemini_client のインポートはここで試みるが、失敗しても import 時点では落とさない
# (原因が分かるメッセージを起動時チェックで出すため)。
try:
    from gemini_client import generate_advanced as _generate_advanced
    _GEMINI_CLIENT_IMPORT_ERROR = None
except Exception as _e:
    _generate_advanced = None
    _GEMINI_CLIENT_IMPORT_ERROR = _e

# 本ツールは全機能が翻訳(AI呼び出し)のため、共通モジュールを読み込めたかどうかが
# そのまま「Gemini が使えるか」になる。
HAS_GEMINI = _generate_advanced is not None
if not HAS_GEMINI:
    print(f"警告: Gemini共通モジュール(gemini_client.py)を読み込めませんでした: "
          f"{_GEMINI_CLIENT_IMPORT_ERROR}")

# 旧版は genai.list_models() で使用可能モデルを自動検出していたが、これはネットワーク
# アクセスを伴うため、直接アクセスが遮断された環境では必ず失敗し、起動時の
# init_gemini() が False を返して sys.exit(1) していた(＝ツールが起動できない)。
# 共通モジュール・プロキシのどちらにも list_models 相当が無いため、自動検出は廃止し、
# 固定モデル名(環境変数 GEMINI_MODEL で上書き可)を使う方式に変更した。
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def _gemini_common_module_error_message():
    """共通モジュールを読み込めなかったときの、原因が分かる案内文を組み立てる。"""
    return ("Gemini共通モジュール(gemini_client.py)を読み込めませんでした。\n"
            f"探索したパス: {' / '.join(_COMMON_DIR_CANDIDATES)}\n"
            f"元のエラー: {_GEMINI_CLIENT_IMPORT_ERROR}\n\n"
            "gemini-common-tools を配置し、必要なら環境変数 GEMINI_COMMON_DIR で\n"
            "gemini_client.py のあるフォルダを指定してください。")


def _schema_to_jsonable(value):
    """REST APIのpayloadへそのまま載せられる素のdict/listへ変換する。
    本ツールの safety_settings は既に素のdictのリストなのでそのまま返るが、
    他ツールのシムと実装を揃えるために残してある(pydanticモデル等が渡された
    場合にJSON化できなくなるのを防ぐ保険)。"""
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    # pydantic v2 (model_dump) / v1 (dict) の両方に対応。REST APIのフィールド名は
    # camelCase なので by_alias=True で別名を使う。
    for attr, kwargs in (("model_dump", {"mode": "json", "exclude_none": True, "by_alias": True}),
                         ("dict", {"exclude_none": True, "by_alias": True})):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return fn(**kwargs)
            except Exception:
                try:
                    return fn()
                except Exception:
                    pass
    return value


class _GeminiGenerateConfig:
    """旧SDKの genai.types.GenerationConfig(...) ＋ safety_settings 相当の設定
    オブジェクト。旧SDKへの依存を断つため、同等の入れ物をここに置く
    (シム側は getattr で属性を読むだけなので実装差の影響を受けない)。"""
    def __init__(self, temperature=None, safety_settings=None,
                 system_instruction=None, response_mime_type=None, response_schema=None):
        self.temperature = temperature
        self.safety_settings = safety_settings
        self.system_instruction = system_instruction
        self.response_mime_type = response_mime_type
        self.response_schema = response_schema


class _CommonUsageMetadata:
    """response.usage_metadata 互換(トークン計測用)。本ツールは現時点で参照して
    いないが、他ツールのシムと契約を揃えておく。"""
    def __init__(self, usage):
        usage = usage if isinstance(usage, dict) else {}
        self.prompt_token_count = usage.get("promptTokenCount", 0)
        self.candidates_token_count = usage.get("candidatesTokenCount", 0)


class _CommonGeminiResponse:
    """client.models.generate_content(...) の戻り値互換。
    本ツールは response.parts で空応答を判定してから response.text を読むため、
    parts も提供する(空応答なら空リストになるので、呼び出し側の
    「空なら ValueError を投げてリトライ」という既存の挙動がそのまま保たれる)。
    レスポンスが想定外の形でも例外を投げず、text は空文字にする。"""
    def __init__(self, raw):
        try:
            self.text = raw["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            self.text = ""
        try:
            self.parts = raw["candidates"][0]["content"]["parts"] or []
        except (KeyError, IndexError, TypeError):
            self.parts = []
        self.usage_metadata = _CommonUsageMetadata(
            raw.get("usageMetadata", {}) if isinstance(raw, dict) else {})


class _CommonGeminiModels:
    """client.models 互換。"""
    def generate_content(self, model=None, contents=None, config=None):
        if _generate_advanced is None:
            raise RuntimeError(_gemini_common_module_error_message())

        payload = {"contents": [{"parts": [{"text": contents}]}]}
        if config is not None:
            # safety_settings は旧SDKへ渡していた時点で既にREST形式
            # (category / threshold のdictリスト)なので、そのまま載せればよい。
            # 載せ忘れると BLOCK_NONE 指定が消え、資料の内容によっては応答が空になり
            # 「一部のバッチだけ翻訳されない」という切り分けにくい症状になる。
            safety = getattr(config, "safety_settings", None)
            if safety:
                payload["safetySettings"] = _schema_to_jsonable(safety)

            system_instruction = getattr(config, "system_instruction", None)
            if isinstance(system_instruction, str) and system_instruction:
                payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
            elif isinstance(system_instruction, dict):
                payload["systemInstruction"] = system_instruction

            gen_cfg = {}
            mime = getattr(config, "response_mime_type", None)
            if mime:
                gen_cfg["responseMimeType"] = mime
            schema = getattr(config, "response_schema", None)
            if schema is not None:
                gen_cfg["responseSchema"] = _schema_to_jsonable(schema)
            temp = getattr(config, "temperature", None)
            if temp is not None:
                gen_cfg["temperature"] = temp
            if gen_cfg:
                payload["generationConfig"] = gen_cfg

        # model は明示的に渡す(共通モジュール側の既定モデルへ勝手にフォールバック
        # されると、意図したモデルと実際に使われるモデルが食い違うため)。
        raw = _generate_advanced(payload, model=model)
        return _CommonGeminiResponse(raw)


class _CommonGeminiClient:
    """genai.Client(api_key=...) 相当。api_key は gemini_client.py 側が環境変数
    GEMINI_API_KEY から読むため、ここでは互換性のために受け取るだけで使用しない。"""
    def __init__(self, api_key=None):
        self.models = _CommonGeminiModels()


def gemini_credentials_available():
    """AI呼び出しが行える見込みがあるかどうかの事前チェック。
    直接呼び出しが遮断されていてもプロキシ経由なら成功しうるため、
    GEMINI_API_KEY / GEMINI_PROXY_URL のどちらか一方でも設定されていれば通す
    (プロキシ専用構成を誤って弾かないため)。"""
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_PROXY_URL"))


# --- 依存関係の確認 ---
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


def check_dependencies(root_window):
    """起動時の依存関係チェック"""
    missing_libs = []
    if not HAS_PYMUPDF:
        missing_libs.append("PyMuPDF")

    if missing_libs:
        error_msg = "以下のライブラリがインストールされていません:\n"
        for lib in missing_libs:
            error_msg += f"- {lib}\n"
        error_msg += "\n以下のコマンドでインストールしてください:\n"
        error_msg += f"pip install {' '.join(missing_libs)}"

        messagebox.showerror("依存関係エラー", error_msg, parent=root_window)
        return False

    # 本ツールは全機能が翻訳(AI呼び出し)のため、共通モジュールが読めない場合は
    # 起動を続けても何もできない。原因が分かる形で案内して終了する。
    if not HAS_GEMINI:
        messagebox.showerror("依存関係エラー", _gemini_common_module_error_message(),
                             parent=root_window)
        return False

    return True


# --- グローバル変数（Gemini互換シムのクライアント） ---
gemini_client = None


def get_logger():
    """デバッグ用ロガーの初期化（コンソールとファイル両方に出力）"""
    logger = logging.getLogger("PDF_Translation")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler("translation_debug.log", encoding="utf-8")
        ch = logging.StreamHandler()
        formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", "%H:%M:%S")
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger


def init_gemini(root_window):
    """Gemini呼び出しの事前チェックと互換シムのクライアント生成。

    旧版はここで genai.configure() の後に genai.list_models() を呼び、使用可能な
    モデルを自動検出していた。しかしこれはネットワークアクセスを伴うため、直接
    アクセスが遮断された環境では必ず例外になり、「API初期化エラー」ダイアログを
    出して sys.exit(1) していた（＝ツールが起動できない）。プロキシ経由なら翻訳
    自体は可能なのに起動段階で止まってしまうため、自動モデル検出は廃止し、固定
    モデル名（環境変数 GEMINI_MODEL で上書き可）を使う方式に変更した。
    この関数はネットワークアクセスを一切行わない。
    """
    global gemini_client
    if _generate_advanced is None:
        messagebox.showerror("エラー", _gemini_common_module_error_message(), parent=root_window)
        return False

    if not gemini_credentials_available():
        messagebox.showerror("エラー",
                             "Gemini認証情報が設定されていません。\n"
                             "以下のいずれかを設定してください:\n"
                             "- 環境変数 GEMINI_API_KEY （直接接続用）\n"
                             "- 環境変数 GEMINI_PROXY_URL （自宅PCプロキシ経由用）\n\n"
                             "※ setx で設定した場合は、コマンドプロンプトを\n"
                             "　 開き直してから起動してください。", parent=root_window)
        return False

    gemini_client = _CommonGeminiClient()
    print(f"使用モデル: {GEMINI_MODEL_NAME}")
    return True


_CJK_RE = re.compile(
    "[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯ｦ-ﾟ]"
)


def _contains_cjk(text):
    """日本語（ひらがな・カタカナ・漢字）・中国語・韓国語の文字を含むか"""
    return bool(_CJK_RE.search(text or ""))


def is_translatable(text):
    """翻訳が必要なテキストかどうかを判定"""
    if not text or str(text).strip() == "":
        return False

    text_str = str(text).strip()

    if text_str in ["", "#", "-", "N/A", "NULL", "•", "◦", "▪", "**", "*", ":", "：",
                    "I.", "II.", "III.", "IV.", "V.", "VI.", "***"]:
        return False
    if text_str.replace(".", "").replace("-", "").isdigit():
        return False

    # 「短すぎる文字列は翻訳しない」の閾値は言語によって意味が変わる。英語の2文字は
    # ほぼ意味を持たない断片だが、日本語・中国語・韓国語では2文字で完全な単語になる
    # （「企業」「震度」「時刻」「対象」など）。日本語→英語の実データでは、この
    # 一律「2文字以下は除外」により表の見出し等22件が未翻訳のまま残っていた。
    # そのためCJK文字を含む場合は1文字から翻訳対象とする。
    if _contains_cjk(text_str):
        return len(text_str) >= 1
    if len(text_str) <= 2:
        return False
    return True


def translate_batch_gemini(texts, target_language="Japanese", batch_idx=0, logger=None):
    """Gemini APIを使用した小バッチ翻訳（リトライ・タイムアウト機構付き）"""
    if not gemini_client or not texts:
        return texts, False

    batch_input = "\n".join([f"[{i+1}] {t}" for i, t in enumerate(texts)])

    prompt = f"""
    Task: Translate the following text into {target_language}.

    Guidelines:
    1. Maintain the exact format [number] for each translated line.
    2. Output ONLY the numbered list. No extra explanations.
    3. Keep technical terms natural.
    4. This text is taken from a slide deck, where each line must fit back into a
       fixed-size box or table cell. Keep every translation as short as the source
       allows: do not add words or explanations that are not in the source, prefer
       concise wording over verbose phrasing, and keep parenthetical notes brief.
       Never pad a short label into a long sentence.

    Source Text:
    {batch_input}
    """

    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    for attempt in range(1, 4):  # 最大3回リトライ
        try:
            if logger: logger.info(f"バッチ {batch_idx+1} 通信開始 (試行 {attempt}/3)")

            # 旧: gemini_model.generate_content(prompt, generation_config=...,
            #         safety_settings=..., request_options={"timeout": 40})
            # 新: 共通モジュール(gemini_client.py)経由の互換シムで同じ内容を送る。
            # request_options={"timeout": 40} は共通モジュールに同等機能が無いため削除した。
            # タイムアウトは gemini_client.py 側の固定値（直接15秒 / プロキシ60秒）になる。
            # 遮断下では最初のバッチだけ直接呼び出しの15秒を待つぶん遅くなるが、一度失敗
            # すると以降はプロキシ直行になるため2バッチ目以降は影響しない（仕様どおり）。
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=prompt,
                config=_GeminiGenerateConfig(temperature=0.1, safety_settings=safety_settings),
            )
            time.sleep(1.5)

            if not response.parts:
                if logger: logger.warning(f"バッチ {batch_idx+1} 空のレスポンスを受信")
                raise ValueError("Empty response from API")

            response_text = response.text.strip()
            results = [None] * len(texts)
            lines = response_text.split('\n')

            for line in lines:
                match = re.match(r'^\[(\d+)\]\s*(.*)', line.strip())
                if match:
                    idx = int(match.group(1)) - 1
                    if 0 <= idx < len(texts):
                        results[idx] = match.group(2).strip()

            for i in range(len(results)):
                if results[i] is None:
                    results[i] = texts[i]

            if logger: logger.info(f"バッチ {batch_idx+1} 成功！")
            return results, False  # 成功（エラーフラグFalse）

        except Exception as e:
            if logger: logger.error(f"バッチ {batch_idx+1} エラー発生: {str(e)}")
            if attempt < 3:
                time.sleep(3)  # エラー時は3秒間隔で待機
            else:
                if logger: logger.error(f"バッチ {batch_idx+1} は3回失敗したためスキップします。")

    return texts, True  # 失敗（原文を返し、エラーフラグTrueを通知）


def translate_super_fast_parallel(all_texts, target_language="Japanese", max_workers=3, progress_callback=None, logger=None):
    """並列処理エンジン（コールバックと強制切断機能付き）"""
    if not all_texts:
        return []

    batch_size = 10
    chunks = [all_texts[i:i + batch_size] for i in range(0, len(all_texts), batch_size)]
    results = [None] * len(chunks)

    abort_event = threading.Event()
    consecutive_errors = 0
    processed_items = 0

    def translate_chunk(chunk_idx, chunk_texts):
        if abort_event.is_set():
            return chunk_idx, (chunk_texts, False)  # 中断フラグが立っていればスルー
        return chunk_idx, translate_batch_gemini(chunk_texts, target_language, chunk_idx, logger)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(translate_chunk, i, chunk) for i, chunk in enumerate(chunks)]

        for future in as_completed(futures):
            try:
                chunk_idx, (translated_chunk, is_error) = future.result()
                results[chunk_idx] = translated_chunk

                # エラーカウントの判定
                if is_error:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0  # 1つでも成功すればリセット

                # 3回連続エラーで即時撤退（フェイルファスト）
                if consecutive_errors >= 3:
                    abort_event.set()
                    if logger: logger.critical("【致命的エラー】3バッチ連続で通信エラー発生。処理を強制中断します。")
                    raise RuntimeError("Gemini APIへの通信が3回連続で失敗しました。\nネットワーク接続かAPI制限をご確認ください。")

                # 進捗UIの更新
                processed_items += len(chunks[chunk_idx])
                if progress_callback:
                    progress_callback(processed_items)

            except RuntimeError as e:
                raise e  # 致命的エラーはそのまま投げる
            except Exception as e:
                if logger: logger.error(f"チャンク結果取得エラー: {str(e)}")

    final_results = []
    for chunk_result in results:
        if chunk_result:
            final_results.extend(chunk_result)
        else:
            final_results.extend([""] * batch_size)

    return final_results


class PdfProgressWindow:
    """進捗表示用ウィンドウ（スレッドセーフ版）"""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Gemini 翻訳進捗")
        self.window.geometry("450x180")
        self.window.resizable(False, False)

        try:
            self.window.transient(parent)
            self.window.grab_set()
        except Exception:
            pass

        self.progress_label = tk.Label(self.window, text="Gemini AI 翻訳を準備中...", font=("Arial", 11, "bold"))
        self.progress_label.pack(pady=15)

        self.status_label = tk.Label(self.window, text="処理を開始します...", font=("Arial", 9))
        self.status_label.pack(pady=5)

        self.progress_frame = tk.Frame(self.window, width=350, height=20, bg="white", relief="sunken")
        self.progress_frame.pack(pady=10)

        self.progress_bar = tk.Frame(self.progress_frame, height=18, bg="#0078D4")
        self.progress_bar.place(x=1, y=1)

        self.time_label = tk.Label(self.window, text="", font=("Arial", 8), fg="blue")
        self.time_label.pack(pady=2)

        self.start_time = time.time()

    def update_progress(self, current, total, status=""):
        # 別スレッドから安全にGUIを更新するため after を使用
        try:
            self.window.after(0, self._update_gui, current, total, status)
        except Exception:
            pass

    def _update_gui(self, current, total, status):
        try:
            percentage = int((current / total) * 100) if total > 0 else 0
            bar_width = int((current / total) * 348) if total > 0 else 0
            self.progress_bar.config(width=bar_width)

            elapsed_time = time.time() - self.start_time

            self.progress_label.config(text=f"翻訳進捗: {current}/{total} ({percentage}%)")
            if status:
                self.status_label.config(text=status)
            self.time_label.config(text=f"経過時間: {elapsed_time:.1f}s")
        except Exception:
            pass

    def close(self):
        try:
            self.window.after(0, self.window.destroy)
        except Exception:
            pass


def _round_coord(v, tol=0.75):
    """近い座標を同一の罫線とみなすための丸め処理"""
    return round(v / tol) * tol


def _analyze_page_graphics(page, logger=None):
    """ページのベクター図形から、表の罫線グリッド（水平線×垂直線が実際に交差して
    形成する領域）を検出し、罫線グリッドとして解釈できない図形の矩形一覧（保護対象
    の目印）とあわせて返す。

    表とグラフが同じページに混在する場合、単純に「ページ内の全水平線・全垂直線」を
    1つの座標集合としてプールすると、離れた場所にあるグラフの矩形の辺（棒グラフの
    左右の辺など）まで表の列線と誤認識し、無関係な座標同士が組み合わさってセルが
    ズレる（後述のUnion-Findで実際に検証済みの不具合）。これを防ぐため、線分同士が
    実際に交差しているかどうかで連結成分（クラスタ）に分け、1つのクラスタ＝1つの
    表とみなす。

    戻り値: (grids, graphic_rects)
        grids: [(v_lines, h_lines), ...] 独立した表グリッドごとの垂直/水平座標リスト
        graphic_rects: 罫線グリッド以外の図形の矩形一覧（ページ全面を覆う背景矩形は除外）
    """
    page_rect = page.rect
    page_area = max(page_rect.width * page_rect.height, 1.0)
    v_segs = []  # [x, y0, y1]
    h_segs = []  # [y, x0, x1]
    graphic_rects = []

    try:
        drawings = page.get_drawings()
    except Exception as e:
        if logger: logger.debug(f"get_drawings失敗: {e}")
        drawings = []

    # 「薄い罫線」とみなす最大の太さ（pt）。実際の表罫線は通常0.5〜2pt程度なので、
    # これより厚い矩形は棒グラフのバーや背景の色ブロックであり、罫線ではない。
    RULE_THICKNESS_MAX = 3.0

    for d in drawings:
        r = fitz.Rect(d.get("rect", fitz.Rect()))
        if not r.is_empty and (r.width * r.height) / page_area <= 0.85:
            graphic_rects.append(r)

        for item in d.get("items", []):
            kind = item[0]
            segments = []
            if kind == "l":
                # 明示的な直線は常に罫線候補（罫線以外に直線を引く用途はまず無い）
                segments.append((item[1], item[2]))
            elif kind == "re":
                rr = fitz.Rect(item[1])
                # ページ全面や帯状の背景、棒グラフの塗りつぶし矩形など「太い」矩形は
                # 罫線ではなく図形そのものなので、その辺を罫線候補に含めない。
                # （実データで、ページ全面の背景矩形の辺がヘッダー帯の境界線と誤って
                # 交差判定され、ページのほぼ全域を覆う巨大な1セルが生成されて
                # チャート全体（色・棒グラフ含む）が塗りつぶされる致命的な不具合が
                # あったため、これを防ぐガード）
                if min(rr.width, rr.height) > RULE_THICKNESS_MAX:
                    continue
                segments.extend([
                    (fitz.Point(rr.x0, rr.y0), fitz.Point(rr.x1, rr.y0)),
                    (fitz.Point(rr.x0, rr.y1), fitz.Point(rr.x1, rr.y1)),
                    (fitz.Point(rr.x0, rr.y0), fitz.Point(rr.x0, rr.y1)),
                    (fitz.Point(rr.x1, rr.y0), fitz.Point(rr.x1, rr.y1)),
                ])
            for p1, p2 in segments:
                if abs(p1.y - p2.y) < 0.6 and abs(p1.x - p2.x) > 8:
                    y = _round_coord((p1.y + p2.y) / 2)
                    x0, x1 = sorted([p1.x, p2.x])
                    h_segs.append([y, x0, x1])
                elif abs(p1.x - p2.x) < 0.6 and abs(p1.y - p2.y) > 8:
                    x = _round_coord((p1.x + p2.x) / 2)
                    y0, y1 = sorted([p1.y, p2.y])
                    v_segs.append([x, y0, y1])

    # Union-Find: 実際に交差する線分同士だけを同一グリッド（同一の表）とみなす
    n = len(v_segs) + len(h_segs)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    tol = 1.5
    for vi, (vx, vy0, vy1) in enumerate(v_segs):
        for hi, (hy, hx0, hx1) in enumerate(h_segs):
            if (vy0 - tol) <= hy <= (vy1 + tol) and (hx0 - tol) <= vx <= (hx1 + tol):
                union(vi, len(v_segs) + hi)

    clusters = {}
    for vi, seg in enumerate(v_segs):
        clusters.setdefault(find(vi), {"v": set(), "h": set()})["v"].add(seg[0])
    for hi, seg in enumerate(h_segs):
        clusters.setdefault(find(len(v_segs) + hi), {"v": set(), "h": set()})["h"].add(seg[0])

    def merge_close(coords, tol=2.5):
        # 二重ストロークの外枠（例: 18.0ptと18.75ptの2本で描かれた実質1本の枠線）は
        # 別々の列線として数えると「内部に列区切りがある本物の表」と誤判定されて
        # しまうため、近接した座標は1本の線として統合してから本数を数える
        merged = []
        for x in sorted(coords):
            if merged and x - merged[-1] <= tol:
                continue
            merged.append(x)
        return merged

    grids = []
    for c in clusters.values():
        v_lines = merge_close(c["v"])
        h_lines = merge_close(c["h"])
        n_v, n_h = len(v_lines), len(h_lines)
        # 単一の矩形（例: 棒グラフの1本）は4辺が互いに交差するためv=2,h=2を満たしてしまい、
        # 「外枠＋行の区切り線のみ（内部の列区切りが無い一覧レイアウト）」もv=2で複数
        # セルの条件を満たしてしまう。後者は各行の中に色付きの棒グラフ等の絵的要素を
        # 含むことが多く、行全体を1セルとして塗り潰すと絵的要素ごと消えてしまう
        # （実データで確認済みの不具合）。縦横それぞれに実際の「内部」区切り線が
        # 2本以上（＝外枠だけでなく本当に複数列・複数行に分かれている）場合のみ、
        # 本物の表（2次元グリッド）とみなす。
        if n_v >= 3 and n_h >= 3:
            grids.append((v_lines, h_lines))

    return grids, graphic_rects


_CJK_CLASS = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯ｦ-ﾟ"
_SPACE_AFTER_CJK = re.compile(r"(?<=[" + _CJK_CLASS + r"])[ \t]+")
_SPACE_BEFORE_CJK = re.compile(r"[ \t]+(?=[" + _CJK_CLASS + r"])")
_TRACKED_RUN = re.compile(
    r"(?:(?<= )|^|(?<=[" + _CJK_CLASS + r"]))"
    r"([0-9A-Za-z](?: [0-9A-Za-z]){1,})"
    r"(?= |$|[" + _CJK_CLASS + r"])"
)
_TRACKED_DIGITS = re.compile(r"(?:(?<= )|^)([0-9](?: [0-9]){1,})(?= |$)")


def _normalize_tracked_spaces(text):
    """字送り（トラッキング）由来の擬似スペースを取り除く。

    PyMuPDFは、文字と文字の間隔が広いと「単語の区切り」とみなして半角スペースを
    自動的に挿入する。字送りを効かせた日本語スライドではこれが1文字ごとに起きるため、
    抽出結果が「2 0 0 4」「9 6 %」のように壊れ、そのまま翻訳AIへ渡っていた
    （日本語→英語の実データで確認）。

    **CJK文字を含むテキストにだけ適用する。** 日本語・中国語・韓国語は単語間に空白を
    置かないため、空白は字送り由来とみなして安全に落とせる。一方、英語原文のPDFでは
    空白そのものが単語の区切りなので、この正規化は一切行わない（従来の動作を維持する）。
    """
    if not text or " " not in text:
        return text

    if _contains_cjk(text):
        # 1文字ずつに割れた英数字の並び（例: "2 0 0 4"）を詰める
        text = _TRACKED_RUN.sub(lambda m: m.group(1).replace(" ", ""), text)
        # CJK文字に隣接する空白を落とす（例: "2004 年から" → "2004年から"）
        text = _SPACE_AFTER_CJK.sub("", text)
        text = _SPACE_BEFORE_CJK.sub("", text)
        return text.strip()

    # CJKを含まない場合、空白そのものが単語の区切りなので原則として手を加えない。
    # ただし数字が1文字ずつ割れたもの（例: 表のセルの "9 6 %"）だけは、英語として
    # ありえない並びなので詰める。日本語資料の数値セルは原文にCJKを含まないため、
    # ここを通さないと字送りで割れたままAIへ渡ってしまう。
    return _TRACKED_DIGITS.sub(lambda m: m.group(1).replace(" ", ""), text).strip()


def _join_spans(records):
    """スパンの文字列を、元の字送りを見ながら連結する。

    v08までは常に半角スペースで連結していた。しかし字送り（トラッキング）を効かせた
    日本語スライドでは、PyMuPDFがほぼ1文字ずつ別スパンとして返すことがあり、その
    結果「2 0 0 4 年」「S E C O M」のように、翻訳AIへ渡す原文が壊れていた
    （日本語→英語の実データで確認）。

    ここでは直前のスパンとの水平方向の隙間を見て、フォントサイズに対して十分離れて
    いる場合だけスペースを入れる。日本語のように単語間に空白を置かない言語でも、
    英語のように置く言語でも、元の見た目どおりの区切りが再現される。
    """
    usable = [r for r in records if r["text"].strip()]
    if not usable:
        return ""

    # 同じ行の中でのスパン間の隙間の「ふつうの大きさ」を求める。字送りを効かせた行では
    # 文字と文字の隙間が一律に広いので、絶対値だけで判定すると全ての隙間が空白に化ける
    # （実データでは「2004」が「2 0 0 4」、「SECOM」が「S E C O M」になっていた）。
    # 本物の単語区切りは、その行の標準的な隙間より目立って広い、という相対判定にする。
    gaps = []
    for prev, rec in zip(usable, usable[1:]):
        if abs(rec["bbox"].y0 - prev["bbox"].y0) < 1.0:
            gaps.append(rec["bbox"].x0 - prev["bbox"].x1)
    typical = sorted(gaps)[len(gaps) // 2] if gaps else 0.0

    parts = []
    prev = None
    for rec in usable:
        text = rec["text"].strip()
        if prev is not None:
            size = max(rec.get("size", 11) or 11, 1.0)
            if abs(rec["bbox"].y0 - prev["bbox"].y0) >= 1.0:
                # 行が変わるとき: 日本語同士なら詰める、英単語同士なら空白を入れる
                need_space = not (_contains_cjk(parts[-1][-1:]) or _contains_cjk(text[:1]))
            else:
                gap = rec["bbox"].x0 - prev["bbox"].x1
                need_space = (gap > max(typical, 0.0) + size * 0.28
                              and gap > size * 0.18)
            if need_space:
                parts.append(" ")
        parts.append(text)
        prev = rec
    return _normalize_tracked_spaces("".join(parts))


def _guess_free_alignment(bbox, box_rect, page_rect):
    """自由配置テキスト（表セル以外）の元の寄せを推定する。

    v08までは表セル以外を一律 TEXT_ALIGN_LEFT で書き戻していた。ところがv08で
    矩形を右方向へ拡張するようになったため、中央寄せのタイトルが「拡張後の広い矩形の
    左端」に置かれ、元より大きく左へずれて見える不具合が起きていた（日本語→英語の
    実データでは、自由配置142件のうち48件がページ中央に配置された要素だった）。

    元のテキスト矩形がページの左右余白に対してほぼ対称なら中央寄せ、右端に寄って
    いれば右寄せとみなす。判定できない場合は従来どおり左寄せ。
    """
    left = bbox.x0 - page_rect.x0
    right = page_rect.x1 - bbox.x1
    width = max(page_rect.width, 1.0)

    if left > width * 0.06 and abs(left - right) <= max(10.0, width * 0.035):
        return fitz.TEXT_ALIGN_CENTER
    if right <= width * 0.04 and left > width * 0.5:
        return fitz.TEXT_ALIGN_RIGHT
    return fitz.TEXT_ALIGN_LEFT


def _merge_paragraph_groups(groups):
    """1行ずつ別ブロックになっている同一段落を、1つの翻訳単位へまとめる。

    PyMuPDFは、スライド系PDFでは段落の各行をそれぞれ別のブロックとして返すことが
    ある（日本語→英語の実データで確認: 3行の本文が block1/block2/block3 に分かれて
    いた）。これには2つの実害がある。

      1. **文脈が切れる**: 「当社では2004年から、大規模災害発生時に従業員・家族の
         安否と事業所被災」という文の途中までが1つの翻訳単位として送られ、
         文として成立しないまま訳される。
      2. **フォントサイズが行ごとにバラつく**: 各行が独立に「収まるまで縮小」される
         ため、同じ段落なのに 12.5pt / 13.0pt / 14.0pt と不揃いになる。

    そこで、フォントサイズ・文字色が同じで、左端がそろっていて、行間が妥当な範囲に
    ある連続した行同士を1つの段落として結合する。表セルは罫線という明確な境界が
    あるため対象外（この関数は自由配置テキストにのみ適用する）。
    """
    if not groups:
        return groups

    def bbox_of(recs):
        r = fitz.Rect()
        for rec in recs:
            r |= rec["bbox"]
        return r

    ordered = sorted(groups, key=lambda g: (round(bbox_of(g).y0, 1), bbox_of(g).x0))
    merged = []
    for recs in ordered:
        if merged:
            prev = merged[-1]
            pb, cb = bbox_of(prev), bbox_of(recs)
            psize = prev[0].get("size", 11) or 11
            csize = recs[0].get("size", 11) or 11
            gap = cb.y0 - pb.y1
            # 重なり幅が狭い方の6割以上あれば「同じ段落の次の行」とみなす
            overlap = min(pb.x1, cb.x1) - max(pb.x0, cb.x0)
            narrow = min(pb.width, cb.width)
            if (abs(psize - csize) <= 0.6
                    and prev[0].get("color") == recs[0].get("color")
                    and abs(pb.x0 - cb.x0) <= max(4.0, psize * 0.6)
                    and overlap >= narrow * 0.6
                    and -psize * 0.3 <= gap <= psize * 0.9):
                merged[-1] = prev + recs
                continue
        merged.append(list(recs))
    return merged


def _guess_alignment(bbox, cell_rect):
    """セル境界とテキストの間隔から、元の寄せ（左/中央/右）を推定する"""
    left_gap = bbox.x0 - cell_rect.x0
    right_gap = cell_rect.x1 - bbox.x1

    if left_gap <= 1.5:
        return fitz.TEXT_ALIGN_LEFT
    if right_gap <= 1.5:
        return fitz.TEXT_ALIGN_RIGHT
    if abs(left_gap - right_gap) <= max(3.0, 0.15 * cell_rect.width):
        return fitz.TEXT_ALIGN_CENTER
    return fitz.TEXT_ALIGN_LEFT


def parse_page_spec(spec_str, total_pages):
    """ページ指定文字列（例: "1-3,5,7-9"、1始まり）を0始まりのページ番号集合に変換する。
    空文字列・空白のみの場合は None（全ページ対象）を返す。不正な指定はValueErrorを送出する。
    """
    spec_str = (spec_str or "").strip()
    if not spec_str:
        return None

    pages = set()
    for token in spec_str.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
                raise ValueError(f"ページ指定の形式が正しくありません: '{token}'")
            start, end = int(parts[0].strip()), int(parts[1].strip())
            if start > end:
                raise ValueError(f"ページ範囲が逆になっています: '{token}'")
            pages.update(range(start, end + 1))
        else:
            if not token.isdigit():
                raise ValueError(f"ページ指定の形式が正しくありません: '{token}'")
            pages.add(int(token))

    if not pages:
        raise ValueError("ページが1つも指定されていません。")

    for p in pages:
        if p < 1 or p > total_pages:
            raise ValueError(f"ページ番号 {p} はこのPDF（全{total_pages}ページ）の範囲外です。")

    return {p - 1 for p in pages}  # 0始まりのページインデックスに変換


def _expand_box_safely(page_rect, bbox, obstacles, align=None,
                       width_factor=1.6, height_factor=2.2, margin=3.0):
    """自由配置テキストの矩形を、他の要素に重ならない範囲で安全に拡張する。

    v20260821_02での修正（中央揃えの要素が右へずれる不具合への対策）:
      v20260821_01では、寄せの種類にかかわらず常に**右方向**へ拡張していた。ところが
      中央寄せの文字は「拡張後の矩形の中央」に置かれるため、右へ広げた分の半分だけ
      右へずれてしまっていた（実データの最終ページのURLで、ページ中央390.0ptに対して
      出力は489.3pt＝約99pt右へずれていた）。
      そこで、中央寄せの場合は元の矩形の中心を保ったまま**左右対称に**拡張し、右寄せの
      場合は右端を固定して**左方向へ**拡張するようにした。左寄せは従来どおり右方向。

    元の英語テキストぴったりの矩形のままだと、翻訳文（特に日本語）が同じフォントサイズ
    では収まらず、フォントサイズが不揃いに縮小されてしまう（実データで確認済み: 200
    ブロック中195ブロックで縮小、1行しか高さの無い見出しでは最大20pt近く縮小される
    ケースもあった）。これを緩和するため、翻訳文を元のフォントサイズのまま挿入できる
    可能性を広げるべく、矩形を拡張してから挿入を試みる（表セルは罫線という明確な境界が
    あるため対象外。自由配置テキストのみに適用する）。
    """
    min_x0, max_x1, max_y1 = _free_space_limits(page_rect, bbox, obstacles, margin)
    expanded_y1 = min(bbox.y0 + bbox.height * height_factor, max(max_y1, bbox.y1))
    expanded_y1 = max(expanded_y1, bbox.y1)
    room = bbox.width * width_factor

    if align == fitz.TEXT_ALIGN_CENTER:
        # 中心を動かさずに左右対称へ広げる（広げた分だけ中央がずれるのを防ぐ）
        center = (bbox.x0 + bbox.x1) / 2
        half = min(room / 2, center - min_x0, max_x1 - center)
        half = max(half, bbox.width / 2)
        x0, x1 = center - half, center + half
    elif align == fitz.TEXT_ALIGN_RIGHT:
        # 右端を固定して左へ広げる
        x1 = bbox.x1
        x0 = min(bbox.x0, max(min_x0, bbox.x1 - room))
    else:
        x0 = bbox.x0
        x1 = max(min(bbox.x0 + room, max_x1), bbox.x1)

    return fitz.Rect(x0, bbox.y0, x1, expanded_y1)


def _free_space_limits(page_rect, bbox, obstacles, margin=3.0):
    """bboxの周囲で、他の要素にぶつからずに広げられる限界を返す。

    戻り値: (左へ広げられる限界x, 右へ広げられる限界x, 下へ広げられる限界y)
    """
    max_x1 = page_rect.x1 - margin
    min_x0 = page_rect.x0 + margin
    max_y1 = page_rect.y1 - margin
    for ob in obstacles:
        # 縦方向に重なりがあり、bboxより右にある障害物 → 右方向の拡張上限にする
        if ob.y1 > bbox.y0 and ob.y0 < bbox.y1 and ob.x0 >= bbox.x1 - 0.5:
            max_x1 = min(max_x1, ob.x0 - margin)
        # 縦方向に重なりがあり、bboxより左にある障害物 → 左方向の拡張下限にする
        if ob.y1 > bbox.y0 and ob.y0 < bbox.y1 and ob.x1 <= bbox.x0 + 0.5:
            min_x0 = max(min_x0, ob.x1 + margin)
        # 横方向に重なりがあり、bboxより下にある障害物 → 下方向の拡張上限にする
        if ob.x1 > bbox.x0 and ob.x0 < bbox.x1 and ob.y0 >= bbox.y1 - 0.5:
            max_y1 = min(max_y1, ob.y0 - margin)

    return min(min_x0, bbox.x0), max(max_x1, bbox.x1), max(max_y1, bbox.y1)


def _clip_expansion_to_background(sampler, bbox, expanded, fill, align=None, step=4.0):
    """拡張した矩形を、背景色が fill と同じである範囲まで切り詰める。

    v08の矩形拡張は「他のテキスト・表セル・図形と重ならないか」だけを見ていた。
    しかしページ全面を覆う装飾（ページ全体の背景矩形やページの縁取り）は、面積が
    大きすぎるため図形一覧から意図的に除外されており、障害物として扱われない。
    その結果、矩形がページの縁取りの上まで伸び、そこを背景色で塗り潰して縁取りを
    破壊する不具合が実データで発生していた（日本語→英語の資料で確認）。

    ここでは実際にページを見て、拡張先の背景色が元の背景色と変わる手前で止める。
    これにより「隣の色帯や縁取りにはみ出して塗り潰す」ことが構造的に起きなくなる。
    """
    if sampler is None:
        return expanded

    def uniform(x, y):
        px = sampler.at(x, y)
        return px is None or _colors_close(tuple(c / 255 for c in px), fill)

    ys = [bbox.y0 + bbox.height * f for f in (0.25, 0.5, 0.75)]

    x1 = expanded.x1
    if x1 > bbox.x1 + step:
        while x1 > bbox.x1 and not all(uniform(x1 - 1, y) for y in ys):
            x1 -= step
        x1 = max(x1, bbox.x1)

    # 中央寄せ・右寄せでは左方向にも拡張するため、左端も同じように切り詰める
    x0 = expanded.x0
    if x0 < bbox.x0 - step:
        while x0 < bbox.x0 and not all(uniform(x0 + 1, y) for y in ys):
            x0 += step
        x0 = min(x0, bbox.x0)

    y1 = expanded.y1
    if y1 > bbox.y1 + step:
        xs = [bbox.x0 + bbox.width * f for f in (0.25, 0.5, 0.75)]
        while y1 > bbox.y1 and not all(uniform(x, y1 - 1) for x in xs):
            y1 -= step
        y1 = max(y1, bbox.y1)

    # 中央寄せは左右対称でなければ意味がないので、狭い側に合わせ直す
    if align == fitz.TEXT_ALIGN_CENTER:
        center = (bbox.x0 + bbox.x1) / 2
        half = max(min(center - x0, x1 - center), bbox.width / 2)
        x0, x1 = center - half, center + half

    return fitz.Rect(x0, expanded.y0, x1, y1)


def extract_translatable_blocks(doc, protect_graphics=False, target_pages=None, logger=None):
    """PDF全ページからテキストブロック（≒段落）単位で翻訳対象を抽出する。

    - 罫線で四方を囲まれたテキスト（表セル）は、罫線から検出した実際のセル矩形と
      元の寄せ（左/中央/右）を box_rect / align として持たせる（表罫線には一切触れない）。
    - 罫線グリッドとして認識できないのに図形・画像に重なっているテキスト（チャートの
      ラベル等）は、protect_graphics=True の場合はレイアウト崩壊を避けるため翻訳対象から
      除外し、原文のまま保持する。
    - target_pages が指定されている場合（0始まりのページインデックス集合）、それ以外の
      ページは完全にスキップする（＝一切のテキスト抽出・墨消しを行わないため、対象外
      ページのレイアウトは100%元のまま保持される）。Noneの場合は全ページが対象。
    """
    blocks_info = []
    protected_count = 0
    cell_count = 0
    page_guard_rects = {}

    for page_index in range(len(doc)):
        if target_pages is not None and page_index not in target_pages:
            continue
        page = doc[page_index]
        page_dict = page.get_text("dict")

        image_rects = [fitz.Rect(b["bbox"]) for b in page_dict.get("blocks", []) if b.get("type") == 1]
        grids, graphic_rects = _analyze_page_graphics(page, logger)
        guard_rects = image_rects + graphic_rects
        page_guard_rects[page_index] = guard_rects

        # 罫線グリッドから実際のセル矩形を構築する。グリッド（＝表）ごとに独立して
        # 隣接する列・行の間の領域のみを1セルとするため、無関係な図形（グラフ等）の
        # 座標と混ざってセルがズレることがなく、PyMuPDFの「ブロック」単位のように
        # セルを跨いで文字が混ざることもない
        # 1セルあたりの最大面積（ページ面積比）。実際の表セルはページの一部分に過ぎない
        # ため、これを大きく超えるセルは「表」ではなく誤検出（背景矩形の辺同士がたまたま
        # 交差した等）である可能性が高く、安全のため採用しない（多重の安全策の1つ）。
        page_area = max(page.rect.width * page.rect.height, 1.0)
        max_cell_area = page_area * 0.3

        cell_rects = []
        for v_lines, h_lines in grids:
            for i in range(len(v_lines) - 1):
                for j in range(len(h_lines) - 1):
                    c = fitz.Rect(v_lines[i], h_lines[j], v_lines[i + 1], h_lines[j + 1])
                    if c.width >= 4 and c.height >= 4 and (c.width * c.height) <= max_cell_area:
                        cell_rects.append(c)

        # ページ内の全スパン（フォント・色を持つ最小単位）を収集
        span_records = []
        for b_idx, block in enumerate(page_dict.get("blocks", [])):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if not text.strip():
                        continue
                    span_records.append({
                        "block_idx": b_idx,
                        "bbox": fitz.Rect(span["bbox"]),
                        "text": text,
                        "size": span.get("size", 11),
                        "color": span.get("color", 0),
                        # 太字かどうか（PyMuPDFのflagsのbit4、またはフォント名で判定）。
                        # v08までは捨てていたため、書き戻すと太字が失われていた。
                        "bold": bool(span.get("flags", 0) & 16)
                                or "bold" in str(span.get("font", "")).lower(),
                    })

        assigned_ids = set()

        # 1) セル矩形の内側にあるスパンをセル単位でグループ化（表罫線には一切触れない）
        for cell in cell_rects:
            members = []
            for rec in span_records:
                if id(rec) in assigned_ids:
                    continue
                bbox = rec["bbox"]
                center = fitz.Point((bbox.x0 + bbox.x1) / 2, (bbox.y0 + bbox.y1) / 2)
                if cell.contains(center):
                    members.append(rec)

            if not members:
                continue
            for m in members:
                assigned_ids.add(id(m))

            members.sort(key=lambda r: (round(r["bbox"].y0, 1), r["bbox"].x0))
            full_text = _join_spans(members)
            if not is_translatable(full_text):
                continue

            member_bbox = fitz.Rect()
            for m in members:
                member_bbox |= m["bbox"]

            cell_count += 1
            inset = 1.2
            # 結合セル（複数の列にまたがるセル）への対応。
            # セルへの割り当ては「文字の中心がどのセルに入るか」で行うため、3列に
            # またがる行のテキストは真ん中の1マスだけに割り当てられる。そのマスの幅で
            # 折り返すと、元は1行だった文字が入りきらずに極端に縮小されたり、マスから
            # はみ出したりする（実データの「余震判定解除（…）」の行で確認）。
            # 文字が元々そのマスの外まで伸びている場合は、実際に文字があった範囲まで
            # セルを広げて、元の見た目どおりの幅で扱う。
            # ただし、はみ出しがわずかな場合（丸め誤差や括弧の食い込み程度）は本当の
            # 結合セルではないので広げない。広げすぎると隣の列へ文字が流れ込む。
            effective = fitz.Rect(cell)
            slack = cell.width * 0.15
            if member_bbox.x0 < cell.x0 - slack or member_bbox.x1 > cell.x1 + slack:
                effective.x0 = min(cell.x0, member_bbox.x0 - inset)
                effective.x1 = max(cell.x1, member_bbox.x1 + inset)
            box_rect = fitz.Rect(
                effective.x0 + inset, effective.y0 + inset,
                effective.x1 - inset, effective.y1 - inset,
            )
            blocks_info.append({
                "page_index": page_index,
                "bbox": member_bbox,
                "box_rect": box_rect,
                "text": full_text,
                "font_size": members[0]["size"] or 11,
                "color": members[0]["color"],
                "bold": members[0].get("bold", False),
                "align": _guess_alignment(member_bbox, effective),
                "grow_limit_y": box_rect.y1,   # 表セルは罫線が境界なので広げない
                "is_cell": True,
            })

        # 2) セルに割り当てられなかったスパンは、元のブロック単位（自由配置の段落）として処理。
        # ただし、PyMuPDFの「ブロック」は、間に大きな空白（＝実際にはチャートの棒グラフや
        # 遠く離れた別の列の値等、無関係な要素が挟まっている）があっても1つのブロックとして
        # まとめてしまうことがある（実データで確認済み。当初は「同一行（Y座標がほぼ一致）
        # かつX方向の隙間が大きい」場合のみ分割していたが、文章＋カテゴリ名＋パーセント値が
        # 微妙に異なるY座標で配置されるレイアウトでは検出できず、依然として行全体を覆う
        # 巨大な矩形が生成されていた）。そのため、Y座標の一致は問わず、ブロック内の全スパンを
        # X座標の区間（の和集合）として捉え、区間同士の隙間が一定以上（GAP_SPLIT_THRESHOLD）
        # 離れている場合は、別々の翻訳単位として分割する。
        GAP_SPLIT_THRESHOLD = 30.0
        remaining_by_block = {}
        for rec in span_records:
            if id(rec) in assigned_ids:
                continue
            remaining_by_block.setdefault(rec["block_idx"], []).append(rec)

        grouped_records = []
        for recs in remaining_by_block.values():
            recs_by_x = sorted(recs, key=lambda r: r["bbox"].x0)
            current = [recs_by_x[0]]
            cur_x1 = recs_by_x[0]["bbox"].x1
            for rec in recs_by_x[1:]:
                if rec["bbox"].x0 - cur_x1 > GAP_SPLIT_THRESHOLD:
                    grouped_records.append(current)
                    current = [rec]
                    cur_x1 = rec["bbox"].x1
                else:
                    current.append(rec)
                    cur_x1 = max(cur_x1, rec["bbox"].x1)
            grouped_records.append(current)

        # 各グループ内は元の読み順（上→下・左→右）に並べ直す
        for recs in grouped_records:
            recs.sort(key=lambda r: (round(r["bbox"].y0, 1), r["bbox"].x0))

        # 1行ずつ別ブロックになっている同一段落をまとめる（文脈の維持とフォント
        # サイズの不揃い解消のため）。詳細は _merge_paragraph_groups を参照。
        grouped_records = _merge_paragraph_groups(grouped_records)
        for recs in grouped_records:
            recs.sort(key=lambda r: (round(r["bbox"].y0, 1), r["bbox"].x0))

        for recs in grouped_records:
            full_text = _join_spans(recs)
            if not is_translatable(full_text):
                continue

            bbox = fitz.Rect()
            for r in recs:
                bbox |= r["bbox"]

            if protect_graphics and any(bbox.intersects(r) for r in guard_rects):
                # 罫線グリッドとして認識できない図形・画像に重なるテキスト（チャートの
                # ラベル等）はレイアウト崩壊を避けるため翻訳せず原文のまま保護する
                protected_count += 1
                continue

            blocks_info.append({
                "page_index": page_index,
                "bbox": bbox,
                "box_rect": bbox,
                "text": full_text,
                "font_size": recs[0]["size"] or 11,
                "color": recs[0]["color"],
                "bold": recs[0].get("bold", False),
                "align": _guess_free_alignment(bbox, bbox, page.rect),
                "is_cell": False,
            })

    # 自由配置テキスト（表セル以外）は、周囲の他のテキスト・表セル・図に重ならない範囲で
    # box_rect を右方向・下方向に拡張する。これにより、翻訳文を元のフォントサイズの
    # まま挿入できる可能性が広がり、フォントサイズの不揃いな縮小を抑えられる。
    blocks_by_page = {}
    for info in blocks_info:
        blocks_by_page.setdefault(info["page_index"], []).append(info)

    for page_index, infos in blocks_by_page.items():
        page = doc[page_index]
        page_rect = page.rect
        # 墨消しより前の（＝原文が載ったままの）ページを1回だけラスタライズして使う
        sampler = _PageSampler(page)
        all_bboxes = [i["bbox"] for i in infos] + page_guard_rects.get(page_index, [])
        for info in infos:
            ci = info["color"]
            text_color = (((ci >> 16) & 255) / 255, ((ci >> 8) & 255) / 255, (ci & 255) / 255)
            # 背景色は「拡張前の元の矩形」の周囲から採取する。拡張後の矩形で採取すると、
            # ページの縁取りなど無関係な領域の色を背景と誤認する（v08で実際に発生）。
            info["fill"] = sample_background_color(
                page, info["bbox"] if not info["is_cell"] else info["box_rect"],
                inside=info["is_cell"], logger=logger,
                text_color=text_color, sampler=sampler,
            )
            if info["is_cell"]:
                # 表セルは罫線が境界。塗る範囲＝流し込む範囲で、広げる余地は無い。
                info["fill_rect"] = info["box_rect"]
                info["max_rect"] = info["box_rect"]
                continue

            others = [b for b in all_bboxes if b is not info["bbox"]]
            # 墨消しで塗る範囲は「元の文字があった場所」だけに限る。流し込み先を広げても
            # 塗る面積は増えないので、背景色の推定がわずかにずれても被害が広がらない。
            info["fill_rect"] = fitz.Rect(
                max(info["bbox"].x0 - 1.0, page_rect.x0),
                max(info["bbox"].y0 - 1.0, page_rect.y0),
                min(info["bbox"].x1 + 1.0, page_rect.x1),
                min(info["bbox"].y1 + 1.0, page_rect.y1),
            )

            # 寄せの種類に応じて拡張方向を変える（中央寄せは左右対称、右寄せは左方向）。
            # 常に右へ広げると、中央寄せの文字が広げた分の半分だけ右へずれる。
            expanded = _expand_box_safely(page_rect, info["bbox"], others, align=info["align"])
            # 拡張先の背景色が変わる手前で止める（縁取りや隣の色帯を塗り潰さないため）
            info["box_rect"] = _clip_expansion_to_background(
                sampler, info["bbox"], expanded, info["fill"], align=info["align"]
            )

            # 元のフォントサイズのまま折り返して収めるために「最大どこまで使ってよいか」。
            # v20260821_02までは幅を元の1.6倍までに制限していたが、実データで測ると
            # 129ブロックすべてに8pt以上の横の余地が残っており、使える幅の中央値954ptに
            # 対して実際に使っていたのは364pt（38%）だけだった。そのぶん行数が増えて
            # 高さが足りなくなり、フォントが4ptまで縮小されていた（1,305文字）。
            # ここでは倍率の上限を外し、障害物と背景色の変わり目だけで決める。
            wide = _expand_box_safely(page_rect, info["bbox"], others, align=info["align"],
                                      width_factor=_MAX_WIDTH_FACTOR,
                                      height_factor=_MAX_HEIGHT_FACTOR)
            info["max_rect"] = _clip_expansion_to_background(
                sampler, info["bbox"], wide, info["fill"], align=info["align"]
            )

    if logger:
        logger.info(
            f"翻訳対象ブロック数: {len(blocks_info)}（うち表セル: {cell_count}） / "
            f"図形保護によるスキップ: {protected_count}"
        )
    return blocks_info


def lang_to_fontname(target_language):
    """翻訳先言語に応じたPyMuPDF内蔵CJKフォント名を返す"""
    if "Japanese" in target_language or "日本" in target_language:
        return "japan"
    if "Chinese" in target_language or "中国" in target_language:
        return "china-s"
    if "Korean" in target_language or "韓国" in target_language:
        return "korea"
    return "helv"


def _fits_in_latin1(text):
    """helv（Helvetica）で表現できる文字だけで構成されているか"""
    try:
        (text or "").encode("cp1252")
        return True
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


# 翻訳文を挿入するときのフォントサイズの下限。
#   - _MIN_FONT_RATIO: 元のフォントサイズに対する下限の比率
#   - _MIN_FONT_SIZE : 絶対的な下限（pt）
# v20260821_01までは一律4ptまで縮めていたため、記号を含む見出しが24pt→11ptまで潰れる
# ことがあった（実データで確認）。縮小はここで止め、それでも収まらない場合は矩形を
# 下方向へ広げて対応する（下記 _draw_text_fitted を参照）。
_MIN_FONT_RATIO = 0.7
_MIN_FONT_SIZE = 6.0

# 「元のフォントサイズを保ったまま折り返して収める」ために使ってよい最大の広さ
# （元のテキスト矩形に対する倍率）。実際の上限は、周囲の他の要素と背景色の変わり目で
# 決まるので、ここは実質的に「倍率では制限しない」という意味の大きな値にしている。
# 通常の行間と、どうしても収まらないときに使う詰めた行間
_NORMAL_LINE_FACTOR = 1.3
_TIGHT_LINE_FACTOR = 1.1

_MAX_WIDTH_FACTOR = 100.0
_MAX_HEIGHT_FACTOR = 100.0

_FONT_CACHE = {}


def _get_font(kind):
    """TextWriter用のフォントオブジェクトを取得する（生成コストが高いのでキャッシュする）。

    kind: "latin" / "latin-bold" / "cjk"

    "cjk" は既定で PyMuPDF 内蔵の "japan" を使う。これは TextWriter 経由で使うと
    Droid Sans Fallback（実体のあるTTF）として扱われるため、
      - 英数字がプロポーショナル幅になる（`insert_textbox(fontname="japan")` の
        Adobe-Japan1 CID参照では英数字まで全角送りになり、行幅が約2.2倍に膨らんでいた）
      - PDFへサブセット埋め込みされる（ビューアの日本語フォント有無に依存しなくなる）
    という2つの利点がある。環境変数 PDF_TRANSLATOR_CJK_FONT にフォントファイルの
    パスを指定すれば、そちらを優先して使う。
    """
    if kind in _FONT_CACHE:
        return _FONT_CACHE[kind]

    if kind == "cjk":
        font = None
        custom = os.environ.get("PDF_TRANSLATOR_CJK_FONT")
        if custom and os.path.isfile(custom):
            try:
                font = fitz.Font(fontfile=custom)
            except Exception:
                font = None
        if font is None:
            font = fitz.Font("japan")
    else:
        font = fitz.Font("hebo" if kind == "latin-bold" else "helv")

    _FONT_CACHE[kind] = font
    return font


def _split_font_runs(text, latin_font, cjk_font):
    """文字ごとに『その文字を描けるフォント』を割り当て、連続する同じフォントをまとめる。

    v20260821_01では、Latin-1に収まらない文字が1つでもあると**行全体**をCJKフォントへ
    切り替えていた。実データでは、CJKフォントで描かれた1,882文字のうち**1,855文字が
    ただの英数字**で、本当に日本語フォントが必要な記号は27文字（■13・①④・②④・※3・
    ◎2・③1）しかなかった。その結果、英字まで全角送りになって行幅が約2.2倍に膨らみ、
    見出しが24pt→11ptまで縮小されていた。ここでフォントを文字単位に割り当てることで、
    英数字は従来どおりの幅で描かれるようになる。
    """
    runs = []
    for ch in text:
        font = latin_font if _fits_in_latin1(ch) else cjk_font
        if runs and runs[-1][0] is font:
            runs[-1][1].append(ch)
        else:
            runs.append((font, [ch]))
    return [(font, "".join(chars)) for font, chars in runs]


def _layout_mixed_text(text, width, fontsize, latin_font, cjk_font):
    """フォント混在のテキストを、指定幅で折り返した行のリストにする。

    戻り値: [[(font, 文字列, 幅), ...], ...]

    折り返しの単位は「語」。欧文の語は途中で切らず、CJKを含む語は1文字ずつ切れる
    （日本語は語中でも改行できるため）。v20260821_02まではフォントの切れ目を折り返し
    単位にしていたため、"Shindo 5-kyo" のように欧文の語の途中に欧文フォントで描けない
    文字が入ると、そこで語が分断されて離れた位置に描かれていた（実データで確認）。
    """
    def width_of(runs):
        return sum(f.text_length(t, fontsize) for f, t in runs)

    lines = []
    for paragraph in (text or "").split("\n"):
        # 1) 空白で語に区切り、語の中だけフォントを切り替える
        words = []
        for token in re.findall(r"\s+|\S+", paragraph):
            if not token.strip():
                words.append([(latin_font, token)])
            elif _contains_cjk(token):
                for ch in token:
                    words.append([(latin_font if _fits_in_latin1(ch) else cjk_font, ch)])
            else:
                words.append(_split_font_runs(token, latin_font, cjk_font))

        # 2) 1語だけで枠幅を超える語（長いURL等）は文字単位に割る。
        #    割らないと永久に折り返せず、「収まらない」と判定されてフォントだけが縮む。
        broken = []
        for runs in words:
            if width_of(runs) <= width or len("".join(t for _, t in runs)) <= 1:
                broken.append(runs)
                continue
            chunk = []
            for font, seg in runs:
                for ch in seg:
                    if chunk and width_of(chunk + [(font, ch)]) > width:
                        broken.append(chunk)
                        chunk = [(font, ch)]
                    elif chunk and chunk[-1][0] is font:
                        chunk[-1] = (font, chunk[-1][1] + ch)
                    else:
                        chunk.append((font, ch))
            if chunk:
                broken.append(chunk)
        words = broken

        # 3) 語を順に詰めて折り返す
        current, used = [], 0.0
        for runs in words:
            w = width_of(runs)
            is_space = not "".join(t for _, t in runs).strip()
            if current and not is_space and used + w > width:
                lines.append(current)
                current, used = [], 0.0
            if not current and is_space:
                continue  # 行頭に残った空白は捨てる
            for font, seg in runs:
                current.append((font, seg, font.text_length(seg, fontsize)))
            used += w
        lines.append(current)
    return lines


def _draw_mixed_text(page, rect, text, fontsize, color, align,
                     bold=False, force=False, line_factor=None):
    """フォントを文字単位で切り替えながら矩形へ流し込む。

    収まらない場合は**何も描かずに**負の値を返す（`insert_textbox` と同じ約束にして、
    呼び出し側のフォントサイズ調整ループをそのまま使えるようにするため）。
    force=True のときは収まらなくても描く（文字が消えるよりはみ出す方がましな場面用）。
    """
    line_factor = _NORMAL_LINE_FACTOR if line_factor is None else line_factor
    latin_font = _get_font("latin-bold" if bold else "latin")
    cjk_font = _get_font("cjk")
    lines = _layout_mixed_text(text, rect.width, fontsize, latin_font, cjk_font)

    ascender = max(latin_font.ascender, cjk_font.ascender)
    descender = min(latin_font.descender, cjk_font.descender)
    line_height = fontsize * line_factor
    total_height = (len(lines) - 1) * line_height + fontsize * (ascender - descender)
    if total_height > rect.height and not force:
        return rect.height - total_height

    writer = fitz.TextWriter(page.rect)
    y = rect.y0 + fontsize * ascender
    for line in lines:
        line_width = sum(a[2] for a in line)
        if align == fitz.TEXT_ALIGN_CENTER:
            x = rect.x0 + (rect.width - line_width) / 2
        elif align == fitz.TEXT_ALIGN_RIGHT:
            x = rect.x1 - line_width
        else:
            x = rect.x0
        for font, seg, seg_width in line:
            # 空白もそのまま描く（描かずに送り幅だけ進めると、出力PDFから文字列を
            # コピーしたときに単語が繋がってしまうため）
            if seg:
                writer.append(fitz.Point(x, y), seg, font=font, fontsize=fontsize)
            x += seg_width
        y += line_height

    writer.write_text(page, color=color)
    return rect.height - total_height


def _needs_mixed_fonts(text, base_fontname):
    """文字単位のフォント切り替えが必要か（欧文フォント指定なのに欧文外の文字がある）"""
    return base_fontname == "helv" and not _fits_in_latin1(text)


def _draw_text_fitted(page, rect, text, font_size, fontname, color, align,
                      bold=False, page_rect=None, grow_limit=None, max_rect=None,
                      logger=None, page_index=0):
    """翻訳文を矩形へ収める。収まらなければ、フォント縮小 → 矩形の下方向拡大の順に試す。

    v20260821_02での変更（記号を含む見出しが極端に小さくなる問題への対策）:
      - 縮小の下限を設けた（元サイズの70%、かつ6pt以上）。v20260821_01までは一律4ptまで
        縮めていたため、実データでは24ptの見出しが11ptまで潰れ、5pt未満の文字が
        413文字（前版の66文字から6倍）に増えていた。
      - 下限まで縮めても収まらない場合は、**矩形を下方向へ広げて**対応する。
        `insert_textbox` は収まらないと**何も描かない**仕様のため、単に「はみ出しを許容」
        すると文字が丸ごと消えてしまう。矩形を広げるのが安全な逃がし方になる。
      - それでも収まらない場合に限り、従来どおり4ptまで縮める（文字が消えるのだけは避ける）。
    """
    mixed = _needs_mixed_fonts(text, fontname)

    def draw(target_rect, size, force=False):
        # force=True（最後の手段）では必ず文字単位描画を使う。insert_textbox は収まらないと
        # **何も描かない**仕様のため、そのまま呼ぶと翻訳文が丸ごと失われる（開発中にテストで
        # 検出）。文字単位描画は force=True ではみ出してでも必ず描くので、文字が消えない。
        if mixed or force:
            return _draw_mixed_text(page, target_rect, text, size, color, align,
                                    bold=bold, force=force)
        # insert_textbox は収まらない場合、負値を返して何も描かない（＝試行しても安全）
        return page.insert_textbox(target_rect, text, fontsize=size, fontname=fontname,
                                   color=color, align=align)

    floor = max(_MIN_FONT_SIZE, font_size * _MIN_FONT_RATIO)

    # 1) まず元の枠に、元のフォントサイズのまま入るか
    if draw(rect, font_size) >= 0:
        return font_size

    # 2) 入らなければ、**縮小する前に**使える範囲まで枠を広げて、元のサイズのまま
    #    折り返して収まらないか試す。v20260821_02までは先に縮小していたため、
    #    広げれば元のサイズで入る場合でもフォントが小さくなっていた。
    wide = max_rect if max_rect is not None else rect
    if wide.width > rect.width + 0.5 or wide.height > rect.height + 0.5:
        if draw(wide, font_size) >= 0:
            if logger:
                logger.info(f"ページ{page_index+1}: 元のフォントサイズ({font_size:.1f}pt)を保つため、"
                            f"空いている範囲まで枠を広げて折り返しました。")
            return font_size
        rect = wide  # 以降の試行も広げた枠で行う（行数を稼げるため縮小量が小さくて済む）

    # 3) それでも入らなければ、下限まで少しずつ縮小する
    size = font_size - 0.5
    while size >= floor:
        if draw(rect, size) >= 0:
            return size
        size -= 0.5

    # 4) 下限まで縮めても入らない場合、フォントを小さくする前に**行間を詰めて**
    #    もう一度試す。表のセルのように高さが罫線で決まっている場所では、行間を
    #    1.3倍から1.1倍にするだけで入る行数が約2割増え、そのぶんフォントサイズを
    #    保てる（実データの表セルで、日本語30文字が英語116文字になる例を確認）。
    size = font_size
    while size >= floor:
        if _draw_mixed_text(page, rect, text, size, color, align,
                            bold=bold, line_factor=_TIGHT_LINE_FACTOR) >= 0:
            if logger:
                logger.info(f"ページ{page_index+1}: 行間を詰めて{size:.1f}ptを維持しました。")
            return size
        size -= 0.5

    # 下限まで縮めても収まらない → 「他の要素が無いと分かっている範囲まで」矩形を下へ広げる。
    # 広げる先は extract_translatable_blocks() が障害物と背景色から求めた限界（grow_limit）
    # までに限る。これを無制限にすると、図の中の小さなラベルが下の要素へ重なって出力される
    # （実データで確認したため、v20260821_02 の開発中に上限を入れた）。
    bottom_limit = grow_limit if grow_limit is not None else rect.y1
    if page_rect is not None:
        bottom_limit = min(bottom_limit, page_rect.y1 - 2)
    grown = rect
    while grown.y1 < bottom_limit - 0.5:
        grown = fitz.Rect(grown.x0, grown.y0, grown.x1,
                          min(grown.y1 + max(rect.height * 0.6, 8.0), bottom_limit))
        if draw(grown, floor) >= 0:
            if logger:
                logger.info(f"ページ{page_index+1}: 翻訳文が元の枠に収まらないため、"
                            f"空いている範囲まで枠を広げて{floor:.1f}ptで配置しました。")
            return floor

    # 最後の手段: 文字が消えるのだけは避けるため、従来どおり縮小する
    size = floor
    while size >= 4:
        if draw(grown, size) >= 0:
            if logger:
                logger.warning(f"ページ{page_index+1}: 翻訳文が長く、{size:.1f}ptまで"
                               f"縮小しました（下限{floor:.1f}ptを下回っています）。")
            return size
        size -= 0.5

    draw(grown, 4, force=True)
    if logger:
        logger.warning(f"ページ{page_index+1}: 翻訳文が枠に収まらず、はみ出して配置しました。")
    return 4


def pick_font_for_text(text, base_fontname, bold=False):
    """挿入する文字列を実際に表現できるフォント名を選ぶ。

    v20260821_01での追加（日本語→英語の実データで、丸数字「③」や「※」が
    すべて "?" に化けていた問題への対策）:
      - 翻訳先が英語のとき base_fontname は "helv"（Helvetica）になるが、helvが
        持つ字形は Latin-1 の範囲しかない。翻訳文にはタイトルの通し番号「①②③」や
        注記の「※」「～」「（）」といった、原文から引き継がれた記号がそのまま
        残ることがあり、これらは helv では描けず "?" になっていた（実データで12箇所）。
      - そこで、挿入する文字列が Latin-1 に収まらない場合は、英数字も日本語記号も
        両方描ける内蔵CJKフォント "japan" へ自動的に切り替える。英文の見た目は
        helv のままにしたいので、収まる場合は helv を使い続ける。
      - あわせて、原文が太字だった場合は Helvetica-Bold（"hebo"）を使う。
        v08までは太字情報を捨てて一律レギュラーで書き戻していた。
    """
    if base_fontname == "helv":
        if not _fits_in_latin1(text):
            return "japan"
        return "hebo" if bold else "helv"
    return base_fontname


LANGUAGE_SUFFIX_MAP = {
    "Japanese": "ja",
    "English": "en",
    "Chinese Simplified": "zh",
    "Korean": "ko",
}


def lang_to_suffix(target_language):
    """出力ファイル名の末尾に付ける2文字言語コードを返す（例: Japanese -> ja）"""
    if target_language in LANGUAGE_SUFFIX_MAP:
        return LANGUAGE_SUFFIX_MAP[target_language]
    return target_language.strip()[:2].lower()


class _PageSampler:
    """ページを1回だけラスタライズして、任意座標の色を高速に引けるようにする。

    v08まではサンプリングのたびに page.get_pixmap(clip=1px) を呼んでいた。1点あたり
    ページのレンダリングが走るため、サンプル点を増やすと現実的な速度で動かなくなる。
    v20260821_01では背景色の判定に多くの点が必要になったため、ページ全体を72dpi
    （1pt = 1px）で1回だけラスタライズし、そこから引く方式に変えた。
    """

    def __init__(self, page):
        self.origin = (page.rect.x0, page.rect.y0)
        try:
            self.pix = page.get_pixmap(dpi=72)
        except Exception:
            self.pix = None

    def at(self, x, y):
        """PDF座標(x, y)の色を (r, g, b) 0〜255で返す（範囲外・失敗時はNone）"""
        if self.pix is None:
            return None
        px = int(x - self.origin[0])
        py = int(y - self.origin[1])
        if px < 0 or py < 0 or px >= self.pix.width or py >= self.pix.height:
            return None
        try:
            p = self.pix.pixel(px, py)
            return (p[0], p[1], p[2])
        except Exception:
            return None


def _sample_pixel(page, x, y):
    """指定座標近傍の1pxを取得する（範囲外・失敗時はNone）。

    互換のために残している薄いラッパー。ページ内で何度も引く場合は _PageSampler を使う。
    """
    return _PageSampler(page).at(x, y)


def _colors_close(a, b, tol=0.09):
    """2色（いずれも0〜1のRGB）が実質同じ色とみなせるか"""
    return sum(abs(x - y) for x, y in zip(a, b)) <= tol * 3


def sample_background_color(page, rect, inside=False, logger=None,
                            text_color=None, sampler=None):
    """背景色を複数点サンプリングし、多数決で近似取得する（失敗時は白）。

    v20260821_01での変更（日本語→英語の実データで「翻訳文が背景と同じ色で塗られ、
    完全に読めなくなる」不具合を確認したことへの対策）:
      - **原因1**: サンプリングを「拡張後の矩形（box_rect）」の外側で行っていた。
        v08で導入した矩形拡張はページ端近くまで伸びることがあり、その外側は
        ページの装飾枠（今回の実データでは濃紺の縁取り）だった。つまり本文とは
        無関係な色を「背景」として拾っていた。→ サンプリングは必ず**元のテキスト
        矩形（bbox）の周囲**で行うようにした。
      - **原因2**: 4点中2点が白・2点が紺という同数の場合、`max(set(...), key=count)`
        は集合の反復順に依存して勝者が決まるため、実質「運任せ」で紺が選ばれる
        ことがあった（実データでは全252ブロック中107ブロックがこの同数状態）。
        → サンプル点を12点に増やし、同数のときは**先に出現した色**を選ぶ決定的な
        規則にした。
      - **原因3**: サンプル点がたまたま隣接する文字の上に落ちると、その文字色を
        背景と誤認する。→ 文字色とほぼ同じ色のサンプルは「文字の上を拾った」
        とみなして除外する（全部除外されてしまう場合のみ、従来どおり全サンプルで
        多数決する）。これにより「文字色と同じ色で塗り潰して文字が消える」という
        最悪のケースが構造的に起きなくなる。
    """
    sampler = sampler or _PageSampler(page)

    if inside:
        # 表セル向け: 罫線の外に出るとセル外の背景を拾ってしまうため、セルの内側だけを
        # サンプリングする。
        # v20260821_03での修正: v20260821_02までは左右2点しか採っていなかった。セルの
        # 左右の内側は文字の始まりと終わりに近く、2点とも文字の上に落ちることがある。
        # その場合は文字色を除外する仕組みが働かず（全部除外すると候補が無くなるため）、
        # **文字色そのものが背景色として採用されて**セルが濃い色で塗り潰されていた
        # （実データの3列結合セルの行で、灰色の帯になって文字が読めなくなっていた）。
        # 文字は上下に余白を持つので、セル内側の上端・下端からも採る。
        inset = 1.5
        xs = [rect.x0 + rect.width * f for f in (0.2, 0.5, 0.8)]
        mid_y = rect.y0 + max(min(rect.height / 2, 4), 0.5)
        candidates = (
            [(x, min(rect.y0 + inset, rect.y1)) for x in xs]
            + [(x, max(rect.y1 - inset, rect.y0)) for x in xs]
            + [(min(rect.x0 + inset, rect.x1), mid_y),
               (max(rect.x1 - inset, rect.x0), mid_y)]
        )
    else:
        # 自由配置のテキスト向け: 矩形のすぐ外側を四辺すべてから広く採取する。
        # 一辺あたり3点にすることで、隣接する文字や図形を1点拾っても多数決で覆せる。
        fx = [rect.x0 + rect.width * f for f in (0.25, 0.5, 0.75)]
        fy = [rect.y0 + rect.height * f for f in (0.25, 0.5, 0.75)]
        candidates = (
            [(rect.x0 - 2, y) for y in fy]
            + [(rect.x1 + 2, y) for y in fy]
            + [(x, rect.y0 - 2) for x in fx]
            + [(x, rect.y1 + 2) for x in fx]
        )

    samples = [p for p in (sampler.at(x, y) for x, y in candidates) if p is not None]
    if not samples:
        if logger: logger.debug("背景色サンプリング失敗: 有効なサンプル点を取得できませんでした")
        return (1, 1, 1)

    pool = samples
    if text_color is not None:
        # 文字色と同じ色のサンプルは「背景ではなく文字の上」を拾ったとみなして除外する
        without_glyphs = [s for s in samples
                          if not _colors_close(tuple(c / 255 for c in s), text_color)]
        if without_glyphs:
            pool = without_glyphs

    # 最頻値。同数のときは先に出現した色を選ぶ（集合の反復順に依存させない）
    best = max(pool, key=lambda c: (pool.count(c), -pool.index(c)))
    return (best[0] / 255, best[1] / 255, best[2] / 255)


def apply_translations_to_pdf(doc, blocks_info, translated_texts, target_language, logger=None):
    """墨消し（redaction、罫線・画像は保護）→ 背景色で塗り潰し
    → 翻訳文を元の寄せ・フォントサイズ自動縮小で再配置"""
    fontname = lang_to_fontname(target_language)

    pages_items = {}
    for info, translated in zip(blocks_info, translated_texts):
        pages_items.setdefault(info["page_index"], []).append((info, translated))

    for page_index, items in pages_items.items():
        page = doc[page_index]

        # 背景色は extract_translatable_blocks() の時点で（＝どのページにも墨消しを
        # 行っていない状態で）採取済みなので、それを使う。未設定の場合だけここで採取する。
        sampler = None
        fills = []
        for info, _ in items:
            fill = info.get("fill")
            if fill is None:
                sampler = sampler or _PageSampler(page)
                ci = info["color"]
                text_color = (((ci >> 16) & 255) / 255, ((ci >> 8) & 255) / 255, (ci & 255) / 255)
                fill = sample_background_color(
                    page, info["bbox"] if not info.get("is_cell") else info["box_rect"],
                    inside=info.get("is_cell", False), logger=logger,
                    text_color=text_color, sampler=sampler,
                )
            fills.append(fill)

        for (info, _translated), fill in zip(items, fills):
            page.add_redact_annot(info.get("fill_rect", info["box_rect"]), fill=fill)

        # images/graphics を保護し、矩形に重なる罫線・画像・チャート図形を一切消さない
        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        except TypeError:
            # 古いPyMuPDFではパラメータ非対応のためデフォルト動作にフォールバック
            page.apply_redactions()

        for (info, translated), _fill in zip(items, fills):
            rect = info["box_rect"]
            color_int = info["color"]
            text_color = (
                ((color_int >> 16) & 255) / 255,
                ((color_int >> 8) & 255) / 255,
                (color_int & 255) / 255,
            )
            align = info.get("align", fitz.TEXT_ALIGN_LEFT)
            bold = info.get("bold", False)
            # 欧文フォント指定なのに欧文外の文字（「③」「※」等）が混じる場合は、
            # 文字単位でフォントを切り替えながら描く（_draw_text_fitted の中で判定する）。
            # それ以外は従来どおり insert_textbox。日本語出力は japan のまま変わらない。
            use_font = fontname if _needs_mixed_fonts(translated, fontname) \
                else pick_font_for_text(translated, fontname, bold=bold)

            _draw_text_fitted(
                page, rect, translated, info["font_size"], use_font,
                text_color, align, bold=bold, page_rect=page.rect,
                grow_limit=info.get("grow_limit_y"), max_rect=info.get("max_rect"),
                logger=logger, page_index=page_index,
            )


def translate_pdf_document_thread(file_path, target_language, progress_window, protect_graphics=False, page_spec=""):
    """バックグラウンドで実行されるメイン処理"""
    logger = get_logger()
    doc = None
    try:
        start_total_time = time.time()
        lang_suffix = lang_to_suffix(target_language)
        output_path = os.path.splitext(file_path)[0] + f"_{lang_suffix}.pdf"

        logger.info(f"=== PDF翻訳開始: {os.path.basename(file_path)} ===")

        # ファイルロックの事前検知（読み込み元）
        try:
            with open(file_path, 'a'): pass
        except PermissionError:
            logger.error(f"[事前検知] 読み込み元ファイルがロックされています: {file_path}")
            progress_window.close()
            messagebox.showerror("ファイルエラー", "対象のPDFファイルが別のアプリで開かれています。\nファイルを閉じてから再度実行してください。")
            return

        # ファイルロックの事前検知（保存先）
        if os.path.exists(output_path):
            try:
                with open(output_path, 'a'): pass
            except PermissionError:
                logger.error(f"[事前検知] 保存先ファイルがロックされています: {output_path}")
                progress_window.close()
                messagebox.showerror("ファイルエラー", "以前に作成した翻訳ファイルが開かれています。\nファイルを閉じてから再度実行してください。")
                return

        doc = fitz.open(file_path)

        try:
            target_pages = parse_page_spec(page_spec, len(doc))
        except ValueError as e:
            doc.close()
            progress_window.close()
            messagebox.showerror("ページ指定エラー", str(e))
            return

        if target_pages is not None:
            logger.info(f"翻訳対象ページ: {sorted(p + 1 for p in target_pages)} / 全{len(doc)}ページ")

        translatable_blocks = extract_translatable_blocks(
            doc, protect_graphics=protect_graphics, target_pages=target_pages, logger=logger
        )

        if not translatable_blocks:
            doc.close()
            progress_window.close()
            messagebox.showinfo("完了", "翻訳対象のテキストが見つかりませんでした。\n（画像のみのスキャンPDFはOCR非対応のため検出できません）")
            return

        texts_only = [b["text"] for b in translatable_blocks]
        total_items = len(texts_only)
        progress_window.update_progress(0, total_items, f"Gemini APIで並列翻訳中... (0/{total_items}項目)")

        # UI更新用のコールバック関数
        def update_ui_callback(processed_count):
            progress_window.update_progress(processed_count, total_items, f"Gemini APIで並列翻訳中... ({processed_count}/{total_items}項目)")

        # ※バックグラウンドスレッドで重い通信処理を実行
        translated_texts = translate_super_fast_parallel(texts_only, target_language, max_workers=3, progress_callback=update_ui_callback, logger=logger)

        progress_window.update_progress(total_items, total_items, "翻訳結果をPDFに適用中...")
        apply_translations_to_pdf(doc, translatable_blocks, translated_texts, target_language, logger)

        progress_window.update_progress(total_items, total_items, "保存中...")

        try:
            doc.save(output_path, garbage=4, deflate=True)
        except PermissionError:
            doc.close()
            progress_window.close()
            messagebox.showerror("保存エラー", "ファイルが他のプログラム（PDF閲覧ソフトなど）で開かれています。\n閉じてから再度実行してください。")
            return
        finally:
            doc.close()
            doc = None

        progress_window.close()
        total_time = time.time() - start_total_time
        logger.info(f"=== 処理完了: 成功 ({total_time:.1f}秒) ===")

        page_info = (
            f"対象ページ: {', '.join(str(p + 1) for p in sorted(target_pages))}\n"
            if target_pages is not None else ""
        )
        messagebox.showinfo("完了",
                          f"レイアウト保持翻訳完了！\n"
                          f"保存先: {output_path}\n"
                          f"{page_info}"
                          f"翻訳項目数: {len(translatable_blocks)}\n"
                          f"処理時間: {total_time:.1f}秒")

    except RuntimeError as e:
        progress_window.close()
        messagebox.showerror("通信エラー強制終了", str(e))

    except Exception as e:
        logger.error(f"予期せぬエラー: {traceback.format_exc()}")
        progress_window.close()
        messagebox.showerror("エラー", f"翻訳処理中にエラーが発生しました:\n{str(e)}")
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def select_file():
    path = filedialog.askopenfilename(
        title="翻訳するPDFファイルを選択してください",
        filetypes=[("PDF files", "*.pdf")]
    )

    if not path:
        return

    # ページ数を表示するために軽くPDFを開いて確認する（失敗しても致命的ではないので無視）
    total_pages = None
    try:
        with fitz.open(path) as probe_doc:
            total_pages = len(probe_doc)
    except Exception:
        pass

    lang_win = tk.Toplevel(root)
    lang_win.title("PDF翻訳設定")
    lang_win.geometry("400x400")
    lang_win.resizable(False, False)
    lang_win.transient(root)
    lang_win.grab_set()

    tk.Label(lang_win, text="翻訳先言語を選択してください", font=("Arial", 12, "bold")).pack(padx=20, pady=20)

    languages = {
        "日本語 (Japanese)": "Japanese",
        "英語 (English)": "English",
        "中国語簡体字 (Chinese)": "Chinese Simplified"
    }

    lang_var = tk.StringVar(lang_win)
    lang_var.set("日本語 (Japanese)")

    lang_menu = tk.OptionMenu(lang_win, lang_var, *languages.keys())
    lang_menu.config(font=("Arial", 10), width=25)
    lang_menu.pack(padx=20, pady=10)

    page_count_text = f"（全{total_pages}ページ）" if total_pages else ""
    tk.Label(
        lang_win, text=f"翻訳するページ{page_count_text}　例: 1-3,5,7-9　空欄で全ページ",
        font=("Arial", 9),
    ).pack(padx=20, pady=(5, 2))
    page_var = tk.StringVar(lang_win, value="")
    page_entry = tk.Entry(lang_win, textvariable=page_var, font=("Arial", 10), width=25, justify="center")
    page_entry.pack(padx=20, pady=(0, 5))

    protect_var = tk.BooleanVar(lang_win, value=False)
    protect_check = tk.Checkbutton(
        lang_win, text="表・グラフに重なるテキストを翻訳しない（安全重視）",
        variable=protect_var, font=("Arial", 9),
    )
    protect_check.pack(padx=20, pady=(5, 0))
    tk.Label(
        lang_win,
        text="※ ONにすると、罫線グリッドとして認識できない図形（チャート等）に\n"
             "　 重なる文字は翻訳せず原文のまま残します（網羅性より安全性を優先）",
        font=("Arial", 8), fg="#666666", justify="left",
    ).pack(padx=20, pady=(0, 5))

    def start_translation():
        selected_language = languages[lang_var.get()]
        protect_graphics = protect_var.get()
        page_spec = page_var.get()

        if total_pages is not None:
            try:
                parse_page_spec(page_spec, total_pages)
            except ValueError as e:
                messagebox.showerror("ページ指定エラー", str(e), parent=lang_win)
                return

        lang_win.destroy()

        # プログレスウィンドウを作成
        progress_window = PdfProgressWindow(root)

        # 画面をフリーズさせないために、別スレッドで翻訳処理を開始！
        thread = threading.Thread(
            target=translate_pdf_document_thread,
            args=(path, selected_language, progress_window, protect_graphics, page_spec)
        )
        thread.daemon = True
        thread.start()

    button_frame = tk.Frame(lang_win)
    button_frame.pack(pady=15)

    tk.Button(button_frame, text="翻訳開始", command=start_translation,
             bg="#0078D4", fg="white", padx=20, pady=8, font=("Arial", 11, "bold")).pack(side=tk.LEFT, padx=10)
    tk.Button(button_frame, text="キャンセル", command=lang_win.destroy,
             padx=20, pady=8, font=("Arial", 11)).pack(side=tk.LEFT, padx=10)


# --- GUI初期設定 ---
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    if not check_dependencies(root):
        sys.exit(1)

    if not init_gemini(root):
        sys.exit(1)

    root.deiconify()
    root.title("PDF Gemini 翻訳ツール")
    root.geometry("500x280")
    root.resizable(False, False)

    main_frame = tk.Frame(root)
    main_frame.pack(expand=True, fill='both', padx=20, pady=20)

    title_label = tk.Label(main_frame, text="PDF Gemini 翻訳ツール", font=("Arial", 16, "bold"))
    title_label.pack(pady=8)

    subtitle_label = tk.Label(main_frame, text="レイアウト保持版 (Gemini API)", font=("Arial", 12), fg="#0078D4")
    subtitle_label.pack(pady=2)

    desc_label = tk.Label(main_frame,
                         text="PDFファイル(.pdf)を選択して翻訳します\n"
                              "文字位置・フォントサイズ・文字色をできる限り保持",
                         font=("Arial", 10))
    desc_label.pack(pady=8)

    select_button = tk.Button(main_frame, text="ファイル選択", command=select_file,
                             font=("Arial", 12), bg="#0078D4", fg="white", padx=20, pady=10)
    select_button.pack(pady=15)

    root.mainloop()
