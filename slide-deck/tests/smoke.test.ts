import assert from "node:assert/strict";
import { test } from "node:test";
import pptxgen from "pptxgenjs";

test("pptxgenjs で 1 枚のスライドの PowerPoint のファイルを、ZIP の形式で書き出せる", async () => {
  const pres = new pptxgen();
  pres.addSlide().addText("smoke", { x: 1, y: 1, w: 3, h: 1 });
  const out = await pres.write({ outputType: "nodebuffer" });
  assert.ok(Buffer.isBuffer(out));
  // PowerPoint のファイルは ZIP なので、先頭の 2 バイトは ZIP のシグネチャ "PK"
  assert.equal(out.subarray(0, 2).toString("latin1"), "PK");
});
