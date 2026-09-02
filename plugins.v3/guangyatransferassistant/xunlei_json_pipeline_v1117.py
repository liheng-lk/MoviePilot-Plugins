"""按用户已验证秒传脚本复刻“迅雷生成 JSON -> 光鸭导入 JSON”两阶段协议。

不要再把迅雷分享读取和光鸭秒传接口拼成一条自创流程。稳定脚本的真实边界是：
1. 迅雷侧把分享文件导出成标准 JSON（sourceTag=xunlei，顶层/行级同时保留
   shareId/passCodeToken，并保留 gcid/md5/cid/tripleCid/wholeCid/downloadUrl）；
2. 光鸭侧 importMd5Json 解析该 JSON，再按既定候选顺序探测 get_res_center_token /
   check_can_flash_upload。

MoviePilot 版本唯一主动裁掉的是 capacity=1/OSS 普通上传兜底：迅雷在插件里只作为
“秒传来源”，秒传不命中必须回退光鸭分享/Magnet/ED2K，不能把大文件下载到 MP。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from .xunlei_flash_v193 import _HEX32_RE, _HEX40_RE, _pick_download_url, _safe_int


class GuangYaXunleiJsonPipelineV1117Mixin:
    """复刻稳定脚本的 Xunlei JSON 生产/消费合同。"""

    build_id = "20260902-r30"

    # ------------------------------------------------------------------
    # Stage A: 迅雷分享 -> 标准 JSON 模板
    # ------------------------------------------------------------------
    def _xunlei_share_files(self, share_id: str, pass_code_token: str) -> List[Dict[str, Any]]:
        rows = list(super()._xunlei_share_files(share_id, pass_code_token) or [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            row["shareId"] = str(share_id or "")
            row["passCodeToken"] = str(pass_code_token or "")
            row["sourceTag"] = "xunlei"
            row["sourceXunlei"] = True
            if row.get("id") and not row.get("fileId"):
                row["fileId"] = str(row.get("id") or "")
        return rows

    def _xunlei_post_json_v1117(self, endpoint: str, body: Dict[str, Any], *, action: str) -> Dict[str, Any]:
        """分享下载链接 POST 路径；保持匿名分享头，不携带用户 Bearer。"""
        url = f"https://api-pan.xunlei.com{endpoint}"
        last_error = ""
        for attempt in range(2):
            headers = dict(self._xunlei_headers(action, refresh=False) or {})
            if not headers.get("x-captcha-token"):
                raise RuntimeError("迅雷 captcha_token 不可用")
            session = self._xunlei_session()
            try:
                response = session.post(
                    url,
                    json=dict(body or {}),
                    headers=headers,
                    timeout=int(getattr(self, "_provider_timeout", 15) or 15),
                )
                try:
                    payload = response.json()
                except Exception:
                    payload = {}
                if response.status_code < 400:
                    return payload if isinstance(payload, dict) else {}
                last_error = str(
                    (payload or {}).get("error_description")
                    or (payload or {}).get("error")
                    or (payload or {}).get("message")
                    or response.text
                    or f"HTTP {response.status_code}"
                )[:300]
                captcha_error = False
                try:
                    captcha_error = bool(self._xunlei_captcha_error(response, payload))
                except Exception:
                    captcha_error = response.status_code in (400, 401, 403) and "captcha" in last_error.lower()
                if attempt == 0 and captcha_error:
                    self._xunlei_runtime_captcha_token = ""
                    refreshed = str(self._refresh_xunlei_captcha(action) or "")
                    if refreshed:
                        continue
                break
            except requests.RequestException as err:
                last_error = str(err)[:300]
                break
        raise RuntimeError(f"迅雷分享下载链接接口失败：{last_error or 'unknown error'}")

    def _xunlei_file_info(self, share_id: str, pass_code_token: str, row: Dict[str, Any]) -> Dict[str, Any]:
        """等价稳定脚本 getFileDetail/_fetchFileHash 的服务端精简版。"""
        merged = dict(row or {})
        merged["shareId"] = str(share_id or "")
        merged["passCodeToken"] = str(pass_code_token or "")
        merged["sourceTag"] = "xunlei"
        merged["sourceXunlei"] = True
        if merged.get("id") and not merged.get("fileId"):
            merged["fileId"] = str(merged.get("id") or "")

        # 快速通道：与脚本 _fetchFileHash 一致，优先 share/file_info。
        try:
            first = dict(super()._xunlei_file_info(share_id, pass_code_token, merged) or merged)
            for key, value in first.items():
                if value not in (None, "", [], {}):
                    merged[key] = value
        except Exception:
            pass

        file_id = str(merged.get("id") or merged.get("fileId") or "").strip()
        parent_id = str(merged.get("parent_id") or merged.get("parentId") or "").strip()

        # 如果 file_info 没给真实下载地址，按脚本继续查当前 parent 的 share/detail。
        if file_id and not str(merged.get("download_url") or merged.get("downloadUrl") or "").strip():
            for with_audit in ("true", "false"):
                try:
                    detail = self._xunlei_get(
                        "/drive/v1/share/detail",
                        {
                            "share_id": share_id,
                            "parent_id": parent_id,
                            "pass_code_token": pass_code_token,
                            "limit": 200,
                            "with_audit": with_audit,
                            "thumbnail_size": "SIZE_LARGE",
                            "usage": "CONSUME",
                        },
                        action="get:/drive/v1/share/detail",
                    )
                    candidates = detail.get("files") or (detail.get("data") or {}).get("files") or []
                    hit = next(
                        (item for item in candidates if isinstance(item, dict) and str(item.get("id") or item.get("file_id") or "") == file_id),
                        None,
                    )
                    if isinstance(hit, dict):
                        normalized = self._xunlei_normalize_file(
                            hit,
                            str(merged.get("path") or "").rsplit("/", 1)[0],
                            parent_id,
                        )
                        for key in ("gcid", "md5", "cid", "download_url", "size"):
                            if normalized.get(key):
                                merged[key] = normalized[key]
                        if merged.get("download_url"):
                            break
                except Exception:
                    continue

        # 与稳定脚本 Path 3 一致：GET/detail 仍没 downloadUrl 时尝试 POST 下载链接端点。
        if file_id and not str(merged.get("download_url") or merged.get("downloadUrl") or "").strip():
            post_candidates: List[Tuple[str, Dict[str, Any]]] = [
                ("/drive/v1/share/download", {"share_id": share_id, "file_ids": [file_id], "pass_code_token": pass_code_token}),
                (f"/drive/v1/share/{share_id}/download", {"file_ids": [file_id], "pass_code_token": pass_code_token}),
                ("/drive/v1/share/files/download", {"share_id": share_id, "file_id": file_id, "pass_code_token": pass_code_token}),
                ("/drive/v1/share/file/download", {"share_id": share_id, "file_id": file_id, "pass_code_token": pass_code_token}),
            ]
            for endpoint, payload in post_candidates:
                try:
                    body = self._xunlei_post_json_v1117(endpoint, payload, action=f"post:{endpoint}")
                    dl = str(_pick_download_url(body) or "").strip().strip("`\"'")
                    if dl.lower().startswith(("http://", "https://")):
                        merged["download_url"] = dl
                        break
                except Exception:
                    continue

        # 稳定脚本路径 4：files/{id} 同时尝试分享 query。该端点在部分账号/区域
        # 才会返回 web_content_link，因此只作为兜底，且仍透传分享上下文。
        if file_id and not str(merged.get("download_url") or merged.get("downloadUrl") or "").strip():
            try:
                detail = self._xunlei_get(
                    f"/drive/v1/files/{file_id}",
                    {
                        "space": "",
                        "usage": "CONSUME",
                        "share_id": share_id,
                        "pass_code_token": pass_code_token,
                    },
                    action=f"get:/drive/v1/files/{file_id}",
                )
                normalized = self._xunlei_normalize_file(
                    dict(detail or {}),
                    str(merged.get("path") or "").rsplit("/", 1)[0],
                    parent_id,
                )
                for key in ("gcid", "md5", "cid", "download_url", "size"):
                    if normalized.get(key):
                        merged[key] = normalized[key]
            except Exception:
                pass

        # 稳定脚本路径 5：最后才尝试 share/save。响应可能直接带文件信息，
        # 也可能只给 task_id；后一种必须先回查任务，再读取新文件详情。
        if file_id and share_id and pass_code_token and not str(
            merged.get("download_url") or merged.get("downloadUrl") or ""
        ).strip():
            try:
                saved = self._xunlei_post_json_v1117(
                    "/drive/v1/share/save",
                    {
                        "share_id": share_id,
                        "file_ids": [file_id],
                        "pass_code_token": pass_code_token,
                    },
                    action="post:/drive/v1/share/save",
                )
                saved_data = saved.get("data") if isinstance(saved.get("data"), dict) else saved
                saved_hit = saved_data.get("file") if isinstance(saved_data, dict) and isinstance(saved_data.get("file"), dict) else saved_data
                task_id = str(
                    (saved_data or {}).get("task_id")
                    or (saved_data or {}).get("taskId")
                    or saved.get("task_id")
                    or saved.get("taskId")
                    or ""
                ).strip()
                if task_id:
                    for index in range(20):
                        try:
                            task = self._xunlei_get(
                                f"/drive/v1/tasks/{task_id}",
                                {},
                                action=f"get:/drive/v1/tasks/{task_id}",
                            )
                            task_data = task.get("data") if isinstance(task.get("data"), dict) else task
                            candidate = (
                                task_data.get("file")
                                or task_data.get("file_info")
                                or task_data.get("files")
                                or task_data.get("result")
                            ) if isinstance(task_data, dict) else None
                            if isinstance(candidate, list):
                                candidate = candidate[0] if candidate else None
                            if isinstance(candidate, dict):
                                saved_hit = candidate
                                break
                        except Exception:
                            pass
                        time.sleep(0.2 if index < 4 else 0.4)
                if isinstance(saved_hit, dict):
                    normalized = self._xunlei_normalize_file(
                        saved_hit,
                        str(merged.get("path") or "").rsplit("/", 1)[0],
                        parent_id,
                    )
                    for key in ("gcid", "md5", "cid", "download_url", "size"):
                        if normalized.get(key):
                            merged[key] = normalized[key]
            except Exception:
                pass

        # JSON 模板字段名与用户脚本对齐。
        if merged.get("download_url") and not merged.get("downloadUrl"):
            merged["downloadUrl"] = str(merged.get("download_url") or "")
        if merged.get("cid") and not merged.get("tripleCid"):
            cid = str(merged.get("cid") or "").strip()
            gcid = str(merged.get("gcid") or "").strip()
            if _HEX40_RE.fullmatch(cid) and cid.lower() != gcid.lower():
                merged["tripleCid"] = cid.lower()
        return merged

    @staticmethod
    def _xunlei_format_size_v1117(size: int) -> str:
        value = float(max(0, int(size or 0)))
        units = ("B", "KB", "MB", "GB", "TB")
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024.0
        return f"{int(size or 0)} B"

    def _xunlei_make_json_v1117(self, rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """等价 helper.makeJson(..., 'xunlei', {shareId, passCodeToken})。"""
        normalized: List[Dict[str, Any]] = []
        top_share = ""
        top_pass = ""
        for raw in rows:
            row = dict(raw or {})
            path = str(row.get("path") or row.get("name") or "").replace("\\", "/").strip()
            if not path:
                continue
            size = _safe_int(row.get("size") or row.get("fileSize"), 0)
            gcid = str(row.get("gcid") or "").strip().lower()
            md5 = str(row.get("md5") or "").strip().lower()
            # v1.1.3 脚本在迅雷极速 JSON 中使用 gcid 前 32 位作为 md5 兜底；
            # 用户实测 cid/downloadUrl 为空时，光鸭仍可据此全部瞬时命中。
            if not _HEX32_RE.fullmatch(md5) and _HEX40_RE.fullmatch(gcid):
                md5 = gcid[:32]
            file_id = str(row.get("fileId") or row.get("id") or "").strip()
            cid = str(row.get("cid") or "").strip()
            triple = str(row.get("tripleCid") or "").strip()
            whole = str(row.get("wholeCid") or "").strip()
            parent_id = str(row.get("parentId") or row.get("parent_id") or "").strip()
            download_url = str(row.get("downloadUrl") or row.get("download_url") or "").strip().strip("`\"'")
            share_id = str(row.get("shareId") or "").strip()
            pass_token = str(row.get("passCodeToken") or "").strip()
            top_share = top_share or share_id
            top_pass = top_pass or pass_token
            # 与 v1.1.3 makeJson 完全一致：行级只写 sourceXunlei，sourceTag 仅写顶层。
            entry: Dict[str, Any] = {"size": str(size), "path": path, "cid": cid, "parentId": parent_id, "downloadUrl": download_url, "sourceXunlei": True}
            if _HEX40_RE.fullmatch(gcid):
                entry["gcid"] = gcid
            if _HEX32_RE.fullmatch(md5):
                entry["md5"] = md5
            if file_id:
                entry["fileId"] = file_id
            if _HEX40_RE.fullmatch(triple):
                entry["tripleCid"] = triple
            if _HEX40_RE.fullmatch(whole):
                entry["wholeCid"] = whole
            if share_id:
                entry["shareId"] = share_id
            if pass_token:
                entry["passCodeToken"] = pass_token
            normalized.append(entry)

        total_size = sum(_safe_int(row.get("size"), 0) for row in normalized)
        result: Dict[str, Any] = {
            "scriptVersion": "1.1.3",
            "scriptAuthor": "sumuve",
            "totalFilesCount": len(normalized),
            "totalSize": total_size,
            "formattedTotalSize": self._xunlei_format_size_v1117(total_size),
            "files": normalized,
            "sourceTag": "xunlei",
        }
        if top_share:
            result["shareId"] = top_share
        if top_pass:
            result["passCodeToken"] = top_pass
        return result

    # ------------------------------------------------------------------
    # Stage B: 标准 JSON -> 光鸭 importMd5Json 的纯秒传子集
    # ------------------------------------------------------------------
    @staticmethod
    def _xunlei_unique_payloads_v1117(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        seen = set()
        for row in rows:
            key = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            if key in seen:
                continue
            seen.add(key)
            result.append(row)
        return result

    def _xunlei_import_json_file_v1117(
        self,
        subscribe: Any,
        obj: Dict[str, Any],
        source_row: Dict[str, Any],
    ) -> Dict[str, Any]:
        files = obj.get("files") if isinstance(obj, dict) else None
        if not isinstance(files, list) or not files:
            return {"success": False, "reason": "内部迅雷 JSON 中无 files 数组"}
        f = dict(files[0] or {})

        top_share = str(obj.get("shareId") or "").strip()
        top_pass = str(obj.get("passCodeToken") or "").strip()
        share_id = str(f.get("shareId") or top_share).strip()
        pass_token = str(f.get("passCodeToken") or top_pass).strip()
        gcid = str(f.get("gcid") or "").strip().upper()
        size = _safe_int(f.get("size"), 0)
        if not _HEX40_RE.fullmatch(gcid) or size <= 0:
            return {"success": False, "reason": "内部迅雷 JSON 缺少有效 GCID/size"}

        lower_gcid = gcid.lower()
        md5 = str(f.get("md5") or "").strip().lower()
        if not _HEX32_RE.fullmatch(md5):
            md5 = lower_gcid[:32]
        upper_md5 = md5.upper()

        cid_values: List[str] = []
        for raw in (f.get("cid"), f.get("tripleCid"), f.get("wholeCid")):
            value = str(raw or "").strip()
            if _HEX40_RE.fullmatch(value) and value.lower() != lower_gcid:
                if value.lower() not in cid_values:
                    cid_values.append(value.lower())
                if value.upper() not in cid_values:
                    cid_values.append(value.upper())

        download_url = str(f.get("downloadUrl") or "").strip().strip("`\"'")
        # 与 importMd5Json 一致：迅雷 JSON 有真实 downloadUrl 时，现场计算标准 3x20KB cid。
        if download_url.lower().startswith(("http://", "https://")):
            triple = str(self._xunlei_compute_triple_cid(download_url, size) or "").strip()
            if _HEX40_RE.fullmatch(triple) and triple.lower() != lower_gcid:
                for value in (triple.lower(), triple.upper()):
                    if value not in cid_values:
                        cid_values.insert(0, value)

        relative_path = str(f.get("path") or source_row.get("path") or source_row.get("name") or "file")
        _, parent_id = self._xunlei_target_parent(subscribe, relative_path)
        name = relative_path.replace("\\", "/").rsplit("/", 1)[-1] or "file"
        snapshot_fn = getattr(self, "_xunlei_snapshot_v1116", None)
        before = snapshot_fn(parent_id, name) if callable(snapshot_fn) else {}

        # importMd5Json 的 capacity=2 候选顺序。capacity=1 是普通上传，插件明确禁用。
        res_combos: List[Dict[str, Any]] = []
        for cid in cid_values:
            res_combos.append({"capacity": 2, "res": {"gcid": lower_gcid, "cid": cid, "fileSize": size}})
            if gcid != lower_gcid:
                res_combos.append({"capacity": 2, "res": {"gcid": gcid, "cid": cid, "fileSize": size}})

        md5_combos: List[Dict[str, Any]] = []
        if md5:
            for cid in cid_values:
                md5_combos.append({"capacity": 2, "res": {"gcid": lower_gcid, "cid": cid, "md5": md5, "fileSize": size}})
                if upper_md5 != md5:
                    md5_combos.append({"capacity": 2, "res": {"gcid": lower_gcid, "cid": cid, "md5": upper_md5, "fileSize": size}})
            md5_combos.append({"capacity": 2, "res": {"gcid": lower_gcid, "md5": md5, "fileSize": size}})
            if upper_md5 != md5:
                md5_combos.append({"capacity": 2, "res": {"gcid": lower_gcid, "md5": upper_md5, "fileSize": size}})
            md5_combos.append({"capacity": 2, "res": {"md5": md5, "fileSize": size}})

        token_candidates = self._xunlei_unique_payloads_v1117([
            *res_combos,
            *md5_combos,
            {"capacity": 2, "res": {"gcid": lower_gcid, "fileSize": size}},
            {"capacity": 2, "res": {"md5": lower_gcid[:32], "fileSize": size}},
        ])

        task_id = ""
        last_error = ""
        for candidate in token_candidates:
            try:
                body = self._guangya_userres_request(
                    "/userres/v1/get_res_center_token",
                    {
                        **candidate,
                        "name": name,
                        "parentId": str(parent_id or ""),
                    },
                )
            except Exception as err:
                last_error = str(err)[:240]
                continue
            code = body.get("code") if isinstance(body, dict) else None
            if code in (156, "156"):
                # 用户脚本把 156 作为已经确认的瞬时秒传命中。
                verify = getattr(self, "_xunlei_wait_exact_file_v1116", None)
                exact = verify(parent_id, name, size, attempts=8) if callable(verify) else {}
                return {
                    "success": True,
                    "instant": True,
                    "file_id": str((exact or {}).get("file_id") or ""),
                    "verified_size": _safe_int((exact or {}).get("size"), 0),
                    "json_stage": True,
                    "reason": "内部 JSON 导入：get_res_center_token code=156",
                }
            candidate_task = str(self._guangya_task_id(body) or "")
            if candidate_task:
                task_id = candidate_task
                break
            last_error = str(
                body.get("msg")
                or body.get("message")
                or body.get("error")
                or code
                or "秒传令牌未命中"
            )[:240]

        if not task_id:
            return {"success": False, "reason": last_error or "内部 JSON 导入未取得 upload task", "json_stage": True}

        # importMd5Json 的 check 候选：真实 cid 优先，其后 md5-only；没有任何两者才纯 gcid。
        checks: List[Dict[str, Any]] = []
        for cid in cid_values:
            checks.append({"taskId": task_id, "gcid": lower_gcid, "cid": cid, "fileSize": size})
            if gcid != lower_gcid:
                checks.append({"taskId": task_id, "gcid": gcid, "cid": cid, "fileSize": size})
            if md5:
                checks.append({"taskId": task_id, "gcid": lower_gcid, "cid": cid, "md5": md5, "fileSize": size})
                if upper_md5 != md5:
                    checks.append({"taskId": task_id, "gcid": lower_gcid, "cid": cid, "md5": upper_md5, "fileSize": size})
        if md5:
            checks.append({"taskId": task_id, "gcid": lower_gcid, "md5": md5, "fileSize": size})
            if upper_md5 != md5:
                checks.append({"taskId": task_id, "gcid": lower_gcid, "md5": upper_md5, "fileSize": size})
        if not checks:
            checks.append({"taskId": task_id, "gcid": lower_gcid, "fileSize": size})
        checks = self._xunlei_unique_payloads_v1117(checks)

        last_check: Dict[str, Any] = {}
        for check in checks:
            try:
                body = self._guangya_userres_request("/userres/v1/check_can_flash_upload", check)
            except Exception as err:
                last_error = str(err)[:240]
                continue
            last_check = dict(body or {})
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and data.get("canFlashUpload") is True:
                break

        check_data = last_check.get("data") if isinstance(last_check, dict) else None
        can_flash = isinstance(check_data, dict) and check_data.get("canFlashUpload") is True
        check_task = str((check_data or {}).get("taskId") or task_id) if isinstance(check_data, dict) else task_id
        had_real_cid = bool(cid_values)

        # 与稳定脚本一致：无 canFlashUpload 但返回 taskId，仅当确实有真实 cid 参与时才轮询。
        # 稳定脚本在这里还可走 OSS；MoviePilot 按既定策略禁用 OSS，所以无真实 cid 直接清 task 回退。
        if not can_flash and not had_real_cid:
            cleanup = getattr(self, "_xunlei_cleanup_placeholders_v1116", None)
            if callable(cleanup):
                cleanup(parent_id, name, size, before, task_id=check_task or task_id)
            else:
                try:
                    self._guangya_userres_request("/userres/v1/file/delete_upload_task", {"taskIds": [check_task or task_id]})
                except Exception:
                    pass
            return {
                "success": False,
                "task_id": check_task or task_id,
                "json_stage": True,
                "reason": "内部 JSON 导入未取得真实 CID/canFlashUpload；按纯秒传策略清理 task 并回退",
            }

        poll = getattr(self, "_xunlei_poll_task_integrity_v1116", None)
        verified = poll(check_task or task_id, parent_id, name, size) if callable(poll) else {}
        if verified:
            return {
                "success": True,
                "instant": True,
                "task_id": check_task or task_id,
                "file_id": str(verified.get("file_id") or ""),
                "verified_size": _safe_int(verified.get("size"), 0),
                "json_stage": True,
                "reason": "内部 JSON 导入：光鸭秒传完成，文件大小校验通过",
            }

        cleanup = getattr(self, "_xunlei_cleanup_placeholders_v1116", None)
        if callable(cleanup):
            recovered = cleanup(parent_id, name, size, before, task_id=check_task or task_id)
            if recovered:
                return {
                    "success": True,
                    "instant": True,
                    "task_id": check_task or task_id,
                    "file_id": str(recovered.get("file_id") or ""),
                    "verified_size": _safe_int(recovered.get("size"), 0),
                    "json_stage": True,
                    "reason": "内部 JSON 导入：轮询结束前目标文件已完整落盘",
                }
        else:
            try:
                self._guangya_userres_request("/userres/v1/file/delete_upload_task", {"taskIds": [check_task or task_id]})
            except Exception:
                pass
        return {
            "success": False,
            "task_id": check_task or task_id,
            "json_stage": True,
            "reason": "内部 JSON 导入秒传未命中；已清理任务/异常占位，回退下一来源",
        }

    def _rapid_transfer_xunlei_file(self, subscribe: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        # 先按脚本生成整份分享 JSON；导入阶段再取当前文件，避免 planner 裁剪模板。
        full_template = row.get("_xunlei_json_template") if isinstance(row, dict) else None
        if not isinstance(full_template, dict):
            full_template = self._xunlei_make_json_v1117([row])
        full_files = full_template.get("files") or []
        batch_index = _safe_int(row.get("_xunlei_json_index"), 0)
        if batch_index < 0 or batch_index >= len(full_files):
            return {"success": False, "reason": "迅雷 JSON 批次索引无效"}
        template = dict(full_template)
        template["files"] = [dict(full_files[batch_index] or {})]
        files = template.get("files") or []
        if not files:
            return {"success": False, "reason": "迅雷 JSON 模板生成失败"}
        preview = dict(files[0] or {})
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【迅雷JSON】整批模板已生成：total=%s current=%s path=%s size=%s gcid=%s md5=%s cid=%s dl=%s share=%s；下一步按光鸭 importMd5Json 合同导入",
            len(full_files), batch_index + 1,
            str(preview.get("path") or "")[:180],
            _safe_int(preview.get("size"), 0),
            "yes" if preview.get("gcid") else "no",
            "yes" if preview.get("md5") else "no",
            "yes" if (preview.get("cid") or preview.get("tripleCid") or preview.get("wholeCid")) else "no",
            "yes" if preview.get("downloadUrl") else "no",
            "yes" if (preview.get("shareId") or template.get("shareId")) else "no",
        )
        return self._xunlei_import_json_file_v1117(subscribe, template, dict(row or {}))

    def _xunlei_import_json_batch_v1123(
        self,
        subscribe: Any,
        template: Dict[str, Any],
        source_rows: Iterable[Dict[str, Any]],
        skip_indexes: Optional[Iterable[int]] = None,
        include_indexes: Optional[Iterable[int]] = None,
    ) -> Dict[str, Any]:
        """接收完整脚本模板，但只按允许索引执行光鸭导入合同。"""
        files = list(template.get("files") or []) if isinstance(template, dict) else []
        rows = [dict(row or {}) for row in source_rows]
        skipped = {int(value) for value in (skip_indexes or [])}
        included = {int(value) for value in include_indexes} if include_indexes is not None else set(range(len(files)))
        if not files or len(files) != len(rows):
            return {"success": False, "results": [], "message": "迅雷完整 JSON 与来源文件数量不一致"}
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【迅雷JSON】批次导入开始：selected=%s source_total=%s share=%s；完整 JSON 已生成，仅按真实缺集索引导入",
            len(included),
            len(files),
            str(template.get("shareId") or "-")[:30],
        )
        results: List[Dict[str, Any]] = []
        for index, (entry, source_row) in enumerate(zip(files, rows)):
            if index not in included:
                continue
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【迅雷JSON】批次文件导入：current=%s/%s path=%s gcid=%s md5=%s cid=%s dl=%s",
                index + 1, len(files), str(entry.get("path") or "")[:180],
                "yes" if entry.get("gcid") else "no", "yes" if entry.get("md5") else "no",
                "yes" if (entry.get("cid") or entry.get("tripleCid") or entry.get("wholeCid")) else "no",
                "yes" if entry.get("downloadUrl") else "no",
            )
            if index in skipped:
                result = {"success": True, "skipped": True, "reason": "此前已确认完成"}
            else:
                single = dict(template)
                single["files"] = [dict(entry or {})]
                result = dict(self._xunlei_import_json_file_v1117(subscribe, single, source_row) or {})
            self._plugin_log(
                "INFO" if result.get("success") else "WARNING",
                "【光鸭转存助手】【迅雷JSON】批次文件结果：current=%s/%s success=%s path=%s reason=%s",
                index + 1, len(files), bool(result.get("success")),
                str(entry.get("path") or "")[:180], str(result.get("reason") or "-")[:280],
            )
            results.append({"index": index, "file": dict(entry or {}), "result": result})
        success_count = sum(1 for item in results if bool((item.get("result") or {}).get("success")))
        self._plugin_log(
            "INFO" if success_count else "WARNING",
            "【光鸭转存助手】【迅雷JSON】批次导入结束：total=%s success=%s failed=%s",
            len(results), success_count, len(results) - success_count,
        )
        return {
            "success": success_count > 0,
            "total": len(results),
            "successful": success_count,
            "results": results,
            "message": f"迅雷 JSON 批次导入完成：成功 {success_count}/{len(results)}",
        }


__all__ = ["GuangYaXunleiJsonPipelineV1117Mixin"]
