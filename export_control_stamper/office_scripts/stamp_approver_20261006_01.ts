/**
 * 該非判定証明書への承認者印影の挿入 (Office Scripts)  20261006_01
 *
 * Excel Online の「自動化」タブ → 新しいスクリプト に、このファイル全体を貼り付けて
 * 保存する。Power Automate の「スクリプトの実行」アクションから呼ばれる想定。
 *
 * 手作業の「挿入 → ピクチャ → セルの上に配置 → このデバイス」を再現する。
 * 画像の左上を、アンカーセル(既定 H15)の左上へ合わせる。
 *
 * 守っていること:
 *   - 何も壊さない: 既存の図形(該非判定者の印影など)には触れない。
 *   - 二重押印をしない: 同名の図形、またはアンカーセルに重なる図形があれば中止する。
 *   - テンプレートが変わったら止まる: シート名・15行目の承認者名が違えば中止する。
 *   - 失敗したら元に戻す: 位置の検証に失敗した場合、挿入した図形を削除する。
 *
 * 戻り値は JSON 文字列。status は次のいずれか。
 *   stamped / already_stamped / template_mismatch / position_error /
 *   invalid_input / script_error
 * stamped 以外はフロー側で停止して通知する(添付は差し替えない)。
 *
 * 注意: Office Scripts は import / export を使えない。補助関数はこのファイル内に置く。
 */

interface StampResult {
  status: string;
  reason: string;
  sheet: string;
  anchor: string;
  shapeName: string;
  anchorLeft: number;
  anchorTop: number;
  anchorWidth: number;
  anchorHeight: number;
  left: number;
  top: number;
  width: number;
  height: number;
  shapeCountBefore: number;
  shapeCountAfter: number;
}

// 位置の検証で許す誤差(pt)。Excel の内部丸めを吸収するだけの値。
const POSITION_TOLERANCE_PT = 1;

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function emptyResult(sheetName: string, anchorCell: string, shapeName: string): StampResult {
  return {
    status: "",
    reason: "",
    sheet: sheetName,
    anchor: anchorCell,
    shapeName: shapeName,
    anchorLeft: 0,
    anchorTop: 0,
    anchorWidth: 0,
    anchorHeight: 0,
    left: 0,
    top: 0,
    width: 0,
    height: 0,
    shapeCountBefore: 0,
    shapeCountAfter: 0,
  };
}

function finish(result: StampResult, status: string, reason: string): string {
  result.status = status;
  result.reason = reason;
  return JSON.stringify(result);
}

// "data:image/png;base64,xxxx" 形式で渡されても受け付ける
function stripDataUri(value: string): string {
  if (!value) {
    return "";
  }
  const marker = "base64,";
  const index = value.indexOf(marker);
  const body = index >= 0 ? value.substring(index + marker.length) : value;
  return body.replace(/\s+/g, "");
}

// 空白(半角・全角)を除いて比較する。「越智 泰造」と「越智泰造」を同一視するため。
function normalizeName(value: string): string {
  return String(value).replace(/[\s\u3000]+/g, "");
}

function rowContainsName(sheet: ExcelScript.Worksheet, row: number, name: string): boolean {
  const values = sheet.getRange("A" + row + ":Z" + row).getValues();
  const wanted = normalizeName(name);
  for (let r = 0; r < values.length; r++) {
    for (let c = 0; c < values[r].length; c++) {
      const cell = values[r][c];
      if (cell !== null && cell !== undefined && normalizeName(String(cell)).indexOf(wanted) >= 0) {
        return true;
      }
    }
  }
  return false;
}

function main(
  workbook: ExcelScript.Workbook,
  stampBase64: string,
  sheetName: string,
  anchorCell: string,
  approverName: string,
  shapeName: string,
  targetWidthPt: number,
  targetHeightPt: number,
  offsetXPt: number,
  offsetYPt: number
): string {
  const result = emptyResult(sheetName, anchorCell, shapeName);
  // addImage が成功したあとに失敗した場合だけ、この図形を削除して元に戻す。
  // (既存の図形を誤って消さないよう、自分で作ったものにだけ参照を持つ)
  let created: ExcelScript.Shape | undefined = undefined;

  try {
    const image = stripDataUri(stampBase64);
    if (image.length < 16) {
      return finish(result, "invalid_input", "stampBase64 が空、または短すぎます");
    }

    const anchorMatch = /^([A-Za-z]+)([0-9]+)$/.exec(anchorCell);
    if (!anchorMatch) {
      return finish(result, "invalid_input", "anchorCell の形式が不正です: " + anchorCell);
    }
    const anchorRow = parseInt(anchorMatch[2], 10);

    const sheet = workbook.getWorksheet(sheetName);
    if (!sheet) {
      return finish(result, "template_mismatch", "シートが見つかりません: " + sheetName);
    }
    if (!rowContainsName(sheet, anchorRow, approverName)) {
      return finish(
        result,
        "template_mismatch",
        anchorRow + "行目に承認者名「" + approverName + "」が見つかりません(テンプレートが変わった可能性)"
      );
    }

    const anchor = sheet.getRange(anchorCell);
    const anchorLeft = anchor.getLeft();
    const anchorTop = anchor.getTop();
    const anchorWidth = anchor.getWidth();
    const anchorHeight = anchor.getHeight();
    result.anchorLeft = round1(anchorLeft);
    result.anchorTop = round1(anchorTop);
    result.anchorWidth = round1(anchorWidth);
    result.anchorHeight = round1(anchorHeight);

    // 二重押印の検出: 同名の図形、またはアンカーセルに重なる図形
    const shapes = sheet.getShapes();
    result.shapeCountBefore = shapes.length;
    for (let i = 0; i < shapes.length; i++) {
      const existing = shapes[i];
      const existingName = existing.getName();
      if (existingName === shapeName) {
        return finish(result, "already_stamped", "同名の図形がすでにあります: " + existingName);
      }
      const left = existing.getLeft();
      const top = existing.getTop();
      const right = left + existing.getWidth();
      const bottom = top + existing.getHeight();
      const overlaps =
        left < anchorLeft + anchorWidth &&
        right > anchorLeft &&
        top < anchorTop + anchorHeight &&
        bottom > anchorTop;
      if (overlaps) {
        return finish(result, "already_stamped", "アンカーセルに重なる図形があります: " + existingName);
      }
    }

    // 挿入
    const shape = sheet.addImage(image);
    created = shape;
    shape.setName(shapeName);

    if (targetWidthPt > 0 && targetHeightPt > 0) {
      shape.setLockAspectRatio(false);
      shape.setWidth(targetWidthPt);
      shape.setHeight(targetHeightPt);
    } else if (targetWidthPt > 0) {
      shape.setLockAspectRatio(true);
      shape.setWidth(targetWidthPt);
    } else if (targetHeightPt > 0) {
      shape.setLockAspectRatio(true);
      shape.setHeight(targetHeightPt);
    }

    const expectedLeft = anchorLeft + offsetXPt;
    const expectedTop = anchorTop + offsetYPt;
    shape.setLeft(expectedLeft);
    shape.setTop(expectedTop);

    // 位置の検証: 手作業なら目で確認する部分を、座標で確かめる
    const actualLeft = shape.getLeft();
    const actualTop = shape.getTop();
    result.left = round1(actualLeft);
    result.top = round1(actualTop);
    result.width = round1(shape.getWidth());
    result.height = round1(shape.getHeight());
    if (
      Math.abs(actualLeft - expectedLeft) > POSITION_TOLERANCE_PT ||
      Math.abs(actualTop - expectedTop) > POSITION_TOLERANCE_PT
    ) {
      shape.delete();
      created = undefined;
      result.shapeCountAfter = sheet.getShapes().length;
      return finish(
        result,
        "position_error",
        "挿入位置が期待とずれたため取り消しました(期待 " +
          round1(expectedLeft) + "," + round1(expectedTop) + " / 実際 " +
          round1(actualLeft) + "," + round1(actualTop) + ")"
      );
    }

    result.shapeCountAfter = sheet.getShapes().length;
    return finish(result, "stamped", "");
  } catch (e) {
    if (created !== undefined) {
      try {
        created.delete();
      } catch (rollbackError) {
        // 取り消しにも失敗した場合は、reason に残してフロー側で人が確認する
        return finish(result, "script_error", String(e) + " / 取り消しにも失敗: " + String(rollbackError));
      }
    }
    return finish(result, "script_error", String(e));
  }
}
