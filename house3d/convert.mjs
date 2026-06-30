import { LibreDwg } from '@mlightcad/libredwg-web';
import fs from 'fs';

const SRC = "./src/NGUYEN_AD.dwg";
const buf = fs.readFileSync(SRC);
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);

const dwg = await LibreDwg.create();
console.error("LibreDwg ready");
const dxf = dwg.dwg_write_dxf(ab);
if (!dxf) { console.error("DXF conversion returned null"); process.exit(1); }
fs.writeFileSync("house.dxf", Buffer.from(dxf));
console.error("Wrote house.dxf bytes:", dxf.length);
