// stamp_approver_20261006_01.ts のローカルテスト(ExcelScript の模擬オブジェクトを使う)。
//
// 実行(このフォルダで。Node.js 22.13 以降):
//     node test_stamp_20261006_01.mjs
//
// 何を確かめるか:
//   スクリプトのロジック(二重押印の検出・テンプレート変更の検出・位置検証と取り消し・
//   既存図形に触れないこと・入力の取り扱い)を、実機の Excel なしで確かめる。
//
// 何を確かめられないか(実機が要る):
//   - ExcelScript の実 API が、模擬オブジェクトと同じ名前・振る舞いか
//     (getLeft / getTop / addImage / setLockAspectRatio など。docs/MEASUREMENT_GUIDE.md の E4)
//   - 画像の自然サイズ(PNG の DPI 情報による差)。手作業の結果との一致は E4 で測る。

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SCRIPT_PATH = join(HERE, "stamp_approver_20261006_01.ts");
const INSPECT_PATH = join(HERE, "inspect_shapes_20261006_01.ts");

// ---- スクリプトを読み込む(型注釈だけを除去して評価する) --------------------
const source = readFileSync(SCRIPT_PATH, "utf-8");
const js = stripTypeScriptTypes(source);
const main = new Function(js + "\nreturn main;")();
const inspect = new Function(stripTypeScriptTypes(readFileSync(INSPECT_PATH, "utf-8")) + "\nreturn main;")();

// ---- ExcelScript の模擬 -------------------------------------------------------
const COL_WIDTH = 64; // pt
const ROW_HEIGHT = 15; // pt

function parseCell(address) {
  const m = /^([A-Za-z]+)([0-9]+)$/.exec(address);
  let col = 0;
  for (const ch of m[1].toUpperCase()) col = col * 26 + (ch.charCodeAt(0) - 64);
  return { col, row: parseInt(m[2], 10) };
}

class FakeShape {
  constructor(sheet, name, left, top, width, height) {
    this.sheet = sheet;
    this.name = name;
    this.left = left;
    this.top = top;
    this.width = width;
    this.height = height;
    this.lockAspect = true;
  }
  getName() { return this.name; }
  getType() { return "Image"; }
  setName(v) { this.name = v; }
  getLeft() { return this.left; }
  getTop() { return this.top; }
  getWidth() { return this.width; }
  getHeight() { return this.height; }
  setLeft(v) { if (!this.sheet.opts.ignoreSetPosition) this.left = v; }
  setTop(v) { if (!this.sheet.opts.ignoreSetPosition) this.top = v; }
  setLockAspectRatio(v) { this.lockAspect = v; }
  setWidth(v) {
    if (this.lockAspect) this.height = (this.height * v) / this.width;
    this.width = v;
  }
  setHeight(v) {
    if (this.lockAspect) this.width = (this.width * v) / this.height;
    this.height = v;
  }
  delete() {
    if (this.sheet.opts.failDelete) throw new Error("delete failed");
    this.sheet.shapes = this.sheet.shapes.filter((s) => s !== this);
  }
}

class FakeRange {
  constructor(sheet, address) {
    this.sheet = sheet;
    this.address = address;
  }
  _bounds() {
    const [a, b] = this.address.split(":");
    const start = parseCell(a);
    const end = b ? parseCell(b) : start;
    return { start, end };
  }
  getLeft() { return (this._bounds().start.col - 1) * COL_WIDTH; }
  getTop() { return (this._bounds().start.row - 1) * ROW_HEIGHT; }
  getWidth() {
    const { start, end } = this._bounds();
    return (end.col - start.col + 1) * COL_WIDTH;
  }
  getHeight() {
    const { start, end } = this._bounds();
    return (end.row - start.row + 1) * ROW_HEIGHT;
  }
  getValues() {
    const { start, end } = this._bounds();
    const rows = [];
    for (let r = start.row; r <= end.row; r++) {
      const row = [];
      for (let c = start.col; c <= end.col; c++) {
        row.push(this.sheet.cells.get(r + ":" + c) ?? "");
      }
      rows.push(row);
    }
    return rows;
  }
}

class FakeSheet {
  constructor(opts = {}) {
    this.opts = opts;
    this.cells = new Map();
    this.shapes = [];
    this.addImageCalls = [];
  }
  setCell(address, value) {
    const { col, row } = parseCell(address);
    this.cells.set(row + ":" + col, value);
  }
  getRange(address) { return new FakeRange(this, address); }
  getShapes() { return [...this.shapes]; }
  addImage(base64) {
    if (this.opts.failAddImage) throw new Error("addImage failed");
    this.addImageCalls.push(base64);
    // 実機では、画像は先頭付近(または選択位置)に入る。ここでは原点に置く。
    const shape = new FakeShape(this, "Picture 1", 0, 0, 60, 40);
    this.shapes.push(shape);
    return shape;
  }
}

class FakeWorkbook {
  constructor(sheet, name = "該非判定証明書") {
    this.sheet = sheet;
    this.name = name;
  }
  getWorksheet(name) { return name === this.name ? this.sheet : undefined; }
}

// 本物のテンプレートに近い状態: 15行目に承認者名、19行目に該非判定者の印影
function templateSheet(opts = {}) {
  const sheet = new FakeSheet(opts);
  sheet.setCell("G14", "Japan site manager");
  sheet.setCell("G15", "越智泰造");
  sheet.setCell("H15", "印");
  sheet.setCell("G19", "別の担当者");
  sheet.shapes.push(new FakeShape(sheet, "OtherStamp", 7 * COL_WIDTH, 18 * ROW_HEIGHT, 50, 50));
  return sheet;
}

const STAMP = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
const BASE_ARGS = ["該非判定証明書", "H15", "越智泰造", "ECS_ApproverStamp", 0, 0, 0, 0];

function run(sheet, stamp = STAMP, args = BASE_ARGS, workbook = new FakeWorkbook(sheet)) {
  return JSON.parse(main(workbook, stamp, ...args));
}

// ---- テスト -------------------------------------------------------------------
let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log("  ok   " + name);
  } catch (e) {
    console.log("  NG   " + name);
    console.log("       " + (e && e.message ? e.message.split("\n").join("\n       ") : e));
    process.exitCode = 1;
  }
}

test("T01 正常: H15の左上に挿入される", () => {
  const sheet = templateSheet();
  const before = sheet.getShapes().length;
  const r = run(sheet);
  assert.equal(r.status, "stamped");
  assert.equal(r.left, 7 * COL_WIDTH);
  assert.equal(r.top, 14 * ROW_HEIGHT);
  assert.equal(r.shapeCountBefore, before);
  assert.equal(r.shapeCountAfter, before + 1);
  const added = sheet.shapes.find((s) => s.getName() === "ECS_ApproverStamp");
  assert.ok(added);
});

test("T02 既存の図形(該非判定者の印影)には触れない", () => {
  const sheet = templateSheet();
  const saji = sheet.shapes[0];
  const snapshot = [saji.getName(), saji.getLeft(), saji.getTop(), saji.getWidth(), saji.getHeight()];
  run(sheet);
  assert.deepEqual(
    [saji.getName(), saji.getLeft(), saji.getTop(), saji.getWidth(), saji.getHeight()],
    snapshot
  );
  assert.ok(sheet.shapes.includes(saji));
});

test("T03 二重押印: 同名の図形があれば中止し、何も追加しない", () => {
  const sheet = templateSheet();
  assert.equal(run(sheet).status, "stamped");
  const count = sheet.getShapes().length;
  const r = run(sheet);
  assert.equal(r.status, "already_stamped");
  assert.equal(sheet.getShapes().length, count);
  assert.equal(sheet.addImageCalls.length, 1);
});

test("T04 手作業で押印済み(別名の図形がH15に重なる)なら中止する", () => {
  const sheet = templateSheet();
  sheet.shapes.push(new FakeShape(sheet, "Picture 7", 7 * COL_WIDTH + 5, 14 * ROW_HEIGHT + 2, 55, 55));
  const r = run(sheet);
  assert.equal(r.status, "already_stamped");
  assert.equal(sheet.addImageCalls.length, 0);
});

test("T05 シートが無ければ template_mismatch", () => {
  const sheet = templateSheet();
  const r = run(sheet, STAMP, BASE_ARGS, new FakeWorkbook(sheet, "別のシート"));
  assert.equal(r.status, "template_mismatch");
  assert.equal(sheet.addImageCalls.length, 0);
});

test("T06 15行目に承認者名が無ければ template_mismatch", () => {
  const sheet = templateSheet();
  sheet.setCell("G15", "別の人");
  const r = run(sheet);
  assert.equal(r.status, "template_mismatch");
  assert.equal(sheet.addImageCalls.length, 0);
});

test("T07 承認者名は空白(半角・全角)の違いを無視して一致する", () => {
  const sheet = templateSheet();
  sheet.setCell("G15", "越智　泰造");
  assert.equal(run(sheet).status, "stamped");
});

test("T08 位置が合わなければ、挿入した図形を削除して position_error", () => {
  const sheet = templateSheet({ ignoreSetPosition: true });
  const before = sheet.getShapes().length;
  const r = run(sheet);
  assert.equal(r.status, "position_error");
  assert.equal(sheet.getShapes().length, before);
  assert.equal(r.shapeCountAfter, before);
});

test("T09 空の画像データは invalid_input(何も追加しない)", () => {
  const sheet = templateSheet();
  assert.equal(run(sheet, "").status, "invalid_input");
  assert.equal(run(sheet, "short").status, "invalid_input");
  assert.equal(sheet.addImageCalls.length, 0);
});

test("T10 data URI 形式・改行入りの画像データも受け付け、純粋なbase64だけを渡す", () => {
  const sheet = templateSheet();
  const wrapped = "data:image/png;base64," + STAMP.slice(0, 20) + "\r\n" + STAMP.slice(20);
  assert.equal(run(sheet, wrapped).status, "stamped");
  assert.equal(sheet.addImageCalls[0], STAMP);
});

test("T11 アンカーセルの形式が不正なら invalid_input", () => {
  const sheet = templateSheet();
  const args = ["該非判定証明書", "15H", "越智泰造", "ECS_ApproverStamp", 0, 0, 0, 0];
  assert.equal(run(sheet, STAMP, args).status, "invalid_input");
});

test("T12 幅を指定すると、縦横比を保って拡縮する", () => {
  const sheet = templateSheet();
  const args = ["該非判定証明書", "H15", "越智泰造", "ECS_ApproverStamp", 30, 0, 0, 0];
  const r = run(sheet, STAMP, args);
  assert.equal(r.status, "stamped");
  assert.equal(r.width, 30);
  assert.equal(r.height, 20); // 元 60x40 を幅30へ → 高さ20
});

test("T13 オフセットを指定すると、その分だけずれた位置に入る", () => {
  const sheet = templateSheet();
  const args = ["該非判定証明書", "H15", "越智泰造", "ECS_ApproverStamp", 0, 0, 4, -2];
  const r = run(sheet, STAMP, args);
  assert.equal(r.status, "stamped");
  assert.equal(r.left, 7 * COL_WIDTH + 4);
  assert.equal(r.top, 14 * ROW_HEIGHT - 2);
});

test("T14 addImage が失敗しても、既存の図形を消さず script_error を返す", () => {
  const sheet = templateSheet({ failAddImage: true });
  const before = sheet.getShapes().length;
  const r = run(sheet);
  assert.equal(r.status, "script_error");
  assert.equal(sheet.getShapes().length, before);
});

test("T15 挿入後の失敗は取り消す(取り消しにも失敗したら、その旨を reason に残す)", () => {
  const sheet = templateSheet({ failDelete: true, ignoreSetPosition: true });
  const r = run(sheet);
  assert.equal(r.status, "script_error");
  assert.match(r.reason, /取り消しにも失敗/);
});

test("T16 戻り値は常に JSON として読め、必須キーを持つ", () => {
  const sheet = templateSheet();
  for (const variant of [run(sheet), run(sheet), run(templateSheet(), "")]) {
    for (const key of ["status", "reason", "sheet", "anchor", "left", "top", "width", "height"]) {
      assert.ok(key in variant, "キーが無い: " + key);
    }
  }
});

test("T17 同名の図形が別の場所へ動かされていても、二重押印として中止する", () => {
  const sheet = templateSheet();
  sheet.shapes.push(new FakeShape(sheet, "ECS_ApproverStamp", 2 * COL_WIDTH, 30 * ROW_HEIGHT, 50, 50));
  const r = run(sheet);
  assert.equal(r.status, "already_stamped");
  assert.match(r.reason, /同名/);
  assert.equal(sheet.addImageCalls.length, 0);
});

test("T18 inspect: 図形の位置・サイズとアンカーの座標を返し、ブックを変更しない", () => {
  const sheet = templateSheet();
  const snapshot = JSON.stringify(sheet.shapes.map((x) => [x.name, x.left, x.top, x.width, x.height]));
  const originalLog = console.log;
  console.log = () => {}; // スクリプトが出力ウィンドウへ書く分は、テストの表示に出さない
  let text;
  try {
    text = inspect(new FakeWorkbook(sheet));
  } finally {
    console.log = originalLog;
  }
  const r = JSON.parse(text);
  assert.equal(r.shapeCount, 1);
  assert.equal(r.shapes[0].name, "OtherStamp");
  assert.equal(r.anchorLeft, 7 * COL_WIDTH);
  assert.equal(r.anchorTop, 14 * ROW_HEIGHT);
  assert.equal(JSON.stringify(sheet.shapes.map((x) => [x.name, x.left, x.top, x.width, x.height])), snapshot);
  assert.equal(sheet.addImageCalls.length, 0);
});

test("T19 inspect: シートが無ければエラーを返す", () => {
  const sheet = templateSheet();
  const r = JSON.parse(inspect(new FakeWorkbook(sheet, "別")));
  assert.ok(r.error);
});

console.log("");
console.log(passed + " 件成功" + (process.exitCode ? "、失敗あり" : ""));
