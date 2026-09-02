"""迅雷秒传完整性校验与空占位清理。

真实运行发现 get_res_center_token 会先创建 upload task；当后续
check_can_flash_upload 未真正命中时，任务/占位文件可能仍短暂出现在目标目录。
旧实现又只凭 get_info_by_task_id 返回 fileId 就判定秒传成功，没有校验 fileSize，
因此 0B/尺寸异常占位存在被误判为成功的风险。

本层坚持“迅雷只做秒传，不做 OSS/本地下载”：
- get_res_center_token code=156 仍视为秒传命中信号，但必须再确认目标目录出现同名且大小一致的文件；
- check_can_flash_upload 只有真实 40-hex CID 才进入探测；无真实 CID 时不做无意义 check；
- canFlashUpload=true 或真实 CID check 返回可轮询 taskId 时，最终仍必须校验 fileId + 文件大小；
- 失败时删除 upload task，并只清理由本次请求新产生的同名 0B/尺寸异常占位，不碰原有文件；
- 同一批次相同 gcid/size/cid 只探测一次，避免不同分享重复制造 upload task。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from .xunlei_flash_v193 import _HEX32_RE, _HEX40_RE, _safe_int


class GuangYaXunleiIntegrityV1116Mixin:
    """在 ViewingDispatch 与旧 XunleiFlash 之间收紧秒传成功合同。"""

    build_id = "20260902-r28"

    # ------------------------------------------------------------------
    # 光鸭目录完整性检查
    # ------------------------------------------------------------------
    def _xunlei_parent_rows_v1116(self, parent_id: str) -> List[Dict[str, Any]]:
        client, _ = self._get_guangya_runtime()
        if not client:
            return []
        getter = getattr(client, "get_file_list", None)
        rows: List[Dict[str, Any]] = []
        if callable(getter):
            for page in range(3):
                try:
                    body = getter(
                        parent_id=str(parent_id or ""),
                        page_size=100,
                        order_by=3,
                        sort_type=1,
                        file_types=[],
                        page=page,
                    )
                except TypeError:
                    try:
                        body = getter(parent_id=str(parent_id or ""), page_size=100, page=page)
                    except Exception:
                        break
                except Exception:
                    break
                data = body.get("data") if isinstance(body, dict) else None
                listing = data.get("list") if isinstance(data, dict) else None
                page_rows = [dict(row) for row in (listing or []) if isinstance(row, dict)]
                rows.extend(page_rows)
                total = _safe_int(data.get("total") if isinstance(data, dict) else 0, 0)
                if not page_rows or len(page_rows) < 100 or (total and len(rows) >= total):
                    break
            return rows

        # 兼容少数旧版 GuangYaClient 没有公开 get_file_list 的运行态。
        try:
            body = self._guangya_userres_request(
                "/userres/v1/file/get_file_list",
                {
                    "parentId": str(parent_id or ""),
                    "page": 0,
                    "pageSize": 100,
                    "orderBy": 3,
                    "sortType": 1,
                    "fileTypes": [],
                },
            )
            data = body.get("data") if isinstance(body, dict) else None
            return [dict(row) for row in ((data or {}).get("list") or []) if isinstance(row, dict)]
        except Exception:
            return []

    @staticmethod
    def _xunlei_remote_meta_v1116(row: Dict[str, Any]) -> Tuple[str, str, int, bool]:
        file_id = str(row.get("fileId") or row.get("fileid") or row.get("file_id") or "").strip()
        name = str(row.get("fileName") or row.get("name") or row.get("file_name") or "").strip()
        size = _safe_int(row.get("fileSize") or row.get("size") or row.get("file_size"), 0)
        is_dir = row.get("resType") == 2 or str(row.get("kind") or "").lower() in {"dir", "folder", "drive#folder"}
        return file_id, name, size, is_dir

    def _xunlei_snapshot_v1116(self, parent_id: str, name: str) -> Dict[str, int]:
        snapshot: Dict[str, int] = {}
        for row in self._xunlei_parent_rows_v1116(parent_id):
            file_id, row_name, row_size, is_dir = self._xunlei_remote_meta_v1116(row)
            if is_dir or not file_id or row_name != name:
                continue
            snapshot[file_id] = row_size
        return snapshot

    def _xunlei_find_exact_file_v1116(
        self,
        parent_id: str,
        name: str,
        expected_size: int,
    ) -> Dict[str, Any]:
        for row in self._xunlei_parent_rows_v1116(parent_id):
            file_id, row_name, row_size, is_dir = self._xunlei_remote_meta_v1116(row)
            if is_dir or not file_id or row_name != name:
                continue
            if row_size == int(expected_size or 0) and row_size > 0:
                return {
                    "file_id": file_id,
                    "name": row_name,
                    "size": row_size,
                    "row": row,
                }
        return {}

    def _xunlei_wait_exact_file_v1116(
        self,
        parent_id: str,
        name: str,
        expected_size: int,
        *,
        attempts: int = 10,
    ) -> Dict[str, Any]:
        for index in range(max(1, int(attempts or 1))):
            found = self._xunlei_find_exact_file_v1116(parent_id, name, expected_size)
            if found:
                return found
            if index + 1 < attempts:
                time.sleep(0.2 if index < 4 else 0.35)
        return {}

    def _xunlei_delete_upload_task_v1116(self, task_id: str) -> bool:
        task_id = str(task_id or "").strip()
        if not task_id:
            return True
        try:
            body = self._guangya_userres_request(
                "/userres/v1/file/delete_upload_task",
                {"taskIds": [task_id]},
            )
            code = body.get("code") if isinstance(body, dict) else None
            msg = str(body.get("msg") or body.get("message") or "") if isinstance(body, dict) else ""
            ok = code in (None, 0, "0", 200, "200") or msg.lower() in {"success", "ok"}
            if not ok:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【迅雷秒传】upload task 清理未确认：task=%s code=%s msg=%s",
                    task_id[:80],
                    code,
                    msg[:180] or "-",
                )
            return bool(ok)
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【迅雷秒传】upload task 清理异常：task=%s error=%s",
                task_id[:80],
                str(err)[:220],
            )
            return False

    def _xunlei_cleanup_placeholders_v1116(
        self,
        parent_id: str,
        name: str,
        expected_size: int,
        before: Dict[str, int],
        *,
        task_id: str = "",
    ) -> Dict[str, Any]:
        self._xunlei_delete_upload_task_v1116(task_id)

        # 删除前再看一次：如果任务其实已经落成完整文件，就绝不清理，并把它当成功。
        exact = self._xunlei_find_exact_file_v1116(parent_id, name, expected_size)
        if exact:
            return exact

        victims: List[str] = []
        for row in self._xunlei_parent_rows_v1116(parent_id):
            file_id, row_name, row_size, is_dir = self._xunlei_remote_meta_v1116(row)
            if is_dir or not file_id or row_name != name or file_id in before:
                continue
            # 只碰本轮新出现且尺寸错误的同名文件，避免误删历史正常内容。
            if row_size <= 0 or row_size != int(expected_size or 0):
                victims.append(file_id)
        if not victims:
            return {}

        client, _ = self._get_guangya_runtime()
        delete_file = getattr(client, "delete_file", None) if client else None
        try:
            if callable(delete_file):
                response = delete_file(victims)
            else:
                response = self._guangya_userres_request(
                    "/userres/v1/file/delete_file",
                    {"fileIds": victims},
                )
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【迅雷秒传】已清理本轮新生成的空/尺寸异常占位：name=%s count=%s expected=%s response=%s",
                name[:180],
                len(victims),
                int(expected_size or 0),
                str((response or {}).get("msg") or (response or {}).get("code") or "submitted")[:120] if isinstance(response, dict) else "submitted",
            )
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【迅雷秒传】占位文件清理失败：name=%s count=%s error=%s",
                name[:180],
                len(victims),
                str(err)[:220],
            )
        return {}

    # ------------------------------------------------------------------
    # task 最终完成必须验证大小，fileId 本身不再代表成功
    # ------------------------------------------------------------------
    def _xunlei_poll_task_integrity_v1116(
        self,
        task_id: str,
        parent_id: str,
        name: str,
        expected_size: int,
    ) -> Dict[str, Any]:
        for index in range(30):
            body = self._guangya_userres_request(
                "/userres/v1/file/get_info_by_task_id",
                {"taskId": str(task_id)},
            )
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict):
                file_id = str(data.get("fileId") or data.get("fileid") or data.get("file_id") or "").strip()
                observed_size = _safe_int(data.get("fileSize") or data.get("size") or data.get("file_size"), 0)
                if file_id and observed_size == int(expected_size or 0) and observed_size > 0:
                    return {
                        "file_id": file_id,
                        "size": observed_size,
                        "task_data": data,
                    }
                if file_id:
                    found = self._xunlei_find_exact_file_v1116(parent_id, name, expected_size)
                    if found:
                        return found
            elif index % 5 == 4:
                found = self._xunlei_find_exact_file_v1116(parent_id, name, expected_size)
                if found:
                    return found
            time.sleep(0.25 if index < 4 else 0.45)

        return self._xunlei_find_exact_file_v1116(parent_id, name, expected_size)

    # ------------------------------------------------------------------
    # 严格秒传：没有完整文件就绝不返回 success=True
    # ------------------------------------------------------------------
    def _rapid_transfer_xunlei_file(self, subscribe: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        gcid = str(row.get("gcid") or "").strip().upper()
        size = _safe_int(row.get("size"), 0)
        if not _HEX40_RE.match(gcid) or size <= 0:
            return {"success": False, "reason": "缺少有效 GCID 或文件大小"}

        md5 = str(row.get("md5") or "").strip().lower()
        if not _HEX32_RE.match(md5):
            # 与用户已验证脚本保持兼容：只作为 get_res_center_token 索引兜底，
            # 不把这 32 位值伪装成 CID 发送给 check_can_flash_upload。
            md5 = gcid.lower()[:32]

        cid_candidates: List[str] = []
        raw_cid = str(row.get("cid") or "").strip().lower()
        if _HEX40_RE.match(raw_cid) and raw_cid != gcid.lower():
            cid_candidates.append(raw_cid)
        if row.get("download_url"):
            triple = self._xunlei_compute_triple_cid(str(row.get("download_url") or ""), size)
            if _HEX40_RE.match(triple) and triple.lower() != gcid.lower() and triple.lower() not in cid_candidates:
                cid_candidates.append(triple.lower())

        _, parent_id = self._xunlei_target_parent(
            subscribe,
            str(row.get("path") or row.get("name") or ""),
        )
        name = str(
            row.get("name")
            or str(row.get("path") or "").rsplit("/", 1)[-1]
            or "file"
        ).strip()
        before = self._xunlei_snapshot_v1116(parent_id, name)

        # 同一预检批次内，相同内容 + 相同真实 CID 不重复创建 upload task。
        dedupe_key = f"{gcid}:{size}:{cid_candidates[0] if cid_candidates else '-'}"
        seen = getattr(self, "_xunlei_flash_integrity_seen_v1116", None)
        if isinstance(seen, set):
            if dedupe_key in seen:
                return {
                    "success": False,
                    "reason": "同批次相同 GCID/size/CID 已探测，跳过重复秒传请求",
                    "duplicate": True,
                }
            seen.add(dedupe_key)

        token_candidates: List[Dict[str, Any]] = []
        for cid in cid_candidates:
            token_candidates.extend([
                {"gcid": gcid.lower(), "cid": cid.lower(), "md5": md5.lower(), "fileSize": size},
                {"gcid": gcid.upper(), "cid": cid.upper(), "md5": md5.upper(), "fileSize": size},
                {"gcid": gcid.lower(), "cid": cid.lower(), "fileSize": size},
            ])
        token_candidates.extend([
            {"gcid": gcid.lower(), "md5": md5.lower(), "fileSize": size},
            {"gcid": gcid.lower(), "fileSize": size},
            {"md5": md5.lower(), "fileSize": size},
        ])

        task_id = ""
        used_res: Dict[str, Any] = {}
        last_error = ""
        for res in token_candidates:
            try:
                body = self._guangya_userres_request(
                    "/userres/v1/get_res_center_token",
                    {
                        "capacity": 2,
                        "res": res,
                        "name": name,
                        "parentId": parent_id,
                    },
                )
            except Exception as err:
                last_error = str(err)[:240]
                continue
            code = body.get("code") if isinstance(body, dict) else None
            if code in (156, "156"):
                exact = self._xunlei_wait_exact_file_v1116(
                    parent_id,
                    name,
                    size,
                    attempts=12,
                )
                if exact:
                    return {
                        "success": True,
                        "instant": True,
                        "file_id": exact.get("file_id"),
                        "verified_size": exact.get("size"),
                        "reason": "get_res_center_token code=156，且目标文件大小校验通过",
                    }
                # 156 本应瞬时完成；看不到完整文件时不能凭业务码宣称成功。
                self._xunlei_cleanup_placeholders_v1116(
                    parent_id,
                    name,
                    size,
                    before,
                )
                return {
                    "success": False,
                    "reason": "get_res_center_token 返回 156，但目标目录未确认到同名同大小文件；已拒绝空壳成功",
                }

            candidate_task = self._guangya_task_id(body)
            if candidate_task:
                task_id = candidate_task
                used_res = dict(res)
                break
            last_error = str(
                body.get("msg")
                or body.get("message")
                or body.get("error")
                or code
                or "秒传令牌未命中"
            )[:240]

        if not task_id:
            return {"success": False, "reason": last_error or "光鸭未创建秒传任务"}

        # 没有真实 CID 时，check_can_flash_upload 没有可靠命中条件；插件又明确禁止 OSS/普通上传，
        # 因此立即清理任务并回退，不制造空轮询/空占位。
        if not cid_candidates:
            recovered = self._xunlei_cleanup_placeholders_v1116(
                parent_id,
                name,
                size,
                before,
                task_id=task_id,
            )
            if recovered:
                return {
                    "success": True,
                    "instant": True,
                    "task_id": task_id,
                    "file_id": recovered.get("file_id"),
                    "verified_size": recovered.get("size"),
                    "reason": "任务清理前已确认目标文件完整，按完整性结果记为成功",
                }
            return {
                "success": False,
                "task_id": task_id,
                "reason": "缺少真实 CID；仅保留秒传模式，已清理 upload task 并回退下一来源",
            }

        accepted_task = ""
        check_message = ""
        for cid in cid_candidates:
            checks = [
                {"taskId": task_id, "gcid": gcid.lower(), "cid": cid.lower(), "fileSize": size},
                {"taskId": task_id, "gcid": gcid.upper(), "cid": cid.upper(), "fileSize": size},
                {"taskId": task_id, "gcid": gcid.lower(), "cid": cid.lower(), "md5": md5.lower(), "fileSize": size},
            ]
            for check in checks:
                try:
                    body = self._guangya_userres_request(
                        "/userres/v1/check_can_flash_upload",
                        check,
                    )
                except Exception as err:
                    check_message = str(err)[:220]
                    continue
                data = body.get("data") if isinstance(body, dict) else None
                if isinstance(data, dict) and data.get("canFlashUpload") is True:
                    accepted_task = str(data.get("taskId") or task_id)
                    break

                # 有真实 CID 的情况下，服务端可能只给“处理中 taskId”；允许轮询，
                # 但绝不再把 taskId/fileId 本身当成功，最终仍由文件大小验真。
                candidate_task = self._guangya_task_id(body)
                code = body.get("code") if isinstance(body, dict) else None
                if candidate_task and code in (None, 0, "0", 147, "147"):
                    accepted_task = candidate_task
                    break
                check_message = str(
                    body.get("msg")
                    or body.get("message")
                    or body.get("error")
                    or code
                    or "未命中"
                )[:220]
            if accepted_task:
                break

        if accepted_task:
            verified = self._xunlei_poll_task_integrity_v1116(
                accepted_task,
                parent_id,
                name,
                size,
            )
            if verified:
                return {
                    "success": True,
                    "instant": True,
                    "task_id": accepted_task,
                    "file_id": verified.get("file_id"),
                    "verified_size": verified.get("size"),
                    "reason": "光鸭秒传完成，fileId 与文件大小校验通过",
                }

        recovered = self._xunlei_cleanup_placeholders_v1116(
            parent_id,
            name,
            size,
            before,
            task_id=accepted_task or task_id,
        )
        if recovered:
            return {
                "success": True,
                "instant": True,
                "task_id": accepted_task or task_id,
                "file_id": recovered.get("file_id"),
                "verified_size": recovered.get("size"),
                "reason": "轮询未确认但目标目录已出现同名同大小完整文件，按完整性结果记为成功",
            }

        return {
            "success": False,
            "task_id": accepted_task or task_id,
            "reason": f"光鸭秒传未命中或完整性校验失败；upload task/新空占位已清理，回退下一来源{('：' + check_message) if check_message else ''}",
        }

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        previous = getattr(self, "_xunlei_flash_integrity_seen_v1116", None)
        self._xunlei_flash_integrity_seen_v1116 = set()
        try:
            return super()._dispatch_xunlei_flash(subscribe)
        finally:
            self._xunlei_flash_integrity_seen_v1116 = previous


__all__ = ["GuangYaXunleiIntegrityV1116Mixin"]
