# OS3 - errors and surprises

- **`sqlite3` CLI missing in the Ubuntu VM** - `preflight.sh` failed. Fix:
  `sudo apt install -y sqlite3`.
- **WAN flag started offline (inherited from OS5)** - `ipc.py` cleared the flag at
  start, so nothing synced until someone pressed "Restore". Fixed with `set()`.
- **TTL checked too early (own design flaw)** - the first version checked the TTL
  right after deciding, and nothing consumed the commands. Redesigned: the Processor
  only issues commands, a separate Actuator checks freshness with its own clock, and
  the TTL counts from the sensor reading. Verified by slowing the Actuator
  (`EDGE_ACTUATOR_DELAY_S=16`): stale commands were rejected and the sign stayed at 50.
- **Fixed 5 ms pause made the race demo too stable** - lost updates were not always
  visible. Changed to a random 0-5 ms pause (same lesson as OS1-2).
- **Receiver database shared between runs** - the mock receiver used one fixed file,
  so test runs mixed their counts. It now sits next to the node database.
- **Fixed ports** - another program on the machine can hold 8000 or 8001.
  `EDGE_API_PORT` and `EDGE_RECEIVER_PORT` move the node.
- **OS3-3 check was wrong, not the queue** - the first version asked that the newest
  item of every producer survive. With several producers, another producer's newer
  items can legitimately push it out. The check now uses one producer and no consumer:
  exactly the newest 500 items must survive.
- **BIS dataset columns not verified (first version)** - the real schema of data.go.kr
  dataset 15048265 could not be confirmed, so the loader accepted several column names and
  a clearly labelled synthetic file was used until the real data was available.
- **Real file has swapped latitude/longitude columns** - in 15074309 the `위도` column holds
  values like 126.67 and `경도` holds 37.45. The first run with the real file skipped all
  7237 rows. Fix: a row whose latitude is above 90 and whose longitude is a valid latitude
  is read swapped and counted in `swapped_rows`. Rows with location 0 are skipped and counted.
- **Headers with spaces** - the real headers are "정류소 명", "정류소 ID". Headers are now
  compared ignoring case and all whitespace.
- **Docker Desktop is not the Ubuntu VM** - Docker Desktop installs Docker on Windows;
  a separate Ubuntu VM cannot see it. The container was run from PowerShell on Windows.
- **Docker Desktop installer: "Virtual Machine Platform" not enabled** - a per-user
  install cannot enable it. Fix: install for all users (administrator) and restart.
