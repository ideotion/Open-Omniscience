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

  // Decode a PrimitiveBlock StringTable (field 1): repeated bytes s = 1. Index 0
  // is the empty string by convention. Tags + member roles index into this table,
  // which is BLOCK-LOCAL — so they must be resolved here, where it is in scope.
  function decodeStringTable(buf, s, e) {
    var out = [];
    eachField(buf, s, e, function (fno, wt, f) {
      if (fno === 1 && wt === 2) out.push(bytesToStr(buf, f.start, f.end));
    });
    return out;
  }

  // Resolve a packed pair of stringtable indices (keys[], vals[]) into a {key:val}
  // object (Way + Relation tags). Missing/short -> {} (honest, never invents).
  function resolveTags(keys, vals, strtab) {
    var tags = {};
    if (!keys || !vals) return tags;
    var n = Math.min(keys.length, vals.length);
    for (var i = 0; i < n; i++) {
      var k = strtab[keys[i]];
      if (k != null) tags[k] = vals[i] != null && strtab[vals[i]] != null ? strtab[vals[i]] : "";
    }
    return tags;
  }

  // Decode an (uncompressed) PrimitiveBlock buffer slice into geometry.
  // Returns { nodes:[{id,lat,lon}], ways:[{id,refs[,tags]}], relations:[...] }.
  // opts.withTags attaches resolved tags to ways; opts.withRelations decodes
  // relations (members {ref,type,role} + resolved tags) — both needed to assemble
  // admin (country) boundaries. ids are GLOBAL; strings are block-local (resolved
  // here). Default (no opts) keeps the original geometry-only shape (+ relations:[]).
  function decodePrimitiveBlock(buf, start, end, opts) {
    opts = opts || {};
    var wantTags = !!opts.withTags, wantRels = !!opts.withRelations;
    var granularity = 100, latOff = 0, lonOff = 0;
    var groups = [], strRange = null;
    eachField(buf, start, end, function (fno, wt, f) {
      if (fno === 1 && wt === 2) strRange = [f.start, f.end];        // StringTable
      else if (fno === 2 && wt === 2) groups.push([f.start, f.end]); // PrimitiveGroup
      else if (fno === 17 && wt === 0) granularity = f.varint;       // granularity
      else if (fno === 19 && wt === 0) latOff = f.varint;            // lat_offset (nano-deg)
      else if (fno === 20 && wt === 0) lonOff = f.varint;            // lon_offset
    });
    var strtab = (wantTags || wantRels) && strRange ? decodeStringTable(buf, strRange[0], strRange[1]) : [];
    var nodes = [], ways = [], relations = [];
    var scale = 1e-9;
    for (var gi = 0; gi < groups.length; gi++) {
      eachField(buf, groups[gi][0], groups[gi][1], function (fno, wt, f) {
        if (fno === 2 && wt === 2) decodeDense(buf, f.start, f.end);
        else if (fno === 3 && wt === 2) decodeWay(buf, f.start, f.end);
        else if (fno === 4 && wt === 2 && wantRels) decodeRelation(buf, f.start, f.end);
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
      var id = 0, refs = null, keys = null, vals = null;
      eachField(b, s, e, function (fno, wt, f) {
        if (fno === 1 && wt === 0) id = f.varint;
        else if (fno === 2 && wt === 2 && wantTags) keys = packedVarints(b, f.start, f.end);  // tag keys
        else if (fno === 3 && wt === 2 && wantTags) vals = packedVarints(b, f.start, f.end);  // tag vals
        else if (fno === 8 && wt === 2) refs = packedVarints(b, f.start, f.end);              // node refs (delta)
      });
      if (!refs || !refs.length) return;
      var rid = 0, out = [];
      for (var i = 0; i < refs.length; i++) { rid += zigzag(refs[i]); out.push(rid); }
      var w = { id: id, refs: out };
      if (wantTags) w.tags = resolveTags(keys, vals, strtab);
      ways.push(w);
    }
    // Relation{ 1:id, 2:keys, 3:vals, 8:roles_sid(int32 idx), 9:memids(sint64 delta),
    //           10:types(0 node,1 way,2 rel) } — used for admin (country) boundaries.
    function decodeRelation(b, s, e) {
      var id = 0, keys = null, vals = null, roles = null, memids = null, types = null;
      eachField(b, s, e, function (fno, wt, f) {
        if (fno === 1 && wt === 0) id = f.varint;
        else if (fno === 2 && wt === 2) keys = packedVarints(b, f.start, f.end);
        else if (fno === 3 && wt === 2) vals = packedVarints(b, f.start, f.end);
        else if (fno === 8 && wt === 2) roles = packedVarints(b, f.start, f.end);
        else if (fno === 9 && wt === 2) memids = packedVarints(b, f.start, f.end);   // sint64 delta
        else if (fno === 10 && wt === 2) types = packedVarints(b, f.start, f.end);
      });
      var members = [];
      if (memids && types) {
        var mid = 0, m = Math.min(memids.length, types.length);
        for (var i = 0; i < m; i++) {
          mid += zigzag(memids[i]);
          members.push({ ref: mid, type: types[i], role: roles ? (strtab[roles[i]] || "") : "" });
        }
      }
      relations.push({ id: id, tags: resolveTags(keys, vals, strtab), members: members });
    }
    return { nodes: nodes, ways: ways, relations: relations };
  }

  // --- admin (country) boundary assembly (pure, node-tested) --- //

  // Stitch open way segments (each [{lat,lon}...]) into CLOSED rings by matching
  // shared endpoints. Returns rings as [[lon,lat]...] (the world_countries.json
  // convention). A segment that never closes is DROPPED — honest, no fake border.
  function stitchRings(segs) {
    var EPS = 1e-7;
    function same(a, b) { return Math.abs(a.lat - b.lat) < EPS && Math.abs(a.lon - b.lon) < EPS; }
    var pool = (segs || []).filter(function (s) { return s && s.length >= 2; });
    var used = new Array(pool.length).fill(false);
    var rings = [];
    for (var i = 0; i < pool.length; i++) {
      if (used[i]) continue;
      used[i] = true;
      var ring = pool[i].slice(), progressed = true;
      while (progressed && !same(ring[0], ring[ring.length - 1])) {
        progressed = false;
        for (var j = 0; j < pool.length; j++) {
          if (used[j]) continue;
          var seg = pool[j], tail = ring[ring.length - 1];
          if (same(tail, seg[0])) { ring = ring.concat(seg.slice(1)); used[j] = true; progressed = true; break; }
          if (same(tail, seg[seg.length - 1])) { ring = ring.concat(seg.slice(0, -1).reverse()); used[j] = true; progressed = true; break; }
        }
      }
      if (ring.length >= 4 && same(ring[0], ring[ring.length - 1])) {
        rings.push(ring.map(function (p) { return [p.lon, p.lat]; }));
      }
    }
    return rings;
  }

  // Assemble country (admin_level=2) boundary polygons from a region parsed with
  // parse(buf, {withTags:true, withRelations:true}). Keyed by the ISO 3166-1 alpha-2
  // tag so the result MERGES into the choropleth by code (fixing microstates the
  // coarse 110m geometry drops). Honest: emits ONLY rings we actually CLOSED from
  // resolved coordinates — never fabricates a border or a code. opts.adminLevel
  // (default "2") picks the boundary level. Returns [{iso2,name,rings,source}].
  function assembleAdminAreas(parsed, opts) {
    opts = opts || {};
    var level = String(opts.adminLevel || "2");
    var nodes = (parsed && parsed.nodes) || [], ways = (parsed && parsed.ways) || [],
        rels = (parsed && parsed.relations) || [];
    var nodeById = new Map(); for (var i = 0; i < nodes.length; i++) nodeById.set(nodes[i].id, nodes[i]);
    var wayById = new Map(); for (var j = 0; j < ways.length; j++) wayById.set(ways[j].id, ways[j]);
    var areas = [];
    function isCountry(tags) {
      if (!tags || String(tags["admin_level"]) !== level) return false;
      return tags["boundary"] === "administrative" || tags["ISO3166-1:alpha2"] != null || tags["ISO3166-1"] != null;
    }
    function iso2Of(tags) {
      var c = tags["ISO3166-1:alpha2"] || tags["ISO3166-1"] || "";
      return /^[A-Za-z]{2}$/.test(c) ? c.toUpperCase() : "";
    }
    function wayCoords(wid) {                          // resolve refs -> coords (drop unresolved)
      var w = wayById.get(wid); if (!w) return null;
      var cs = []; for (var k = 0; k < w.refs.length; k++) { var nd = nodeById.get(w.refs[k]); if (nd) cs.push(nd); }
      return cs.length >= 2 ? cs : null;
    }
    for (var r = 0; r < rels.length; r++) {
      var rel = rels[r];
      if (!isCountry(rel.tags)) continue;
      var iso = iso2Of(rel.tags); if (!iso) continue; // can't place on the code-keyed choropleth
      var segs = [];
      for (var mi = 0; mi < rel.members.length; mi++) {
        var mem = rel.members[mi];
        if (mem.type !== 1) continue;                  // ways only
        if (mem.role && mem.role !== "outer") continue;// outer rings (inner/holes skipped)
        var cs = wayCoords(mem.ref); if (cs) segs.push(cs);
      }
      var rings = stitchRings(segs);
      if (rings.length) areas.push({ iso2: iso, name: rel.tags["name"] || "", rings: rings, source: "osm-relation" });
    }
    for (var w2 = 0; w2 < ways.length; w2++) {         // standalone closed boundary ways
      var ww = ways[w2];
      if (!isCountry(ww.tags)) continue;
      var iso2 = iso2Of(ww.tags); if (!iso2) continue;
      var cs2 = wayCoords(ww.id); if (!cs2) continue;
      var rings2 = stitchRings([cs2]);
      if (rings2.length) areas.push({ iso2: iso2, name: ww.tags["name"] || "", rings: rings2, source: "osm-way" });
    }
    return areas;
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
    var nodes = [], ways = [], relations = [];
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
      var geo = decodePrimitiveBlock(pbBuf, pbStart, pbEnd, opts);
      for (var i = 0; i < geo.nodes.length && nodes.length < maxNodes; i++) nodes.push(geo.nodes[i]);
      for (var j = 0; j < geo.ways.length; j++) ways.push(geo.ways[j]);
      for (var rr = 0; geo.relations && rr < geo.relations.length; rr++) relations.push(geo.relations[rr]);
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
    return { nodes: nodes, ways: ways, relations: relations, bbox: bbox, blocks: blocks, truncated: truncated };
  }

  var API = {
    readVarint: readVarint, zigzag: zigzag, eachField: eachField,
    packedVarints: packedVarints, decodeStringTable: decodeStringTable, resolveTags: resolveTags,
    decodePrimitiveBlock: decodePrimitiveBlock, stitchRings: stitchRings,
    assembleAdminAreas: assembleAdminAreas,
    readBlobHeader: readBlobHeader, readBlob: readBlob, inflate: inflate, parse: parse,
  };
  root.OOPBF = API;
  if (typeof module !== "undefined" && module.exports) module.exports = API;  // node test
})(typeof self !== "undefined" ? self : (typeof globalThis !== "undefined" ? globalThis : this));
