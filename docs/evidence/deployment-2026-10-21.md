# Mac Worker deployment 2026-10-20T23:21:23Z

## Preconditions
- execution_units: unit-local-mac-02, owner=NULL, browser_stopped=true, generation=9
- active root tasks: none
- no real task created

## Backup / candidate
- .runtime/backups/perf03-20261021/deployed-baseline (running 23:05 code)
- .runtime/backups/perf03-20261021/candidate (new code)
- SHA256SUMS recorded; see manifest DEPLOY.md

## Restart
- launchctl kickstart -k gui/501/com.yumeng.xingtu.collection-worker
- before: PID 20406, runs=2
- after: PID 54216, runs=3, state=running
- startup log: 2026-10-21 07:20:31,065 INFO xingtu.worker collection worker polling xingtu-unit-local-mac-02 on 100.86.124.51:7233

## Temporal poller
- xingtu-unit-local-mac-02: alive=True, fresh_pollers=2, poller_entries=2, freshest_age=40.9s, checked_at 2026-10-20T23:21:12Z

## Candidate SHA256
fda504f2e5a9e598357c0b1e60345615b8cdff4c2d6703e059c704a6f60c92d8  deployed-baseline/browser_host.py
1c0da6f48142338513b185e897c631a19accfcafc0c6157791574e0c951a2eec  deployed-baseline/engine.py
51d127c4d9223567503a74c48efb7acccbb5ebae982a04514c81f17da8c9337b  deployed-baseline/repository.py
65d34a67702e2dc7a77bfbd5aa306d9fd7b6209f691b1745de88801774ab42da  deployed-baseline/worker.py
1e80bb8329e1e8859ce923b7fcea451dc8ff94f07e8573ba0f85155f7ff3146a  candidate/browser_host.py
ae91389ebd4a4da1b3c1285da1e9fdd52a29b8e16b8b33b4d83067e0c3e68c76  candidate/engine.py
549c579696108b8d9f8dcef04c450d1f7f73cb142d3b5f51d54b259458c31c5a  candidate/repository.py
639377a723f3187de285f79c7b532effd17831b66e2ecb3e379da8286526e63d  candidate/worker.py

## Blockade
- Mac phone WiFi is symmetric NAT; Tailscale relay sea 378ms; DB connect timeouts; MinIO GET 27KiB/s.
- Real 宠物/10 NOT created; no production data changed.
- Playwright MCP tool is not mounted in this session; real browser acceptance pending network restoration (will use system Chrome via Playwright, or MCP if enabled).
