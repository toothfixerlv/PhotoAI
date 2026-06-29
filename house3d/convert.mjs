import { LibreDwg } from '@mlightcad/libredwg-web';
import fs from 'fs';

const SRC = "/root/.claude/uploads/cd402fc1-03a0-5439-8be5-720f98b35a95/3f0118e5-NGUYEN_AD.dwg";
const buf = fs.readFileSync(SRC);
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);

const dwg = await LibreDwg.create();
console.error("LibreDwg ready");
const dxf = dwg.dwg_write_dxf(ab);
if (!dxf) { console.error("DXF conversion returned null"); process.exit(1); }
fs.writeFileSync("house.dxf", Buffer.from(dxf));
console.error("Wrote house.dxf bytes:", dxf.length);
