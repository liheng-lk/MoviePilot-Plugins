# GuangYa Transfer Assistant Single-File Design

**Date:** 2026-09-12

## Goal

将 `plugins.v3/guangyatransferassistant` 的全部 Python 运行时代码收敛到唯一的 `__init__.py`，同时完成统一业务主链：

MoviePilot 订阅 → TG/GYING 资源发现 → 资源匹配 → 按资源类型执行 → 真实落盘确认 → MP 优先命名 → 通知。

## Runtime file constraint

插件目录中最终只允许一个 Python 运行时文件：

- `plugins.v3/guangyatransferassistant/__init__.py`

允许继续保留 `plugin.json`、README、图片、说明文档等非 Python 资源。测试代码保留在 `tests/v3/guangyatransferassistant/`。

## Single-file internal architecture

`__init__.py` 按职责区域组织，不再使用跨文件 Mixin 链：

1. constants / regex / lightweight data helpers
2. MoviePilot subscription routing and synchronization
3. Telegram resource discovery
4. GYING resource discovery
5. normalized resource candidate model
6. media / year / season / episode matching
7. execution routing
8. GuangYa share direct restore
9. Xunlei JSON flash-transfer
10. Magnet / ED2K cloudcollection
11. remote landing verification
12. MP-priority final naming
13. notification / status / API / UI
14. public `GuangYaTransferAssistant` plugin class

Historical persisted keys and public API routes remain compatible where needed, but new internal symbols do not add version suffixes.

## Resource execution contract

- `magnet` → GuangYa native `cloudcollection`
- `ed2k` → GuangYa native `cloudcollection`
- `xunlei` → resolve share → build JSON → select authoritative missing episodes → GuangYa flash transfer
- `guangya` → native GuangYa share restore API

TG and GYING are discovery providers only. They emit normalized candidates and never implement separate transfer semantics.

## Matching contract

MoviePilot subscription identity is authoritative:

- title / aliases
- media type
- year
- season
- authoritative missing episodes

A candidate can execute only after the final payload gate confirms that real share/file metadata is compatible with the subscription. Physical episode coverage must be a subset of the authoritative missing set.

## Naming contract

MoviePilot-recognized identity has highest priority.

TV target:

`<MP剧名> - SxxExx - <retained technical tags>.<ext>`

Movie target:

`<MP片名> (<year>) - <retained technical tags>.<ext>`

Retain useful source tags when present, including resolution, source, codec, HDR/DV, audio and release group. Do not reintroduce incorrect source title/year/episode identity.

## Success contract

A transfer is not complete merely because an API returned success or a task reached completed. Success requires:

1. candidate identity accepted;
2. requested missing episode/movie selected;
3. transfer method succeeds;
4. expected real file appears in target GuangYa directory;
5. file size / identity evidence is valid when available;
6. final filename is confirmed;
7. completion notification is emitted exactly once.

Pre-existing same-name files must not be attributed to a new task without new-file evidence.

## Source priority

The runtime priority remains:

`Xunlei flash > GuangYa direct share > Magnet > ED2K`

No normal MoviePilot downloader, qBittorrent, Transmission, Aria2, local full-file relay or OSS fallback is introduced.

## Migration rule

This is a structural migration first. Existing behavior contracts must remain green while modules are inlined. Business behavior changes are added only after the single-file runtime is stable.

## Test gates

- plugin directory contains exactly one `*.py`: `__init__.py`
- no relative imports from removed runtime modules
- full GuangYa contract suite passes
- dedicated tests cover four resource routes, MP-priority naming, landing verification and single notification semantics
