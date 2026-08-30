# v3.5.6 real-runtime regression case

Observed upgrade state:

- `retry_wait=11`
- `capacity_wait=1121`
- worker queue empty
- repeated scans submit `0`
- previous error contains `源文件未进入 MoviePilot 预览`

Expected after v3.5.6 first scan:

1. only legacy retry rows whose `last_error` contains the missing-preview token get `retry_at=0`;
2. those rows become `ready` through the existing OrganizerStateStore classifier;
3. the current sticky Season can be submitted again immediately;
4. v3.5.5 performs MoviePilot per-member preview rescue;
5. unresolved members become blocked, safe members continue, and TV sticky can release;
6. unrelated retry rows keep their original backoff.
