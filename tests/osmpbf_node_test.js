/*
 * Node test for src/static/osmpbf.js — proves the protobuf varint/zigzag
 * primitives, the dense-node delta decode (exact WGS84 degrees), the full
 * .osm.pbf container parse (raw blob), and the bounded-preview (maxBlocks)
 * behaviour. A tiny protobuf ENCODER is written here independently of the
 * decoder, so a green round-trip + the hand-computed expected DEGREES make the
 * test non-vacuous. Run by tests/test_osmpbf_parser.py (and standalone:
 * `node tests/osmpbf_node_test.js`). GPL-3.0-or-later.
 */
"use strict";
const path = require("path");
const PBF = require(path.join(__dirname, "..", "src", "static", "osmpbf.js"));

let failures = 0;
function ok(cond, msg) { if (!cond) { console.error("FAIL: " + msg); failures++; } }
function eqf(a, b, msg, eps) { ok(Math.abs(a - b) < (eps || 1e-7), msg + " (got " + a + ", want " + b + ")"); }

// --- a minimal protobuf encoder (independent of the decoder under test) --- //
function encVarint(n) {
  const out = [];
  do { let b = n % 128; n = Math.floor(n / 128); if (n > 0) b |= 0x80; out.push(b); } while (n > 0);
  return out;
}
function encZig(n) { return n >= 0 ? 2 * n : -2 * n - 1; }       // sint64 -> unsigned
function tag(field, wire) { return encVarint(field * 8 + wire); }
function lenField(field, bytes) { return tag(field, 2).concat(encVarint(bytes.length), bytes); }
function varField(field, n) { return tag(field, 0).concat(encVarint(n)); }
function packedZig(field, deltas) {
  let body = []; for (const d of deltas) body = body.concat(encVarint(encZig(d)));
  return lenField(field, body);
}

// --- 1. primitives --- //
ok(PBF.readVarint(new Uint8Array([0x96, 0x01]), 0)[0] === 150, "readVarint 150 (protobuf canonical)");
ok(PBF.readVarint(new Uint8Array([0x00]), 0)[0] === 0, "readVarint 0");
ok(PBF.zigzag(0) === 0 && PBF.zigzag(1) === -1 && PBF.zigzag(2) === 1 && PBF.zigzag(3) === -2, "zigzag small");
ok(PBF.zigzag(4294967294) === 2147483647, "zigzag large (>2^31)");

// --- 2. a PrimitiveBlock with two dense nodes at known coords --- //
// granularity 100, offsets 0: lat_deg = 1e-9 * 100 * cumdelta.
// node1 lat cumdelta 515000000 -> 51.5°, lon -1000000 -> -0.1°
// node2 lat +10000000 -> 525000000 -> 52.5°, lon +6000000 -> 5000000 -> 0.5°
const denseBody = []
  .concat(packedZig(1, [1, 1]))                       // ids (delta) -> 1, 2
  .concat(packedZig(8, [515000000, 10000000]))        // lat deltas
  .concat(packedZig(9, [-1000000, 6000000]));         // lon deltas
// PrimitiveBlock.field2 = PrimitiveGroup, whose field2 = DenseNodes (two wraps).
const group = lenField(2, lenField(2, denseBody));
const primitiveBlock = [].concat(group, varField(17, 100));  // + granularity (offsets default 0)

const pbU8 = new Uint8Array(primitiveBlock);
const decoded = PBF.decodePrimitiveBlock(pbU8, 0, pbU8.length);
ok(decoded.nodes.length === 2, "decodePrimitiveBlock: two nodes (got " + decoded.nodes.length + ")");
if (decoded.nodes.length === 2) {
  eqf(decoded.nodes[0].lat, 51.5, "node1 lat");
  eqf(decoded.nodes[0].lon, -0.1, "node1 lon");
  eqf(decoded.nodes[1].lat, 52.5, "node2 lat");
  eqf(decoded.nodes[1].lon, 0.5, "node2 lon");
  ok(decoded.nodes[0].id === 1 && decoded.nodes[1].id === 2, "node ids delta-decoded");
}

// --- 3. a full .osm.pbf (raw blob) parsed by parse() --- //
function blobUnit(type, primitiveBlockBytes) {
  const blob = lenField(1, primitiveBlockBytes);             // Blob.field1 = raw (uncompressed)
  const header = [].concat(lenField(1, Array.from(Buffer.from(type, "utf8"))), varField(3, blob.length));
  const lenPrefix = []; const dv = Buffer.alloc(4); dv.writeInt32BE(header.length, 0);
  for (const b of dv) lenPrefix.push(b);
  return lenPrefix.concat(header, blob);
}
const file = [].concat(
  blobUnit("OSMHeader", []),                                  // skipped block
  blobUnit("OSMData", primitiveBlock),
  blobUnit("OSMData", primitiveBlock),
  blobUnit("OSMData", primitiveBlock)
);
const ab = new Uint8Array(file).buffer;

(async () => {
  const r = await PBF.parse(ab, {});
  ok(r.blocks === 3, "parse reads all 3 OSMData blocks (got " + r.blocks + ")");
  ok(r.nodes.length === 6, "parse accumulates 6 nodes (2×3; got " + r.nodes.length + ")");
  ok(r.bbox && Math.abs(r.bbox.minLat - 51.5) < 1e-7 && Math.abs(r.bbox.maxLat - 52.5) < 1e-7, "bbox from decoded nodes");

  // bounded preview: maxBlocks caps the work + flags truncation honestly
  const r2 = await PBF.parse(ab, { maxBlocks: 2 });
  ok(r2.blocks === 2, "maxBlocks=2 stops after 2 blocks (got " + r2.blocks + ")");
  ok(r2.truncated === true, "truncated flag set when more data remains");

  if (failures) { console.error(failures + " assertion(s) failed"); process.exit(1); }
  console.log("OSMPBF OK — all assertions passed");
  process.exit(0);
})().catch((e) => { console.error("ERROR: " + (e && e.stack || e)); process.exit(2); });
