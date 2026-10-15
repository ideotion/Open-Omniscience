import json,sys
r=json.load(open(sys.argv[1])); print(sys.argv[1], r["status"], r.get("reason"))
for p in r["phases"]:
    print(" ",p["name"],p["status"],p["wall_seconds"],"s | peak rss",round((p.get("peak_rss_bytes") or 0)/1e6),"MB | disk peak",round((p.get("disk_used_peak_bytes") or 0)/1e6),"MB | mem avail min",round((p.get("memory_available_min_bytes") or 0)/1e6),"MB")
    if p.get("error_tail"): print("   ERR",p["error_tail"][:300].replace("\n"," // "))
    a=p.get("app_report")
    if a and p["name"]=="ingest":
        c=a["counts"]; o=sum(c[k] for k in ("building","road","poi","place","landuse","water","power","admin"))
        print("   objects",o,"osm_db(+wal)",a["osm_db_bytes"],"extract",a["extract_bytes"],"B/object",round(a["osm_db_bytes"]/max(o,1)),"obj/s",round(o/p["wall_seconds"]), "border",a["border"].get("ways_found"),"ways_missing_loc",c["ways_missing_locations"])
