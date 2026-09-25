// The synthetic OSM extract, read by the REAL in-browser reader (Q1018, S04-08's S5).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// `node tests/osm_extract_node_test.js [path]` -- the path defaults to the committed
// fixture; tests/test_osm_fixture.py also passes the file the download manager just
// wrote, so the chain download -> file on disk -> reader -> country area runs end to end
// without a socket.
//
// Every expected value below is written out from scripts/make_osm_fixture.py's literals,
// not read back from the reader, so a reader that decoded the file wrongly cannot agree
// with itself here.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const PBF = require(path.join(__dirname, "..", "src", "static", "osmpbf.js"));

const file = process.argv[2] || path.join(__dirname, "fixtures", "osm", "synthetic.osm.pbf");
const bytes = fs.readFileSync(file);
const ab = (b) => b.buffer.slice(b.byteOffset, b.byteOffset + b.length);
const OPTS = { withTags: true, withRelations: true };

function check(r, label) {
  assert.deepStrictEqual(r.nodes, [
    { id: 1, lat: 0.1, lon: 0.1 }, { id: 2, lat: 0.1, lon: 0.2 },
    { id: 3, lat: 0.2, lon: 0.2 }, { id: 4, lat: 0.2, lon: 0.1 },
  ], label + ": the four corners");
  assert.deepStrictEqual(r.ways.map((w) => [w.id, w.refs]), [[10, [1, 2, 3]], [11, [3, 4, 1]]],
    label + ": the two open border ways");
  assert.strictEqual(r.relations.length, 1, label);
  const rel = r.relations[0];
  assert.strictEqual(rel.tags["ISO3166-1:alpha2"], "ZZ", label + ": the private-use code");
  assert.deepStrictEqual(rel.members, [
    { ref: 10, type: 1, role: "outer" }, { ref: 11, type: 1, role: "outer" },
  ], label);
  assert.strictEqual(r.blocks, 1, label + ": one data block (the header block is skipped)");
  assert.strictEqual(r.truncated, false, label);
  // The pipeline's output: the two open ways stitched into ONE closed ring.
  const areas = PBF.assembleAdminAreas(r);
  assert.strictEqual(areas.length, 1, label + ": exactly one country, from the relation");
  const a = areas[0];
  assert.strictEqual(a.iso2, "ZZ", label);
  assert.strictEqual(a.name, "Fixture Land", label);
  assert.strictEqual(a.source, "osm-relation", label);
  assert.strictEqual(a.rings.length, 1, label);
  const ring = a.rings[0];
  assert.strictEqual(ring.length, 5, label + ": four corners and the closing point");
  assert.deepStrictEqual(ring[0], ring[ring.length - 1], label + ": the ring is closed");
}

// Split the file into its [header, blob] records so one can be re-wrapped.
function records(buf) {
  const out = [];
  let pos = 0;
  while (pos + 4 <= buf.length) {
    const hlen = buf.readInt32BE(pos);
    const hdr = PBF.readBlobHeader(buf, pos + 4, pos + 4 + hlen);
    const blobStart = pos + 4 + hlen;
    out.push({ type: hdr.type, blob: buf.subarray(blobStart, blobStart + hdr.datasize) });
    pos = blobStart + hdr.datasize;
  }
  return out;
}
function varint(n) { const o = []; do { let b = n % 128; n = Math.floor(n / 128); if (n) b |= 0x80; o.push(b); } while (n); return o; }
function lenField(f, bytes) { return Buffer.concat([Buffer.from(varint(f * 8 + 2).concat(varint(bytes.length))), bytes]); }
function uintField(f, n) { return Buffer.from(varint(f * 8).concat(varint(n))); }
function fileblock(type, blob) {
  const header = Buffer.concat([lenField(1, Buffer.from(type, "ascii")), uintField(3, blob.length)]);
  const len = Buffer.alloc(4); len.writeInt32BE(header.length);
  return Buffer.concat([len, header, blob]);
}

(async () => {
  // 1. The file as written.
  check(await PBF.parse(ab(bytes), OPTS), "raw");

  // 2. The same block zlib-compressed, which is how Geofabrik ships every extract. The
  //    fixture is raw so its digest can be pinned; this covers the inflate path.
  const recs = records(bytes);
  assert.deepStrictEqual(recs.map((r) => r.type), ["OSMHeader", "OSMData"]);
  const rebuilt = Buffer.concat(recs.map((r) => {
    const raw = PBF.readBlob(r.blob, 0, r.blob.length).raw;
    assert.ok(raw, r.type + " is not a raw blob -- the generator changed");
    const block = r.blob.subarray(raw[0], raw[1]);
    const z = zlib.deflateSync(block);
    return fileblock(r.type, Buffer.concat([uintField(2, block.length), lenField(3, z)]));
  }));
  check(await PBF.parse(ab(rebuilt), OPTS), "zlib");

  // 3. A download cut short mid-blob: the reader stops, and invents nothing.
  const cut = await PBF.parse(ab(bytes.subarray(0, bytes.length - 20)), OPTS);
  assert.strictEqual(cut.blocks, 0, "a truncated data blob was decoded anyway");
  assert.deepStrictEqual(cut.nodes, []);
  assert.deepStrictEqual(PBF.assembleAdminAreas(cut), [], "a border was fabricated from a cut file");

  console.log("osm_extract_node_test: all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
