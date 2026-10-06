/**
 * 図形の位置とサイズを読み取る(読み取り専用)  20261006_01
 *
 * 手作業で押印済みの証明書を Excel Online で開き、このスクリプトを実行する。
 * 結果は、スクリプトの「出力」ウィンドウ(console.log)と戻り値に出る。
 *
 * 目的: 手作業の「セルの上に配置」で入った印影の、位置とサイズ(pt)を測り、
 *       stamp_approver が同じ結果になるかを確かめる基準にする(docs/MEASUREMENT_GUIDE.md の E4)。
 *
 * このスクリプトは、ブックを一切変更しない。
 *
 * 引数を持たない形にしてある。Excel の「自動化」タブから、そのまま実行できるようにするため
 * (引数のあるスクリプトは、Power Automate からでないと実行できないと認識している。未確認)。
 * シート名とアンカーは、下の定数を書き換えて使う。
 */

const SHEET_NAME = "該非判定証明書";
const ANCHOR_CELL = "H15";

interface ShapeInfo {
  name: string;
  type: string;
  left: number;
  top: number;
  width: number;
  height: number;
}

function main(workbook: ExcelScript.Workbook): string {
  const sheetName = SHEET_NAME;
  const anchorCell = ANCHOR_CELL;
  const sheet = workbook.getWorksheet(sheetName);
  if (!sheet) {
    return JSON.stringify({ error: "シートが見つかりません: " + sheetName });
  }
  const anchor = sheet.getRange(anchorCell);
  const shapes = sheet.getShapes();
  const infos: ShapeInfo[] = [];
  for (let i = 0; i < shapes.length; i++) {
    const shape = shapes[i];
    infos.push({
      name: shape.getName(),
      type: String(shape.getType()),
      left: Math.round(shape.getLeft() * 10) / 10,
      top: Math.round(shape.getTop() * 10) / 10,
      width: Math.round(shape.getWidth() * 10) / 10,
      height: Math.round(shape.getHeight() * 10) / 10,
    });
  }
  const result = {
    sheet: sheetName,
    anchor: anchorCell,
    anchorLeft: Math.round(anchor.getLeft() * 10) / 10,
    anchorTop: Math.round(anchor.getTop() * 10) / 10,
    anchorWidth: Math.round(anchor.getWidth() * 10) / 10,
    anchorHeight: Math.round(anchor.getHeight() * 10) / 10,
    shapeCount: infos.length,
    shapes: infos,
  };
  const text = JSON.stringify(result);
  console.log(text);
  return text;
}
