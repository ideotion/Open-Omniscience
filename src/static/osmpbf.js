/*
 * Open Omniscience — minimal, dependency-free OSM PBF (.osm.pbf) reader.
 * GPL-3.0-or-later.
 *
 * Parses the geometry out of a Geofabrik-style `.osm.pbf` extract entirely in
 * the browser (THEME-2: render a downloaded offline-map region without any
 * network call or heavy WebGL dependency). It is deliberately BOUNDED — a region
 * file can be hundreds of MB, so the parser stops after `maxBlocks` primitive
 * blocks (a faithful PREVIEW of the region, never an OOM), and the caller is told
 * (`truncated`) so it can say so honestly. No fabricated data: we only emit the
 * nodes/ways actually decoded.
 *
 * Format (https://wiki.openstreetmap.org/wiki/PBF_Format):
 *   file = repeat[ int32-BE BlobHeader length | BlobHeader | Blob ]
 *   BlobHeader{ 1:type(string "OSMHeader"|"OSMData"), 3:datasize(int32) }
 *   Blob{ 1:raw(bytes) | (2:raw_size + 3:zlib_data(bytes)) }   ← we handle raw + zlib
 *   PrimitiveBlock{ 1:StringTable, 2:repeat PrimitiveGroup, 17:granularity=100,
 *                   19:lat_offset, 20:lon_offset }
 *   PrimitiveGroup{ 2:DenseNodes, 3:repeat Way }
 *   DenseNodes{ 1:packed sint64 id(delta), 8:packed sint64 lat(delta), 9:packed sint64 lon(delta) }
 *   Way{ 1:int64 id, 8:packed sint64 refs(delta) }
 *   coord = 1e-9 * (offset + granularity * cumulative_delta)
 *
 * The protobuf varint/zigzag primitives + the dense-node delta decode are pure
 * and node-tested (tests/test_osmpbf_parser.py runs this under node against a
 * hand-encoded fixture); the zlib + fetch + ooMap overlay are the browser glaze.
 */
(function (root) {
  "use strict";

  // --- protobuf wire-format primitives (pure, node-tested) --- //

  // Read an unsigned base-128 varint at `pos`. Accumulates with Number (safe to
  // 2^53 — OSM ids are ~1e10, well within range). Returns [value, nextPos].
  function readVarint(buf, pos) {
    var shiftMul = 1, val = 0, b;
    do {
      b = buf[pos++];
      val += (b & 0x7f) * shiftMul;
      shiftMul *= 128;
    } while (b & 0x80);
    return [val, pos];
  }

  // ZigZag decode (sint64): even -> n/2, odd -> -(n+1)/2. Number-safe (no 64-bit
  // bitwise, which would break above 2^31).
  function zigzag(n) { return (n % 2) ? -(n + 1) / 2 : n / 2; }

  // Iterate the protobuf fields in buf[start,end): cb(fieldNumber, wireType, reader)
  // where reader exposes the current position + helpers, and MUST advance `state.pos`
  // past the field's value. Returns nothing; the caller collects via the callback.
  function eachField(buf, start, end, cb) {
    var pos = start;
    while (pos < end) {
      var key, fno, wt;
      var r = readVarint(buf, pos); key = r[0]; pos = r[1];
      fno = Math.floor(key / 8); wt = key & 7;
      if (wt === 0) {            // varint
        var v = readVarint(buf, pos); pos = v[1];
        cb(fno, wt, { varint: v[0] });
      } else if (wt === 2) {     // length-delimited
        var l = readVarint(buf, pos); pos = l[1];
        var s = pos, e = pos + l[0]; pos = e;
        cb(fno, wt, { start: s, end: e });
      } else if (wt === 5) {     // 32-bit
        var s4 = pos; pos += 4; cb(fno, wt, { start: s4, end: pos });
      } else if (wt === 1) {     // 64-bit
        var s8 = pos; pos += 8; cb(fno, wt, { start: s8, end: pos });
      } else {                   // unknown/group — bail (we never emit these)
        break;
      }
    }
  }

  // Decode a packed repeated varint field into an array of unsigned values.
  function packedVarints(buf, start, end) {
    var out = [], pos = start, r;
    while (pos < end) { r = readVarint(buf, pos); out.push(r[0]); pos = r[1]; }
    return out;
  }

  // --- OSM blocks (pure, node-tested) --- //

  // Decode an (uncompressed) PrimitiveBlock buffer slice into geometry.
  // Returns { nodes:[{id,lat,lon}], ways:[{id,refs:[ids]}] } in WGS84 degrees.
  function decodePrimitiveBlock(buf, start, end) {
    var granularity = 100, latOff = 0, lonOff = 0;
    var groups = [];
    eachField(buf, start, end, function (fno, wt, f) {
      if (fno === 2 && wt === 2) groups.push([f.start, f.end]);      // PrimitiveGroup
      else if (fno === 17 && wt === 0) granularity = f.varint;       // granularity
      else if (fno === 19 && wt === 0) latOff = f.varint;            // lat_offset (nano-deg)
      else if (fno === 20 && wt === 0) lonOff = f.varint;            // lon_offset
    });
    var nodes = [], ways = [];
    var scale = 1e-9;
    for (var gi = 0; gi < groups.length; gi++) {
      eachField(buf, groups[gi][0], groups[gi][1], function (fno, wt, f) {
        if (fno === 2 && wt === 2) decodeDense(buf, f.start, f.end);
        else if (fno === 3 && wt === 2) decodeWay(buf, f.start, f.end);
      });
    }
    function decodeDense(b, s, e) {
      var ids = null, lats = null, lons = null;
      eachField(b, s, e, function (fno, wt, f) {
        if (wt !== 2) return;
        if (fno === 1) ids = packedVarints(b, f.start, f.end);
        else if (fno === 8) lats = packedVarints(b, f.start, f.end);
        else if (fno === 9) lons = packedVarints(b, f.start, f.end);
      });
      if (!ids || !lats || !lons) return;
      var id = 0, lat = 0, lon = 0;
      var n = Math.min(ids.length, lats.length, lons.length);
      for (var i = 0; i < n; i++) {
        id += zigzag(ids[i]); lat += zigzag(lats[i]); lon += zigzag(lons[i]);
        nodes.push({
          id: id,
          lat: scale * (latOff + granularity * lat),
          lon: scale * (lonOff + granularity * lon),
        });
      }
    }
    function decodeWay(b, s, e) {
      var id = 0, refs = null;
      eachField(b, s, e, function (fno, wt, f) {
        if (fno === 1 && wt === 0) id = f.varint;
        else if (fno === 8 && wt === 2) refs = packedVarints(b, f.start, f.end);
      });
      if (!refs || !refs.length) return;
      var rid = 0, out = [];
      for (var i = 0; i < refs.length; i++) { rid += zigzag(refs[i]); out.push(rid); }
      ways.push({ id: id, refs: out });
    }
    return { nodes: nodes, ways: ways };
  }

  // Read the BlobHeader{type,datasize} from buf at `pos` (after its int32-BE length
  // prefix has been consumed). Returns { type, datasize }.
  function readBlobHeader(buf, start, end) {
    var type = "", datasize = 0;
    eachField(buf, start, end, function (fno, wt, f) {
      if (fno === 1 && wt === 2) type = bytesToStr(buf, f.start, f.end);
      else if (fno === 3 && wt === 0) datasize = f.varint;
    });
    return { type: type, datasize: datasize };
  }

  // Read a Blob{raw|zlib_data}: returns { raw:[s,e] } or { zlib:[s,e] } (slice into buf).
  function readBlob(buf, start, end) {
    var raw = null, zlib = null;
    eachField(buf, start, end, function (fno, wt, f) {
      if (fno === 1 && wt === 2) raw = [f.start, f.end];        // uncompressed
      else if (fno === 3 && wt === 2) zlib = [f.start, f.end];  // zlib_data
    });
    return { raw: raw, zlib: zlib };
  }

  function bytesToStr(buf, s, e) {
    var out = "";
    for (var i = s; i < e; i++) out += String.fromCharCode(buf[i]);
    try { return decodeURIComponent(escape(out)); } catch (x) { return out; }
  }

  // zlib inflate via the native DecompressionStream (browser + node ≥18). Returns
  // a Promise<Uint8Array>. We feed the zlib stream ("deflate" = zlib-wrapped).
  async function inflate(u8) {
    var DS = root.DecompressionStream;
    if (!DS) throw new Error("DecompressionStream unavailable");
    var ds = new DS("deflate");
    var w = ds.writable.getWriter(); w.write(u8); w.close();
    var chunks = [], r = ds.readable.getReader();
    for (;;) { var x = await r.read(); if (x.done) break; chunks.push(x.value); }
    var len = chunks.reduce(function (a, c) { return a + c.length; }, 0);
    var out = new Uint8Array(len), o = 0;
    for (var i = 0; i < chunks.length; i++) { out.set(chunks[i], o); o += chunks[i].length; }
    return out;
  }

  // --- top-level: parse a whole .osm.pbf ArrayBuffer (BOUNDED) --- //
  // opts.maxBlocks (default 12), opts.maxNodes (default 200000): hard caps so a
  // huge region degrades to an honest PREVIEW. Returns
  //   { nodes, ways, bbox:{minLat,minLon,maxLat,maxLon}, blocks, truncated }.
  async function parse(arrayBuffer, opts) {
    opts = opts || {};
    var maxBlocks = opts.maxBlocks || 12;
    var maxNodes = opts.maxNodes || 200000;
    var buf = new Uint8Array(arrayBuffer);
    var dv = new DataView(arrayBuffer);
    var pos = 0, blocks = 0, truncated = false;
    var nodes = [], ways = [];
    while (pos + 4 <= buf.length) {
      var hlen = dv.getInt32(pos, false); pos += 4;          // int32-BE BlobHeader length
      if (hlen <= 0 || pos + hlen > buf.length) break;
      var hdr = readBlobHeader(buf, pos, pos + hlen); pos += hlen;
      if (pos + hdr.datasize > buf.length) break;
      var blobS = pos, blobE = pos + hdr.datasize; pos = blobE;
      if (hdr.type !== "OSMData") continue;                  // skip OSMHeader (+ any other)
      var blob = readBlob(buf, blobS, blobE);
      var pbStart, pbEnd, pbBuf;
      if (blob.raw) { pbBuf = buf; pbStart = blob.raw[0]; pbEnd = blob.raw[1]; }
      else if (blob.zlib) {
        var inflated = await inflate(buf.subarray(blob.zlib[0], blob.zlib[1]));
        pbBuf = inflated; pbStart = 0; pbEnd = inflated.length;
      } else continue;
      var geo = decodePrimitiveBlock(pbBuf, pbStart, pbEnd);
      for (var i = 0; i < geo.nodes.length && nodes.length < maxNodes; i++) nodes.push(geo.nodes[i]);
      for (var j = 0; j < geo.ways.length; j++) ways.push(geo.ways[j]);
      blocks++;
      if (blocks >= maxBlocks || nodes.length >= maxNodes) { truncated = pos < buf.length; break; }
    }
    // bbox from the decoded nodes (honest: only what we parsed).
    var bbox = null;
    for (var k = 0; k < nodes.length; k++) {
      var nd = nodes[k];
      if (!bbox) bbox = { minLat: nd.lat, maxLat: nd.lat, minLon: nd.lon, maxLon: nd.lon };
      else {
        if (nd.lat < bbox.minLat) bbox.minLat = nd.lat; if (nd.lat > bbox.maxLat) bbox.maxLat = nd.lat;
        if (nd.lon < bbox.minLon) bbox.minLon = nd.lon; if (nd.lon > bbox.maxLon) bbox.maxLon = nd.lon;
      }
    }
    return { nodes: nodes, ways: ways, bbox: bbox, blocks: blocks, truncated: truncated };
  }

  var API = {
    readVarint: readVarint, zigzag: zigzag, eachField: eachField,
    packedVarints: packedVarints, decodePrimitiveBlock: decodePrimitiveBlock,
    readBlobHeader: readBlobHeader, readBlob: readBlob, inflate: inflate, parse: parse,
  };
  root.OOPBF = API;
  if (typeof module !== "undefined" && module.exports) module.exports = API;  // node test
})(typeof self !== "undefined" ? self : (typeof globalThis !== "undefined" ? globalThis : this));
