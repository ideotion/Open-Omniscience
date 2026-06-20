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
function packedVar(field, vals) {                       // packed PLAIN varints (keys/vals/roles/types)
  let body = []; for (const v of vals) body = body.concat(encVarint(v));
  return lenField(field, body);
}
function strEntry(s) { return lenField(1, Array.from(Buffer.from(s, "utf8"))); }  // StringTable.s

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

// --- 2b. tags + a boundary RELATION -> assembleAdminAreas (THEME-2 #51) --- //
// A PrimitiveBlock with a StringTable, 4 dense nodes forming a unit square, two
// ways splitting its perimeter, and an admin_level=2 boundary relation (ISO MC)
// whose two outer ways close into the country ring. Proves the StringTable +
// way/relation tag + member decode and the ring stitching to a closed polygon.
(function () {
  // StringTable: index 0 = "" then the tag/role strings the relation references.
  const ST = ["", "boundary", "administrative", "admin_level", "2", "ISO3166-1:alpha2", "MC", "name", "Testland", "outer"];
  let stBody = []; for (const s of ST) stBody = stBody.concat(strEntry(s));
  const stringTable = lenField(1, stBody);                       // PrimitiveBlock.field1

  // 4 dense nodes (ids 1..4) at the corners of a unit square (lat/lon in degrees):
  //   1:(0,0) 2:(0,1) 3:(1,1) 4:(1,0). coord = 1e-7 * cumdelta, so 1.0deg = 1e7.
  const dense = []
    .concat(packedZig(1, [1, 1, 1, 1]))                         // ids -> 1,2,3,4
    .concat(packedZig(8, [0, 0, 1e7, 0]))                       // lat cum -> 0,0,1,1
    .concat(packedZig(9, [0, 1e7, 0, -1e7]));                   // lon cum -> 0,1,1,0
  const denseGroup = lenField(2, lenField(2, dense));           // group{ field2 DenseNodes }

  // way 100 = nodes 1,2,3 ; way 101 = nodes 3,4,1  (perimeter split, no tags)
  const way100 = [].concat(varField(1, 100), packedZig(8, [1, 1, 1]));      // refs delta 1,2,3
  const way101 = [].concat(varField(1, 101), packedZig(8, [3, 1, -3]));     // refs delta 3,4,1
  const waysGroup = lenField(2, [].concat(lenField(3, way100), lenField(3, way101)));

  // relation 500: boundary=administrative, admin_level=2, ISO3166-1:alpha2=MC,
  // name=Testland ; members = way 100 (outer), way 101 (outer)
  const rel = [].concat(
    varField(1, 500),
    packedVar(2, [1, 3, 5, 7]),                                 // keys -> boundary,admin_level,ISO..,name
    packedVar(3, [2, 4, 6, 8]),                                 // vals -> administrative,2,MC,Testland
    packedVar(8, [9, 9]),                                       // roles_sid -> outer,outer
    packedZig(9, [100, 1]),                                     // memids delta (sint64) -> 100,101
    packedVar(10, [1, 1])                                       // types -> WAY,WAY
  );
  const relGroup = lenField(2, lenField(4, rel));               // group{ field4 Relation }

  const pb = [].concat(stringTable, denseGroup, waysGroup, relGroup, varField(17, 100));
  const u8 = new Uint8Array(pb);
  // default (no opts) is geometry-only + backward-compatible
  const plain = PBF.decodePrimitiveBlock(u8, 0, u8.length);
  ok(plain.nodes.length === 4 && plain.ways.length === 2, "decode: 4 nodes + 2 ways");
  ok(Array.isArray(plain.relations) && plain.relations.length === 0, "relations only when asked (backward compat)");
  // with tags + relations
  const full = PBF.decodePrimitiveBlock(u8, 0, u8.length, { withTags: true, withRelations: true });
  ok(full.relations.length === 1, "withRelations decodes the boundary relation");
  if (full.relations.length === 1) {
    const r = full.relations[0];
    ok(r.tags["boundary"] === "administrative" && r.tags["admin_level"] === "2", "relation tags resolved via StringTable");
    ok(r.tags["ISO3166-1:alpha2"] === "MC" && r.tags["name"] === "Testland", "ISO + name tags resolved");
    ok(r.members.length === 2 && r.members[0].ref === 100 && r.members[1].ref === 101, "members delta-decoded (ways 100,101)");
    ok(r.members[0].type === 1 && r.members[0].role === "outer", "member type WAY + role 'outer' resolved");
  }
  const areas = PBF.assembleAdminAreas(full);
  ok(areas.length === 1, "assembleAdminAreas closes one country (got " + areas.length + ")");
  if (areas.length === 1) {
    const a = areas[0];
    ok(a.iso2 === "MC", "area keyed by ISO 3166-1 alpha-2");
    ok(a.rings.length === 1, "one closed outer ring");
    const ring = a.rings[0];
    ok(ring.length === 5, "ring is closed (4 corners + repeat; got " + ring.length + ")");
    // rings are [lon,lat]; first==last, and the square corners are present
    ok(Math.abs(ring[0][0] - ring[ring.length - 1][0]) < 1e-9 && Math.abs(ring[0][1] - ring[ring.length - 1][1]) < 1e-9, "ring first==last");
    const set = ring.slice(0, 4).map(p => p[0] + "," + p[1]).sort().join("|");
    ok(set === "0,0|0,1|1,0|1,1", "ring covers the four unit-square corners (got " + set + ")");
  }
  // a non-boundary relation (wrong admin_level) is ignored -> no fabricated area
  const noLevel = PBF.assembleAdminAreas({ nodes: full.nodes, ways: full.ways, relations: [{ id: 9, tags: { boundary: "administrative", admin_level: "6", "ISO3166-1:alpha2": "ZZ" }, members: full.relations[0].members }] });
  ok(noLevel.length === 0, "admin_level!=2 is not a country (no area)");
})();

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
